import pathlib,tempfile,json,sys,threading,time,unittest
sys.path.insert(0,str(pathlib.Path(__file__).parent))
from workspace import Workbench
from codex_backend import CodexBackend,CodexConnectionError

class SyncTest(unittest.TestCase):
 def test_patches(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);w=Workbench(root/'sessions',root/'model',lambda:{})
   d=w.post('sessions',{});d['messages']=[{'id':'m1','role':'assistant','status':'streaming','content':'你好😀','tools':[{'result':{'data':'x'*10000}}]}];w.save(d)
   p=w.post('session-action',{'id':d['id'],'action':'sync'});self.assertEqual(p['changes'][0]['text']['replace'],'你好😀')
   c=p['changes'][0];known={'m1':{'text_hash':c['text']['hash'],'text_length':c['text']['length'],'meta_hash':c['meta_hash']}}
   req={'id':d['id'],'action':'sync','known':known,'meta_hash':p['meta_hash']}
   unchanged=w.post('session-action',req);self.assertEqual(unchanged['changes'],[]);self.assertNotIn('meta',unchanged)
   d['messages'][0]['content']+='\n恢复内容';w.save(d);change=w.post('session-action',req)['changes'][0]
   self.assertEqual(change['text']['append'],'\n恢复内容');self.assertNotIn('fields',change);self.assertLess(len(json.dumps(change)),500)
   # Unicode length is supplied by the server; repeated reconnect patches have a base hash.
   self.assertEqual(change['text']['base'],known['m1']['text_hash']);self.assertEqual(w.post('session-action',req)['changes'][0],change)
   d['messages'][0]['content']='纠正后的最终内容';d['messages'][0]['status']='done';w.save(d)
   change=w.post('session-action',req)['changes'][0];self.assertEqual(change['text']['replace'],'纠正后的最终内容');self.assertEqual(change['fields']['status'],'done')
   self.assertTrue(w.get('model')['session_sync'])

class Reconnect(CodexBackend):
 def __init__(self):super().__init__();self.stage=0;self.turns=0;self.cursors=[]
 def rpc(self,method,params=None):
  if method=='account/read':return {'account':{'type':'chatgpt'}}
  if method=='thread/start':return {'thread':{'id':'t'}}
  if method=='turn/start':self.turns+=1;return {'turn':{'id':'u'}}
  if method=='turn/interrupt':return {}
  raise AssertionError(method)
 def transport(self,path,data):
  if data.get('snapshot'):return {'epoch':'e','cursor':0,'events':[]}
  self.cursors.append(data['after']);self.stage+=1
  if self.stage==2:raise CodexConnectionError('synthetic temporary disconnect')
  def e(method,params):return {'message':{'method':method,'params':{'threadId':'t','turnId':'u',**params}}}
  events=[e('item/agentMessage/delta',{'itemId':'m','delta':'部分'})] if self.stage==1 else [e('turn/completed',{'turn':{'status':'completed','items':[{'type':'agentMessage','id':'m','text':'部分及最终完整内容'}]}})]
  return {'epoch':'e','cursor':self.stage,'events':events}

class RecoveryTest(unittest.TestCase):
 def test_terminal_error_preserves_partial_without_waiting(self):
  class Fatal(Reconnect):
   def transport(self,path,data):
    if not data.get('snapshot') and self.stage==1:
     return {'epoch':'e','cursor':2,'events':[{'message':{'method':'error','params':{'threadId':'t','turnId':'u','willRetry':False,'error':{'message':'synthetic permanent failure'}}}}]}
    return super().transport(path,data)
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);w=Workbench(root/'s',root/'m',lambda:{})
   w.codex=Fatal();w.configure({'provider':'codex','model':''});d=w.post('sessions',{});w.post('send',{'id':d['id'],'text':'fixture'})
   deadline=time.monotonic()+3
   while w.active and time.monotonic()<deadline:time.sleep(.02)
   final=w.load(d['id'])['messages'][-1];self.assertEqual(final['status'],'error');self.assertEqual(final['content'],'部分');self.assertIn('permanent',final['error']);self.assertEqual(w.codex.turns,1)

 def test_slow_account_rpc_does_not_block_messages(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);w=Workbench(root/'s',root/'m',lambda:{})
   w.write(w.model_path,{'provider':'codex'});entered=threading.Event();release=threading.Event()
   def slow(*a,**k):entered.set();release.wait(2);return {'logged_in':True}
   w.codex.status=slow
   for call in [lambda:w.get('model'),lambda:w.post('codex',{'action':'status'})]:
    entered.clear();release.clear();t=threading.Thread(target=call);t.start();self.assertTrue(entered.wait(1))
    acquired=w.lock.acquire(timeout=.15)
    if acquired:w.lock.release()
    release.set();t.join();self.assertTrue(acquired,'Account read blocked conversation lock')

 def test_retry_read_without_restarting_turn(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);w=Workbench(root/'s',root/'m',lambda:{})
   w.codex=Reconnect();w.configure({'provider':'codex','model':''});d=w.post('sessions',{});w.post('send',{'id':d['id'],'text':'fixture'})
   deadline=time.monotonic()+5
   while w.active and time.monotonic()<deadline:time.sleep(.02)
   final=w.load(d['id'])['messages'][-1];self.assertEqual(final['status'],'done');self.assertEqual(final['content'],'部分及最终完整内容');self.assertNotIn('activity',final)
   self.assertEqual(w.codex.turns,1);self.assertEqual(w.codex.cursors,[0,1,1])

if __name__=='__main__':unittest.main()
