import base64,datetime,io,json,pathlib,tempfile,time,unittest,zipfile
from workspace import Workbench
from workflows import Workflows,TZ
from agent_broker import AgentBroker

class Model:
    def __init__(self):self.started=[]
    def status(self):return {'logged_in':True}
    def options(self,model,effort,fast):return {'model':model or 'fixture','effort':effort or 'medium','serviceTier':'priority' if fast else 'default'}
    def run(self,bench,active,model):
        with bench.lock:
            self.started.append((active['doc']['id'],active['no_tools'],model))
            active['doc']['messages'][-1].update(status='done',content='fixture completed')
            bench.save(active['doc']);bench.active=None

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
        self.broker=AgentBroker();self.broker.register({'id':'fixture-pc','machine_id':'a'*64,'workspace':'C:\\Fixture','capabilities':['files','system']})
        self.w=Workbench(self.root/'sessions',self.root/'model.json',lambda:{},self.broker);self.w.codex=Model()
        self.w.write(self.w.model_path,{'provider':'codex','codex_model':'fixture','codex_effort':'low','codex_fast':False})
        self.f=self.w.workflows
    def tearDown(self):
        for _ in range(100):
            if not self.w.active:break
            time.sleep(.01)
        self.tmp.cleanup()
    def create(self,**kw):return self.f.put_schedule({'title':'fixture schedule','prompt':'hello','mode':'interval','minutes':5,'enabled':True,'require_windows':True,'plugin_ids':[],**kw})
    def settle(self):
        for _ in range(100):
            if not self.w.active:break
            time.sleep(.01)
        self.f.tick()
    def zip(self,entries):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            for name,content in entries.items():z.writestr(name,content)
        return base64.b64encode(buf.getvalue()).decode()
    def test_plugins_roundtrip_and_selection(self):
        p=self.f.put_plugin({'id':'fixture','title':'测试插件','description':'safe','instructions':'MARKER-INSTRUCTIONS'})
        exported=self.f.export_zip(p['id']);self.f.action({'action':'plugin-delete','id':p['id']});self.f.import_zip(exported['base64'])
        d=self.w.post('sessions',{})
        with self.w.lock:self.w.begin({'id':d['id'],'text':'test','plugin_ids':['fixture']})
        self.settle();saved=self.w.load(d['id']);self.assertIn('MARKER-INSTRUCTIONS',self.w.payload(saved,self.w.model(False))['messages'][1]['content'])
        self.f.action({'action':'plugin-toggle','id':'fixture'})
        with self.assertRaises(ValueError):self.f.resolve(['fixture'])
        with self.assertRaises(ValueError):self.f.resolve(['a','b','c','d'])
    def test_reject_unsupported_plugins_and_zip_escape(self):
        base={'.codex-plugin/plugin.json':json.dumps({'name':'fixture','skills':'./skills/'}),'skills/main/SKILL.md':'safe'}
        for extra in [{'../escape.txt':'bad'},{'hooks/start.sh':'bad'},{'.mcp.json':'{}'}]:
            with self.assertRaises(ValueError):self.f.import_zip(self.zip({**base,**extra}))
        base['.codex-plugin/plugin.json']=json.dumps({'name':'fixture','mcpServers':'./.mcp.json'})
        with self.assertRaises(ValueError):self.f.import_zip(self.zip(base))
    def test_due_once_only_and_model_snapshot(self):
        s=self.create();s['next_due']=time.time()-1;self.f.save()
        with self.w.lock:self.f.tick();self.f.tick()
        self.settle();self.assertEqual(len(self.w.codex.started),1)
        self.assertEqual(self.f.data['runs'][-1]['status'],'done')
        self.assertEqual(self.w.codex.started[0][2]['codex_effort'],'low')
        self.assertEqual(self.w.load(self.w.codex.started[0][0])['title'],'fixture schedule')
        self.f.tick();self.assertEqual(len(self.w.codex.started),1)
    def test_approval_snapshot_and_legacy_default(self):
        self.w.configure({'provider':'codex','model':'fixture','default_approval_mode':'assist'})
        s=self.create();self.assertEqual(s['approval_mode'],'assist')
        self.w.configure({'provider':'codex','model':'fixture','default_approval_mode':'full'})
        with self.w.lock:r=self.f.dispatch(s,True)
        self.settle();self.assertEqual(self.w.load(r['session_id'])['messages'][0]['approval_mode'],'assist')
        s.pop('approval_mode')
        with self.w.lock:r=self.f.dispatch(s,True)
        self.settle();self.assertEqual(self.w.load(r['session_id'])['approval_mode'],'manual')
    def test_offline_wrong_workspace_and_missed_window(self):
        s=self.create();s['next_due']=time.time()-1;self.broker.client['seen']=0
        self.f.tick();self.assertTrue(self.f.waiting);self.assertEqual(len(self.w.codex.started),0)
        self.broker.client.update(seen=time.monotonic(),workspace='C:\\Different');self.f.tick()
        self.assertIn('不符',self.f.waiting[s['id']])
        s['next_due']=time.time()-601;self.f.tick();self.assertEqual(self.f.data['runs'][-1]['status'],'skipped')
        self.assertGreater(s['next_due'],time.time());self.assertEqual(len(self.w.codex.started),0)
    def test_crash_claim_not_replayed(self):
        s=self.create(mode='once',at=time.time()+20,require_windows=False);s['at']=s['next_due']=time.time()-1
        def crash(*args,**kwargs):raise KeyboardInterrupt('power lost')
        self.w.begin=crash
        with self.assertRaises(KeyboardInterrupt):self.f.dispatch(s)
        recovered=Workflows(self.w,self.f.path);recovered.recover();recovered.tick()
        self.assertEqual(recovered.data['runs'][-1]['status'],'interrupted')
        self.assertFalse(recovered.data['schedules'][0]['enabled']);self.assertEqual(len(self.w.codex.started),0)
    def test_plugin_change_blocks_schedule(self):
        self.f.put_plugin({'id':'fixture','title':'test','instructions':'original'})
        s=self.create(plugin_ids=['fixture']);s['next_due']=time.time()-1
        self.f.put_plugin({'id':'fixture','title':'test','instructions':'changed'},True)
        self.f.tick();self.assertFalse(s['enabled']);self.assertIn('重新保存',self.f.data['runs'][-1]['error'])
    def test_ai_only_has_no_windows_tools(self):
        s=self.create(require_windows=False);self.f.dispatch(s,manual=True);self.settle()
        self.assertTrue(self.w.codex.started[0][1]);d=self.w.load(self.w.codex.started[0][0]);self.assertNotIn('tools',self.w.payload(d,self.w.model(False)))
    def test_pause_and_delete_and_validation(self):
        s=self.create();self.f.action({'action':'schedule-toggle','id':s['id']});self.assertFalse(s['enabled'])
        self.f.action({'action':'schedule-delete','id':s['id']});self.assertFalse(self.f.data['schedules'])
        with self.assertRaises(ValueError):self.create(minutes=0)
        with self.assertRaises(ValueError):self.create(mode='daily',time='24:99')
    def test_weekday_clock(self):
        friday=datetime.datetime(2026,9,25,20,0,tzinfo=TZ).timestamp()
        next_run=Workflows.next_time({'mode':'weekdays','time':'09:00'},friday)
        self.assertEqual(datetime.datetime.fromtimestamp(next_run,TZ).isoformat(),'2026-09-28T09:00:00+08:00')
    def test_new_connection_same_machine_stays_bound(self):
        s=self.create();self.broker.client['seen']=0
        self.broker.register({'id':'new-instance','machine_id':'a'*64,'workspace':'C:\\Fixture','capabilities':['files']})
        self.assertEqual(self.f.block_reason(s),'')
        self.broker.client['machine_id']='b'*64
        self.assertIn('不符',self.f.block_reason(s))

if __name__=='__main__':unittest.main()
