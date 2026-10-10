import unittest,tempfile,pathlib,copy,threading,json
from unittest.mock import patch
from workspace import Workbench

class Regenerate(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();p=pathlib.Path(self.temp.name);self.w=Workbench(p/'sessions',p/'model.json',lambda:{})
  self.w.codex.status=lambda *a,**k:{'logged_in':True};self.w.codex.options=lambda model,*a:{'model':model};self.calls=[]
  def rpc(method,params):self.calls.append((method,params));return {'thread':{'id':'forked'}}
  self.w.codex.rpc=rpc;self.w.configure({'provider':'codex','model':'global-model','effort':'medium','fast':False})
  self.d=self.w.post('sessions',{});self.d.update(provider='codex',codex_thread='original',approval_mode='manual',token_usage={'total':{'inputTokens':9999,'outputTokens':100}})
  self.d['messages']=[]
  for i in range(3):
   self.d['messages'] += [{'id':'u'+str(i),'role':'user','content':'question '+str(i),'attachments':[],'plugins':[]},
    {'id':'a'+str(i),'role':'assistant','content':'answer '+str(i),'status':'done','turn_id':'turn'+str(i),'model':'old-model','settings_snapshot':{'provider':'codex','model':'old-model','effort':'high','fast':True},'token_usage':{'total':{'inputTokens':(i+1)*100,'outputTokens':(i+1)*10}}}]
  self.w.save(self.d)
 def tearDown(self):self.temp.cleanup()
 def send(self,**args):
  with patch('workspace.threading.Thread.start'):return self.w.post('session-action',{'id':self.d['id'],'action':'regenerate','message_id':'a1','request_id':'a'*32,**args})
 def test_boundary_immutable_original_model_and_baseline(self):
  old=self.w.load(self.d['id']);b=self.send();self.assertEqual(old,self.w.load(self.d['id']))
  self.assertNotEqual(b['id'],old['id']);self.assertEqual([m['content'] for m in b['messages'][:-1]],['question 0','answer 0','question 1'])
  self.assertEqual(b['messages'][-1]['settings_snapshot']['model'],'old-model');self.assertTrue(b['model_override']['fast']);self.assertEqual(b['approval_mode'],'manual')
  self.assertEqual(self.calls[0],('thread/fork',{'threadId':'original','lastTurnId':'turn0','excludeTurns':True,'sandbox':'read-only','approvalPolicy':'on-request','model':'old-model'}));self.assertEqual(b['token_usage'],old['messages'][1]['token_usage']);self.assertEqual(b['messages'][-1]['meter']['records'],[])
  self.assertEqual(self.send()['id'],b['id']);self.assertEqual(len(self.calls),1)
  with self.assertRaises(ValueError):self.send(text='different')
 def test_edit_first_new_thread_no_future_and_keep_context(self):
  self.d['messages'][0]['attachments']=[{'name':'removed.txt','kind':'text','content':'original attachment'}]
  self.d['messages'][0]['plugins']=[{'id':'old-plugin','title':'old','instructions':'original instructions'}];self.w.save(self.d)
  b=self.send(message_id='u0',text='edited first',model_mode='current');self.assertEqual(self.calls,[]);self.assertNotIn('codex_thread',b);self.assertEqual(len(b['messages']),2)
  self.assertEqual(b['messages'][0]['attachments'],self.d['messages'][0]['attachments']);self.assertEqual(b['messages'][0]['plugins'],self.d['messages'][0]['plugins']);self.assertTrue(b['branch']['edited']);self.assertEqual(b['messages'][-1]['model'],'global-model')
  payload=json.dumps(self.w.payload(self.w.active['doc'],self.w.model(False)));self.assertNotIn('question 1',payload);self.assertIn('original attachment',payload);self.assertIn('original instructions',payload)
 def test_custom_model_scope_and_approval(self):
  oldmodel=self.w.model(False);b=self.send(model_mode='custom',override={'provider':'codex','model':'other','effort':'low','fast':False,'api_key':'must-not-copy'})
  self.assertEqual(self.w.model(False),oldmodel);self.assertNotIn('model_override',self.w.load(self.d['id']));self.assertEqual(b['model_override']['model'],'other');self.assertNotIn('must-not-copy',json.dumps(b));self.assertEqual(self.w.active['approval_mode'],'manual')
 def test_api_payload_truncates_tools_and_uses_original_attachment_snapshot(self):
  self.w.write(self.w.model_path,{'provider':'api','base_url':'https://fixture.invalid/v1','model':'api-global','api_key':'secret'});self.d['provider']='api';self.d.pop('codex_thread');self.d['messages'][1]['protocol']=[{'role':'assistant','content':'earlier tools'}];self.d['messages'][3]['protocol']=[{'role':'assistant','content':'discarded tools'}]
  for m in self.d['messages']:
   if m['role']=='assistant':m.update(model='api-original',settings_snapshot={'provider':'api','model':'api-original'})
  self.w.save(self.d);b=self.send(model_mode='custom',override={'provider':'api','model':'api-new'});payload=json.dumps(self.w.payload(self.w.active['doc'],self.w.session_model(self.w.active['doc'])))
  self.assertIn('earlier tools',payload);self.assertNotIn('discarded tools',payload);self.assertNotIn('question 2',payload);self.assertEqual(b['messages'][-1]['model'],'api-new');self.assertEqual(self.calls,[])
 def test_invalid_busy_trash_and_missing_context(self):
  before=self.w.load(self.d['id'])
  for kwargs in ({'request_id':'bad'},{'message_id':'nope'},{'text':' '},{'model_mode':'bad'},{'model_mode':'custom','override':{'provider':'api','model':'x'}}):
   with self.assertRaises(ValueError):self.send(**kwargs)
  self.w.active={'doc':{'id':'other'}}
  with self.assertRaises(ValueError):self.send()
  self.w.active=None;self.d['state']='trash';self.w.save(self.d)
  with self.assertRaises(ValueError):self.send()
  self.d['state']='active';self.d['messages'][1].pop('turn_id');self.w.save(self.d)
  with self.assertRaises(ValueError):self.send()
  self.assertEqual(len(list(self.w.root.glob('*/session.json'))),1)
 def test_preflight_failure_cleans_only_new_branch(self):
  self.w.codex.status=lambda *a,**k:{'logged_in':False};old=self.w.load(self.d['id'])
  with self.assertRaises(ValueError):self.send()
  self.assertEqual(old,self.w.load(self.d['id']));self.assertEqual(len(list(self.w.root.glob('*/session.json'))),1);self.assertEqual(self.calls[-1],('thread/delete',{'threadId':'forked'}))
 def test_archived_source_allowed_no_automatic_schedule(self):
  self.d.update(state='archived',schedule={'id':'schedule'},pinned=True);self.w.save(self.d);b=self.send(message_id='u0')
  self.assertEqual(b['state'],'active');self.assertNotIn('schedule',b);self.assertFalse(b['pinned']);self.assertEqual(self.w.load(self.d['id'])['state'],'archived')
 def test_archived_fork_restores_archive_even_on_failure(self):
  self.d['state']='archived';self.w.save(self.d);self.send()
  self.assertEqual([c[0] for c in self.calls],['thread/unarchive','thread/fork','thread/archive']);self.assertEqual(self.calls[-1][1]['threadId'],'original')
  self.w.active=None;self.calls=[]
  def broken(method,params):
   self.calls.append((method,params))
   if method=='thread/fork':raise ValueError('synthetic fork failure')
   return {}
  self.w.codex.rpc=broken
  with self.assertRaises(ValueError):self.send(request_id='b'*32)
  self.assertEqual([c[0] for c in self.calls],['thread/unarchive','thread/fork','thread/archive'])

if __name__=='__main__':unittest.main()
