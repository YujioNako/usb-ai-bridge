import assert from 'node:assert/strict';
import {createPanel,SerialLink,allowed} from '../windows/serial-panel.mjs';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';

const calls=[];
const link={ready:true,error:'',request:async(method,route,body)=>{calls.push({method,route,body});return {status:200,body:Buffer.from(JSON.stringify({ssid:'coco_ext'})).toString('base64')};}};
const server=createPanel(link,'fixture-token');
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base='http://127.0.0.1:'+server.address().port;
try {
  assert.equal((await fetch(base+'/api/wifi/status')).status,401);
  assert.equal((await fetch(base+'/api/wifi/status',{headers:{Authorization:'Bearer fixture-token',Origin:'http://evil.example'}})).status,403);
  assert.equal((await fetch(base+'/api/proxy',{headers:{Authorization:'Bearer fixture-token'}})).status,403);
  assert.equal(calls.length,0);
  assert.equal((await (await fetch(base+'/api/wifi/status',{headers:{Authorization:'Bearer fixture-token'}})).json()).ssid,'coco_ext');
  link.ready=false;
  assert.equal((await fetch(base+'/api/wifi/status',{headers:{Authorization:'Bearer fixture-token'}})).status,503);
  assert.equal((await (await fetch(base+'/health')).json()).transport,'serial');
  assert.equal(allowed('CONNECT','example.com:443'),false);
} finally {await new Promise(r=>server.close(r));}

const child=new EventEmitter();child.stdin=new PassThrough();child.stdout=new PassThrough();child.stderr=new PassThrough();child.kill=()=>child.emit('close');
const transport=new SerialLink('fixture-token');
child.stdin.on('data',b=>{
  const request=JSON.parse(b);
  if(request.method==='HELLO'){
    const response=JSON.stringify({v:1,id:request.id,status:200,body:Buffer.from('{"protocol":"usb-ai-serial","version":1}').toString('base64')})+'\n';
    child.stdout.write(response.slice(0,10));child.stdout.write(response.slice(10));
  }
});
const ready=new Promise(r=>transport.once('ready',r));transport.attach(child);await ready;
assert.equal(transport.ready,true);
const request=transport.request('POST','/api/wifi',Buffer.from('{}'));
child.emit('close');await assert.rejects(request,/may have completed/);
assert.equal(transport.pending.size,0);
console.log('PASS: authentication, origin checks, endpoint restriction, offline health, fragmented handshake and no replay on disconnect');
