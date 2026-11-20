const CACHE='voiceledger-pro-v15-voice-preview';
const SHELL=['./index.html','./manifest.webmanifest','./voiceledger-icon.svg'];
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)));self.skipWaiting();});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(names=>Promise.all(names.filter(name=>name.startsWith('voiceledger-pro-')&&name!==CACHE).map(name=>caches.delete(name)))));self.clients.claim();});
self.addEventListener('fetch',event=>{const request=event.request;if(request.method!=='GET'||new URL(request.url).origin!==self.location.origin)return;
if(request.mode==='navigate'){event.respondWith(fetch(request).then(response=>{if(response.ok){const copy=response.clone();caches.open(CACHE).then(c=>c.put(request,copy));}return response;}).catch(()=>caches.match(request).then(hit=>hit||caches.match('./index.html'))));return;}
event.respondWith(caches.match(request).then(hit=>hit||fetch(request)));});