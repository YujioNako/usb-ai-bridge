/* Local Markdown, stable message nodes, compact tool traces and opt-in tail following. */
window.WorkbenchView=(()=>{
 const md=window.markdownit({html:false,breaks:false,linkify:true,typographer:false});
 md.validateLink=url=>/^(https?:|mailto:)/i.test(url);
 md.renderer.rules.image=(tokens,i)=>'<span class="markdown-image-label">[图片：'+md.utils.escapeHtml(tokens[i].content)+']</span>';
 const linkOpen=md.renderer.rules.link_open||((tokens,i,options,env,self)=>self.renderToken(tokens,i,options));
 md.renderer.rules.link_open=(tokens,i,options,env,self)=>{tokens[i].attrSet('target','_blank');tokens[i].attrSet('rel','noopener noreferrer');return linkOpen(tokens,i,options,env,self)};
 const cache=new Map();let currentId=null,follow=true,adjusting=false;
 const root=()=>document.getElementById('messages');
 const el=(tag,cls,text)=>{const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x};
 function morph(parent,fresh){
  const wanted=[...fresh.childNodes];for(let i=0;i<wanted.length;i++){
   const next=wanted[i],old=parent.childNodes[i];
   if(!old){parent.append(next.cloneNode(true));continue}
   if(old.nodeType!==next.nodeType||old.nodeName!==next.nodeName){old.replaceWith(next.cloneNode(true));continue}
   if(old.nodeType===Node.TEXT_NODE){if(old.data!==next.data){if(next.data.startsWith(old.data))old.appendData(next.data.slice(old.data.length));else old.data=next.data;}continue}
   if(old.nodeType!==Node.ELEMENT_NODE)continue;
   for(const a of [...old.attributes])if(!next.hasAttribute(a.name))old.removeAttribute(a.name);
   for(const a of next.attributes)if(old.getAttribute(a.name)!==a.value)old.setAttribute(a.name,a.value);
   morph(old,next);
  }
  while(parent.childNodes.length>wanted.length)parent.lastChild.remove();
 }
 function withScroll(fn){const box=root(),top=box.scrollTop;adjusting=true;fn();box.scrollTop=follow?box.scrollHeight:top;requestAnimationFrame(()=>{adjusting=false});updateJump()}
 function paint(body,text,role){
  if(body._shown===text)return;body._shown=text;
  if(role==='user'){body.textContent=text;return}
  const template=document.createElement('template');template.innerHTML=md.render(text);morph(body,template.content);
 }
 function content(body,text,m){
  if(body._target===text)return;body._target=text;clearTimeout(body._timer);
  const before=body._shown||'',tail=text.startsWith(before)?Array.from(text.slice(before.length)):[];
  if(m.status==='streaming'&&tail.length>0&&tail.length<240&&!document.hidden&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
   let n=0;const step=()=>{if(!body.isConnected)return;n=Math.min(tail.length,n+Math.max(1,Math.ceil(tail.length/4)));withScroll(()=>paint(body,before+tail.slice(0,n).join(''),m.role));if(n<tail.length)body._timer=setTimeout(step,40)};step();
  }else withScroll(()=>paint(body,text,m.role));
 }
 function category(t){const name=String(t.name||'工具').replace(/^windows_/,'');const op=t.arguments?.op||'';
  if(name==='files')return ['write','append','edit','patch','move','copy','mkdir','archive_extract','delete'].includes(op)?['edit','✎','修改文件']:['files','▤','读取文件'];
  if(name==='browser')return op==='screenshot'?['image','▧','查看图片']:['browser','◎','操作浏览器'];
  if(name==='shell')return ['shell','›_','运行命令'];return [name,'◇',name==='system'?'查看系统信息':name];
 }
 function traces(tools){
  const holder=el('div','tool-marks');const groups=new Map();
  for(const t of tools){const [key,icon,label]=category(t);if(!groups.has(key))groups.set(key,{key,icon,label,items:[]});groups.get(key).items.push(t)}
  for(const g of groups.values()){
   const group=el('details','tool-mark');group.dataset.detailKey='group-'+g.key;const summary=el('summary');
   const waiting=g.items.some(t=>['approval','reviewing'].includes(t.status));const bad=g.items.filter(t=>['error','expired','denied'].includes(t.status)).length;const running=g.items.some(t=>['preparing','queued','running'].includes(t.status));
   summary.append(el('span','tool-icon',g.icon),el('span','',g.label+' · '+g.items.length+' 次'+(waiting?' · 等待审批':bad?' · '+bad+' 次未完成':running?' · 进行中':'')));group.append(summary);
   group.classList.toggle('needs-attention',waiting||!!bad);group.open=waiting||!!bad;
   g.items.forEach((t,i)=>{const card=toolCard(t);card.dataset.detailKey='tool-'+(t.call_id||t.job_id||t.id||g.key+'-'+i);group.append(card)});holder.append(group);
  }return holder;
 }
 function phase(m){
  if(m.status==='stopping')return '正在停止';if(m.status!=='streaming')return {done:'已完成',error:'生成失败',interrupted:'已中断',cancelled:'已停止'}[m.status]||'';
  if(m.questions?.some(q=>q.status==='waiting'))return '等待你的回答';
  if(m.tools?.some(t=>t.status==='approval'))return '等待你的审批';
  if(m.tools?.some(t=>['preparing','reviewing','queued','running'].includes(t.status)))return '正在使用工具';
  return {thinking:'正在思考',working:'正在处理',writing:'正在生成',reconnecting:'模型连接恢复中'}[m.activity]||(m.content?'正在生成':'正在连接模型');
 }
 function footer(box,m){
  const f=box.querySelector('.message-footer');if(!f)return;
  f.querySelector('.phase-label').textContent=phase(m);f.classList.toggle('is-active',['streaming','stopping'].includes(m.status));
  f.querySelector('.message-error').textContent=m.error||'';f.querySelector('.message-info').textContent=m.notice||'';
  f.querySelector('.download-reply').hidden=!m.content;f.querySelector('.continue-reply').hidden=!['error','interrupted'].includes(m.status);
  box.querySelector('.copy-message')?.classList.toggle('hidden',!m.content);
  usage(box,m);
 }
 function usage(box,m){
  const u=m.usage_display;if(!u)return;const sig=JSON.stringify(u);if(box._usageSig===sig)return;box._usageSig=sig;
  let d=box.querySelector('.turn-usage');if(!d){d=el('details','turn-usage');d.dataset.detailKey='usage';box.append(d)}
  const open=d.open;d.replaceChildren();const t=u.tokens,n=v=>Number(v||0).toLocaleString('zh-CN'),money=Object.entries(u.amounts||{}).map(([c,v])=>(c==='CNY'?'¥':'$')+Number(v).toFixed(6)).join(' + ');
  const plan=u.provider==='codex',price=money?((u.unpriced?'部分':'')+(plan?'API 等价参考 ':'预估费用 ')+money):'未配置单价';
  const credits=u.credits==null?'':'预估 '+(u.credit_unpriced?'部分 ':'')+Number(u.credits).toFixed(4)+' credits · ';
  d.append(el('summary','',u.records?.length?`本轮 ${u.estimated?'约 ':''}${n(t.total)} tokens · ${plan?credits:''}${price}`:'本轮用量 · 等待统计'));
  const line=el('div','usage-breakdown');line.textContent=`输入 ${n(t.input)}（缓存命中 ${n(t.cached)} / 写入 ${n(t.cache_write)}） · 输出 ${n(t.output)}（推理 ${n(t.reasoning)}）`;d.append(line);
  d.append(el('p','hint',u.estimated?'包含文本长度粗估；缺失的隐藏推理、图片等无法还原。':'Token 来自服务返回的计数；费用按保存的单价估算。'));
  if(u.review_tokens)d.append(el('p','hint',`其中独立审批 ${n(u.review_tokens)} tokens，已计入总数。`));
  if(!plan&&u.review_tokens)d.append(el('p','hint','独立审批使用 Codex 套餐，API 预估金额不包含该项；其 API 等价参考费用 '+(Object.entries(u.reference_amounts||{}).map(([c,v])=>c+' '+Number(v).toFixed(6)).join(' + ')||'未配置单价')+'，预估 '+(u.credits==null?'未知':Number(u.credits).toFixed(4))+' credits。'));
  d.append(el('p','hint',plan?'套餐 credits 和 API 等价费用均为参考，不是实际扣款，也不代表套餐剩余额度。':'费用不含税费、外部工具费用及供应商特殊计费；实际以服务账单为准。'));
  d.append(el('p','hint','缓存已包含在输入中，推理已包含在输出中，不重复相加。'));
  if(u.unpriced)d.append(el('p','hint','部分模型未匹配单价，不能把显示的金额视作完整费用。'));
  for(const note of u.notes||[])d.append(el('p','hint',note));
  const rows=el('div','usage-records');for(const r of u.records||[]){const p=r.price;rows.append(el('p','hint',`${r.scope==='main'?'模型请求':'独立审批'} · ${p.model||'未知模型'} · ${p.tier==='priority'?'快速':'标准'} · ${n(r.tokens.total)} tokens · ${r.source==='reported'?'回传':'粗估'} · 单价日期 ${p.date}${p.long_context?' · 长上下文费率':''}`))}d.append(rows);
  const settings=el('button','','设置参考单价');settings.type='button';settings.onclick=()=>window.showUsagePrices?.();d.append(settings);d.open=open;
 }
 function base(m){
  const box=el('article','message '+m.role);box._message=m;box.append(el('div','message-label',m.role==='user'?'你':m.model||'助手'),el('div','message-text'));
  for(const f of m.attachments||[]){box.append(el('span','tag',f.name));if(f.kind==='image'){const image=el('img','attached-image');image.src=f.content;image.alt=f.name;box.append(image)}}
  if(m.tools?.length)box.append(traces(m.tools));
  if(m.role==='assistant'){
   const f=el('div','message-footer');const dot=el('span','activity-dot');dot.setAttribute('aria-hidden','true');f.append(dot,el('span','phase-label'),el('span','message-error error'),el('span','message-info'));
   const save=el('button','download-reply','下载回复');save.onclick=()=>download('回复.md',box._message.content,'text/markdown;charset=utf-8');
   const resume=el('button','continue-reply','从中断处继续');resume.onclick=()=>{if(busy)return;document.getElementById('prompt').value='请接着上一条未完成的回复继续，先检查已完成的内容和工具结果，避免重复执行已完成的操作。';document.getElementById('prompt').focus();notice('已填入继续指令，确认后点击发送。')};f.append(save,resume);box.append(f);footer(box,m);
  }return box;
 }
 function signature(m){const v={...m};for(const key of ['content','status','activity','error','notice','meter','usage_display','token_usage'])delete v[key];return JSON.stringify(v)}
 function preserveDetails(old,next){const states=new Map([...old.querySelectorAll('details')].map((d,i)=>[d.dataset.detailKey||'detail-'+i,d.open]));[...next.querySelectorAll('details')].forEach((d,i)=>{const key=d.dataset.detailKey||'detail-'+i;if(states.has(key)&&!d.classList.contains('needs-attention')&&(!d.querySelector('button')||d.dataset.detailKey==='usage'))d.open=states.get(key);else if(states.has(key)&&!d.classList.contains('needs-attention')&&d.dataset.detailKey?.startsWith('group-'))d.open=states.get(key)})}
 function render(){
  if(!session)return;const box=root();if(currentId!==session.id){cache.forEach(v=>clearTimeout(v.node.querySelector('.message-text')._timer));cache.clear();box.replaceChildren();currentId=session.id;follow=true;}
  document.getElementById('session-title').textContent=session.title;busy=session.messages.some(m=>['streaming','stopping'].includes(m.status));
  document.getElementById('send').disabled=busy||uploadingContext;document.getElementById('stop').classList.toggle('hidden',!busy);document.getElementById('rename').disabled=busy;document.getElementById('upload').disabled=busy;
  withScroll(()=>{
   if(!session.messages.length){if(!box.querySelector('.empty')){box.innerHTML='<div class="empty"><div class="empty-mark">✳</div><h2>从一个任务开始</h2><p>描述你要完成的工作，或添加文件、图片和插件作为上下文。</p><button id="empty-settings">配置模型</button></div>';document.getElementById('empty-settings').onclick=showSettings}return}
   box.querySelector('.empty')?.remove();const ids=new Set();
   session.messages.forEach((m,i)=>{
    const id=m.id||'legacy-'+i;ids.add(id);let item=cache.get(id);const sig=signature(m);
    if(!item||item.sig!==sig){const node=renderMessage(m);node.dataset.messageId=id;if(item){const previous=item.node.querySelector('.message-text');node.querySelector('.message-text').replaceWith(previous);preserveDetails(item.node,node);if(item.questions===JSON.stringify(m.questions)){const forms=[...item.node.querySelectorAll('.question-card')];node.querySelectorAll('.question-card').forEach((form,j)=>{if(forms[j])form.replaceWith(forms[j])})}item.node.replaceWith(node)}item={node,sig,questions:JSON.stringify(m.questions)};cache.set(id,item)}
    item.node._message=m;if(box.children[i]!==item.node)box.insertBefore(item.node,box.children[i]||null);footer(item.node,m);content(item.node.querySelector('.message-text'),m.content||'',m);
    if(m.status!=='streaming'){const body=item.node.querySelector('.message-text');clearTimeout(body._timer);paint(body,m.content||'',m.role)}
   });
   for(const [id,item] of cache)if(!ids.has(id)){clearTimeout(item.node.querySelector('.message-text')._timer);item.node.remove();cache.delete(id)}
  });
  const filesSig=JSON.stringify([session.files,[...chosen],busy,session.approval_mode,[...attachmentPreviews]]);if(render.filesSig!==filesSig){render.filesSig=filesSig;renderFiles()}
 }
 function updateJump(){const b=document.getElementById('jump-latest');if(b)b.hidden=follow||root().scrollHeight-root().clientHeight<60}
 function init(){const box=root(),wrap=el('div','jump-wrap'),button=el('button','jump-latest','↓ 回到最新');button.id='jump-latest';button.hidden=true;button.onclick=()=>{follow=true;withScroll(()=>{})};wrap.append(button);box.after(wrap);
  box.addEventListener('wheel',e=>{if(e.deltaY<0){follow=false;updateJump()}},{passive:true});
  box.addEventListener('touchmove',()=>{follow=false;updateJump()},{passive:true});
  box.addEventListener('scroll',()=>{if(adjusting)return;follow=box.scrollHeight-box.scrollTop-box.clientHeight<=2;updateJump()},{passive:true});
  const banner=el('div','connection-banner hidden');banner.id='connection-banner';banner.setAttribute('role','status');banner.append(el('span','connection-text'));const retry=el('button','','立即重试');retry.onclick=()=>window.retrySessionSync?.();banner.append(retry);box.before(banner);
 }
 function connection(error){const b=document.getElementById('connection-banner');if(!b)return;b.classList.toggle('hidden',!error);b.querySelector('span').textContent=error||''}
 document.addEventListener('DOMContentLoaded',init);
 return {base,render,connection,phase,markdown:source=>md.render(source),followLatest:()=>{follow=true;updateJump()}};
})();
