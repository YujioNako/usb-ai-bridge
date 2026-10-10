import unittest,io,json,pathlib,tempfile,threading,copy
import usage_meter as u
from workspace import Workbench
from codex_backend import CodexBackend
import approval_review

def raw(i,o,c=0,w=0,r=0):return dict(inputTokens=i,outputTokens=o,cachedInputTokens=c,cacheWriteInputTokens=w,reasoningOutputTokens=r,totalTokens=i+o)
def api_usage(i,o):return {'prompt_tokens':i,'completion_tokens':o,'prompt_tokens_details':{'cached_tokens':20},'completion_tokens_details':{'reasoning_tokens':5}}
def event(method,params):return {'message':{'method':method,'params':{'threadId':'t','turnId':'u',**params}}}
class Stream(io.BytesIO):headers={'Content-Type':'text/event-stream'}
def stream(events,done=True):return Stream(b''.join(('data: '+json.dumps(e)+'\n\n').encode() for e in events)+(b'data: [DONE]\n\n' if done else b''))

class MeterTests(unittest.TestCase):
 def test_cost_cache_reasoning_and_tiers(self):
  t=u.normalized(raw(1000,100,400,100,80),True);self.assertEqual(t['total'],1100)
  p=u.pricing([],'codex','gpt-6-sol');self.assertAlmostEqual(u.fee(t,p)['amount'],.00233);self.assertAlmostEqual(u.fee(t,p)['credits'],.057)
  f=u.fee(t,u.pricing([],'codex','gpt-6-sol',fast=True));self.assertAlmostEqual(f['amount'],.00466);self.assertAlmostEqual(f['credits'],.1425)
  long=u.pricing([],'codex','gpt-6-sol',long=True);self.assertEqual(long['rates']['input'],4);self.assertEqual(long['rates']['output'],15)
  self.assertIsNone(u.fee(t,u.pricing([],'api','gpt-6-sol','https://other.invalid/v1'))['amount'])
  self.assertIsNone(u.fee(t,u.pricing([],'codex','unknown'))['amount'])
 def test_cumulative_and_reconnect(self):
  m=u.create('codex');s={'previous':u.normalized(raw(1000,100,200),True)}
  value={'total':raw(3000,300,600,0,70),'last':raw(500,50,100,0,10)}
  u.codex_event(m,s,value,[],'gpt-6-sol',False);u.codex_event(m,s,value,[],'gpt-6-sol',False)
  self.assertEqual(u.summarize(m)['tokens']['total'],2200)
  u.codex_event(m,s,{'total':raw(3300,330,600,0,80),'last':raw(300,30)},[],'gpt-6-sol',False)
  self.assertEqual(u.summarize(m)['tokens']['total'],2530)
  u.codex_event(m,s,{'total':raw(100,10),'last':raw(100,10)},[],'gpt-6-sol',False);self.assertTrue(m['notes'])
 def test_custom_binding_validation_and_snapshot(self):
  row=dict(provider='api',endpoint='https://other.invalid/v1',model='custom',tier='standard',currency='CNY',input=1,cached=.1,cache_write=1,output=2)
  book=u.custom_rates([row]);p=u.pricing(book,'api','custom',row['endpoint']);book[0]['input']=99
  self.assertEqual(p['rates']['input'],1);self.assertIsNone(u.pricing(book,'api','custom','https://different.invalid/v1')['rates'])
  for bad in ({'endpoint':None},{'input':float('nan')},{'output':True},{'endpoint':'https://u:secret@example.com/v1'}):
   with self.assertRaises(ValueError):u.custom_rates([{**row,**bad}])
 def test_legacy_and_separate_review_reference(self):
  d={'messages':[{'role':'user','content':'hello'},{'role':'assistant','content':'ok','status':'done','model':'unknown'}]}
  display=u.decorate(d,[])['messages'][-1]['usage_display'];self.assertTrue(display['estimated']);self.assertEqual(display['amounts'],{});self.assertTrue(display['notes'])
  d['messages'][-1].update(status='interrupted',meter=u.create('api'));display=u.decorate(d,[])['messages'][-1]['usage_display'];self.assertTrue(display['estimated']);self.assertGreater(display['tokens']['total'],0)
  m=u.create('api');t=u.normalized(raw(1000,100),True)
  u.put(m,'api',t,u.pricing([],'api','gpt-6-sol','https://api.openai.com/v1'));u.put(m,'review',t,u.pricing([],'codex','gpt-6-sol'),scope='review')
  v=u.summarize(m);self.assertEqual(v['amounts'],{'USD':.003});self.assertEqual(v['reference_amounts'],{'USD':.003});self.assertEqual(v['tokens']['total'],2200)
 def test_stream_json_and_missing_usage(self):
  with tempfile.TemporaryDirectory() as temp:
   root=pathlib.Path(temp);w=Workbench(root/'sessions',root/'model.json',lambda:{});d=w.post('sessions',{})
   d['messages']=[{'role':'user','content':'test'},{'role':'assistant','content':'','status':'streaming','meter':u.create('api')}]
   a={'doc':d,'stop':threading.Event(),'price_book':[]};model={'provider':'api','model':'gpt-6-sol','base_url':'https://api.openai.com/v1'}
   w.open_stream=lambda *args:stream([{'choices':[{'delta':{'content':'ok'},'finish_reason':'stop'}]},{'choices':[],'usage':api_usage(100,20)}])
   w.read_round(a,model,{'messages':[{'content':'test'}]})
   response=Stream(json.dumps({'choices':[{'message':{'content':'second'}}],'usage':api_usage(200,30)}).encode());response.headers={'Content-Type':'application/json'}
   w.open_stream=lambda *args:response;w.read_round(a,model,{'messages':[{'content':'tools result'}]})
   v=u.summarize(d['messages'][-1]['meter']);self.assertEqual(v['tokens']['total'],350);self.assertEqual(v['tokens']['reasoning'],10);self.assertFalse(v['estimated']);self.assertEqual(len(v['records']),2)
   w.open_stream=lambda *args:stream([{'choices':[{'delta':{'content':'partial'}}]}],False)
   with self.assertRaises(ValueError):w.read_round(a,model,{'messages':[{'content':'test'}]})
   v=u.summarize(d['messages'][-1]['meter']);self.assertTrue(v['estimated']);self.assertTrue(v['notes']);self.assertEqual(len(v['records']),3)
   w.prices({'operation':'save','rate':dict(provider='api',endpoint=model['base_url'],model=model['model'],tier='standard',currency='USD',input=100,cached=10,cache_write=100,output=100)})
   self.assertEqual(d['messages'][-1]['meter']['records'][0]['price']['rates']['input'],2)
 def test_codex_usage_after_completion_and_review(self):
  class Fake(CodexBackend):
   def rpc(self,method,params=None):
    if method=='thread/start':return {'thread':{'id':'t'},'model':'gpt-6-sol'}
    if method=='turn/start':return {'turn':{'id':'u'}}
    return {}
   def transport(self,path,data):
    if data.get('snapshot'):return {'cursor':0,'epoch':'e'}
    return {'cursor':1,'epoch':'e','events':[event('item/completed',{'item':{'type':'agentMessage','id':'m','text':'{"decision":"approve","reason":"ok"}'}}),event('turn/completed',{'turn':{'status':'completed'}}),event('thread/tokenUsage/updated',{'tokenUsage':{'total':raw(100,20),'last':raw(100,20)}})]}
  with tempfile.TemporaryDirectory() as temp:
   root=pathlib.Path(temp);w=Workbench(root/'sessions',root/'model.json',lambda:{});d=w.post('sessions',{});d['messages']=[{'role':'user','content':'test'},{'role':'assistant','content':'','status':'streaming'}];a={'doc':d,'stop':threading.Event(),'price_book':[]};w.active=a
   Fake().run(w,a,{'provider':'codex','model':'gpt-6-sol'});self.assertEqual(d['messages'][-1]['status'],'done');self.assertEqual(u.summarize(d['messages'][-1]['meter'])['tokens']['total'],120)
   result=approval_review.review(Fake(),a,'files',{'op':'list'},'fixture');self.assertEqual(result['decision'],'approve');self.assertEqual(u.summarize(result['usage_meter'])['tokens']['total'],120)

if __name__=='__main__':unittest.main()
