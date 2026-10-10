import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
const source=await fs.readFile('pi/app/workbench.js','utf8');
const connectSource=source.slice(source.indexOf('async function connect(){'),source.indexOf('async function showSettings'));
async function scenario({authFail=false,historyFail=false,sessionFail=false,deviceFail=false}={}){
 const nodes={};const node=id=>nodes[id]??={textContent:'',classList:{hidden:id==='shell',add(){this.hidden=true},remove(){this.hidden=false}},value:'fixture-key'};
 const calls=[];let deviceReject;const warnings=[];
 const context={$:node,token:'fixture-key',active:false,sessionLoadSeq:0,sessionStorage:{setItem(){calls.push('saved')}},
  loadModel:async()=>{if(authFail)throw Error('auth')},device:()=>new Promise((_r,j)=>deviceReject=j),
  refreshAgent:()=>calls.push('agent'),refreshHistory:async()=>{if(historyFail)throw Error('history timeout');return [{id:'fixture'}]},
  openSession:async()=>{calls.push('open');if(sessionFail)throw Error('session timeout')},newSession:async()=>calls.push('create'),notice:t=>warnings.push(t)};
 vm.createContext(context);vm.runInContext(connectSource,context);
 if(authFail){await assert.rejects(context.connect(),/auth/);assert.equal(context.active,false);assert.equal(deviceReject,undefined);return;}
 await context.connect(); // Must complete even while device() is still pending.
 assert(context.active);assert(node('login').classList.hidden);assert(!node('shell').classList.hidden);
 if(historyFail||sessionFail){assert.equal(warnings.length,1);assert.match(warnings[0],/已连接 Pi/);assert(!calls.includes('create'));}
 if(deviceFail){deviceReject(Error('status timeout'));await Promise.resolve();assert.match(node('device-status').textContent,/设备状态暂时不可用/);assert(context.active);}
}
await scenario({authFail:true});await scenario({historyFail:true});await scenario({sessionFail:true});await scenario({deviceFail:true});
const req=source.slice(source.indexOf('async function request('),source.indexOf('const api='));
const context={AbortController,setTimeout,clearTimeout,Error,JSON,token:'fixture-key',fetch:async()=>{throw Object.assign(Error('aborted'),{name:'AbortError'})}};
vm.createContext(context);vm.runInContext(req,context);
for(const [route,label] of [['status','读取设备状态'],['workbench/sessions','加载历史会话'],['workbench/session?id=fixture','加载会话内容'],['workbench/model','读取模型配置']]){
 await assert.rejects(context.request(route),e=>e.code==='REQUEST_TIMEOUT'&&e.message.includes(label)&&e.message.includes('不代表 USB 已断开'));
}
console.log('PASS: authentication required; pending device status does not block login; history/session failure preserves access; timeout identifies exact request');
