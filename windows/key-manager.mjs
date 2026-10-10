import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
export const keyError=(message,code,status)=>Object.assign(Error(message),{code,status});
export const validKey=k=>typeof k==='string'&&/^[!-~]{16,128}$/.test(k);
export async function writePrivate(file,value){
 const text=JSON.stringify(value,null,2);
 if(process.platform==='win32'){
  await new Promise((resolve,reject)=>{
   const child=spawn(path.join(process.env.SystemRoot||'C:\\Windows','System32/WindowsPowerShell/v1.0/powershell.exe'),['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',path.join(here,'Write-PrivateConfig.ps1'),'-ConfigPath',path.resolve(file)],{windowsHide:true,stdio:['pipe','ignore','pipe']});
   let error='';const timer=setTimeout(()=>{child.kill();reject(Error('本机配置写入超时，请重新打开启动器以恢复'));},12000);
   child.stderr.on('data',b=>{error+=b.toString()});child.on('error',e=>{clearTimeout(timer);reject(e)});child.stdin.on('error',()=>{});
   child.on('close',code=>{clearTimeout(timer);code===0?resolve():reject(Error('本机配置未能安全保存，请检查文件权限'))});child.stdin.end(text);
  });
 }else{const tmp=file+'.new';const handle=await fs.open(tmp,'w',0o600);try{await handle.writeFile(text);await handle.sync()}finally{await handle.close()}await fs.rename(tmp,file);}
}
export class KeyManager {
 constructor(file,link,writer=writePrivate){this.file=file;this.link=link;this.writer=writer;this.busy=false;this.cfg=null;this.recovery=false;this.lastError='';}
 async load(){this.cfg=JSON.parse(await fs.readFile(this.file,'utf8'));return this;}
 async save(cfg){await this.writer(this.file,cfg);this.cfg=cfg;}
 async hello(key){const r=await this.link.request('HELLO','',Buffer.alloc(0),8000,key);if([401,403].includes(r.status))throw keyError('设备管理密钥不匹配，请输入 Pi 当前的管理密钥（不是 Wi-Fi 或系统登录密码）','KEY_REQUIRED',401);if(r.status!==200)throw keyError('Pi 串口服务暂时不可用','DEVICE_UNAVAILABLE',503);const v=JSON.parse(Buffer.from(r.body,'base64'));if(v.protocol!=='usb-ai-serial'||v.version!==1)throw keyError('USB 设备协议不匹配，请检查 COM 端口','DEVICE_PROTOCOL',502);}
 async remote(action,data={},key=this.cfg.admin_token){const r=await this.link.request('POST','/api/security/key',Buffer.from(JSON.stringify({action,...data})),12000,key);const body=JSON.parse(Buffer.from(r.body,'base64'));if(r.status!==200)throw Error(body.error||'密钥同步失败');return body;}
 async finish(key){const cfg={...this.cfg,admin_token:key,sealed_stale:true,key_updated_at:new Date().toISOString()};delete cfg.key_change;await this.save(cfg);this.link.token=key;this.recovery=false;this.lastError='';}
 async handshake(){
  if(this.busy)throw Error('密钥同步处理中');this.busy=true;
  try{
   await this.load();const pending=this.cfg.key_change;
   if(!pending){await this.hello(this.cfg.admin_token);this.link.token=this.cfg.admin_token;return;}
   this.recovery=true;
   try{await this.hello(pending.new_key);await this.finish(pending.new_key);return;}catch(e){if(e.code!=='KEY_REQUIRED')throw e;}
   await this.hello(this.cfg.admin_token);this.link.token=this.cfg.admin_token;this.link.ready=true;
   const status=await this.remote('status');
   if(status.id===pending.id){await this.remote('commit',{id:pending.id});await this.hello(pending.new_key);await this.finish(pending.new_key);}
   else{const cfg={...this.cfg};delete cfg.key_change;await this.save(cfg);this.recovery=false;this.lastError='上次修改未提交，已保留原密钥';}
  }finally{this.busy=false;}
 }
 async rotate(key,confirmation){
  if(this.busy||this.recovery)throw Error('正在同步或恢复密钥，请等待串口恢复');
  if(!validKey(key))throw Error('请输入 16–128 位不含空格的 ASCII 字母、数字或符号');
  if(key!==confirmation)throw Error('两次输入的新密钥不一致');
  if(key===this.cfg.admin_token)throw Error('新密钥与当前密钥相同');
  this.busy=true;const id=crypto.randomBytes(16).toString('hex');let journaled=false;
  try{
   await this.remote('prepare',{id,new_key:key});
   try{await this.save({...this.cfg,key_change:{id,new_key:key}});journaled=true;}
   catch(e){await this.remote('cancel',{id}).catch(()=>{});throw e;}
   await this.remote('commit',{id});await this.hello(key);await this.finish(key);
   return {ok:true,backup_stale:true};
  }catch(e){
   if(journaled){this.recovery=true;this.lastError='密钥同步结果待确认；请保持设备连接，正在自动恢复';this.link.ready=false;this.link.child?.kill();throw Error(this.lastError);}
   throw e;
  }finally{this.busy=false;}
 }
 async pair(key){
  if(!validKey(key))throw keyError('请输入 16–128 位不含空格的 Pi 管理密钥','INVALID_KEY',400);if(this.busy)throw keyError('正在校验设备密钥，请稍候','KEY_BUSY',503);if(!this.link.child||this.link.child.stdin?.destroyed)throw keyError('USB 串口未连接，请检查数据线、COM 端口及是否被其他客户端占用','USB_DISCONNECTED',503);this.busy=true;
  try{await this.hello(key);if(this.cfg.admin_token!==key||this.cfg.key_change)await this.finish(key);this.link.token=key;this.link.ready=true;this.link.error='';this.link.authRequired=false;this.recovery=false;this.lastError='';this.link.emit?.('ready');return {ok:true};}
  finally{this.busy=false;}
 }
 async backup(password,confirmation){
  if(this.busy||this.recovery)throw Error('请等待密钥同步结束');
  if(typeof password!=='string'||password.length<12||password.length>128||password!==confirmation)throw Error('请两次输入相同的 12–128 位备份解锁口令');
  this.busy=true;
  try{
   const salt=crypto.randomBytes(32),iv=crypto.randomBytes(16);
   const keys=await new Promise((resolve,reject)=>crypto.pbkdf2(password,salt,200000,64,'sha256',(e,k)=>e?reject(e):resolve(k)));
   const cfg={...this.cfg};delete cfg.key_change;delete cfg.sealed_stale;
   const cipher=crypto.createCipheriv('aes-256-cbc',keys.subarray(0,32),iv);
   const ciphertext=Buffer.concat([cipher.update(JSON.stringify(cfg),'utf8'),cipher.final()]);
   const mac=crypto.createHmac('sha256',keys.subarray(32)).update(Buffer.concat([Buffer.from('USB-AI-DEVICE-V1'),salt,iv,ciphertext])).digest();keys.fill(0);
   const result={version:1,algorithm:'AES-256-CBC-HMAC-SHA256-PBKDF2-SHA256',iterations:200000,salt:salt.toString('base64'),iv:iv.toString('base64'),ciphertext:ciphertext.toString('base64'),mac:mac.toString('base64')};
   const file=path.join(path.dirname(this.file),'device.sealed.json');const tmp=file+'.new';await fs.writeFile(tmp,JSON.stringify(result,null,2));await fs.rename(tmp,file);await this.save({...this.cfg,sealed_stale:false});return result;
  }finally{this.busy=false;}
 }
}
