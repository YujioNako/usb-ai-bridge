import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';

const sleep=ms=>new Promise(r=>setTimeout(r,ms));
class CDP {
  constructor(ws){this.ws=ws;this.next=1;this.pending=new Map();this.events=new Map();
    ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=this.pending.get(m.id);if(p){this.pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}}else this.events.get(m.method)?.(m.params);});
    ws.addEventListener('close',()=>this.rejectAll());
  }
  static async connect(url){const ws=new WebSocket(url);await new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error('Browser debugging connection timed out.')),10000);ws.addEventListener('open',()=>{clearTimeout(t);resolve();},{once:true});ws.addEventListener('error',()=>{clearTimeout(t);reject(Error('Browser debugging connection failed.'));},{once:true});});return new CDP(ws);}
  send(method,params={}){return new Promise((resolve,reject)=>{const id=this.next++;const timer=setTimeout(()=>{this.pending.delete(id);reject(Error('Browser command timed out: '+method));},20000);this.pending.set(id,{resolve,reject,timer});this.ws.send(JSON.stringify({id,method,params}));});}
  rejectAll(){for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(Error('Browser operation interrupted.'));}this.pending.clear();}
  close(){this.rejectAll();this.ws.close();}
}

export class Browser {
  constructor(tools,options={}){this.tools=tools;this.options=options;this.connections=new Map();this.child=null;this.port=null;this.profile=null;this.refKey='__usbai_'+crypto.randomBytes(10).toString('hex');}
  async start(){
    if(this.port)return;
    const candidates=[this.options.browserPath,process.env['ProgramFiles(x86)']&&path.join(process.env['ProgramFiles(x86)'],'Microsoft/Edge/Application/msedge.exe'),process.env.ProgramFiles&&path.join(process.env.ProgramFiles,'Microsoft/Edge/Application/msedge.exe'),process.env.ProgramFiles&&path.join(process.env.ProgramFiles,'Google/Chrome/Application/chrome.exe'),process.env.LOCALAPPDATA&&path.join(process.env.LOCALAPPDATA,'Google/Chrome/Application/chrome.exe')].filter(Boolean);
    let exe;for(const candidate of candidates){try{await fs.access(candidate);exe=candidate;break;}catch{}}
    if(!exe)throw Error('Install Microsoft Edge or Google Chrome to enable browser tools.');
    this.profile=path.join(this.tools.root,'.usbai-browser',crypto.randomUUID());await fs.mkdir(this.profile,{recursive:true});
    const flags=['--remote-debugging-port=0','--remote-debugging-address=127.0.0.1','--user-data-dir='+this.profile,'--no-first-run','--no-default-browser-check','--disable-background-mode','--disable-sync','--window-size=1280,900','about:blank'];
    if(this.options.headless)flags.unshift('--headless=new');
    if(this.options.proxy)flags.unshift('--proxy-server=http://'+this.options.proxy.device_ip+':7890');
    this.child=spawn(exe,flags,{windowsHide:true,stdio:'ignore'});let launchError;this.child.on('error',e=>{launchError=e;});
    const deadline=Date.now()+20000;
    while(Date.now()<deadline){if(launchError)throw launchError;try{const text=await fs.readFile(path.join(this.profile,'DevToolsActivePort'),'utf8');this.port=Number(text.split('\n')[0]);if(this.port>0&&this.port<65536)return;}catch{}await sleep(200);}
    throw Error('Browser did not expose a local debugging endpoint; check browser policy.');
  }
  async http(route,method='GET'){await this.start();const r=await fetch('http://127.0.0.1:'+this.port+route,{method,signal:AbortSignal.timeout(8000)});if(!r.ok)throw Error('Browser endpoint failed: '+r.status);return r.json();}
  async tabs(){return (await this.http('/json/list')).filter(t=>t.type==='page');}
  async cdp(id){
    const tabs=await this.tabs();const target=tabs.find(t=>t.id===id);
    if(!target)throw Error('Tab does not exist; call tabs first.');
    if(this.connections.has(id))return this.connections.get(id);
    const parsed=new URL(target.webSocketDebuggerUrl);if(!['127.0.0.1','localhost'].includes(parsed.hostname))throw Error('Invalid debugger address.');
    const c=await CDP.connect(target.webSocketDebuggerUrl);this.connections.set(id,c);
    await c.send('Page.enable');await c.send('Runtime.enable');
    const downloads=await this.tools.resolve('Downloads',true);await fs.mkdir(downloads,{recursive:true});
    await c.send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:downloads}).catch(()=>{});
    if(this.options.proxy){
      const attempts=new Map();
      c.events.set('Fetch.requestPaused',p=>{c.send('Fetch.continueRequest',{requestId:p.requestId}).catch(()=>{});});
      c.events.set('Fetch.authRequired',p=>{
        const n=(attempts.get(p.requestId)||0)+1;attempts.set(p.requestId,n);
        const response=p.authChallenge.source==='Proxy'&&n<=2?{response:'ProvideCredentials',username:this.options.proxy.proxy_user,password:this.options.proxy.proxy_password}:{response:'CancelAuth'};
        c.send('Fetch.continueWithAuth',{requestId:p.requestId,authChallengeResponse:response}).catch(()=>{});
      });
      await c.send('Fetch.enable',{handleAuthRequests:true});
    }
    return c;
  }
  async eval(c,expression){const r=await c.send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;}
  url(raw){const u=new URL(raw);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)throw Error('Only HTTP(S) URLs without embedded credentials are accepted.');return u.href;}
  async waitReady(c){const deadline=Date.now()+12000;while(Date.now()<deadline){try{if(await this.eval(c,"document.readyState !== 'loading'"))return;}catch{}await sleep(150);}}
  async element(c,ref){
    if(typeof ref!=='string'||ref.length>100)throw Error('Use a ref returned by snapshot.');
    const r=await c.send('Runtime.evaluate',{expression:`(()=>{const e=window[${JSON.stringify(this.refKey)}]?.get(${JSON.stringify(ref)});if(!e||!e.isConnected)throw Error('Stale element ref; take a new snapshot.');e.scrollIntoView({block:'center',inline:'center'});return e;})()`});
    if(r.exceptionDetails||!r.result.objectId)throw Error('Stale element ref; take a new snapshot.');return r.result.objectId;
  }
  async execute(a){
    if(a.op==='tabs')return {tabs:(await this.tabs()).map(t=>({id:t.id,title:t.title,url:t.url}))};
    if(a.op==='open'){
      const url=this.url(a.url);const t=await this.http('/json/new?about:blank','PUT');const c=await this.cdp(t.id);const result=await c.send('Page.navigate',{url});if(result.errorText)throw Error(result.errorText);await this.waitReady(c);return {tab:t.id,url};
    }
    if(typeof a.tab!=='string')throw Error('A tab ID is required; call tabs first.');
    const c=await this.cdp(a.tab);
    if(a.op==='navigate'){const url=this.url(a.url);const result=await c.send('Page.navigate',{url});if(result.errorText)throw Error(result.errorText);await this.waitReady(c);return {tab:a.tab,url};}
    if(a.op==='close'){await c.send('Page.close');c.close();this.connections.delete(a.tab);return {closed:a.tab};}
    if(a.op==='snapshot'){
      const prefix=crypto.randomBytes(5).toString('hex');
      return this.eval(c,`(()=>{const map=new Map();window[${JSON.stringify(this.refKey)}]=map;let n=0;const elements=[];
        for(const e of document.querySelectorAll('a,button,input,textarea,select,[role="button"],[contenteditable="true"]')){const r=e.getBoundingClientRect();const style=getComputedStyle(e);if(!r.width||!r.height||style.visibility==='hidden'||style.display==='none')continue;if(n>=200)break;
        const ref=${JSON.stringify(prefix)}+'-'+(++n);map.set(ref,e);elements.push({ref,tag:e.tagName.toLowerCase(),type:e.type||'',label:(e.getAttribute('aria-label')||e.labels?.[0]?.innerText||e.innerText||e.placeholder||e.name||'').slice(0,200),value:e.type==='password'?'[password]':String(e.value||'').slice(0,200),href:e.tagName==='A'?e.href:undefined,options:e.tagName==='SELECT'?Array.from(e.options).slice(0,50).map(o=>({value:o.value,text:o.text})):undefined});}
        return {url:location.href,title:document.title,text:(document.body?.innerText||'').slice(0,24000),elements,iframes:Array.from(document.querySelectorAll('iframe')).map(e=>({src:e.src,title:e.title})),note:'Cross-origin iframe contents require opening their URL in a dedicated tab.'};})()`);
    }
    if(['click','fill','select','upload'].includes(a.op)){
      const objectId=await this.element(c,a.ref);
      try{
        if(a.op==='click'){
          const r=await c.send('Runtime.callFunctionOn',{objectId,functionDeclaration:'function(){const r=this.getBoundingClientRect();const x=r.left+r.width/2,y=r.top+r.height/2;const top=document.elementFromPoint(x,y);if(top!==this&&!this.contains(top))throw Error("Element is covered; take a new snapshot.");return {x,y};}',returnByValue:true});
          if(r.exceptionDetails)throw Error('Element cannot be clicked; take a new snapshot.');const {x,y}=r.result.value;
          await c.send('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',clickCount:1});await c.send('Input.dispatchMouseEvent',{type:'mouseReleased',x,y,button:'left',clickCount:1});await sleep(250);
        }else if(a.op==='fill'){
          if(typeof a.text!=='string'||a.text.length>64000)throw Error('Invalid input text.');
          const r=await c.send('Runtime.callFunctionOn',{objectId,functionDeclaration:'function(){if(!this.matches("input,textarea,[contenteditable=true]"))throw Error("Not a text field");this.focus();if(this.select)this.select();else{const r=document.createRange();r.selectNodeContents(this);const s=getSelection();s.removeAllRanges();s.addRange(r);}}'});if(r.exceptionDetails)throw Error('Not an editable field.');
          await c.send('Input.insertText',{text:a.text});
        }else if(a.op==='select'){
          const r=await c.send('Runtime.callFunctionOn',{objectId,functionDeclaration:'function(value){if(this.tagName!=="SELECT"||!Array.from(this.options).some(o=>o.value===value))throw Error("Unknown option");this.value=value;this.dispatchEvent(new Event("input",{bubbles:true}));this.dispatchEvent(new Event("change",{bubbles:true}));}',arguments:[{value:a.text}]});if(r.exceptionDetails)throw Error('Select option failed.');
        }else{
          const file=await this.tools.resolve(a.path);if(!(await fs.stat(file)).isFile())throw Error('Upload requires a file.');
          await c.send('DOM.setFileInputFiles',{files:[file],objectId});
        }
      }finally{await c.send('Runtime.releaseObject',{objectId}).catch(()=>{});}
      return {ok:true,note:'Take a new snapshot to verify the result.'};
    }
    if(a.op==='press'){
      const keys={Enter:13,Tab:9,Escape:27,Backspace:8,ArrowDown:40,ArrowUp:38};if(!keys[a.key])throw Error('Unsupported key.');
      await c.send('Input.dispatchKeyEvent',{type:'keyDown',key:a.key,code:a.key,windowsVirtualKeyCode:keys[a.key],...(a.key==='Enter'?{text:'\r'}:{})});await c.send('Input.dispatchKeyEvent',{type:'keyUp',key:a.key,code:a.key,windowsVirtualKeyCode:keys[a.key]});return {ok:true};
    }
    if(a.op==='scroll'){await c.send('Input.dispatchMouseEvent',{type:'mouseWheel',x:400,y:300,deltaX:Math.max(-2000,Math.min(2000,a.x||0)),deltaY:Math.max(-2000,Math.min(2000,a.y||600))});return {ok:true};}
    if(a.op==='screenshot'){
      const p=await this.tools.target(a.path||'browser-'+Date.now()+'.jpg');const result=await c.send('Page.captureScreenshot',{format:'jpeg',quality:45,captureBeyondViewport:false});const bytes=Buffer.from(result.data,'base64');await this.tools.atomicWrite(p,bytes,false);return {path:path.relative(this.tools.root,p),...(bytes.length<=180000?{image:'data:image/jpeg;base64,'+result.data}:{}),bytes:bytes.length};
    }
    throw Error('Unknown browser operation.');
  }
  abort(){for(const c of this.connections.values())c.rejectAll();}
  async close(){for(const c of this.connections.values())c.close();this.connections.clear();if(this.port){try{const version=await this.http('/json/version');const c=await CDP.connect(version.webSocketDebuggerUrl);await c.send('Browser.close').catch(()=>{});c.close();}catch{}}this.child?.kill();this.port=null;}
}
