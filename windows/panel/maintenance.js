const $=id=>document.getElementById(id);
let token=sessionStorage.getItem('usbai-token')||'', sid=null, offset=0, seq=0;
let queue=[], pending=null, online=false, generation=0, sizeDirty=true;
const encoder=new TextEncoder();
const terminal=new Terminal({cursorBlink:true,fontSize:14,fontFamily:'Consolas, "Cascadia Mono", monospace',scrollback:3000,disableStdin:true,theme:{background:'#101b20',foreground:'#dfebe5'},linkHandler:{activate:()=>{}}});
const fit=new FitAddon.FitAddon();terminal.loadAddon(fit);terminal.open($('terminal'));fit.fit();
// Never allow remote escape sequences to read or replace the Windows clipboard.
terminal.parser.registerOscHandler(52,()=>true);
function status(message,error=false){$('status').textContent=message;$('status').classList.toggle('error',error);}
function enabled(value){online=value;terminal.options.disableStdin=!value;$('interrupt').disabled=$('escape').disabled=!value;}
function controls(){ $('open').disabled=!!sid;$('user').disabled=!!sid;$('key').disabled=!!sid;$('close').disabled=!sid; }
const b64=bytes=>btoa(String.fromCharCode(...bytes));
function enqueue(bytes){if(!online)return;if(queue.reduce((n,b)=>n+b.length,0)+bytes.length>65536){status('输入太长，请分批粘贴（最多 64 KB）',true);return;}for(let i=0;i<bytes.length;i+=4096)queue.push(bytes.slice(i,i+4096));}
terminal.onData(text=>enqueue(encoder.encode(text)));
terminal.onBinary(text=>enqueue(Uint8Array.from(text,c=>c.charCodeAt(0))));
terminal.onResize(()=>{sizeDirty=true;});
new ResizeObserver(()=>{fit.fit();if(terminal.cols>240||terminal.rows>100)terminal.resize(Math.min(240,terminal.cols),Math.min(100,terminal.rows));}).observe($('terminal'));
async function api(data,keepalive=false){
 const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),10000);
 try{const r=await fetch('/api/maintenance',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(data),signal:ctrl.signal,keepalive});let j;try{j=await r.json()}catch{throw Error('USB 响应不完整')}
 if(!r.ok){const e=Error(j.error||'维护请求失败');e.fatal=[400,401,403,404].includes(r.status);throw e;}return j;
 }finally{clearTimeout(timer)}
}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function pump(current,gen,user){
 let opened=false,failedAt=0;
 while(sid===current&&gen===generation){
  try{
   if(!opened){const r=await api({action:'open',session:current,user,cols:terminal.cols,rows:terminal.rows});if(r.closed)throw Object.assign(Error(r.reason),{fatal:true});opened=true;}
   if(pending===null&&queue.length)pending={seq:seq+1,data:b64(queue.shift())};
   if(pending){const r=await api({action:'input',session:current,...pending});if(sid!==current)return;seq=r.seq;pending=null;}
   if(sizeDirty){sizeDirty=false;try{await api({action:'resize',session:current,cols:terminal.cols,rows:terminal.rows})}catch(e){sizeDirty=true;throw e}}
   const r=await api({action:'poll',session:current,offset});
   if(sid!==current||gen!==generation)return;
   if(r.truncated)terminal.write('\r\n[断线期间输出过多，仅保留最近 512 KB]\r\n');
   if(r.data)await new Promise(resolve=>terminal.write(Uint8Array.from(atob(r.data),c=>c.charCodeAt(0)),resolve));
   offset=r.offset;
   if(r.closed&&!r.more){status(r.reason);sid=null;pending=null;queue=[];enabled(false);controls();return;}
   failedAt=0;enabled(true);status('USB 已连接 · SSH 本机终端');
   await sleep(r.more||queue.length?20:120);
  }catch(e){
   if(sid!==current||gen!==generation)return;
   enabled(false);queue=[];
   if(e.fatal){status(e.message,true);api({action:'close',session:current}).catch(()=>{});sid=null;pending=null;controls();return;}
   failedAt||=Date.now();status('USB 通信暂时中断，正在恢复；输入已暂停。'+(e.name==='AbortError'?'请求超时':e.message),true);
   if(Date.now()-failedAt>90000){status('连接未恢复，维护会话已停止。请重新连接并检查上次命令结果。',true);sid=null;pending=null;controls();return;}
   // Retry only the identical numbered input; Pi acknowledges without retyping.
   await sleep(1200);
  }
 }
}
$('login').onsubmit=event=>{event.preventDefault();if(sid)return;token=$('key').value.trim()||sessionStorage.getItem('usbai-token')||'';if(!token){status('请输入面板管理密钥',true);return;}
 sessionStorage.setItem('usbai-token',token);$('key').value='';sid=Array.from(crypto.getRandomValues(new Uint8Array(32)),n=>n.toString(16).padStart(2,'0')).join('');offset=seq=0;pending=null;queue=[];sizeDirty=true;terminal.reset();enabled(false);controls();status('正在通过 USB 连接 Pi 本机 SSH…');pump(sid,++generation,$('user').value.trim());terminal.focus();};
$('close').onclick=async()=>{const old=sid;if(!old)return;sid=null;++generation;pending=null;queue=[];enabled(false);controls();try{await api({action:'close',session:old});status('已断开 SSH')}catch{status('关闭请求未确认；Pi 会在失联 90 秒后清理会话。',true)}};
$('interrupt').onclick=()=>{enqueue(new Uint8Array([3]));terminal.focus()};$('escape').onclick=()=>{enqueue(new Uint8Array([27]));terminal.focus()};
window.addEventListener('pagehide',()=>{if(sid)api({action:'close',session:sid},true).catch(()=>{})});
window.addEventListener('storage',event=>{if(event.key==='usbai-token'&&!event.newValue&&sid)$('close').click()});
if(token)$('key').placeholder='已使用当前面板登录密钥';
