import unittest,tempfile,pathlib,threading,json
from unittest.mock import patch
from workspace import Workbench,file_reference
from agent_broker import AgentBroker
class Documents(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();p=pathlib.Path(self.tmp.name);self.b=AgentBroker();self.b.register({'id':'fixture','machine_id':'a'*64,'workspace':'C:\\Fixture','capabilities':['files']});self.w=Workbench(p/'sessions',p/'model.json',lambda:{},self.b);self.doc=self.w.post('sessions',{});self.ref={'storage':'windows','path':'.usbai-attachments/'+self.doc['id']+'/'+'b'*24+'/book.xlsx','bytes':8000000,'sha256':'c'*64,'machine_id':'a'*64,'workspace':'C:\\Fixture'}
 def tearDown(self):self.tmp.cleanup()
 def add(self,ref=None):return self.w.post('files',{'id':self.doc['id'],'kind':'file','name':'book.xlsx','reference':ref or self.ref})
 def test_persistence_and_model_reference(self):
  d=self.add();f=d['files'][0];self.assertEqual(f['size'],8000000);self.assertEqual(f['reference'],self.ref);self.assertLess(len(f['content']),1000)
  d['messages']=[{'role':'user','content':'Analyze','attachments':[f]},{'role':'assistant','content':''}];payload=self.w.payload(d,{'model':'fixture'});self.assertIn('必须调用',payload['messages'][0]['content']);self.assertIn('Windows 文件引用',payload['messages'][-1]['content']);self.assertIn('book.xlsx',payload['messages'][-1]['content'])
 def test_invalid_and_wrong_target(self):
  for field,value in [('bytes',True),('bytes',100000001),('path','../secret'),('machine_id','z'*64),('workspace','D:\\Other'),('path','.usbai-attachments/'+'d'*24+'/'+'b'*24+'/file.xlsx')]:
   with self.assertRaises(ValueError):self.add({**self.ref,field:value})
 def test_turn_requires_matching_online_tools(self):
  d=self.add();args={'id':d['id'],'text':'Analyze','file_ids':[d['files'][0]['id']]};model={'provider':'api','model':'fixture','base_url':'https://model.test/v1','api_key':'fixture'}
  with self.assertRaises(ValueError):self.w.begin(args,model_override=model,no_tools=True)
  self.b.client['workspace']='C:\\Other'
  with self.assertRaises(ValueError):self.w.begin(args,model_override=model)
  self.b.client['workspace']='C:\\Fixture'
  with patch.object(threading.Thread,'start',lambda _:None):result=self.w.begin(args,model_override=model)
  self.assertEqual(result['messages'][-2]['attachments'][0]['reference'],self.ref)
 def test_legacy_text_unchanged_and_remove(self):
  self.w.post('files',{'id':self.doc['id'],'kind':'text','name':'old.txt','content':'old text'});d=self.add();self.assertEqual(d['files'][0]['content'],'old text');d=self.w.post('files',{'id':d['id'],'action':'remove','file_id':d['files'][1]['id']});self.assertEqual(len(d['files']),1)
if __name__=='__main__':unittest.main()
