import fs from 'node:fs/promises';
import {KeyManager} from './key-manager.mjs';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {EventEmitter} from 'node:events';

const here=path.dirname(fileURLToPath(import.meta.url));
const MAX=6000000;
const get=new Set(['/api/status','/api/nodes','/api/wifi/status','/api/agent/status','/api/workbench/workflows','/api/workbench/model','/api/workbench/sessions']);
const post=new Set(['/api/maintenance','/api/wifi','/api/wifi/scan','/api/subscription','/api/select','/api/test','/api/delay',
  ...['register','poll','result','control','approve','job','run'].map(x=>'/api/agent/'+x),
  ...['model','sessions','rename','files','send','stop','codex','session-action','steer','answer','workflows'].map(x=>'/api/workbench/'+x)]);
export const allowed=(method,route)=>method==='GET'&&(get.has(route)||/^\/api\/workbench\/session\?id=[a-f0-9]{24}$/.test(route))||method==='POST'&&post.has(route);

export class SerialLink extends EventEmitter {
  constructor(token){super();this.token=token;this.pending=new Map();this.buffer='';this.ready=false;this.child=null;this.stopped=false;this.error='Not connected';this.authRequired=false;}
  attach(child){
    this.child=child;this.buffer='';this.ready=false;this.authRequired=false;
    child.stdin.on('error',()=>{if(this.child===child)this.fail('Serial writer disconnected')});
    child.stdout.on('data',chunk=>{
      if(this.child!==child)return;
      this.buffer+=chunk.toString('ascii');
      if(this.buffer.length>MAX){this.fail('Serial frame too large');child.kill();return;}
      let pos;
      while((pos=this.buffer.indexOf('\n'))>=0){
        const line=this.buffer.slice(0,pos);this.buffer=this.buffer.slice(pos+1);
        let response;try{response=JSON.parse(line);}catch{continue;}
        if(response.v!==1||!Number.isInteger(response.status)||typeof response.body!=='string')continue;
        const p=this.pending.get(response.id);if(!p)continue;
        this.pending.delete(response.id);clearTimeout(p.timer);p.resolve(response);
      }
    });
    child.stderr.on('data',b=>{if(this.child!==child)return;this.error=b.toString().trim().slice(0,400);});
    child.on('error',()=>{if(this.child===child)this.fail('Cannot start serial worker')});
    child.on('close',()=>{if(this.child!==child)return;this.child=null;this.fail('USB serial disconnected');this.emit('disconnected');});
    // Device identity must be confirmed before forwarding application requests.
    const handshake=this.handshake?this.handshake():this.request('HELLO','',Buffer.alloc(0),8000).then(r=>{
      const hello=JSON.parse(Buffer.from(r.body,'base64').toString());
      if(r.status!==200||hello.protocol!=='usb-ai-serial'||hello.version!==1)throw Error('Pi serial service not ready or device token mismatch');
    });
    handshake.then(()=>{
      if(this.child!==child||this.stopped)return;this.ready=true;this.authRequired=false;this.error='';this.emit('ready');
    }).catch(e=>{if(this.child!==child||this.stopped)return;this.ready=false;this.error=e.message;if(e.code==='KEY_REQUIRED'){this.authRequired=true;return;}child.kill();});
  }
  request(method,route,body,timeout=75000,authToken=this.token){
    if(!this.child||this.child.stdin.destroyed)return Promise.reject(Error('USB serial unavailable'));
    if(method!=='HELLO'&&!this.ready)return Promise.reject(Error('Pi serial handshake incomplete'));
    if(this.pending.size>=12)return Promise.reject(Error('Serial queue is full'));
    const id=crypto.randomUUID();
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.pending.delete(id);reject(Error('Serial request timed out; operation may have completed. Check its status before retrying.'));},timeout);
      this.pending.set(id,{resolve,reject,timer});
      this.child.stdin.write(JSON.stringify({v:1,id,method,path:route,body:body.toString('base64'),token:authToken})+'\n',e=>{if(e)this.fail('Serial write failed');});
    });
  }
  fail(message){this.ready=false;this.authRequired=false;this.error=message;for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(Error(message+'; an in-flight operation may have completed.'));}this.pending.clear();}
  stop(){this.stopped=true;this.child?.kill();this.fail('Stopped');}
}

export function createPanel(link,token,assets=path.join(here,'panel'),keys=null,attachments=null){
  let pairingAttempts=[];
  const readBody=async(req,max)=>{let body=Buffer.alloc(0);for await(const b of req){body=Buffer.concat([body,b]);if(body.length>max)throw Error('Request too large')}return JSON.parse(body.toString()||'{}')};
  const staticFiles=new Map([...['markdown-it.min.js','workbench-view.js','workbench-sync.js'].map(n=>['/'+n,[n,'text/javascript']]),['/',['index.html','text/html']],['/device',['device.html','text/html']],['/workbench.js',['workbench.js','text/javascript']],['/workflows-ui.js',['workflows-ui.js','text/javascript']],['/workbench.css',['workbench.css','text/css']]]);
  for(const [route,file,type] of [['/maintenance','maintenance.html','text/html'],['/maintenance.js','maintenance.js','text/javascript'],['/maintenance.css','maintenance.css','text/css'],['/xterm.js','xterm.js','text/javascript'],['/xterm-fit.js','xterm-fit.js','text/javascript'],['/xterm.css','xterm.css','text/css']]) staticFiles.set(route,[file,type]);
  const server=http.createServer(async(req,res)=>{
    const send=(status,value,type='application/json')=>{res.writeHead(status,{'Content-Type':type+'; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer'});res.end(Buffer.isBuffer(value)?value:JSON.stringify(value));};
    // Reject DNS-rebinding and cross-origin browser requests, including on loopback.
    const expected='127.0.0.1:'+req.socket.localPort;
    if(req.headers.host!==expected)return send(403,{error:'Invalid local Host'});
    if(req.headers.origin&&req.headers.origin!=='http://'+expected)return send(403,{error:'Invalid Origin'});
    if(req.method==='GET'&&staticFiles.has(req.url)){
      const [name,type]=staticFiles.get(req.url);
      try{return send(200,await fs.readFile(path.join(assets,name)),type);}catch{return send(500,{error:'Panel files are missing'});}
    }
    if(req.method==='GET'&&req.url==='/health')return send(200,{ok:true,transport:'serial',connected:link.ready});
    if(req.method==='POST'&&req.url==='/api/security/pair'&&keys){
      pairingAttempts=pairingAttempts.filter(t=>Date.now()-t<60000);
      if(pairingAttempts.length>=10)return send(429,{error:'尝试过于频繁，请稍后重试'});
      try{const data=await readBody(req,2000);return send(200,await keys.pair(data.key));}catch(e){
        const status=e.status||(e instanceof SyntaxError?400:503);
        if(status===400||status===401)pairingAttempts.push(Date.now());
        return send(status,{error:e.message,code:e.code||(status===400?'INVALID_REQUEST':'PAIR_FAILED'),retryable:e.code==='KEY_BUSY',retry_after_ms:e.code==='KEY_BUSY'?750:undefined});
      }
    }
    const supplied=Buffer.from(req.headers.authorization||''),required=Buffer.from('Bearer '+(keys?.cfg.admin_token||token));
    if(supplied.length!==required.length||!crypto.timingSafeEqual(supplied,required))return send(401,{error:'Device token required'});
    if(req.method==='POST'&&['/api/attachments','/api/attachments/download'].includes(req.url)){
      if(!attachments)return send(409,{error:'请使用新版 Start-Serial.cmd 启动并选择 Windows 工作目录后添加文档'});
      try{
        const data=await readBody(req,380000);
        if(req.url.endsWith('/download')){
          const file=await attachments.handle({...data,action:'download'});const h=await fs.open(file.path,'r');
          res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Length':file.size,'Content-Disposition':"attachment; filename*=UTF-8''"+encodeURIComponent(file.name),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
          const stream=h.createReadStream();stream.on('error',()=>res.destroy());res.on('close',()=>stream.destroy());stream.pipe(res);return;
        }
        return send(200,await attachments.handle(data));
      }catch(e){return send(400,{error:e.message})}
    }
    if(req.method==='GET'&&req.url==='/api/security/status'&&keys)return send(200,{supported:true,busy:keys.busy,recovery:keys.recovery,backup_stale:!!keys.cfg.sealed_stale,error:keys.lastError});
    if(req.method==='POST'&&['/api/security/change-key','/api/security/backup'].includes(req.url)&&keys){
      try{const data=await readBody(req,2000);return send(200,req.url.endsWith('change-key')?await keys.rotate(data.new_key,data.confirm_key):await keys.backup(data.password,data.confirm_password));}catch(e){return send(400,{error:e.message,recovery:keys.recovery})}
    }
    if(req.method==='GET'&&req.url==='/api/transport')return send(200,{transport:'serial',connected:link.ready,auth_required:!!link.authRequired,busy:!!keys?.busy,recovery:!!keys?.recovery,error:link.error});
    if(keys?.busy)return send(503,{error:'正在校验设备密钥，请稍候',code:'KEY_BUSY',retryable:true,retry_after_ms:750});
    if(link.authRequired)return send(401,{error:'请输入 Pi 当前的管理密钥以完成配对',code:'KEY_REQUIRED'});
    if(keys?.recovery)return send(503,{error:'上次密钥修改尚待恢复，请检查 USB 连接后重试',code:'KEY_RECOVERY'});
    if(!allowed(req.method,req.url))return send(403,{error:'Application endpoint not allowed'});
    if(!link.ready)return send(503,{error:'USB 串口未连接或 Pi 串口服务尚未启动；此面板不依赖 Wi-Fi。',code:'USB_DISCONNECTED'});
    let body=Buffer.alloc(0);
    try{
      for await(const b of req){body=Buffer.concat([body,b]);if(body.length>400000){send(413,{error:'Request too large'});return;}}
      const r=await link.request(req.method,req.url,body);
      send(r.status,Buffer.from(r.body,'base64'));
    }catch(e){if(!res.headersSent)send(502,{error:e.message});}
  });
  server.on('connect',(_req,socket)=>socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'));
  server.on('upgrade',(_req,socket)=>socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'));
  return server;
}

export async function main(){
  const args=process.argv.slice(2),option=(k,d)=>args.includes(k)?args[args.indexOf(k)+1]:d;
  const port=option('--port','');if(!/^COM[0-9]+$/.test(port))throw Error('Specify --port COM<number>');
  const devicePath=option('--device',path.join(here,'device.json'));
  const cfg=JSON.parse(await fs.readFile(devicePath,'utf8'));
  const link=new SerialLink(cfg.admin_token),keys=await new KeyManager(devicePath,link).load();
  link.handshake=()=>keys.handshake();
  let attachments=null;
  if(option('--workspace','')){
    const {WindowsTools}=await import('./client.mjs');const {AttachmentStore}=await import('./attachments.mjs');
    attachments=await new AttachmentStore(await new WindowsTools(option('--workspace','')).init()).init();
  }
  const server=createPanel(link,cfg.admin_token,path.join(here,'panel'),keys,attachments);
  const pidFile=path.join(here,'serial-panel.pid');
  let retry;
  const connect=()=>{if(!link.stopped)link.attach(spawn(path.join(here,'SerialWorker.exe'),[port],{windowsHide:true,stdio:['pipe','pipe','pipe']}));};
  link.on('disconnected',()=>{if(!link.stopped){clearTimeout(retry);retry=setTimeout(connect,3000);}});
  link.on('ready',()=>console.log('Pi serial service authenticated on '+port));
  server.listen(18766,'127.0.0.1',()=>{fs.writeFile(pidFile,String(process.pid)).catch(()=>{});console.log('Local panel: http://127.0.0.1:18766/');connect();});
  server.on('error',e=>{console.error(e.message);link.stop();process.exitCode=1;});
  const stop=()=>{link.stop();clearTimeout(retry);server.close();attachments?.close().catch(()=>{});fs.unlink(pidFile).catch(()=>{});};
  process.on('SIGINT',stop);process.on('SIGTERM',stop);
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(e=>{console.error(e.message);process.exitCode=1;});
