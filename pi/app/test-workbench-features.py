import pathlib,tempfile,threading,time,unittest
from workspace import Workbench
from codex_backend import CodexBackend

class Runtime(CodexBackend):
    def __init__(self):super().__init__();self.calls=[];self.answers=[];self.stage=0;self.fail=False
    def rpc(self,method,params=None):
        self.calls.append((method,params))
        if self.fail:raise ValueError('fixture runtime offline')
        if method=='account/read':return {'account':{'type':'chatgpt'}}
        if method=='model/list':return {'data':[{'model':'fixture','isDefault':True,'defaultReasoningEffort':'medium','supportedReasoningEfforts':[{'reasoningEffort':e} for e in ('low','medium','high','xhigh','max')],'serviceTiers':[{'id':'priority'}]}]}
        if method in ('thread/start','thread/resume','thread/unarchive'):return {'thread':{'id':'thread-fixture'}}
        if method=='thread/fork':return {'thread':{'id':'thread-fork'}}
        if method=='turn/start':self.stage=0;return {'turn':{'id':'turn-fixture'}}
        return {}
    def transport(self,path,data):
        if path=='/reply':self.answers.append(data);return {}
        if data.get('snapshot'):return {'epoch':'fixture','cursor':1,'events':[]}
        self.stage+=1
        def event(method,params,rid=None):
            message={'method':method,'params':{'threadId':'thread-fixture','turnId':'turn-fixture',**params}}
            if rid is not None:message['id']=rid
            return {'message':message}
        if self.stage==1:
            events=[event('turn/plan/updated',{'plan':[{'step':'Verify','status':'inProgress'}]}),event('thread/tokenUsage/updated',{'tokenUsage':{'last':{'totalTokens':13},'total':{'totalTokens':20}}}),event('item/tool/requestUserInput',{'questions':[{'id':'q','question':'Choose','options':None}]},'request-fixture')]
        elif not self.answers:events=[]
        else:events=[event('item/agentMessage/delta',{'itemId':'answer','delta':'done'}),event('turn/completed',{'turn':{'status':'completed'}})]
        return {'epoch':'fixture','cursor':self.stage+1,'events':events}

class Features(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=pathlib.Path(self.tmp.name)
        self.w=Workbench(root/'sessions',root/'model.json',lambda:{});self.w.codex=Runtime()
        self.w.configure({'provider':'codex','model':'fixture','effort':'high','fast':True})
        self.doc=self.w.post('sessions',{'title':'keep'});self.sid=self.doc['id']
    def tearDown(self):
        if self.w.active:
            self.w.active['stop'].set()
            for _ in range(100):
                if not self.w.active:break
                time.sleep(.02)
        self.tmp.cleanup()
    def act(self,action,**kw):return self.w.post('session-action',{'id':self.sid,'action':action,**kw})
    def test_archive_restore_delete_and_fork(self):
        d=self.w.load(self.sid);d['codex_thread']='thread-fixture';self.w.save(d)
        clone=self.act('fork');self.assertEqual(clone['codex_thread'],'thread-fork');self.assertNotEqual(clone['id'],self.sid)
        self.assertTrue(self.act('pin')['pinned'])
        self.assertEqual(self.act('archive')['state'],'archived')
        with self.assertRaises(ValueError):self.w.post('send',{'id':self.sid,'text':'forbidden'})
        self.act('trash');self.assertEqual(self.act('restore')['state'],'archived')
        self.act('unarchive');self.act('trash')
        with self.assertRaises(ValueError):self.act('purge',confirm='wrong')
        self.act('purge',confirm=self.sid)
        self.assertEqual(self.w.load(clone['id'])['title'],'keep · 分支')
        with self.assertRaises(ValueError):self.w.load(self.sid)
        self.assertIn(('thread/delete',{'threadId':'thread-fixture'}),self.w.codex.calls)
    def test_failed_remote_archive_preserves_local(self):
        d=self.w.load(self.sid);d['codex_thread']='thread-fixture';self.w.save(d);self.w.codex.fail=True
        with self.assertRaises(ValueError):self.act('archive')
        self.assertEqual(self.w.load(self.sid).get('state','active'),'active')
    def test_options_validation_and_standard_reset(self):
        self.assertEqual(self.w.model()['effort'],'high');self.assertTrue(self.w.model()['fast'])
        with self.assertRaises(ValueError):self.w.configure({'provider':'codex','model':'fixture','effort':'invented','fast':True})
        self.assertEqual(self.w.model()['effort'],'high')
        self.w.configure({'provider':'codex','model':'fixture','effort':'','fast':False})
        effective=self.w.codex.options('fixture','',False)
        self.assertEqual(effective,{'model':'fixture','effort':'medium','serviceTier':'default'})
    def test_stream_questions_steer_usage_and_settings(self):
        self.w.post('send',{'id':self.sid,'text':'test'})
        for _ in range(150):
            if self.w.active and self.w.active.get('questions'):break
            time.sleep(.02)
        self.assertTrue(self.w.active['questions'])
        with self.assertRaises(ValueError):self.act('trash')
        with self.assertRaises(ValueError):self.w.post('answer',{'id':self.sid,'request_id':'other','answers':{'q':'a'}})
        self.w.post('steer',{'id':self.sid,'text':'additional instruction'})
        self.w.post('answer',{'id':self.sid,'request_id':'request-fixture','answers':{'q':'a'}})
        for _ in range(150):
            if self.w.active is None:break
            time.sleep(.02)
        self.assertIsNone(self.w.active)
        d=self.w.load(self.sid);reply=d['messages'][-1]
        self.assertEqual(reply['status'],'done');self.assertEqual(reply['questions'][0]['status'],'answered')
        self.assertEqual(reply['plan'][0]['step'],'Verify');self.assertEqual(d['token_usage']['last']['totalTokens'],13)
        start=next(p for m,p in self.w.codex.calls if m=='turn/start')
        self.assertEqual((start['effort'],start['serviceTier']),('high','priority'))
        self.assertEqual(self.w.codex.answers[0]['result'],{'answers':{'q':{'answers':['a']}}})
        self.assertEqual(reply['steering'][0]['text'],'additional instruction')
    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):self.w.post('session-action',{'id':'../model.json','action':'purge','confirm':'../model.json'})

if __name__=='__main__':unittest.main()
