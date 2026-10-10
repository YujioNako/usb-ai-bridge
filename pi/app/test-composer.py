import unittest,tempfile,pathlib,threading,base64,time
from unittest.mock import patch
from workspace import Workbench
from agent_broker import AgentBroker
import approval_review
class Composer(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();root=pathlib.Path(self.tmp.name);self.b=AgentBroker();self.b.register({'id':'fixture','capabilities':['shell','files'],'workspace':'fixture'})
  self.w=Workbench(root/'sessions',root/'model.json',lambda:{},self.b);self.d=self.w.post('sessions',{})
 def tearDown(self):self.tmp.cleanup()
 def active(self,mode):
  d=self.w.post('session-action',{'id':self.d['id'],'action':'permissions','mode':mode});d['messages']=[{'role':'user','content':'list only'},{'role':'assistant','content':''}]
  return {'doc':d,'stop':threading.Event()}
 def test_permissions_persist_and_lock(self):
  a=self.active('assist');self.assertEqual(self.w.load(self.d['id'])['approval_mode'],'assist');self.w.active=a
  with self.assertRaises(ValueError):self.w.post('session-action',{'id':self.d['id'],'action':'permissions','mode':'full'})
  self.w.active=None
  with self.assertRaises(ValueError):self.active('bad')
 def test_manual_and_full(self):
  for mode,expected in [('manual','approval'),('full','queued')]:
   job=self.w.submit_job(self.active(mode),'shell',{'command':'Get-Date'},{});self.assertEqual(job['status'],expected);self.b.cancel(job['id'])
 def test_assist_branches(self):
  for decision,expected in [('approve','queued'),('manual','approval'),('deny','denied')]:
   with patch.object(approval_review,'review',return_value={'decision':decision,'reason':'fixture','reviewer':'fixture'}):
    trace={};job=self.w.submit_job(self.active('assist'),'shell',{'command':'Get-Date'},trace);self.assertEqual(job['status'],expected);self.assertEqual(trace['review']['decision'],decision);self.b.cancel(job['id'])
 def test_stop_during_review(self):
  a=self.active('assist')
  def stop(*args):a['stop'].set();return {'decision':'approve','reason':'fixture','reviewer':'fixture'}
  with patch.object(approval_review,'review',side_effect=stop):job=self.w.submit_job(a,'shell',{'command':'Get-Date'},{});self.assertEqual(job['status'],'cancelled')
 def test_no_execution_before_review(self):
  job=self.b.submit('shell',{'command':'Get-Date'},approval_mode='assist');self.assertEqual(job['status'],'reviewing')
  with self.assertRaises(ValueError):self.b.approve({'job_id':job['id'],'allow':True})
  self.b.cancel(job['id']);self.assertEqual(self.b.reviewed(job['id'],{'decision':'approve'})['status'],'cancelled')
 def test_review_fallback(self):
  class Offline:
   def transport(self,*args):raise ValueError('offline')
  result=approval_review.review(Offline(),self.active('assist'),'shell',{},'.');self.assertEqual(result['decision'],'manual')
 def test_actual_reviewer_contract(self):
  class Runtime:
   def __init__(self):self.calls=[]
   def rpc(self,method,params):
    self.calls.append((method,params))
    if method=='thread/start':return {'thread':{'id':'review-thread'}}
    if method=='turn/start':return {'turn':{'id':'review-turn'}}
    return {}
   def transport(self,path,data):
    if data.get('snapshot'):return {'epoch':'fixture','cursor':1}
    return {'epoch':'fixture','cursor':3,'events':[{'message':{'method':'item/completed','params':{'threadId':'review-thread','item':{'type':'agentMessage','id':'message','text':'{"decision":"approve","reason":"只输出测试标记"}'}}}},{'message':{'method':'turn/completed','params':{'threadId':'review-thread','turn':{'status':'completed'}}}}]}
  runtime=Runtime();r=approval_review.review(runtime,self.active('assist'),'shell',{'command':'Write-Output test'},'.')
  self.assertEqual(r['decision'],'approve');params=runtime.calls[0][1];self.assertEqual(params['dynamicTools'],[]);self.assertEqual(params['sandbox'],'read-only');self.assertEqual(params['approvalPolicy'],'never');self.assertTrue(params['ephemeral'])
  self.assertTrue(any(method=='thread/delete' for method,_ in runtime.calls))
 def test_image_text_remove_payload(self):
  image='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
  d=self.w.post('files',{'id':self.d['id'],'name':'pic.png','kind':'image','content':image});f=d['files'][0]
  d['messages']=[{'role':'user','content':'See it','attachments':[f]},{'role':'assistant','content':''}]
  payload=self.w.payload(d,{'model':'fixture'});self.assertEqual(payload['messages'][-1]['content'][-1]['image_url']['url'],image)
  d=self.w.post('files',{'id':d['id'],'action':'remove','file_id':f['id']});self.assertEqual(d['files'],[])
  for content in ['data:image/svg+xml;base64,AAAA','data:image/png;base64,aGVsbG8=','https://example.com/p.png']:
   with self.assertRaises(ValueError):self.w.post('files',{'id':d['id'],'name':'bad.png','kind':'image','content':content})
 def test_read_tools_no_review(self):
  with patch.object(approval_review,'review',side_effect=AssertionError('must not review')):
   job=self.w.submit_job(self.active('assist'),'files',{'op':'list'},{});self.assertEqual(job['status'],'queued')
if __name__=='__main__':unittest.main()


