'use strict';
const $=id=>document.getElementById(id);
let token=sessionStorage.getItem('usbai-token')||'';
const hash=new URLSearchParams(location.hash.slice(1));
if(hash.has('token')){token=hash.get('token');history.replaceState(null,'',location.pathname)}
let session=null,model=null,active=false,busy=false,polling=false;
const chosen=new Set();let previewFile=null,lastRender='';
async function request(route,data){const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);try{const r=await fetch('/api/'+route,{method:data===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data),signal:controller.signal});const j=await r.json();if(!r.ok){const e=Error(j.error||'请求失败');e.status=r.status;e.code=j.code;e.retryable=j.retryable;e.retryAfter=j.retry_after_ms;throw e;}return j}catch(e){if(e.name==='AbortError'){const steps={'workbench/model':'读取模型配置','status':'读取设备状态','workbench/sessions':'加载历史会话','security/pair':'校验管理密钥'};const step=route.startsWith('workbench/session?')?'加载会话内容':steps[route]||'请求 '+route.split('?')[0];const timeout=Error(step+'超过 20 秒未完成。此提示不代表 USB 已断开。');timeout.code='REQUEST_TIMEOUT';timeout.route=route.split('?')[0];throw timeout;}throw e}finally{clearTimeout(timer)}}
const api=(route,data)=>{const changed=data!==undefined&&['send','files','sessions','session-action','rename','stop','steer','answer'].includes(route)&&data.action!=='sync';if(changed)window.WorkbenchSync?.invalidate();return request('workbench/'+route,data).finally(()=>{if(changed)window.WorkbenchSync?.invalidate()})};
function notice(text=''){$('notice').textContent=text}
function download(name,text,type='text/plain;charset=utf-8'){const u=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}
async function refreshHistory(){const r=await api('sessions');historyRows=r.sessions;renderHistory();return historyRows.filter(s=>(s.state||'active')==='active')}
function renderMessageBase(m){return WorkbenchView.base(m)}
function renderBase(){WorkbenchView.render()}
const attachmentPreviews=new Map();
function fileSize(n){return n>=1048576?(n/1048576).toFixed(1)+' MiB':n>=1024?(n/1024).toFixed(1)+' KiB':n+' B'}
async function localAttachment(data,downloadFile=false){const r=await fetch('/api/attachments'+(downloadFile?'/download':''),{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(data),signal:AbortSignal.timeout(60000)});if(!r.ok){let e;try{e=await r.json()}catch{}throw Error(e?.error||'本机附件服务不可用，请更新并重启 Start-Serial.cmd')}return downloadFile?r.blob():r.json()}
async function showAttachment(f){previewFile=f;$('preview-title').textContent=f.name;$('file-preview').replaceChildren();$('download-file').disabled=false;
 if(f.kind==='file'){
  $('file-preview').textContent='正在读取本机文件…';attachmentPreviews.set(f.id,'解析中');renderFiles();
  try{const result=await localAttachment({action:'preview',reference:f.reference});attachmentPreviews.set(f.id,'可读取');if(previewFile?.id===f.id)$('file-preview').textContent=fileSize(f.size)+' · 本机原文件\n'+f.reference.path+'\n\n'+JSON.stringify(result,null,2)}
  catch(e){attachmentPreviews.set(f.id,'查看提示');if(previewFile?.id===f.id)$('file-preview').textContent='原文件已保留。\n'+e.message}
  renderFiles();
 }else if(f.kind==='image'){const image=document.createElement('img');image.src=f.content;image.alt=f.name;$('file-preview').append(image)}else $('file-preview').textContent=f.content;
}
function renderFiles(){if(!session)return;const files=session.files||[];$('files').replaceChildren();for(const f of files){const row=document.createElement('div');row.className='file';const check=document.createElement('input');check.type='checkbox';check.checked=chosen.has(f.id);check.disabled=busy;check.setAttribute('aria-label','发送时附加 '+f.name);check.onchange=()=>{check.checked?chosen.add(f.id):chosen.delete(f.id);attachSummary()};const btn=document.createElement('button');btn.textContent=f.name+(f.kind==='file'?' · '+fileSize(f.size)+' · '+(attachmentPreviews.get(f.id)||'已保存'): '');btn.onclick=()=>showAttachment(f);const remove=document.createElement('button');remove.textContent='×';remove.title='移除附件（已发送的历史副本保留）';remove.disabled=busy;remove.onclick=async()=>{try{const sid=session.id;const updated=await api('files',{id:sid,action:'remove',file_id:f.id});if(session?.id!==sid)return;session=updated;chosen.delete(f.id);if(previewFile?.id===f.id){previewFile=null;$('file-preview').textContent='已移除附件';$('download-file').disabled=true}render()}catch(e){notice(e.message)}};row.append(check,btn,remove);$('files').append(row)}attachSummary();renderPermissions()}
function attachSummary(){const root=$('attach-summary');root.replaceChildren();for(const f of session?.files||[]){if(!chosen.has(f.id))continue;const chip=document.createElement('button');chip.type='button';chip.className='tag';chip.textContent=(f.kind==='image'?'图片 · ':f.kind==='file'?'文件 · ':'')+f.name+' ×';chip.title='取消本轮附加';chip.onclick=()=>{chosen.delete(f.id);renderFiles()};root.append(chip)}}
let sessionLoadSeq=0;
async function openSession(id){saveDraft();window.WorkbenchSync?.invalidate();const loadSeq=++sessionLoadSeq;const loaded=await api('session?id='+encodeURIComponent(id));if(loadSeq!==sessionLoadSeq)return;window.WorkbenchSync?.invalidate();session=loaded;WorkbenchView.connection();chosen.clear();previewFile=null;$('file-preview').textContent='选择文件以查看内容。';$('preview-title').textContent='文件预览';$('download-file').disabled=true;lastRender='';$('prompt').value=sessionStorage.getItem('draft-'+session.id)||'';notice();render();await refreshHistory()}
async function newSession(){$('session-filter').value='active';const created=await api('sessions',{});await openSession(created.id);$('prompt').focus()}
async function loadModel(){model=await api('model');$('model-status').textContent=model.ready?((model.model||'账号默认模型')+' · '+(model.provider==='codex'?'ChatGPT 套餐':'通过树莓派代理')):(model.provider==='codex'?'请登录 ChatGPT':'模型尚未配置');return model}
async function device(){const d=await request('status');$('device-status').textContent='Mihomo '+(d.version||'未运行')+'\nWi-Fi：'+(d.wifi_ssid||'未连接')+'\nUSB：'+(d.usb.some(x=>x.state==='configured')?'已连接':'未连接数据线')}
async function connect(){
 token=$('token').value||token;await loadModel();sessionStorage.setItem('usbai-token',token);
 $('login').classList.add('hidden');$('shell').classList.remove('hidden');active=true;
 $('device-status').textContent='正在读取设备状态…';
 device().catch(e=>{$('device-status').textContent='设备状态暂时不可用：'+e.message;});
 refreshAgent();if(typeof refreshWorkflows==='function')refreshWorkflows().catch(()=>{});
 const openingAt=sessionLoadSeq;
 try{const sessions=await refreshHistory();if(openingAt!==sessionLoadSeq)return;if(sessions.length)await openSession(sessions[0].id);else await newSession();}
 catch(e){notice('已连接 Pi；历史会话加载未完成：'+e.message+' 可重新选择左侧会话，或刷新页面重试。');}
}
async function showSettings(){try{await loadModel();$('model-provider').value=model.provider==='codex'?'codex':model.has_key?'api':'codex';providerChanged();$('base-url').value=model.base_url||'';$('model-id').value=model.model;$('api-key').value='';$('model-vision').checked=!!model.vision;$('api-include-usage').checked=model.include_usage!==false;$('key-state').textContent=model.has_key?'密钥已保存在设备上；更换服务地址时需重新输入。':'尚未保存密钥。';$('default-approval-mode').value=model.default_approval_mode||'manual';$('model-error').textContent='';$('model-dialog').showModal();if($('model-provider').value==='codex')refreshCodex().then(()=>renderModelOptions()).catch(e=>{$('codex-account').textContent=e.message})}catch(e){notice(e.message)}}
let connecting=false;
async function connectFromLogin(){
 if(connecting)return;connecting=true;const button=$('connect'),label=button.textContent;button.disabled=true;button.textContent='连接中…';$('login-error').textContent='';
 const deadline=Date.now()+30000;let pairing=false,paired=false;
 try{for(;;){try{
  if(pairing){await request('security/pair',{key:$('token').value||token});pairing=false;paired=true;}
  await connect();$('login-error').textContent='';return;
 }catch(e){
  if(!pairing&&!paired&&e.status===401){pairing=true;continue;}
  if(e.code==='KEY_BUSY'&&Date.now()<deadline){$('login-error').textContent='正在校验设备密钥，请稍候…';await new Promise(r=>setTimeout(r,Math.min(1500,Math.max(300,e.retryAfter||750))));continue;}
  if(e.code==='KEY_BUSY')throw Error('设备校验超过 30 秒，请检查 USB 数据线、COM 端口及是否启动了多个客户端，然后重试。');
  throw e;
 }}}catch(e){$('login-error').textContent=e.message;}finally{connecting=false;button.disabled=false;button.textContent=label;}
}
$('connect').onclick=connectFromLogin;$('token').onkeydown=e=>{if(e.key==='Enter')$('connect').click()};
$('new-session').onclick=()=>newSession().catch(e=>notice(e.message));$('settings').onclick=showSettings;$('setup-model').onclick=showSettings;$('close-settings').onclick=()=>$('model-dialog').close();
$('model-form').onsubmit=async e=>{e.preventDefault();const button=e.submitter||$('model-form').querySelector('button[type=submit]');button.disabled=true;try{model=await api('model',$('model-provider').value==='codex'?{default_approval_mode:$('default-approval-mode').value,provider:'codex',model:$('codex-model').value,effort:$('codex-effort').value,fast:$('codex-fast').checked}:{default_approval_mode:$('default-approval-mode').value,base_url:$('base-url').value,model:$('model-id').value,api_key:$('api-key').value,vision:$('model-vision').checked,include_usage:$('api-include-usage').checked});$('api-key').value='';await loadModel();if(session){session=await api('session?id='+encodeURIComponent(session.id));render()}$('model-dialog').close();notice(model.ready?'全局默认设置已保存；继承的会话下一轮生效。':'设置已保存，请完成 ChatGPT 登录。')}catch(e){$('model-error').textContent=e.message}finally{button.disabled=false}};
$('composer').onsubmit=async e=>{e.preventDefault();if(uploadingContext){notice('请等待附件上传结束');return;}if(busy||uploadingContext||changingPermissions)return;const text=$('prompt').value.trim();if(!text)return;if(!model?.ready){notice('请先配置模型。');await showSettings();return}$('send').disabled=true;try{if(!session)await newSession();session=await api('send',{id:session.id,text,file_ids:[...chosen],plugin_ids:typeof selectedWorkflowPlugins==='undefined'?[]:[...selectedWorkflowPlugins]});$('prompt').value='';saveDraft();chosen.clear();notice();WorkbenchView.followLatest();render();window.WorkbenchSync?.retry();await refreshHistory()}catch(e){notice(e.message);$('send').disabled=false}};
$('prompt').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('composer').requestSubmit()}};
$('stop').onclick=async()=>{try{await api('stop',{id:session.id});notice('已请求停止生成。')}catch(e){notice(e.message)}};
$('rename').onclick=async()=>{if(!session)return;const title=window.prompt('会话名称',session.title);if(!title)return;try{session=await api('rename',{id:session.id,title});render();await refreshHistory()}catch(e){notice(e.message)}};
$('export').onclick=()=>{if(session)download('会话-'+session.id+'.json',JSON.stringify(session,null,2),'application/json;charset=utf-8')};
$('upload').onclick=()=>$('file-input').click();$('file-input').onchange=()=>uploadContext($('file-input').files);
$('download-file').onclick=async()=>{if(!previewFile)return;const f=previewFile;try{if(f.kind==='file'){const blob=await localAttachment({reference:f.reference},true);download(f.name,blob,'application/octet-stream')}else if(f.kind==='image'){const a=document.createElement('a');a.href=f.content;a.download=f.name;a.click()}else download(f.name,f.content)}catch(e){notice(e.message)}};
$('logout').onclick=()=>{sessionStorage.removeItem('usbai-token');token='';active=false;$('shell').classList.add('hidden');$('login').classList.remove('hidden');$('token').value=''};
setInterval(()=>{if(active)device().catch(()=>{})},20000);



let agentBusy=false,agentState=null,manualFilesPath='.',lastAgentJobs='';
function toolCard(t){const d=document.createElement('details');d.className='tool-card';const summary=document.createElement('summary');const names={preparing:'准备中',reviewing:'AI 审批中',approval:'等待确认',queued:'排队中',running:'执行中',done:'完成',error:'失败',denied:'已拒绝',expired:'超时',cancelled:'已取消'};summary.textContent=t.name+' · '+(names[t.status]||t.status);d.append(summary);const pre=document.createElement('pre');const result={...(t.result||{})};delete result.image;pre.textContent=JSON.stringify({arguments:t.arguments,result},null,2);d.append(pre);if(t.review){const review=document.createElement('p');review.className='review-reason';review.textContent=t.review.reviewer+' · '+t.review.decision+'：'+t.review.reason;d.append(review)}if(t.approval_mode==='full'){const p=document.createElement('p');p.textContent='本会话选择了默认全通过';d.append(p)}if(t.result?.image?.startsWith('data:image/jpeg;base64,')){const img=document.createElement('img');img.src=t.result.image;img.alt='工具返回的截图';d.append(img)}if(t.status==='approval'){d.open=true;const text=document.createElement('p');text.textContent=t.name==='shell'?'此命令使用当前 Windows 用户权限，可访问工作目录之外的内容。':'确认执行上面列出的操作。';d.append(text);for(const [label,allow] of [['允许执行',true],['拒绝',false]]){const b=document.createElement('button');b.textContent=label;b.onclick=async()=>{b.disabled=true;try{await request('agent/approve',{job_id:t.job_id||t.id,allow});await refreshAgent()}catch(e){notice(e.message)}};d.append(b)}}return d}
async function refreshAgent(){if(agentBusy||!active)return;agentBusy=true;try{agentState=await request('agent/status');$('agent-status').textContent=agentState.online?'Windows 工具在线':'配套程序未连接';$('agent-workspace').textContent=agentState.online?agentState.client.name+'\n'+agentState.client.workspace:'请在 Windows 运行 Start-Agent.cmd';for(const id of ['browse-root','browser-tabs'])$(id).disabled=!agentState.online;const jobs=agentState.jobs.filter(j=>!j.session_id||j.status==='approval');const jobsText=JSON.stringify(jobs);if(jobsText!==lastAgentJobs){lastAgentJobs=jobsText;$('agent-jobs').replaceChildren(...jobs.slice(-6).reverse().map(toolCard));}for(const job of jobs){if(job.name==='files'&&job.arguments.op==='list'&&job.status==='done'&&job.id!==$('agent-files').dataset.job){$('agent-files').dataset.job=job.id;renderDiskFiles(job.result)}}}catch(e){$('agent-status').textContent='连接中断'}finally{agentBusy=false}}
async function runTool(name,args){try{const j=await request('agent/run',{name,arguments:args});notice('工具任务已提交：'+name);await refreshAgent();return j}catch(e){notice(e.message)}}
function renderDiskFiles(result){manualFilesPath=result.path||'.';const root=$('agent-files');root.replaceChildren();const title=document.createElement('div');title.textContent=manualFilesPath;root.append(title);const up=document.createElement('button');up.textContent='上一级';up.onclick=()=>{const parts=manualFilesPath.replaceAll('\\','/').split('/').filter(p=>p&&p!=='.');parts.pop();runTool('files',{op:'list',path:parts.join('/')||'.'})};root.append(up);for(const f of result.entries||[]){const b=document.createElement('button');b.textContent=(f.type==='directory'?'▸ ':'')+f.name;b.disabled=f.type==='link';b.onclick=()=>runTool('files',{op:f.type==='directory'?'list':'read',path:(manualFilesPath==='.'?'':manualFilesPath+'/')+f.name});root.append(b)}}
$('browse-root').onclick=()=>runTool('files',{op:'list',path:'.'});$('browser-tabs').onclick=()=>runTool('browser',{op:'tabs'});
setInterval(()=>refreshAgent(),2000);

let codexRefreshing=false,codexModelsLoaded=false;
function providerChanged(){const useCodex=$('model-provider').value==='codex';$('codex-settings').classList.toggle('hidden',!useCodex);$('api-settings').classList.toggle('hidden',useCodex);for(const id of ['base-url','model-id'])$(id).required=!useCodex;}
$('model-provider').onchange=()=>{providerChanged();if($('model-provider').value==='codex')refreshCodex().then(()=>renderModelOptions()).catch(e=>{$('codex-account').textContent=e.message})};
async function refreshCodex(){
 if(codexRefreshing)return;codexRefreshing=true;
 try{
  const s=await api('codex',{action:'status'}),l=s.login||{};
  $('codex-account').textContent=s.logged_in?'已登录：'+(s.account?.email||'ChatGPT')+' · '+(s.account?.planType||''):s.error||l.error||({starting:'正在生成授权码…',waiting:'等待你在官方页面完成登录',expired:'授权码已过期，请重新登录'}[l.state]||'尚未登录');
  $('codex-login').disabled=s.logged_in||['starting','waiting'].includes(l.state);$('codex-logout').disabled=!s.logged_in&&!['waiting'].includes(l.state);
  const waiting=!s.logged_in&&l.state==='waiting';$('codex-authorization').classList.toggle('hidden',!waiting);
  if(waiting){const url=new URL(l.url);if(url.origin!=='https://auth.openai.com')throw Error('授权地址异常');$('codex-auth-link').href=url.href;$('codex-code').textContent=l.code;}
  if(s.logged_in&&!codexModelsLoaded){const r=await api('codex',{action:'models'});modelCatalog=r.models;const select=$('codex-model');select.replaceChildren(new Option('使用账号默认模型',''),...r.models.map(m=>new Option(m.displayName||m.model,m.model)));select.value=model?.provider==='codex'?model.model||'':'';codexModelsLoaded=true;renderModelOptions();}
  if(s.logged_in){try{const r=await api('codex',{action:'limits'});const limits=Object.values(r.rateLimitsByLimitId||{codex:r.rateLimits}).filter(Boolean);$('codex-limits').textContent=limits.map(l=>{const parts=[l.primary,l.secondary].filter(Boolean).map(w=>Math.max(0,100-w.usedPercent)+'% 剩余'+(w.resetsAt?'（'+new Date(w.resetsAt*1000).toLocaleString()+' 重置）':''));return (l.limitName||l.limitId||'用量')+'：'+parts.join(' / ')}).join('；')||'用量暂不可用';}catch{$('codex-limits').textContent='已登录，用量暂不可用';}if(model?.provider==='codex'&&!model.ready)await loadModel();}
 }finally{codexRefreshing=false}
}
$('codex-login').onclick=async()=>{try{$('codex-login').disabled=true;await api('model',{provider:'codex',model:$('codex-model').value});await api('codex',{action:'login'});await loadModel();await refreshCodex()}catch(e){$('codex-account').textContent=e.message;$('codex-login').disabled=false}};
$('codex-logout').onclick=async()=>{try{await api('codex',{action:'logout'});codexModelsLoaded=false;await loadModel();await refreshCodex()}catch(e){$('codex-account').textContent=e.message}};
$('codex-refresh').onclick=()=>{codexModelsLoaded=false;refreshCodex().catch(e=>{$('codex-account').textContent=e.message})};
setInterval(()=>{if(active&&$('model-dialog').open&&$('model-provider').value==='codex')refreshCodex().catch(()=>{})},5000);

$('security-settings').onclick=async()=>{try{const s=await request('security/status');$('security-notice').textContent=s.recovery?s.error:s.backup_stale?'当前密钥已变更，请导出新的加密配置。':'';$('security-dialog').showModal()}catch(e){notice('密钥设置需要新版 Windows 串口启动器：'+e.message)}};
$('close-security').onclick=()=>{$('security-dialog').close();for(const id of ['new-admin-key','confirm-admin-key','backup-password','backup-confirm'])$(id).value=''};
$('security-form').onsubmit=async e=>{e.preventDefault();const newKey=$('new-admin-key').value,confirmKey=$('confirm-admin-key').value;if(newKey!==confirmKey){$('security-notice').textContent='两次输入不一致';return}const button=$('change-admin-key');button.disabled=true;$('security-notice').textContent='正在同步，请保持 USB 连接…';try{await request('security/change-key',{new_key:newKey,confirm_key:confirmKey});token=newKey;sessionStorage.setItem('usbai-token',token);$('token').value='';$('new-admin-key').value='';$('confirm-admin-key').value='';$('security-notice').textContent='两端密钥已更新，当前页面保持登录。请导出新的加密配置。';await loadModel()}catch(e){$('security-notice').textContent=e.message+'；若连接已恢复但此页失效，请退出后使用新密钥连接。'}finally{button.disabled=false}};
$('export-device-backup').onclick=async()=>{const b=$('export-device-backup');b.disabled=true;try{const data=await request('security/backup',{password:$('backup-password').value,confirm_password:$('backup-confirm').value});download('device.sealed.json',JSON.stringify(data,null,2),'application/json');$('backup-password').value='';$('backup-confirm').value='';$('security-notice').textContent='已导出并更新本机加密配置，请保管好备份解锁口令。'}catch(e){$('security-notice').textContent=e.message}finally{b.disabled=false}};

let historyRows=[],modelCatalog=[];
const effortNames={low:'低',medium:'中',high:'高',xhigh:'极高',max:'最大'};
const questionDrafts=new Map();
function renderHistory(){
 const filter=$('session-filter').value,query=$('session-search').value.toLocaleLowerCase();
 const rows=historyRows.filter(s=>(s.state||'active')===filter&&s.title.toLocaleLowerCase().includes(query));
 $('session-list').replaceChildren(...rows.map(s=>{const b=document.createElement('button');b.textContent=(s.pinned?'★ ':'')+(s.running?'● ':'')+s.title;b.title=s.title;b.classList.toggle('selected',s.id===session?.id);b.onclick=()=>openSession(s.id).catch(e=>notice(e.message));return b}));
 if(!rows.length){const p=document.createElement('p');p.className='muted';p.textContent='暂无符合条件的会话';$('session-list').append(p)}
}
$('session-filter').onchange=()=>refreshHistory().catch(e=>notice(e.message));$('session-search').oninput=renderHistory;
function renderModelOptions(reset=false){
 const m=modelCatalog.find(m=>m.model===$('codex-model').value)||modelCatalog.find(m=>m.isDefault);
 const selected=reset?'':model?.effort||'';
 const efforts=(m?.supportedReasoningEfforts||[]).filter(e=>Object.hasOwn(effortNames,e.reasoningEffort));
 $('codex-effort').replaceChildren(new Option('模型默认'+(m?.defaultReasoningEffort?'（'+(effortNames[m.defaultReasoningEffort]||m.defaultReasoningEffort)+'）':''),''),...efforts.map(e=>new Option(effortNames[e.reasoningEffort],e.reasoningEffort)));
 $('codex-effort').value=efforts.some(e=>e.reasoningEffort===selected)?selected:'';
 const fast=m?.serviceTiers?.find(t=>t.id==='priority');$('codex-fast').disabled=!fast;$('codex-fast').checked=!!fast&&(reset?false:!!model?.fast);
 $('codex-fast-hint').textContent=fast?'优先处理，会增加套餐用量消耗。实际可用性和速度由账号及服务端决定。':'当前模型未提供快速模式。';
}
$('codex-model').onchange=()=>renderModelOptions(true);
function saveDraft(){if(session)sessionStorage.setItem('draft-'+session.id,$('prompt').value)}
$('prompt').addEventListener('input',saveDraft);
$('session-action').onchange=async()=>{
 const action=$('session-action').value;$('session-action').value='';if(!action||!session)return;
 if(action==='trash'&&!confirm('将“'+session.title+'”移到回收站？可以还原。'))return;
 if(action==='purge'&&!confirm('永久删除“'+session.title+'”及其附件和 Codex 会话？此操作无法撤销。'))return;
 try{const id=session.id,result=await api('session-action',{id,action,confirm:action==='purge'?id:undefined});
  if(action==='purge'){sessionStorage.removeItem('draft-'+id);session=null;const rows=await refreshHistory();if(rows.length)await openSession(rows[0].id);else await newSession();notice('会话已永久删除。');}
  else{if(action==='fork')$('session-filter').value='active';await openSession(result.id);$('session-filter').value=result.state||'active';renderHistory();notice(action==='fork'?'已创建独立分支，原会话保留。':'会话已更新。')}
 }catch(e){notice(e.message)}
};
function render(){
 renderBase();if(!session)return;renderRegenerationState();
 const closed=(session.state||'active')!=='active';$('send').disabled=busy||closed||uploadingContext;$('upload').disabled=busy||closed;
 $('steer').classList.toggle('hidden',!busy||session.provider!=='codex');$('steer').disabled=closed;
 $('session-action').disabled=busy;$('prompt').placeholder=closed?'请先恢复会话再继续':'描述任务…';
 const state={archived:'已归档 · 取消归档后可继续',trash:'回收站 · 还原后可继续'}[session.state];
 const usage=session.token_usage,last=usage?.last;
 const tokens=usage?.total?'Codex 线程累计 '+(usage.total.totalTokens||0).toLocaleString()+' tokens（独立审批另计）':'';
 $('session-status').textContent=[busy?WorkbenchView.phase(session.messages.at(-1)):null,state,tokens].filter(Boolean).join(' · ');
 if(session.settings)renderPermissions();
 else if(model?.provider==='codex'&&model.ready)$('model-status').textContent=(model.model||'账号默认模型')+' · 思考 '+(effortNames[model.effort]||'默认')+' · '+(model.fast?'快速':'标准');
}
$('steer').onclick=async()=>{const text=$('prompt').value.trim();if(!text)return;const b=$('steer');b.disabled=true;try{await api('steer',{id:session.id,text});$('prompt').value='';saveDraft();notice('补充指令已发送到当前任务。')}catch(e){notice(e.message)}finally{b.disabled=false}};
function renderMessage(m){
 const box=renderMessageBase(m);appendRegenerationActions(box,m);for(const plugin of m.plugins||[]){const tag=document.createElement('span');tag.className='tag';tag.textContent='插件：'+plugin.title;box.append(tag)}
 {const copy=document.createElement('button');copy.className='copy-message';copy.textContent='复制';copy.onclick=()=>navigator.clipboard.writeText(box._message.content).then(()=>notice('已复制')).catch(()=>notice('浏览器未允许剪贴板访问，请手动选择文本'));box.append(copy)}
 if(m.settings?.effort){const p=document.createElement('small');p.className='turn-settings';p.textContent='本轮：'+(effortNames[m.settings.effort]||m.settings.effort)+' · '+(m.settings.serviceTier==='priority'?'快速（已请求）':'标准');box.append(p)}
 if(m.plan?.length){const d=document.createElement('details');d.className='tool-card';d.open=m.status==='streaming';const s=document.createElement('summary');s.textContent='任务计划';d.append(s);for(const step of m.plan){const p=document.createElement('p');p.textContent=({pending:'○ ',inProgress:'◉ ',completed:'✓ '}[step.status]||'')+step.step;d.append(p)}box.append(d)}
 for(const item of m.steering||[]){const p=document.createElement('p');p.className='steering-note';p.textContent='你的补充指令：'+item.text;box.append(p)}
 for(const request of m.questions||[]){
  const form=document.createElement('form');form.className='question-card';const title=document.createElement('strong');title.textContent=request.status==='waiting'?'需要你的回答':request.status==='answered'?'问题已回答':'问题已结束';form.append(title);
  const inputs=[];
  for(const q of request.questions){const label=document.createElement('label');label.textContent=q.question;const input=document.createElement('input');input.type=q.isSecret?'password':'text';input.maxLength=4000;input.required=true;input.disabled=request.status!=='waiting';input.placeholder='选择建议选项或输入回答';const key=request.id+':'+q.id;input.value=questionDrafts.get(key)||'';input.oninput=()=>questionDrafts.set(key,input.value);label.append(input);form.append(label);inputs.push([q.id,input]);
   if(request.status==='waiting')for(const o of q.options||[]){const b=document.createElement('button');b.type='button';b.textContent=o.label;b.title=o.description;b.onclick=()=>{input.value=o.label;questionDrafts.set(key,o.label)};form.append(b)}
  }
  if(request.status==='waiting'){const b=document.createElement('button');b.type='submit';b.textContent='提交回答';b.className='primary';form.append(b);form.onsubmit=async e=>{e.preventDefault();b.disabled=true;try{await api('answer',{id:session.id,request_id:request.id,answers:Object.fromEntries(inputs.map(([id,input])=>[id,input.value]))});for(const q of request.questions)questionDrafts.delete(request.id+':'+q.id);notice('已提交回答。')}catch(e){notice(e.message);b.disabled=false}}}
  box.append(form);
 }
 return box;
}
$('export-md').onclick=()=>{if(session){const content='# '+session.title+'\n\n'+session.messages.map(m=>'## '+(m.role==='user'?'你':'助手')+'\n\n'+m.content+(m.steering?.length?'\n\n补充指令：\n'+m.steering.map(s=>'- '+s.text).join('\n'):'')).join('\n\n');download('会话-'+session.id+'.md',content,'text/markdown;charset=utf-8')}};
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.shiftKey&&e.key.toLowerCase()==='o'&&active&&!document.querySelector('dialog[open]')){e.preventDefault();newSession().catch(e=>notice(e.message))}});
window.addEventListener('DOMContentLoaded',()=>{if(token)connectFromLogin()});


// Composer context and per-session Windows approval policy.
let changingPermissions=false,uploadingContext=false;
const approvalNames={manual:'自行审批',assist:'帮我审批',full:'默认全通过'};
function renderPermissions(){
 if(!session||changingPermissions)return;
 const settings=session.settings,mode=settings?.approval_mode||session.approval_mode||model?.default_approval_mode||'manual';
 $('approval-mode').value=session.approval_mode||'inherit';$('approval-mode').disabled=busy;
 $('approval-mode').options[0].textContent='继承全局（'+(approvalNames[settings?.default_approval_mode||model?.default_approval_mode||'manual'])+'）';
 $('approval-hint').textContent=(session.approval_mode?'此会话单独设置：':'继承全局：')+approvalNames[mode]+'。'+{manual:'命令和文件删除等待你批准。',assist:'独立 AI 审查命令和删除，判断不清时交给你；会使用 Codex 用量。',full:'命令和删除自动放行。PowerShell 使用当前 Windows 用户权限。'}[mode];
 $('approval-hint').classList.toggle('full-access',mode==='full');renderSessionModelSummary();
}
$('approval-mode').onchange=async()=>{if(!session||busy)return;const sid=session.id;changingPermissions=true;$('approval-mode').disabled=true;try{const updated=await api('session-action',{id:sid,action:'permissions',mode:$('approval-mode').value});if(session?.id===sid)session=updated;notice('已保存此会话的审批方式。')}catch(e){notice(e.message)}finally{changingPermissions=false;renderPermissions()}};
function closeContextMenu(){$('context-menu').classList.add('hidden');$('add-context').setAttribute('aria-expanded','false')}
$('add-context').onclick=()=>{const show=$('context-menu').classList.contains('hidden');$('context-menu').classList.toggle('hidden',!show);$('add-context').setAttribute('aria-expanded',String(show))};
for(const [id,target] of [['context-files','file-input'],['context-plugins','plugins-open'],['context-workspace','browse-root'],['context-schedules','schedules-open']])$(id).onclick=()=>{closeContextMenu();$(target).click()};
document.addEventListener('click',e=>{if(!e.target.closest('.composer-add'))closeContextMenu()});document.addEventListener('keydown',e=>{if(e.key==='Escape')closeContextMenu()});
async function imageContext(file){
 if(file.size>12000000)throw Error('原图最多 12 MB');
 const bitmap=await createImageBitmap(file);try{
  let scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height));const canvas=document.createElement('canvas');
  for(let attempt=0;attempt<5;attempt++){canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);const content=canvas.toDataURL('image/jpeg',.85-attempt*.08);if(content.length<210000)return {kind:'image',content,name:file.name.replace(/\.[^.]+$/,'')+'.jpg'};scale*=.78}
  throw Error('图片压缩后仍过大，请裁剪后重试');
 }finally{bitmap.close()}
}
let cancelAttachmentUpload=false;
$('cancel-upload').onclick=()=>{cancelAttachmentUpload=true;notice('正在取消当前上传…')};
async function uploadBinary(file,sid){
 if(!model?.file_attachments){await loadModel();if(!model?.file_attachments)throw Error('Pi 后端需要安装本次文档附件更新；旧后端只支持文本和图片。')}
 if(file.size>100000000)throw Error(file.name+' 超过 100 MB');
 const begin=await localAttachment({action:'begin',session:sid,name:file.name,bytes:file.size});let done=false;
 try{
  for(let offset=0;offset<file.size;offset+=begin.chunk_bytes){
   if(cancelAttachmentUpload)throw Error('已取消上传');
   const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('无法读取文件'));reader.readAsDataURL(file.slice(offset,offset+begin.chunk_bytes))});
   const r=await localAttachment({action:'chunk',upload_id:begin.upload_id,offset,content});$('upload-progress').value=Math.round(r.received/Math.max(1,file.size)*100);notice('正在添加 '+file.name+' · '+$('upload-progress').value+'%');
  }
  if(cancelAttachmentUpload)throw Error('已取消上传');
  const result=await localAttachment({action:'finish',upload_id:begin.upload_id});done=true;return result;
 }finally{if(!done)await localAttachment({action:'abort',upload_id:begin.upload_id}).catch(()=>{})}
}
async function uploadContext(files){
 if(busy||uploadingContext){notice('请等待当前操作结束后添加附件');return}uploadingContext=true;cancelAttachmentUpload=false;$('upload-progress').classList.remove('hidden');$('cancel-upload').classList.remove('hidden');$('send').disabled=true;
 let added=0;
 try{if(!session)await newSession();const sid=session.id;
  for(const f of [...files]){if(cancelAttachmentUpload)throw Error('已取消上传');if(session?.id===sid&&session.files.length>=20)throw Error('每个会话最多 20 个附件');$('upload-progress').value=0;notice('正在添加 '+f.name);let data;
   if(/^image\/(png|jpeg|webp)$/.test(f.type))data=await imageContext(f);
   else if(f.size<=64000&&/\.(txt|md|json|ya?ml|py|js|ts|html|css|log|xml|sql|ps1|sh)$/i.test(f.name)){const content=new TextDecoder('utf-8',{fatal:true}).decode(await f.arrayBuffer());if(content.includes('\u0000'))throw Error('此文件不是 UTF-8 文本');data={name:f.name,content,kind:'text'}}
   else data=await uploadBinary(f,sid);
   const updated=await api('files',{id:sid,...data});added++;if(session?.id===sid){session=updated;chosen.add(updated.files.at(-1).id);render()}
  }
  notice('已添加 '+added+' 个附件并选中。文档原件保存在 Windows 工作目录，发送后由工具按需读取；图片仍为压缩副本。');
 }catch(e){notice((added?'已添加 '+added+' 个；':'')+e.message)}finally{uploadingContext=false;$('file-input').value='';$('upload-progress').classList.add('hidden');$('cancel-upload').classList.add('hidden');$('send').disabled=busy}
}
$('composer').addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();$('composer').classList.add('dragover')}});
$('composer').addEventListener('dragleave',()=>$('composer').classList.remove('dragover'));
$('composer').addEventListener('drop',e=>{e.preventDefault();$('composer').classList.remove('dragover');if(e.dataTransfer.files.length)uploadContext(e.dataTransfer.files)});
async function pasteWindowsFiles(){
 if(busy||uploadingContext){notice('请等待当前操作结束后粘贴文件');return}
 uploadingContext=true;cancelAttachmentUpload=false;$('send').disabled=true;$('upload-progress').classList.remove('hidden');$('cancel-upload').classList.remove('hidden');let added=0;
 try{
  if(!model?.file_attachments){await loadModel();if(!model?.file_attachments)throw Error('请先安装 Pi 文档附件更新')}
  if(!session)await newSession();const sid=session.id;notice('正在读取 Windows 文件剪贴板…');
  const {files}=await localAttachment({action:'clipboard-list'});if(!files.length)throw Error('剪贴板中没有文件。请在资源管理器选中文件并按 Ctrl+C，再点击“粘贴 Windows 文件”；也可拖入或选择文件。');
  if(files.length+session.files.length>20)throw Error('每个会话最多 20 个附件，请减少本次选择');
  for(const f of files){
   if(cancelAttachmentUpload)throw Error('已取消剩余文件');notice('正在复制 '+f.name+' · '+fileSize(f.bytes));
   const data=await localAttachment({action:'clipboard-import',session:sid,id:f.id});
   const updated=await api('files',{id:sid,...data});added++;$('upload-progress').value=Math.round(added/files.length*100);
   if(session?.id===sid){session=updated;chosen.add(updated.files.at(-1).id);render()}
  }
  notice('已从 Windows 剪贴板添加 '+added+' 个文件。原文件保持不变，附件副本保存在工作目录。');
 }catch(e){notice((added?'已添加 '+added+' 个；':'')+e.message)}finally{uploadingContext=false;$('send').disabled=busy;$('upload-progress').classList.add('hidden');$('cancel-upload').classList.add('hidden')}
}
$('context-paste').onclick=()=>{closeContextMenu();pasteWindowsFiles()};
$('prompt').addEventListener('paste',e=>{const files=[...e.clipboardData.items].filter(x=>x.kind==='file').map(x=>x.getAsFile()).filter(Boolean);if(files.length){e.preventDefault();uploadContext(files)}else if(!e.clipboardData.getData('text/plain')&&!e.clipboardData.getData('text/html')){e.preventDefault();pasteWindowsFiles()}});

// Per-session model overrides contain no provider credentials.
let sessionModelTarget=null,sessionModelProvider='codex',sessionModelCatalog=[],sessionModelSaved=null;
function renderSessionModelSummary(){
 if(!session?.settings)return;const s=session.settings,m=s.model;
 $('session-settings').disabled=busy;
 $('model-status').textContent=(s.provider_conflict?'连接方式已改变，请更新会话模型 · ':'')+(m.model||'账号默认模型')+' · '+(s.model_source==='session'?'此会话单独设置':'继承全局')+(m.effort?' · 思考：'+(effortNames[m.effort]||m.effort):'')+(m.fast?' · 快速':'');
}
function sessionModelOptions(reset=false){
 const m=sessionModelCatalog.find(m=>m.model===$('session-codex-model').value)||sessionModelCatalog.find(m=>m.isDefault);
 const efforts=(m?.supportedReasoningEfforts||[]).filter(e=>Object.hasOwn(effortNames,e.reasoningEffort));
 $('session-effort').replaceChildren(new Option('模型默认',''),...efforts.map(e=>new Option(effortNames[e.reasoningEffort],e.reasoningEffort)));
 $('session-effort').value=reset?'':sessionModelSaved?.effort||'';
 const fast=m?.serviceTiers?.some(t=>t.id==='priority');$('session-fast').disabled=!fast;$('session-fast').checked=!!fast&&!reset&&!!sessionModelSaved?.fast;
}
$('session-model-source').onchange=()=>{$('session-model-fields').disabled=$('session-model-source').value==='global'};
$('session-codex-model').onchange=()=>sessionModelOptions(true);
$('session-settings').onclick=async()=>{
 if(!session||busy)return;const sid=session.id;$('session-settings').disabled=true;
 try{await loadModel();const doc=await api('session?id='+encodeURIComponent(sid));if(session?.id!==sid)return;session=doc;
  sessionModelTarget=sid;sessionModelProvider=model.provider==='codex'?'codex':'api';sessionModelSaved=doc.settings.model;
  $('session-model-source').value=doc.model_override?'session':'global';$('session-model-source').onchange();
  $('session-model-summary').textContent='全局默认：'+(model.model||'账号默认模型')+'。保存后从下一轮生效，可随时恢复继承全局。';
  $('session-codex-model').classList.toggle('hidden',sessionModelProvider!=='codex');$('session-codex-options').classList.toggle('hidden',sessionModelProvider!=='codex');
  $('session-api-model').classList.toggle('hidden',sessionModelProvider!=='api');$('session-api-model-label').classList.toggle('hidden',sessionModelProvider!=='api');$('session-api-model').value=sessionModelSaved.model||'';
  $('session-model-error').textContent='';
  if(sessionModelProvider==='codex'){const r=await api('codex',{action:'models'});if(session?.id!==sid)return;sessionModelCatalog=r.models;$('session-codex-model').replaceChildren(new Option('账号默认模型',''),...r.models.map(m=>new Option(m.displayName||m.model,m.model)));if(sessionModelSaved.model&&!r.models.some(m=>m.model===sessionModelSaved.model))$('session-codex-model').add(new Option(sessionModelSaved.model+'（需重新选择）',sessionModelSaved.model));$('session-codex-model').value=sessionModelSaved.model||'';sessionModelOptions()}
  $('session-model-dialog').showModal();renderSessionModelSummary();
 }catch(e){notice(e.message)}finally{$('session-settings').disabled=busy}
};
$('session-model-close').onclick=()=>$('session-model-dialog').close();
$('session-model-form').onsubmit=async e=>{
 e.preventDefault();if(!sessionModelTarget)return;const button=e.submitter||$('session-model-form').querySelector('button[type=submit]');button.disabled=true;
 try{const override=$('session-model-source').value==='global'?null:{provider:sessionModelProvider,model:sessionModelProvider==='codex'?$('session-codex-model').value:$('session-api-model').value,effort:sessionModelProvider==='codex'?$('session-effort').value:'',fast:sessionModelProvider==='codex'&&$('session-fast').checked};
  const updated=await api('session-action',{id:sessionModelTarget,action:'model-settings',override});if(session?.id===sessionModelTarget){session=updated;render()}
  $('session-model-dialog').close();notice(override?'已保存此会话模型；下一轮生效。':'此会话已恢复继承全局模型。');
 }catch(e){$('session-model-error').textContent=e.message}finally{button.disabled=false}
};

function priceProviderChanged(){$('price-endpoint').disabled=$('price-provider').value!=='api';$('price-endpoint').required=!$('price-endpoint').disabled}
$('price-provider').onchange=priceProviderChanged;
function fillPrice(r){for(const key of ['provider','endpoint','model','tier','currency','input','cached','cache_write','output'])$('price-'+key).value=r[key]??'';priceProviderChanged()}
function priceList(data){
 $('usage-price-source').replaceChildren(document.createTextNode('内置参考核对日期 '+data.checked_at+' · '+data.builtin_models.join('、')+'。 '));
 for(const [label,url] of [['API 价格','https://developers.openai.com/api/docs/pricing'],['套餐计费说明','https://learn.chatgpt.com/docs/pricing']]){const a=document.createElement('a');a.textContent=label+' ';a.href=url;a.target='_blank';a.rel='noopener noreferrer';$('usage-price-source').append(a)}
 $('usage-price-list').replaceChildren();for(const r of data.rates){const row=document.createElement('div');row.className='usage-price-row';const name=document.createElement('span');name.textContent=(r.provider==='codex'?'套餐参考':'API')+' · '+r.model+' · '+r.tier+' · '+r.currency+(r.endpoint?' · '+r.endpoint:'');const edit=document.createElement('button');edit.type='button';edit.textContent='编辑';edit.onclick=()=>fillPrice(r);const del=document.createElement('button');del.type='button';del.textContent='移除';del.onclick=async()=>{try{priceList(await api('model',{action:'prices',operation:'delete',rate:r}))}catch(e){$('usage-price-error').textContent=e.message}};row.append(name,edit,del);$('usage-price-list').append(row)}
}
window.showUsagePrices=async()=>{try{const data=await api('model',{action:'prices'});fillPrice({provider:model?.provider==='codex'?'codex':'api',endpoint:model?.base_url||'',model:session?.settings?.model?.model||model?.model||'',tier:session?.settings?.model?.fast?'priority':'standard',currency:'USD'});priceList(data);$('usage-price-error').textContent='';if(!$('usage-prices-dialog').open)$('usage-prices-dialog').showModal()}catch(e){notice(e.message)}};
$('usage-prices-open').onclick=window.showUsagePrices;$('usage-prices-close').onclick=()=>$('usage-prices-dialog').close();
$('usage-prices-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter||$('usage-prices-form').querySelector('button[type=submit]');b.disabled=true;try{const rate={};for(const k of ['provider','endpoint','model','tier','currency'])rate[k]=$('price-'+k).value.trim();for(const k of ['input','cached','cache_write','output'])rate[k]=Number($('price-'+k).value);priceList(await api('model',{action:'prices',operation:'save',rate}));$('usage-price-error').textContent='已保存；用于接下来发起的轮次。'}catch(e){$('usage-price-error').textContent=e.message}finally{b.disabled=false}};

let regeneration=null,regenerating=false,regenerationCatalog=[];
function appendRegenerationActions(box,m){
 if(!m.id)return;const row=document.createElement('div');row.className='message-actions';
 const actions=m.role==='user'?[['编辑并重新生成','edit']]:m.role==='assistant'?[['重新生成','retry'],['换模型生成','model']]:[];
 for(const [label,kind] of actions){const b=document.createElement('button');b.type='button';b.className='regenerate-action';b.textContent=label;b.onclick=()=>openRegeneration(box._message.id,kind);row.append(b)}box.append(row);
}
function renderRegenerationState(){
 const disabled=busy||regenerating||session.state==='trash'||!model?.regenerate;
 document.querySelectorAll('.regenerate-action').forEach(b=>{b.disabled=disabled;b.hidden=!model?.regenerate});
 const root=$('branch-navigation');if(!root)return;const key=JSON.stringify([session.id,session.branch,historyRows.map(r=>[r.id,r.title,r.state,r.branch?.parent_id])]);if(root._key===key)return;root._key=key;root.replaceChildren();
 const family=historyRows.filter(r=>(r.branch?.parent_id===session.id||session.branch&&r.branch?.parent_id===session.branch.parent_id)&&r.state!=='trash');
 if(session.branch){const text=document.createElement('span');text.textContent='来自「'+session.branch.parent_title+'」第 '+session.branch.turn+' 轮 · '+(session.branch.edited?'编辑后生成':'重新生成');const back=document.createElement('button');back.type='button';back.textContent='返回原会话';back.onclick=()=>openSession(session.branch.parent_id).catch(e=>notice(e.message));root.append(text,back)}
 if(family.length){const select=document.createElement('select');select.setAttribute('aria-label','切换生成分支');select.append(new Option('切换生成分支…',''));for(const r of family)select.append(new Option(r.title+(r.id===session.id?'（当前）':''),r.id));select.onchange=()=>{if(select.value)openSession(select.value).catch(e=>notice(e.message))};root.append(select)}
 root.classList.toggle('hidden',!root.childNodes.length);
}
function regenerationOptions(reset=false){
 const chosen=regenerationCatalog.find(m=>m.model===$('regenerate-codex-model').value)||regenerationCatalog.find(m=>m.isDefault),saved=regeneration?.settings||{};
 $('regenerate-effort').replaceChildren(new Option('模型默认',''),...(chosen?.supportedReasoningEfforts||[]).filter(e=>Object.hasOwn(effortNames,e.reasoningEffort)).map(e=>new Option(effortNames[e.reasoningEffort],e.reasoningEffort)));
 $('regenerate-effort').value=reset?'':saved.effort||'';const fast=chosen?.serviceTiers?.some(t=>t.id==='priority');$('regenerate-fast').disabled=!fast;$('regenerate-fast').checked=!!fast&&!reset&&!!saved.fast;
}
$('regenerate-codex-model').onchange=()=>regenerationOptions(true);
$('regenerate-mode').onchange=()=>{$('regenerate-model-fields').hidden=$('regenerate-mode').value!=='custom';$('regenerate-model-fields').disabled=$('regenerate-mode').value!=='custom'};
async function openRegeneration(mid,kind){
 if(!session||busy||regenerating)return;const sid=session.id;
 try{const doc=await api('session?id='+encodeURIComponent(sid));if(session?.id!==sid)return;
  let index=doc.messages.findIndex(m=>m.id===mid);if(index<0)throw Error('消息已不存在');if(doc.messages[index].role==='assistant')index--;const user=doc.messages[index],reply=doc.messages[index+1]?.role==='assistant'?doc.messages[index+1]:{};if(user?.role!=='user')throw Error('没有对应提问');
  const snap=reply.settings_snapshot||user.settings_snapshot||doc.settings.model,provider=doc.provider||model.provider||'api';
  regeneration={id:sid,message_id:user.id,kind,provider,settings:{model:reply.model||snap.model||doc.settings.model.model,effort:snap.effort||reply.settings?.effort||'',fast:snap.fast??(reply.settings?.serviceTier==='priority')}};
  $('regenerate-title').textContent=kind==='edit'?'编辑提问并重新生成':kind==='model'?'换用模型生成':'重新生成';$('regenerate-text').value=user.content;$('regenerate-text').readOnly=kind!=='edit';
  $('regenerate-context').textContent='保留原提问的附件：'+((user.attachments||[]).map(f=>f.name).join('、')||'无')+'；插件：'+((user.plugins||[]).map(p=>p.title).join('、')||'无');
  $('regenerate-model-summary').textContent='原轮模型：'+(regeneration.settings.model||'账号默认')+'；当前会话：'+(doc.settings.model.model||'账号默认')+'。';
  $('regenerate-mode').value=kind==='model'?'custom':'original';$('regenerate-mode').onchange();$('regenerate-api-model').value=regeneration.settings.model||'';
  $('regenerate-api-model').hidden=provider!=='api';$('regenerate-api-label').hidden=provider!=='api';$('regenerate-api-model').required=provider==='api';$('regenerate-codex-model').hidden=provider!=='codex';$('regenerate-codex-options').hidden=provider!=='codex';
  $('regenerate-error').textContent='';
  if(provider==='codex'){const result=await api('codex',{action:'models'});if(session?.id!==sid)return;regenerationCatalog=result.models;$('regenerate-codex-model').replaceChildren(new Option('账号默认模型',''),...result.models.map(m=>new Option(m.displayName||m.model,m.model)));if(regeneration.settings.model&&!result.models.some(m=>m.model===regeneration.settings.model))$('regenerate-codex-model').add(new Option(regeneration.settings.model+'（需重新选择）',regeneration.settings.model));$('regenerate-codex-model').value=regeneration.settings.model||'';regenerationOptions()}
  $('regenerate-dialog').showModal();if(kind==='edit')$('regenerate-text').focus();
 }catch(e){notice(e.message)}
}
function closeRegeneration(){if(!regenerating)$('regenerate-dialog').close()}
$('regenerate-close').onclick=closeRegeneration;$('regenerate-cancel').onclick=closeRegeneration;$('regenerate-dialog').addEventListener('cancel',e=>{if(regenerating)e.preventDefault()});
$('regenerate-form').onsubmit=async e=>{
 e.preventDefault();if(!regeneration||regenerating)return;const r=regeneration,mode=$('regenerate-mode').value,payload={id:r.id,action:'regenerate',message_id:r.message_id,text:$('regenerate-text').value,model_mode:mode};
 if(mode==='custom')payload.override={provider:r.provider,model:r.provider==='codex'?$('regenerate-codex-model').value:$('regenerate-api-model').value,effort:r.provider==='codex'?$('regenerate-effort').value:'',fast:r.provider==='codex'&&$('regenerate-fast').checked};
 const key=JSON.stringify(payload);if(r.key!==key){r.key=key;r.request_id=crypto.randomUUID().replaceAll('-','')}payload.request_id=r.request_id;
 regenerating=true;$('regenerate-submit').disabled=true;$('regenerate-error').textContent='正在创建分支…';
 try{saveDraft();const next=await api('session-action',payload);$('regenerate-dialog').close();$('session-filter').value='active';await refreshHistory();await openSession(next.id);notice('已在新分支生成，原会话仍保留。')}
 catch(e){$('regenerate-error').textContent=e.message+'。如连接超时，可再次点击同一操作；系统会查找已创建的分支，避免重复生成。'}
 finally{regenerating=false;$('regenerate-submit').disabled=false;if(session)renderRegenerationState()}
};
