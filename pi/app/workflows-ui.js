'use strict';
const selectedWorkflowPlugins=new Set(),schedulePluginSelection=new Set();
let workflowState={plugins:[],schedules:[],runs:[],waiting:{}},workflowLoading=false,pluginEditing=false;
const wfApi=data=>api('workflows',data);
const wfTime=value=>value?new Date(value*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'无后续执行';
function wfButton(label,action){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=async()=>{b.disabled=true;try{await action()}catch(e){const id=$('schedules-dialog').open?'schedules-notice':'plugins-notice';$(id).textContent=e.message}finally{b.disabled=false}};return b}
function pluginChoices(root,selection,includeDisabled=false){
 root.replaceChildren();
 for(const p of workflowState.plugins){if(!p.enabled&&!includeDisabled){selection.delete(p.id);continue}const label=document.createElement('label');label.className='plugin-choice';const c=document.createElement('input');c.type='checkbox';c.checked=selection.has(p.id);c.disabled=!p.enabled&&!selection.has(p.id);c.onchange=()=>{if(c.checked&&!p.enabled){c.checked=false;selection.delete(p.id);return}if(c.checked&&selection.size>=3){c.checked=false;notice('每次最多选择 3 个插件');return}c.checked?selection.add(p.id):selection.delete(p.id)};label.append(c,document.createTextNode(p.title+(p.enabled?'':'（停用）')));root.append(label)}
 if(!root.childNodes.length){const t=document.createElement('span');t.className='hint';t.textContent='没有已启用插件，可在侧栏管理。';root.append(t)}
}
async function refreshWorkflows(){
 if(workflowLoading)return;workflowLoading=true;
 try{workflowState=await wfApi();const available=new Set(workflowState.plugins.filter(p=>p.enabled).map(p=>p.id));for(const id of selectedWorkflowPlugins)if(!available.has(id))selectedWorkflowPlugins.delete(id);pluginChoices($('workflow-picks'),selectedWorkflowPlugins);renderPlugins();renderSchedules();}
 finally{workflowLoading=false}
}
function resetPlugin(){pluginEditing=false;$('plugin-form').reset();$('plugin-id').disabled=false;}
function renderPlugins(){
 const list=$('plugins-list');list.replaceChildren();
 for(const p of workflowState.plugins){const card=document.createElement('section');card.className='workflow-card';const h=document.createElement('h3');h.textContent=p.title+(p.enabled?'':' · 已停用');const d=document.createElement('p');d.textContent=p.description||p.id;card.append(h,d);
  card.append(wfButton('查看 / 编辑',async()=>{const full=await wfApi({action:'plugin-read',id:p.id});pluginEditing=true;$('plugin-id').value=p.id;$('plugin-id').disabled=true;$('plugin-title').value=full.title;$('plugin-description').value=full.description;$('plugin-instructions').value=full.instructions;$('plugin-form').scrollIntoView({block:'start'})}),
   wfButton(p.enabled?'停用':'启用',async()=>{await wfApi({action:'plugin-toggle',id:p.id});await refreshWorkflows()}),
   wfButton('导出 ZIP',async()=>{const r=await wfApi({action:'plugin-export',id:p.id});const bytes=Uint8Array.from(atob(r.base64),c=>c.charCodeAt(0));download(r.filename,bytes,'application/zip')}),
   wfButton('移除',async()=>{if(confirm('移除插件“'+p.title+'”？已发送会话中的历史副本仍保留。')){await wfApi({action:'plugin-delete',id:p.id});selectedWorkflowPlugins.delete(p.id);await refreshWorkflows()}}));list.append(card);
 }
}
$('plugins-open').onclick=async()=>{$('plugins-notice').textContent='';$('plugins-dialog').showModal();try{await refreshWorkflows()}catch(e){$('plugins-notice').textContent=e.message}};
$('plugins-close').onclick=()=>$('plugins-dialog').close();$('plugin-new').onclick=()=>{resetPlugin();$('plugin-form').scrollIntoView({block:'start'})};
$('plugin-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter||$('plugin-form').querySelector('[type=submit]');b.disabled=true;try{await wfApi({action:'plugin-save',replace:pluginEditing,plugin:{id:$('plugin-id').value,title:$('plugin-title').value,description:$('plugin-description').value,instructions:$('plugin-instructions').value}});$('plugins-notice').textContent='插件已保存。绑定旧版本的定时任务需重新检查并保存。';resetPlugin();await refreshWorkflows()}catch(e){$('plugins-notice').textContent=e.message}finally{b.disabled=false}};
$('plugin-import').onclick=()=>$('plugin-file').click();$('plugin-file').onchange=async()=>{try{const file=$('plugin-file').files[0];if(!file)return;if(file.size>200000)throw Error('插件 ZIP 最大 200 KB');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));await wfApi({action:'plugin-import',base64:btoa(binary)});$('plugins-notice').textContent='插件已导入并启用。请在输入框上方勾选，或将其绑定定时任务。';await refreshWorkflows()}catch(e){$('plugins-notice').textContent=e.message}finally{$('plugin-file').value=''}};
function scheduleFields(){const m=$('schedule-mode').value;for(const [id,visible] of [['time',m==='daily'||m==='weekdays'],['minutes',m==='interval'],['at',m==='once']]){$('schedule-'+id+'-wrap').classList.toggle('hidden',!visible);$('schedule-'+id).required=visible;$('schedule-'+id).disabled=!visible}}
function resetSchedule(){
 $('schedule-form').reset();$('schedule-id').value='';$('schedule-form-title').textContent='新建任务';schedulePluginSelection.clear();pluginChoices($('schedule-plugins'),schedulePluginSelection);scheduleFields();
 const d=new Date(Date.now()+10*60000+8*3600000);$('schedule-at').value=d.toISOString().slice(0,16);
}
function scheduleDescription(s){const frequency={daily:'每天 '+s.time,weekdays:'工作日 '+s.time,interval:'每 '+s.minutes+' 分钟',once:'单次'}[s.mode];return frequency+' · '+(s.require_windows?((s.target?.name||'Windows')+' / '+s.target?.workspace):'仅 AI 对话')}
function editSchedule(s){
 $('schedule-id').value=s.id;$('schedule-title').value=s.title;$('schedule-prompt').value=s.prompt;$('schedule-mode').value=s.mode;$('schedule-time').value=s.time||'09:00';$('schedule-minutes').value=s.minutes||60;
 if(s.at)$('schedule-at').value=new Date(s.at*1000+8*3600000).toISOString().slice(0,16);
 $('schedule-windows').checked=s.require_windows;$('schedule-enabled').checked=s.enabled;schedulePluginSelection.clear();for(const id of s.plugin_ids)schedulePluginSelection.add(id);pluginChoices($('schedule-plugins'),schedulePluginSelection,true);scheduleFields();$('schedule-form-title').textContent='编辑任务（保存时重新绑定当前模型与电脑）';$('schedule-form').scrollIntoView({block:'start'});
}
function renderSchedules(){
 const list=$('schedules-list');list.replaceChildren();
 for(const s of workflowState.schedules){const card=document.createElement('section');card.className='workflow-card';const title=document.createElement('h3');title.textContent=s.title+' · '+(s.enabled?'已启用':'已暂停');const detail=document.createElement('p');detail.textContent=scheduleDescription(s)+'\n下次：'+wfTime(s.next_due)+'\n模型：'+(s.model.model||'账号默认')+' / '+(effortNames[s.model.codex_effort]||'默认思考')+' / '+(s.model.codex_fast?'快速':'标准');detail.textContent+='\n审批：'+(approvalNames[s.approval_mode||'manual']);if(workflowState.waiting[s.id])detail.textContent+='\n'+workflowState.waiting[s.id];card.append(title,detail,
   wfButton('编辑',async()=>editSchedule(s)),wfButton(s.enabled?'暂停':'启用',async()=>{await wfApi({action:'schedule-toggle',id:s.id});await refreshWorkflows()}),
   wfButton('立即运行',async()=>{const r=await wfApi({action:'schedule-run',id:s.id});$('schedules-notice').textContent=r.status==='error'?'启动失败：'+r.error:'已手动启动一次；原定执行时间不变。';await refreshWorkflows();await refreshHistory()}),
   wfButton('停止本次',async()=>{await wfApi({action:'schedule-stop',id:s.id});$('schedules-notice').textContent='已请求停止本次执行；计划仍保留。'}),
   wfButton('删除计划',async()=>{if(confirm('删除“'+s.title+'”的定时计划？历史会话和执行记录仍保留。')){await wfApi({action:'schedule-delete',id:s.id});await refreshWorkflows()}}));list.append(card);
 }
 if(!workflowState.schedules.length)list.textContent='还没有定时任务。';
 const runs=$('schedule-runs');runs.replaceChildren();const labels={starting:'正在启动',running:'执行中',done:'完成',error:'失败',cancelled:'已停止',interrupted:'重启中断',skipped:'已跳过'};
 for(const r of workflowState.runs){const card=document.createElement('section');card.className='workflow-card';const text=document.createElement('p');text.textContent=r.title+' · '+(labels[r.status]||r.status)+' · '+new Date(r.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+(r.error?'\n'+r.error:'');card.append(text);if(r.session_id)card.append(wfButton('查看会话',async()=>{await openSession(r.session_id);$('session-filter').value=session.state||'active';renderHistory();$('schedules-dialog').close()}));runs.append(card)}
 if(!workflowState.runs.length)runs.textContent='暂无执行记录。';if(workflowState.scheduler_error)$('schedules-notice').textContent='调度错误：'+workflowState.scheduler_error;
}
$('schedules-open').onclick=async()=>{$('schedules-notice').textContent='';$('schedules-dialog').showModal();try{await refreshWorkflows();resetSchedule()}catch(e){$('schedules-notice').textContent=e.message}};
$('schedules-close').onclick=()=>$('schedules-dialog').close();$('schedule-new').onclick=()=>{resetSchedule();$('schedule-form').scrollIntoView({block:'start'})};$('schedule-mode').onchange=scheduleFields;
$('schedule-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter||$('schedule-form').querySelector('[type=submit]');b.disabled=true;try{const data={action:'schedule-save',id:$('schedule-id').value||undefined,title:$('schedule-title').value,prompt:$('schedule-prompt').value,mode:$('schedule-mode').value,time:$('schedule-time').value,minutes:Number($('schedule-minutes').value),at:new Date($('schedule-at').value+':00+08:00').getTime()/1000,require_windows:$('schedule-windows').checked,enabled:$('schedule-enabled').checked,plugin_ids:[...schedulePluginSelection]};await wfApi(data);$('schedules-notice').textContent='任务已保存，使用保存时的模型设置、插件版本和目标电脑。';resetSchedule();await refreshWorkflows()}catch(e){$('schedules-notice').textContent=e.message}finally{b.disabled=false}};
setInterval(()=>{if(active&&($('schedules-dialog').open||$('plugins-dialog').open))refreshWorkflows().catch(()=>{})},5000);
setInterval(()=>{if(active)refreshHistory().catch(()=>{})},15000);
