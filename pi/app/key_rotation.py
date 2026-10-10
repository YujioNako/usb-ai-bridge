"""Two-phase management-key rotation; caller holds the shared settings lock."""
import json,os,pathlib,re,time

def valid_key(value):return isinstance(value,str) and bool(re.fullmatch(r'[!-~]{16,128}',value))
class KeyRotation:
 def __init__(self,path):self.path=pathlib.Path(path)
 def write(self,data):
  temp=self.path.with_name(self.path.name+'.key-new')
  fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
  with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f);f.flush();os.fsync(f.fileno())
  temp.replace(self.path)
  if os.name!='nt':
   fd=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY)
   try:os.fsync(fd)
   finally:os.close(fd)
 def action(self,data,busy=False):
  settings=json.loads(self.path.read_text(encoding='utf-8'));pending=settings.get('key_pending',{})
  if pending and pending.get('expires',0)<time.time():settings.pop('key_pending');self.write(settings);pending={}
  action=data.get('action');rid=data.get('id','')
  if action=='status':return {'pending':bool(pending),'id':pending.get('id'),'last_id':settings.get('key_last_id')}
  if not isinstance(rid,str) or not re.fullmatch('[a-f0-9]{32}',rid):raise ValueError('密钥变更编号无效')
  if action=='prepare':
   if busy:raise ValueError('请等待当前 AI 或工具任务结束后修改密钥')
   key=data.get('new_key')
   if not valid_key(key):raise ValueError('密钥需为 16–128 位不含空格的 ASCII 字母、数字或符号')
   if key==settings['admin_token']:raise ValueError('新密钥与当前密钥相同')
   if pending and (pending['id']!=rid or pending['new_key']!=key):raise ValueError('已有密钥修改等待完成，请先恢复或取消')
   settings['key_pending']={'id':rid,'new_key':key,'expires':time.time()+300};self.write(settings)
   return {'prepared':True,'id':rid}
  if action=='cancel':
   if pending and pending['id']==rid:settings.pop('key_pending');self.write(settings)
   return {'cancelled':True}
  if action=='commit':
   if settings.get('key_last_id')==rid:return {'committed':True,'id':rid}
   if not pending or pending['id']!=rid:raise ValueError('密钥变更已过期或不存在，当前密钥未修改')
   if busy:raise ValueError('请等待当前 AI 或工具任务结束后修改密钥')
   settings['admin_token']=pending['new_key'];settings['key_last_id']=rid;settings.pop('key_pending');self.write(settings)
   return {'committed':True,'id':rid}
  raise ValueError('密钥操作不存在')
