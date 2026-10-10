import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const worker=fileURLToPath(new URL('./worker.mjs',import.meta.url));
export const supported=p=>/\.(xlsx?|xlsm|xlsb|ods|csv|tsv|docx?|pdf|zip)$/i.test(p);
export async function documentRead(tools,args){
 const input=await tools.resolve(args.path);const request={...args,path:input};
 if(args.op==='archive_extract'){
  if(typeof args.destination!=='string'||!args.destination)throw Error('请选择未存在的解压目标目录');
  request.destination=await tools.target(args.destination);
 }
 return new Promise((resolve,reject)=>{
  const child=spawn(process.execPath,['--max-old-space-size=256',worker],{windowsHide:true,stdio:['pipe','pipe','pipe'],env:{SystemRoot:process.env.SystemRoot,PATH:process.env.PATH,TEMP:process.env.TEMP}});
  tools.running=child;let out='',err='',settled=false;
  const timer=setTimeout(()=>{child.kill();reject(Error('文档处理超过 45 秒，已停止。请缩小文件或读取范围。'));settled=true;},45000);
  child.stdout.on('data',b=>{out+=b;if(out.length>280000){settled=true;child.kill();reject(Error('文档结果超过传输限制，请缩小范围'));}});
  child.stderr.on('data',b=>{if(err.length<2000)err+=b;});
  child.on('error',e=>{clearTimeout(timer);settled=true;reject(e);});
  child.on('close',code=>{clearTimeout(timer);if(tools.running===child)tools.running=null;if(settled)return;try{const r=JSON.parse(out);if(r.error)throw Error(r.error);if(code!==0)throw Error('文档解析进程退出');resolve({...r,path:args.path,...(args.op==='archive_extract'?{destination:args.destination}: {})});}catch(e){reject(Error(e.message+(out?'':': '+err.slice(0,200))))}});
  child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify(request));
 });
}
