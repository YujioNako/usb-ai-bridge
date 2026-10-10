import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {spawn, execFile} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {Browser} from './browser.mjs';

const here=path.dirname(fileURLToPath(import.meta.url));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const safeError=e=>String(e.message||e).slice(0,2000);

export class WindowsTools {
  constructor(root,options={}) {this.root=path.resolve(root);this.options=options;this.browser=null;this.running=null;}
  async init(){await fs.mkdir(this.root,{recursive:true});this.root=await fs.realpath(this.root);return this;}
  async resolve(input='.',allowMissing=false){
    if(typeof input!=='string'||!input||input.includes('\0')||path.isAbsolute(input)||/[:]/.test(input))throw Error('Use a relative workspace path.');
    const normalized=input.replaceAll('\\','/');
    const parts=normalized.split('/').filter(x=>x&&x!=='.');
    if(parts.some(x=>x==='..'||x.toLowerCase()==='.usbai-browser'||/[. ]$/.test(x)||/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i.test(x)))throw Error('Unsafe path component.');
    let current=this.root;
    for(let i=0;i<parts.length;i++){
      current=path.join(current,parts[i]);
      try{const info=await fs.lstat(current);if(info.isSymbolicLink())throw Error('Symbolic links and junctions are not allowed.');
        const real=await fs.realpath(current);const rel=path.relative(this.root,real);
        if(rel.startsWith('..')||path.isAbsolute(rel))throw Error('Path is outside the workspace.');
        if(info.isFile()&&info.nlink>1)throw Error('Hard-linked files are not allowed.');
      }catch(e){if(e.code==='ENOENT'&&allowMissing)continue;throw e;}
    }
    return current;
  }
  async target(input){const p=await this.resolve(input,true);if(p===this.root)throw Error('Cannot modify the workspace root.');await this.resolve(path.relative(this.root,path.dirname(p))||'.');return p;}
  async atomicWrite(p,data,overwrite=false){
    const temp=path.join(path.dirname(p),'.usbai-'+crypto.randomUUID()+'.tmp');
    await fs.writeFile(temp,data,{flag:'wx'});
    try{
      if(!overwrite){await fs.copyFile(temp,p,fs.constants.COPYFILE_EXCL);}
      else{await fs.rename(temp,p);return;}
    }finally{await fs.unlink(temp).catch(()=>{});}
  }
  async files(a){
    const op=a.op;const input=a.path||'.';
    if(['document','archive_list','archive_read','archive_extract'].includes(op)||(op==='read'&&a.encoding!=='base64'&&/\.(xlsx?|xlsm|xlsb|ods|csv|tsv|docx?|pdf|zip)$/i.test(input))){
      const module=await import(this.options.documentModule||new URL('./documents/api.mjs',import.meta.url).href);
      return module.documentRead(this,{...a,path:input});
    }
    if(op==='list'){
      const p=await this.resolve(input);const entries=await fs.readdir(p,{withFileTypes:true});
      return {path:input,entries:entries.slice(0,500).map(e=>({name:e.name,type:e.isSymbolicLink()?'link':e.isDirectory()?'directory':'file'})),truncated:entries.length>500};
    }
    if(op==='read'){
      const p=await this.resolve(input);const stat=await fs.stat(p);if(!stat.isFile())throw Error('Not a regular file.');
      const offset=Number.isInteger(a.offset)&&a.offset>=0?a.offset:0;const limit=Math.min(64000,Math.max(1,a.limit||48000));
      const h=await fs.open(p,'r');let bytes;try{const b=Buffer.alloc(limit);const r=await h.read(b,0,limit,offset);bytes=b.subarray(0,r.bytesRead);}finally{await h.close();}
      return {path:input,size:stat.size,offset,next_offset:offset+bytes.length,encoding:a.encoding==='base64'?'base64':'utf8',content:bytes.toString(a.encoding==='base64'?'base64':'utf8'),truncated:offset+bytes.length<stat.size};
    }
    if(op==='write'){
      if(typeof a.content!=='string'||a.content.length>140000)throw Error('Write content must be a string up to 140000 characters.');
      const p=await this.target(input);const bytes=Buffer.from(a.content,a.encoding==='base64'?'base64':'utf8');
      if(a.overwrite)await this.resolve(input,true);
      await this.atomicWrite(p,bytes,!!a.overwrite);return {path:input,bytes:bytes.length};
    }
    if(op==='replace'){
      if(typeof a.find!=='string'||!a.find||typeof a.content!=='string')throw Error('find and content are required.');
      const p=await this.target(input);const stat=await fs.stat(p);if(stat.size>2000000)throw Error('Replace is limited to 2 MB text files.');
      const old=await fs.readFile(p,'utf8');const count=old.split(a.find).length-1;if(count!==1)throw Error('find must match exactly once; found '+count);
      await this.atomicWrite(p,old.replace(a.find,()=>a.content),true);return {path:input,replacements:1};
    }
    if(op==='mkdir'){const p=await this.resolve(input,true);await fs.mkdir(p,{recursive:true});return {path:input,created:true};}
    if(op==='move'){
      const p=await this.target(input);await this.resolve(input);const dest=await this.target(a.destination);
      try{await fs.lstat(dest);throw Error('Destination already exists.');}catch(e){if(e.code!=='ENOENT')throw e;}
      await fs.rename(p,dest);return {path:input,destination:a.destination};
    }
    if(op==='delete'){
      const p=await this.target(input);const stat=await fs.lstat(p);
      // A non-recursive delete never follows hidden links or erases an entire project tree.
      if(stat.isDirectory())await fs.rmdir(p);else await fs.unlink(p);return {path:input,deleted:true};
    }
    if(op==='search'){
      if(typeof a.find!=='string'||!a.find||a.find.length>1000)throw Error('A literal search string is required.');
      const start=await this.resolve(input),matches=[];let scanned=0,truncated=false;
      const walk=async dir=>{for(const e of await fs.readdir(dir,{withFileTypes:true})){
        if(scanned>=1000||matches.length>=100){truncated=true;return;}
        if(e.isSymbolicLink()||['.git','node_modules','.usbai-browser'].includes(e.name))continue;
        const full=path.join(dir,e.name);const rel=path.relative(this.root,full);await this.resolve(rel);
        if(e.isDirectory()){await walk(full);continue;}if(!e.isFile())continue;scanned++;
        const stat=await fs.stat(full);if(stat.size>256000)continue;
        const text=await fs.readFile(full,'utf8');if(text.includes('\0'))continue;
        text.split(/\r?\n/).forEach((line,i)=>{if(matches.length<100&&line.includes(a.find))matches.push({path:rel,line:i+1,text:line.slice(0,300)});});
      }};await walk(start);return {matches,scanned,truncated};
    }
    throw Error('Unknown file operation.');
  }
  stop(){if(this.running){const child=this.running;if(process.platform==='win32')execFile('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{windowsHide:true},()=>{});else child.kill('SIGKILL');}this.browser?.abort();}
  async process(exe,args,{timeout=60000,input}={}){
    return new Promise((resolve,reject)=>{
      const env={...process.env};for(const k of ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NODE_OPTIONS'])delete env[k];
      const child=spawn(exe,args,{cwd:this.root,env,windowsHide:true,stdio:['pipe','pipe','pipe']});this.running=child;
      let stdout='',stderr='',timedOut=false;
      const timer=setTimeout(()=>{timedOut=true;this.stop();},timeout);
      child.stdout.on('data',b=>{if(stdout.length<64000)stdout+=b.toString();});
      child.stderr.on('data',b=>{if(stderr.length<8000)stderr+=b.toString();});
      child.once('error',e=>{clearTimeout(timer);this.running=null;reject(e);});
      child.once('close',code=>{clearTimeout(timer);this.running=null;resolve({exit_code:code,stdout:stdout.slice(0,64000),stderr:stderr.slice(0,8000),timed_out:timedOut});});
      child.stdin.end(input||'');
    });
  }
  async execute(name,args){
    if(!args||typeof args!=='object'||Array.isArray(args))throw Error('Arguments must be an object.');
    if(name==='files')return this.files(args);
    if(name==='system')return {platform:os.platform(),release:os.release(),architecture:os.arch(),hostname:os.hostname(),workspace:this.root,node:process.version};
    if(name==='shell'){
      if(typeof args.command!=='string'||!args.command||args.command.length>16000)throw Error('Invalid PowerShell command.');
      const prefix="$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); ";
      return this.process('powershell.exe',['-NoProfile','-NonInteractive','-EncodedCommand',Buffer.from(prefix+args.command,'utf16le').toString('base64')],{timeout:Math.min(60,Math.max(1,args.timeout||30))*1000});
    }
    if(name==='browser'){
      if(!this.browser)this.browser=new Browser(this,this.options);
      return this.browser.execute(args);
    }
    throw Error('Unknown tool: '+name);
  }
  async close(){this.stop();await this.browser?.close();}
}

export async function runClient(config){
  const cfg=JSON.parse(await fs.readFile(config.device,'utf8'));const base=config.base||'http://'+cfg.device_ip+':8765';
  const url=new URL(base);if(url.protocol!=='http:'||!['172.31.240.1','127.0.0.1','localhost'].includes(url.hostname)||url.username||url.password)throw Error('Only the USB device or a local development endpoint is allowed.');
  const tools=await new WindowsTools(config.workspace,{proxy:config.browserProxy?cfg:null}).init();
  const id=crypto.randomUUID();const machineId=crypto.createHash('sha256').update(os.hostname()+'\0'+os.homedir()+'\0'+os.userInfo().username).digest('hex');let clientKey='',stopping=false;let current=null;
  const api=async(route,data,timeout=22000)=>{
    cfg.admin_token=JSON.parse(await fs.readFile(config.device,'utf8')).admin_token;
    const r=await fetch(base+'/api/agent/'+route,{method:'POST',headers:{Authorization:'Bearer '+cfg.admin_token,'Content-Type':'application/json'},body:JSON.stringify(data),signal:AbortSignal.timeout(timeout),redirect:'error'});
    const j=await r.json();if(!r.ok)throw Error(j.error||'Device HTTP '+r.status);return j;
  };
  const identity=()=>({id,client_key:clientKey});
  const register=async()=>{const r=await api('register',{id,machine_id:machineId,name:os.hostname(),workspace:tools.root,capabilities:['files','browser','shell','system']});clientKey=r.client_key;console.log('Connected. Workspace: '+tools.root);};
  const shutdown=()=>{stopping=true;tools.stop();};process.once('SIGINT',shutdown);process.once('SIGTERM',shutdown);
  let failures=0;const completed=new Map();
  try{
    while(!stopping){
      try{
        if(!clientKey)await register();
        const {job}=await api('poll',identity());failures=0;if(!job)continue;
        if(completed.has(job.id)){await api('result',{...identity(),job_id:job.id,result:completed.get(job.id)});continue;}
        current=job.id;console.log(new Date().toISOString()+' '+job.name+' '+(job.arguments.op||''));
        let controlBusy=false;const monitor=setInterval(async()=>{if(controlBusy)return;controlBusy=true;try{const r=await api('control',identity(),7000);if(r.cancelled.includes(current))tools.stop();}catch{}finally{controlBusy=false;}},1000);
        let result;
        try{result=await tools.execute(job.name,job.arguments);}catch(e){result={error:safeError(e)};}
        finally{clearInterval(monitor);current=null;}
        completed.set(job.id,result);if(completed.size>100)completed.delete(completed.keys().next().value);
        // Retry delivery of the stored result only; never repeat the file/browser/shell operation.
        for(let attempt=0;attempt<3;attempt++){try{await api('result',{...identity(),job_id:job.id,result});break;}catch(e){if(attempt===2)throw e;await sleep(1000);}}
      }catch(e){failures++;if(failures===1||failures%10===0)console.error('Connection unavailable: '+safeError(e));if(/注册已失效/.test(safeError(e)))clientKey='';await sleep(Math.min(10000,1000*failures));}
    }
  }finally{await tools.close();}
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const args=process.argv.slice(2);const option=(k,defaultValue)=>{const i=args.indexOf(k);return i<0?defaultValue:args[i+1];};
  runClient({device:option('--device',path.join(here,'device.json')),workspace:option('--workspace',path.join(here,'Workspace')),base:option('--base',null),browserProxy:args.includes('--browser-proxy')}).catch(e=>{console.error(safeError(e));process.exitCode=1;});
}
