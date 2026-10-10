import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {readClipboardFiles} from './clipboard-files.mjs';
export const machineId=()=>crypto.createHash('sha256').update(os.hostname()+'\0'+os.homedir()+'\0'+os.userInfo().username).digest('hex');
export class AttachmentStore {
 constructor(tools,options={}){this.tools=tools;this.pending=new Map();this.clipboard=new Map();this.readClipboard=options.readClipboard||readClipboardFiles;}
 async init(){await this.tools.resolve('.usbai-attachments',true);await fs.mkdir(path.join(this.tools.root,'.usbai-attachments'),{recursive:true});return this;}
 async check(ref){
  if(!ref||ref.machine_id!==machineId()||typeof ref.workspace!=='string'||ref.workspace.toLowerCase()!==this.tools.root.toLowerCase())throw Error('附件属于另一台电脑或工作目录，请连接原工作目录或重新添加文件');
  if(typeof ref.path!=='string'||!/^\.usbai-attachments\/[a-f0-9]{24}\/[a-f0-9]{24}\/[^/\\]+$/.test(ref.path))throw Error('附件引用无效');
  const p=await this.tools.resolve(ref.path);const stat=await fs.stat(p);if(!stat.isFile()||stat.size!==ref.bytes)throw Error('附件已移动或大小改变，请重新添加');return {path:p,size:stat.size,name:path.basename(p)};
 }
 async abort(id){const item=this.pending.get(id);if(!item)return;this.pending.delete(id);await item.handle.close().catch(()=>{});await fs.unlink(item.temp).catch(()=>{});}
 async handle(data){
  for(const [id,item] of this.pending)if(!item.busy&&Date.now()-item.time>15*60*1000)await this.abort(id);
  for(const [id,item] of this.clipboard)if(Date.now()-item.time>60000)this.clipboard.delete(id);
  if(data.action==='clipboard-list'){
   this.clipboard.clear();const paths=await this.readClipboard();const files=[];
   if(paths.length>20)throw Error('一次最多粘贴 20 个文件');
   for(const source of paths){
    // Do not authenticate to network shares or follow copied shortcuts/links.
    if(!/^[a-z]:[\\/]/i.test(source))throw Error('仅支持本地磁盘文件；请先把网络共享文件复制到本机');
    const stat=await fs.lstat(source);if(!stat.isFile()||stat.isSymbolicLink())throw Error('请复制普通文件；文件夹请先压缩为 ZIP');
    if(stat.size>100000000)throw Error(path.basename(source)+' 超过 100 MB');
    const id=crypto.randomBytes(16).toString('hex');this.clipboard.set(id,{source,size:stat.size,mtime:stat.mtimeMs,time:Date.now()});
    files.push({id,name:path.basename(source),bytes:stat.size});
   }
   return {files};
  }
  if(data.action==='clipboard-import'){
   const item=this.clipboard.get(data.id);if(!item)throw Error('剪贴板文件选择已过期，请重新粘贴');this.clipboard.delete(data.id);
   const input=await fs.open(item.source,'r');let upload;
   try{
    const stat=await input.stat();if(!stat.isFile()||stat.size!==item.size||stat.mtimeMs!==item.mtime)throw Error('原文件已改变，请重新复制');
    upload=await this.handle({action:'begin',session:data.session,name:path.basename(item.source),bytes:stat.size});
    const buffer=Buffer.alloc(upload.chunk_bytes);let offset=0;
    while(offset<stat.size){const {bytesRead}=await input.read(buffer,0,Math.min(buffer.length,stat.size-offset),offset);if(!bytesRead)throw Error('原文件读取中断');await this.handle({action:'chunk',upload_id:upload.upload_id,offset,content:buffer.subarray(0,bytesRead).toString('base64')});offset+=bytesRead;}
    const after=await input.stat();if(after.size!==stat.size||after.mtimeMs!==stat.mtimeMs)throw Error('复制过程中原文件发生改变，请重试');
    return await this.handle({action:'finish',upload_id:upload.upload_id});
   }catch(e){if(upload)await this.abort(upload.upload_id);throw e}finally{await input.close()}
  }
  if(data.action==='begin'){
   if(this.pending.size>=4)throw Error('正在上传的文件过多');
   if(!/^[a-f0-9]{24}$/.test(data.session||''))throw Error('会话编号无效');
   if(!Number.isInteger(data.bytes)||data.bytes<0||data.bytes>100000000)throw Error('单个文件最多 100 MB');
   if(typeof data.name!=='string'||!data.name.trim()||data.name.length>180)throw Error('文件名无效');
   let name=data.name.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').replace(/[. ]+$/g,'');if(!name||/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i.test(name))name='file-'+name;
   const id=crypto.randomBytes(12).toString('hex'),folder='.usbai-attachments/'+data.session+'/'+id;
   const directory=await this.tools.resolve(folder,true);await fs.mkdir(directory,{recursive:true});await this.tools.resolve(folder);
   const relative=folder+'/'+name,p=await this.tools.target(relative),temp=p+'.upload';
   const handle=await fs.open(temp,'wx',0o600);this.pending.set(id,{handle,temp,path:p,relative,name,size:data.bytes,bytes:0,hash:crypto.createHash('sha256'),time:Date.now(),busy:false});
   return {upload_id:id,chunk_bytes:262144};
  }
  if(data.action==='preview'){await this.check(data.reference);return this.tools.files({op:'document',path:data.reference.path,limit:/\.(xlsx?|xlsm|xlsb|ods|csv|tsv|zip)$/i.test(data.reference.path)?20:/\.pdf$/i.test(data.reference.path)?2:12000});}
  if(data.action==='download')return this.check(data.reference);
  const item=this.pending.get(data.upload_id);if(!item)throw Error('上传已结束或过期，请重新添加');if(item.busy)throw Error('上传请求尚未完成');item.busy=true;
  try{
   if(data.action==='abort'){await this.abort(data.upload_id);return {ok:true};}
   if(data.action==='chunk'){
    if(data.offset!==item.bytes||typeof data.content!=='string'||data.content.length>350000||data.content.length%4!==0||!/^[A-Za-z0-9+/]*={0,2}$/.test(data.content))throw Error('上传分块无效或顺序不一致');
    const b=Buffer.from(data.content,'base64');if(!b.length||item.bytes+b.length>item.size)throw Error('上传大小不一致');
    let written=0;while(written<b.length){const r=await item.handle.write(b,written,b.length-written,item.bytes+written);if(!r.bytesWritten)throw Error('文件写入中断');written+=r.bytesWritten;}
    item.hash.update(b);item.bytes+=b.length;item.time=Date.now();return {received:item.bytes};
   }
   if(data.action==='finish'){
    if(item.bytes!==item.size)throw Error('文件未上传完整');await item.handle.sync();await item.handle.close();await fs.rename(item.temp,item.path);this.pending.delete(data.upload_id);
    const reference={storage:'windows',path:item.relative,bytes:item.bytes,sha256:item.hash.digest('hex'),machine_id:machineId(),workspace:this.tools.root};
    return {name:item.name,kind:'file',reference,content:JSON.stringify(reference),size:item.bytes};
   }
   throw Error('附件操作不存在');
  }finally{item.busy=false}
 }
 async close(){for(const id of [...this.pending.keys()])await this.abort(id)}
}
