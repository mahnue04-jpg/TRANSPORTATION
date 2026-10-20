const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/nova-synapse/synapse.js'),'utf8');
const languages=fs.readFileSync(path.join(__dirname,'../static/nova-synapse/synapse-languages.js'),'utf8');
const events=['TrackSubscribed','TrackUnsubscribed','ParticipantConnected','ParticipantDisconnected','LocalTrackPublished','LocalTrackUnpublished','DataReceived','AudioPlaybackStatusChanged','Reconnecting','Reconnected','TrackMuted','TrackUnmuted','Disconnected'];
function setup(configured,guest=false){
 const nodes=new Map(),requests=[],connections=[],rooms=[];
 let made=0;
 const titles={A:'Meeting A',B:'Meeting B'};
 const element=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,style:{},children:[],handlers:{},appendChild(x){this.children.push(x);},replaceChildren(){this.children=[];},setAttribute(k,v){this[k]=v;},getAttribute(k){return this[k];},removeAttribute(k){delete this[k];},addEventListener(k,fn){this.handlers[k]=fn;},scrollIntoView(){}});return nodes.get(id);};
 class Room{constructor(){rooms.push(this);this.state='connected';this.handlers={};this.remoteParticipants=new Map();this.localParticipant={name:'Host',isMicrophoneEnabled:false,isCameraEnabled:false,isScreenShareEnabled:false,async setMicrophoneEnabled(value){this.isMicrophoneEnabled=value;},async setCameraEnabled(value){this.isCameraEnabled=value;},async setScreenShareEnabled(value){this.isScreenShareEnabled=value;},async publishData(){if(this.failSend)throw new Error('send failed');}};}on(k,fn){this.handlers[k]=fn;}async connect(url,token){connections.push({url,token});}async disconnect(){}}
 const labeled={create:'create','saved-heading':'saved','saved-note':'savednote','lang-note':'langnote'};
 const document={documentElement:{},querySelectorAll(selector){if(selector!=='[data-i]')return [];return Object.entries(labeled).map(([id,key])=>{const node=element(id);node['data-i']=key;return node;});},getElementById:element,createElement:()=>element('made-'+(++made))};
 const fetch=async(url,opts)=>{
   requests.push({url,opts});
   let result=[];
   if(url.endsWith('/status'))result={configured};
   else if(url.endsWith('/join'))result={title:'Meeting',host:false,meeting_id:'meeting',server_url:'wss://media.example.com',participant_token:'scoped-grant'};
   else if(url.includes('/title')){const id=url.split('/').at(-2);titles[id]=JSON.parse(opts.body).title;result={meeting_id:id,title:titles[id],host:true,expires_at:'2026-10-11T00:00:00Z'};}
   else if(url.endsWith('/meetings') && opts.method==='POST')result={meeting_id:'A',title:titles.A,invite_path:'/nova/synapse#room=A&invite=private-A',expires_at:'2026-10-11T00:00:00Z'};
   else if(url.endsWith('/meetings'))result=Object.keys(titles).map(id=>({meeting_id:id,title:titles[id]}));
   else if(url.endsWith('/host')){const id=url.split('/').at(-2);result={meeting_id:id,title:titles[id]||('Meeting '+id),host:true,server_url:'wss://media.example.com',participant_token:'host-grant',expires_at:'2026-10-11T00:00:00Z'};}
   else if(url.endsWith('/invitation')){const id=url.split('/').at(-2);result={meeting_id:id,title:titles[id]||('Meeting '+id),invite_path:'/nova/synapse#room='+id+'&invite=new-private',expires_at:'2026-10-11T00:00:00Z'};}
   return {ok:true,json:async()=>result};
 };
 const window={AmiCorSession:{getAccessToken(){return guest?null:'session';},async restore(){}},addEventListener(){}};
 const location={origin:'https://amicor.example.com',hash:guest?'#room=meeting&invite=private-secret':''};
 const context={document,window,location,localStorage:{getItem(){return null;},setItem(){}},navigator:{},URLSearchParams,TextEncoder,TextDecoder,fetch,LivekitClient:{Room,RoomEvent:Object.fromEntries(events.map(name=>[name,name]))}};
 vm.runInNewContext(languages,context);
 vm.runInNewContext(source,context);
 return {element,requests,connections,document,rooms};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('unconfigured service disables creation and joining without claiming a working call',async()=>{const s=setup(false);await settle();assert.equal(s.element('create').disabled,true);assert.equal(s.element('guest-join').disabled,true);assert.match(s.element('connection').textContent,/not connected/);assert.equal(s.connections.length,0);});
test('guest invitation joins only its own room and starts with camera and microphone off',async()=>{const s=setup(true,true);await settle();s.element('name').value='Visitor';await s.element('guest-form').handlers.submit({preventDefault(){}});assert.equal(s.connections.length,1);assert.equal(s.connections[0].token,'scoped-grant');const request=s.requests.find(r=>r.url.endsWith('/join'));assert.equal(request.opts.headers.Authorization,undefined);assert.equal(JSON.parse(request.opts.body).invite,'private-secret');assert.equal(s.element('mic').textContent,'Microphone off');assert.equal(s.element('camera').textContent,'Camera off');assert.equal(s.element('host-controls').hidden,true);s.element('language').value='ar';s.element('language').handlers.change();assert.equal(s.document.documentElement.dir,'rtl');assert.equal(s.element('camera').textContent,'الكاميرا مغلقة');});

test('resuming another meeting hides the previous invite and allows a correct new link',async()=>{
 const s=setup(true);await settle();
 s.element('title').value='Meeting A';
 await s.element('create-form').handlers.submit({preventDefault(){}});
 assert.match(s.element('invite-link').value,/room=A/);
 assert.equal(s.element('invitation-controls').hidden,false);
 assert.match(s.element('participants').textContent,/Participants \(1\)/);
 s.element('saved-list').children[1].handlers.click();await settle();
 assert.equal(s.element('invitation-controls').hidden,true);
 assert.equal(s.element('invite-link').value,'');
 await s.element('renew-invite').handlers.click();
 assert.match(s.element('invite-link').value,/room=B/);
 assert.equal(s.element('invitation-controls').hidden,false);
 assert.match(s.element('invite-expiry').textContent,/Invitation expires/);
});

test('media status follows toggles and remains correct after switching language',async()=>{
 const s=setup(true,true);await settle();s.element('name').value='Visitor';
 await s.element('guest-form').handlers.submit({preventDefault(){}});
 assert.match(s.element('room-status').textContent,/Microphone off.*Camera off/);
 await s.element('mic').handlers.click();await s.element('camera').handlers.click();
 assert.match(s.element('room-status').textContent,/Microphone on.*Camera on/);
 s.element('language').value='ar';s.element('language').handlers.change();
 assert.match(s.element('room-status').textContent,/الميكروفون مفتوح.*الكاميرا مفتوحة/);
 assert.equal(s.element('rename-form').hidden,true);
 assert.equal(s.element('share').hidden,true);
});

test('saved meeting heading lists titles and a rename survives the next load',async()=>{
 const s=setup(true);await settle();
 assert.equal(s.element('saved-heading').textContent,'Saved meetings');
 assert.match(s.element('saved-note').textContent,/not recordings/);
 assert.deepEqual(s.element('saved-list').children.map(button=>button.textContent),['Meeting A','Meeting B']);
 s.element('title').value='Meeting A';
 await s.element('create-form').handlers.submit({preventDefault(){}});
 s.element('rename-title').value='Easy Care check-in';
 await s.element('rename-form').handlers.submit({preventDefault(){}});
 const saved=s.requests.filter(request=>request.url.endsWith('/title'));
 assert.equal(saved.length,1);
 assert.equal(JSON.parse(saved[0].opts.body).title,'Easy Care check-in');
 assert.equal(s.element('meeting-title').textContent,'Easy Care check-in');
 assert.ok(s.element('saved-list').children.some(button=>button.textContent==='Easy Care check-in'));
 assert.match(s.element('notice').textContent,/Meeting name saved/);
});

test('chat delivers both ways and a failed send stays beside the composer',async()=>{
 const s=setup(true);await settle();
 s.element('title').value='Meeting A';
 await s.element('create-form').handlers.submit({preventDefault(){}});
 const room=s.rooms.at(-1);
 room.localParticipant.failSend=true;
 s.element('chat-input').value='Need a hand';
 await s.element('chat-form').handlers.submit({preventDefault(){}});
 assert.equal(s.element('chat-error').hidden,false);
 assert.equal(s.element('chat-error').textContent,'Message was not sent. Try again.');
 assert.equal(s.element('chat-input').value,'Need a hand');
 assert.equal(s.element('chat-log').children.length,0);
 assert.equal(s.element('notice').textContent,'');
 s.element('language').value='ar';
 s.element('language').handlers.change();
 assert.equal(s.document.documentElement.dir,'rtl');
 assert.equal(s.element('chat-error').textContent,'لم تُرسل الرسالة. حاول مرة أخرى.');
 room.localParticipant.failSend=false;
 s.element('chat-input').value='On my way';
 await s.element('chat-form').handlers.submit({preventDefault(){}});
 assert.equal(s.element('chat-error').hidden,true);
 assert.equal(s.element('chat-input').value,'');
 assert.equal(s.element('chat-log').children.at(-1).textContent,'Host: On my way');
 const incoming=new TextEncoder().encode(JSON.stringify({text:'See you there'}));
 room.handlers.DataReceived(incoming,{name:'Visitor'});
 assert.equal(s.element('chat-log').children.at(-1).textContent,'Visitor: See you there');
});

test('screen languages stay interface text, with Arabic as the only right-to-left option',async()=>{
 const html=fs.readFileSync(path.join(__dirname,'../static/nova-synapse/index.html'),'utf8');
 const css=fs.readFileSync(path.join(__dirname,'../static/nova-synapse/synapse.css'),'utf8');
 assert.match(css,/body\.in-call #chat-panel\{position:sticky/);
 assert.match(css,/body\.in-call \.meeting-panel\{display:grid/);
 assert.match(css,/#chat-error\{/);
 const used=new Set([...source.matchAll(/\bt\('([a-z]+)'\)/g)].map(match=>match[1]));
 for (const key of html.matchAll(/data-i="([a-z]+)"/g)) used.add(key[1]);
 ['micon','cameraon','sharing','unlock','newinvite','renamed','people','expires'].forEach(key=>used.add(key));
 const packs=vm.runInNewContext(languages+'\nwindow.SynapseExtraPhrases;',{window:{}});
 for (const [code,pack] of Object.entries(packs)) {
  for (const key of used) assert.ok(pack[key] && String(pack[key]).trim(), code+' missing '+key);
 }
 const waveA=['pt','zh','de','hi','ja'];
 const waveB=['it','ru','el','ko','tr'];
 const codes=['en','so','ar','fr','es',...waveA,...waveB];
 assert.equal(codes.length,15);
 for (const code of codes) assert.match(html,new RegExp('value="'+code+'"'));
 assert.match(html,/id="saved-heading"/);
 assert.match(html,/id="chat-error"/);
 assert.match(html,/synapse-languages\.js/);
 const s=setup(true);await settle();
 for (const code of codes) {
  s.element('language').value=code;
  s.element('language').handlers.change();
  assert.equal(s.document.documentElement.lang,code);
  assert.equal(s.document.documentElement.dir,code==='ar'?'rtl':'ltr');
  assert.ok(s.element('create').textContent.length>1);
  assert.ok(s.element('saved-heading').textContent.length>1);
  assert.match(s.element('lang-note').textContent,/.{12,}/);
  if(code==='en') assert.match(s.element('lang-note').textContent,/does not translate speech/);
  if(code==='ar') assert.match(s.element('lang-note').textContent,/لا يترجم/);
  if(code!=='en'){
   assert.notEqual(s.element('create').textContent,'Create meeting');
   assert.notEqual(s.element('saved-heading').textContent,'Saved meetings');
  }
 }
});
