const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function setup(lang, voices) {
  const spoken = [], natural = [], hooks = {};
  const window = {speechSynthesis:{cancel(){},getVoices(){return voices;},speak(x){spoken.push(x);}},
    AmiCorHumanVoice:{createEngine(){return {speak(text){natural.push(text);return Promise.resolve();}};}}};
  const context = {window,localStorage:{getItem(){return lang;}},SpeechSynthesisUtterance:function(text){this.text=text;},
    document:{readyState:'loading',addEventListener(name,fn){hooks[name]=fn;},querySelector(){return null;}},queueMicrotask};
  vm.runInNewContext(fs.readFileSync(__dirname+'/novaVoiceControls.js','utf8'), context);
  return {api:window.AmiCorNovaVoiceControls,spoken,natural};
}
test('Spanish playback chooses Spanish voice and avoids English-only engine',()=>{
  const x=setup('es-US',[{lang:'en-US'},{lang:'es-MX'}]);
  x.api.speak('Hola');
  assert.equal(x.spoken[0].lang,'es-US');
  assert.equal(x.spoken[0].voice.lang,'es-MX');
  assert.equal(x.natural.length,0);
});
test('missing selected-language voice never silently uses English',()=>{
  const x=setup('so-SO',[{lang:'en-US'}]);x.api.speak('Salaan');
  assert.equal(x.spoken.length,0); assert.equal(x.natural.length,0);
});
test('invalid stored locale resolves to English',()=>{
  const x=setup('invalid',[]);assert.equal(x.api.language(),'en-US');
});
