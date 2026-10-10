import unittest,tempfile,pathlib,threading,json
from unittest.mock import patch
from workspace import Workbench
from agent_broker import AgentBroker

class SessionSettings(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();p=pathlib.Path(self.tmp.name)
  self.b=AgentBroker();self.b.register({'id':'fixture','capabilities':['shell','files'],'workspace':'fixture'})
  self.w=Workbench(p/'sessions',p/'model.json',lambda:{},self.b)
  self.w.codex.status=lambda *a,**k:{'logged_in':True}
  self.w.codex.options=lambda model,effort,fast:{'model':model or 'default','effort':effort or 'medium'}
  self.w.configure({'provider':'codex','model':'global-a','effort':'medium','fast':False})
  self.a=self.w.post('sessions',{});self.c=self.w.post('sessions',{})
 def tearDown(self):self.tmp.cleanup()
 def setting(self,sid,**args):return self.w.post('session-action',{'id':sid,**args})
 def test_inherit_override_reset_isolation_and_persistence(self):
  override={'provider':'codex','model':'local','effort':'high','fast':True,'api_key':'must-not-persist'}
  self.setting(self.a['id'],action='model-settings',override=override)
  self.setting(self.a['id'],action='permissions',mode='manual')
  self.w.configure({'provider':'codex','model':'global-b','effort':'low','fast':False,'default_approval_mode':'assist'})
  a=self.w.session_view(self.w.load(self.a['id']));c=self.w.session_view(self.w.load(self.c['id']))
  self.assertEqual((a['settings']['model']['model'],a['settings']['approval_mode']),('local','manual'))
  self.assertEqual((c['settings']['model']['model'],c['settings']['approval_mode']),('global-b','assist'))
  self.assertNotIn('must-not-persist',self.w.path(a['id']).read_text())
  fresh=Workbench(self.w.root,self.w.model_path,lambda:{},self.b)
  self.assertEqual(fresh.session_model(fresh.load(a['id']))['codex_fast'],True)
  self.setting(a['id'],action='model-settings',override=None);self.setting(a['id'],action='permissions',mode='inherit')
  self.assertEqual(self.w.session_model(self.w.load(a['id']))['model'],'global-b')
  self.assertEqual(self.w.effective_approval(self.w.load(a['id'])),'assist')
 def test_turn_snapshot_drives_tool_approval_and_history(self):
  self.w.configure({'provider':'codex','model':'global-a','default_approval_mode':'full'})
  with patch('workspace.threading.Thread.start'):
   doc=self.w.begin({'id':self.a['id'],'text':'synthetic test'})
  self.assertEqual(doc['messages'][-1]['settings_snapshot']['approval_mode'],'full')
  m=self.w.model(False);m['default_approval_mode']='manual';self.w.write(self.w.model_path,m)
  job=self.w.submit_job(self.w.active,'shell',{'command':'Get-Date'},{});self.assertEqual(job['status'],'queued');self.b.cancel(job['id'])
  self.assertIn('当前审批模式：full',self.w.payload(self.w.active['doc'],m)['messages'][0]['content'])
  for action,args in [('permissions',{'mode':'manual'}),('model-settings',{'override':None})]:
   with self.assertRaises(ValueError):self.setting(self.a['id'],action=action,**args)
 def test_metadata_sync_changes_when_global_defaults_change(self):
  a=self.w.sync({'id':self.a['id']})
  self.w.configure({'provider':'codex','model':'new','default_approval_mode':'assist'})
  b=self.w.sync({'id':self.a['id'],'meta_hash':a['meta_hash']})
  self.assertNotEqual(a['meta_hash'],b['meta_hash']);self.assertEqual(b['meta']['settings']['approval_mode'],'assist')
 def test_invalid_inputs_do_not_mutate_and_no_credentials_exposed(self):
  old=self.w.load(self.a['id'])
  for value in ['bad',{'provider':'api','model':'wrong'},{'provider':'codex','model':123},{'provider':'codex','model':'x','fast':'false'}]:
   with self.assertRaises(ValueError):self.setting(self.a['id'],action='model-settings',override=value)
  with self.assertRaises(ValueError):self.w.configure({'provider':'codex','model':'new','default_approval_mode':'invalid'})
  self.assertEqual(old,self.w.load(old['id']))
  self.w.write(self.w.model_path,{'provider':'api','base_url':'https://example.test/v1','model':'a','api_key':'PRIVATE','default_approval_mode':'assist'})
  view=self.w.get('session?id='+old['id']);self.assertNotIn('PRIVATE',json.dumps(view))
  self.setting(old['id'],action='model-settings',override={'provider':'api','model':'b'})
  self.assertEqual(self.w.session_model(self.w.load(old['id']))['model'],'b')
  self.w.configure({'base_url':'https://example.test/v1','model':'c','api_key':''})
  self.assertEqual(self.w.default_approval(),'assist')
 def test_provider_conflict_and_fork_preserve_preferences(self):
  self.setting(self.a['id'],action='model-settings',override={'provider':'codex','model':'local'})
  self.setting(self.a['id'],action='permissions',mode='assist')
  clone=self.setting(self.a['id'],action='fork');self.assertEqual(clone['approval_mode'],'assist');self.assertEqual(clone['model_override']['model'],'local')
  self.w.write(self.w.model_path,{'provider':'api','model':'a','base_url':'https://example.test','api_key':'key'})
  self.assertTrue(self.w.session_view(clone)['settings']['provider_conflict'])
  with self.assertRaises(ValueError):self.w.session_model(clone)
if __name__=='__main__':unittest.main()
