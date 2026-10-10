import assert from 'node:assert/strict';
import {createPanel,allowed} from '../windows/serial-panel.mjs';
const calls=[];const link={ready:true,request:async(method,path,body)=>{calls.push({method,path});return {status:200,body:Buffer.from('{"ok":true}').toString('base64')}}};
const server=createPanel(link,'test-key','windows/panel');await new Promise(r=>server.listen(0,'127.0.0.1',r));const url='http://127.0.0.1:'+server.address().port;
try{
 for(const p of ['/maintenance','/maintenance.js','/maintenance.css'])assert.equal((await fetch(url+p)).status,200);
 const send=headers=>fetch(url+'/api/maintenance',{method:'POST',headers,body:JSON.stringify({action:'open',session:'ab'.repeat(32),user:'fixture'})});
 assert.equal((await send({})).status,401);assert.equal((await send({Authorization:'Bearer test-key',Origin:'http://evil.invalid'})).status,403);assert.equal(calls.length,0);
 assert.equal((await send({Authorization:'Bearer test-key'})).status,200);assert.equal(calls.length,1);assert.equal(allowed('POST','/api/maintenance?host=x'),false);
 link.ready=false;assert.equal((await send({Authorization:'Bearer test-key'})).status,503);console.log('PASS maintenance routing/authentication/Origin/USB offline');
}finally{await new Promise(r=>server.close(r));}
