/* One request in flight; server snapshots/patches are authoritative after reconnect. */
window.WorkbenchSync=(()=>{
 let generation=0,owner=null,known={},metaHash='',timer=null,running=false,failures=0,urgent=false;
 function invalidate(){generation++;known={};metaHash=''}
 function merge(packet){
  if(packet.id!==session.id)throw Error('会话同步目标不一致');
  const rows=new Map(session.messages.map(m=>[m.id,{...m}])),versions=structuredClone(known);
  for(const c of packet.changes){let row=rows.get(c.id)||{id:c.id,content:''};const v=versions[c.id]||{};
   if(c.fields){row={...c.fields,content:row.content||''};v.meta_hash=c.meta_hash;}
   if(c.text){if(Object.hasOwn(c.text,'replace'))row.content=c.text.replace;else{if(v.text_hash!==c.text.base)throw Error('会话内容需要重新同步');row.content=(row.content||'')+c.text.append;}v.text_hash=c.text.hash;v.text_length=c.text.length;}
   rows.set(c.id,row);versions[c.id]=v;
  }
  const messages=packet.order.map(id=>{const m=rows.get(id);if(!m)throw Error('会话消息需要重新同步');return m});
  const next={...(packet.meta||session),messages,updated_at:packet.updated_at};
  session=next;known=Object.fromEntries(packet.order.map(id=>[id,versions[id]]));metaHash=packet.meta_hash;
 }
 function schedule(delay){clearTimeout(timer);timer=setTimeout(poll,delay)}
 async function poll(){
  if(running){urgent=true;return}if(!active||!session){schedule(800);return}running=true;const sid=session.id,g=generation;
  if(owner!==sid){owner=sid;known={};metaHash=''}
  try{
   const packet=model?.session_sync?await api('session-action',{id:sid,action:'sync',known,meta_hash:metaHash}):await api('session?id='+encodeURIComponent(sid));
   if(!active||session?.id!==sid||g!==generation)return;
   const wasBusy=busy;if(model?.session_sync)merge(packet);else session=packet;
   failures=0;WorkbenchView.connection();render();if(wasBusy&&!busy)refreshHistory().catch(()=>{});
  }catch(e){
   if(active&&session?.id===sid&&g===generation){failures++;known={};metaHash='';const message=e.status===401?'管理密钥已失效，请重新登录。':e.status===400?'会话同步失败：'+e.message:'USB 面板连接中断，正在重试。恢复后会同步已有内容，不会重发任务。';WorkbenchView.connection(message)}
  }finally{running=false;const delay=urgent?0:failures?Math.min(5000,500*2**Math.min(failures,4)):busy?400:1800;urgent=false;schedule(delay)}
 }
 function retry(){if(running){urgent=true;return}schedule(0)}
 window.retrySessionSync=retry;document.addEventListener('DOMContentLoaded',()=>schedule(500));window.addEventListener('online',retry);document.addEventListener('visibilitychange',()=>{if(!document.hidden)retry()});
 return {invalidate,retry,merge};
})();
