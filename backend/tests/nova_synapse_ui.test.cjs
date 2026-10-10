const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/nova-synapse/synapse.js'),'utf8');
function setup(configured,guest=false){
 const nodes=new Map(),requests=[],connections=[];
 const element=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,style:{},children:[],handlers:{},appendChild(x){this.children.push(x);},replaceChildren(){this.children=[];},setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];},addEventListener(k,fn){this.handlers[k]=fn;},scrollIntoView(){}});return nodes.get(id);};
 class Room{constructor(){this.state='connected';this.handlers={};this.remoteParticipants=new Map();this.localParticipant={isMicrophoneEnabled:false,isCameraEnabled:false,isScreenShareEnabled:false,async setMicrophoneEnabled(value){this.isMicrophoneEnabled=value;},async setCameraEnabled(value){this.isCameraEnabled=value;}};}on(k,fn){this.handlers[k]=fn;}async connect(url,token){connections.push({url,token});}async disconnect(){}}
 const document={documentElement:{},querySelectorAll(){return [];},getElementById:element,createElement:()=>element('new')};
 const fetch=async(url,opts)=>{
   requests.push({url,opts});
   let result=[];
   if(url.endsWith('/status'))result={configured};
   else if(url.endsWith('/join'))result={title:'Meeting',host:false,meeting_id:'meeting',server_url:'wss://media.example.com',participant_token:'scoped-grant'};
   else if(url.endsWith('/meetings') && opts.method==='POST')result={meeting_id:'A',title:'Meeting A',invite_path:'/nova/synapse#room=A&invite=private-A',expires_at:'2026-10-11T00:00:00Z'};
   else if(url.endsWith('/meetings'))result=[{meeting_id:'A',title:'Meeting A'},{meeting_id:'B',title:'Meeting B'}];
   else if(url.endsWith('/host')){const id=url.split('/').at(-2);result={meeting_id:id,title:'Meeting '+id,host:true,server_url:'wss://media.example.com',participant_token:'host-grant',expires_at:'2026-10-11T00:00:00Z'};}
   else if(url.endsWith('/invitation')){const id=url.split('/').at(-2);result={meeting_id:id,title:'Meeting '+id,invite_path:'/nova/synapse#room='+id+'&invite=new-private',expires_at:'2026-10-11T00:00:00Z'};}
   return {ok:true,json:async()=>result};
 };
 const window={AmiCorSession:{getAccessToken(){return guest?null:'session';},async restore(){}},addEventListener(){}};
 const location={origin:'https://amicor.example.com',hash:guest?'#room=meeting&invite=private-secret':''};
 vm.runInNewContext(source,{document,window,location,localStorage:{getItem(){return null;},setItem(){}},navigator:{},URLSearchParams,TextEncoder,TextDecoder,fetch,LivekitClient:{Room,RoomEvent:{}}});
 return {element,requests,connections,document};
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
 s.element('meetings').children[1].handlers.click();await settle();
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
