import pathlib,tempfile,json,time,threading,sys
sys.path.insert(0,str(pathlib.Path(__file__).parent))
from workspace import Workbench
from codex_backend import CodexBackend
from agent_broker import AgentBroker

class Fake(CodexBackend):
 def __init__(self):super().__init__();self.calls=[];self.stage=0;self.replies=[];self.interrupted=False
 def rpc(self,method,params=None):
  self.calls.append((method,params))
  if method=='account/read':return {'account':{'type':'chatgpt','email':'fixture@example.invalid','planType':'plus'}}
  if method=='thread/start':
   assert params['sandbox']=='read-only'
   assert all(t['type']=='function' and t['name'].startswith('windows_') for t in params['dynamicTools'])
   return {'thread':{'id':'t1'}}
  if method=='thread/resume':assert params['threadId']=='t1';return {'thread':{'id':'t1'}}
  if method=='turn/start':self.stage=0;return {'turn':{'id':'u1'}}
  if method=='turn/interrupt':self.interrupted=True;return {}
  raise AssertionError(method)
 def transport(self,path,data):
  if path=='/reply':self.replies.append(data);return {'ok':True}
  if data.get('snapshot'):return {'epoch':'e1','cursor':1,'events':[]}
  self.stage+=1
  def event(method,p,rid=None):
   msg={'method':method,'params':{'threadId':'t1','turnId':'u1',**p}}
   if rid:msg['id']=rid
   return {'seq':self.stage+1,'message':msg}
  events=[event('item/tool/call',{'tool':'windows_files','arguments':{'op':'list'},'callId':'c1'},'r1')] if self.stage==1 else [event('item/agentMessage/delta',{'itemId':'m1','delta':'已读取工作目录'}),event('turn/completed',{'turn':{'id':'u1','status':'completed'}})]
  return {'epoch':'e1','cursor':self.stage+1,'events':events}

with tempfile.TemporaryDirectory() as tmp:
 root=pathlib.Path(tmp);broker=AgentBroker();auth=broker.register({'id':'fixture','capabilities':['files'],'workspace':'fixture-only'})
 def worker():
  data={'id':'fixture',**auth};job=broker.poll(data)['job'];assert job['arguments']=={'op':'list'}
  broker.result({**data,'job_id':job['id'],'result':{'entries':[]}})
 w=Workbench(root/'sessions',root/'model.json',lambda:{},broker);w.codex=Fake()
 result=w.configure({'provider':'codex','model':''});assert result['ready'] and 'api_key' not in result
 doc=w.post('sessions',{});doc=w.post('files',{'id':doc['id'],'name':'skip.txt','content':'NEVER INCLUDE THIS'})
 threading.Thread(target=worker,daemon=True).start();w.post('send',{'id':doc['id'],'text':'list files'})
 limit=time.monotonic()+4
 while w.active and time.monotonic()<limit:time.sleep(.02)
 assert w.active is None
 saved=w.load(doc['id']);assert saved['messages'][-1]['status']=='done';assert saved['messages'][-1]['content']=='已读取工作目录'
 assert w.codex.replies[0]['result']['success']
 assert 'NEVER INCLUDE THIS' not in json.dumps(w.codex.calls)
 assert saved['codex_thread']=='t1'
 # A second turn resumes the persisted Codex history instead of replaying previous work.
 threading.Thread(target=worker,daemon=True).start();w.post('send',{'id':doc['id'],'text':'again'})
 limit=time.monotonic()+4
 while w.active and time.monotonic()<limit:time.sleep(.02)
 assert w.active is None and any(c[0]=='thread/resume' for c in w.codex.calls)
 # Refuse backend changes in an existing history, without sending it to another provider.
 w.configure({'base_url':'https://fixture.invalid/v1','model':'fixture','api_key':'fixture'})
 try:w.post('send',{'id':doc['id'],'text':'do not send'})
 except ValueError:pass
 else:raise AssertionError('Backend crossing accepted')
print('PASS: Codex tool loop, selected attachments only, stream persistence, resume, provider boundary')
# Additional cancellation and restart checks use the same fake event source.
class Restart(Fake):
 def transport(self,path,data):
  packet=super().transport(path,data)
  if path=='/events' and not data.get('snapshot'):packet['epoch']='restarted'
  return packet
with tempfile.TemporaryDirectory() as tmp:
 root=pathlib.Path(tmp);w=Workbench(root/'sessions',root/'model.json',lambda:{})
 w.codex=Restart();w.configure({'provider':'codex','model':''});doc=w.post('sessions',{})
 w.post('send',{'id':doc['id'],'text':'test restart'})
 limit=time.monotonic()+4
 while w.active and time.monotonic()<limit:time.sleep(.02)
 assert w.load(doc['id'])['messages'][-1]['status']=='error'
 assert w.codex.interrupted
 # Stop is observed before a tool can be submitted.
 active={'doc':w.load(doc['id']),'stop':threading.Event(),'client_id':None}
 active['stop'].set();w.codex=Fake()
 answer=w.codex.tool(w,active,{'tool':'windows_files','arguments':{'op':'write','path':'should-not-exist'}},['files'])
 assert not answer['success']
print('PASS: runtime restart interrupts without replay; cancellation prevents tool submission')
