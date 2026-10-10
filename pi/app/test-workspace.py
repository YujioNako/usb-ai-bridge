import io,json,pathlib,tempfile,time,urllib.error
from workspace import Workbench

class Stream(io.BytesIO):
    headers={'Content-Type':'text/event-stream'}
    def readline(self,size=-1):
        time.sleep(.015)
        return super().readline(size)

def stream(*pieces):
    chunks=[('data: '+json.dumps({'choices':[{'delta':{'content':p}}]})+'\n\n').encode() for p in pieces]
    return Stream(b''.join(chunks)+b'data: [DONE]\n\n')

def wait(w):
    limit=time.monotonic()+5
    while w.active and time.monotonic()<limit: time.sleep(.01)
    assert w.active is None,'worker did not complete'

with tempfile.TemporaryDirectory() as tmp:
    root=pathlib.Path(tmp)
    w=Workbench(root/'sessions',root/'model.json',lambda:{})
    assert not w.model()['ready']
    d=w.post('sessions',{})
    try: w.post('send',{'id':d['id'],'text':'hello'})
    except ValueError: pass
    else: raise AssertionError('missing key accepted')
    w.post('model',{'base_url':'https://model.test/v1','model':'fixture','api_key':'test-key-not-real'})
    assert 'api_key' not in w.model()
    try: w.post('model',{'base_url':'https://different.test/v1','model':'fixture'})
    except ValueError: pass
    else: raise AssertionError('key was silently reused on another host')
    try: w.get('session?id=../../settings')
    except ValueError: pass
    else: raise AssertionError('traversal accepted')
    d=w.post('files',{'id':d['id'],'name':'selected.txt','content':'Selected fixture text'})
    selected=d['files'][0]['id']
    d=w.post('files',{'id':d['id'],'name':'private.txt','content':'Not selected fixture text'})
    def reply(model,payload):
        text=json.dumps(payload)
        assert 'Selected fixture text' in text
        assert 'Not selected fixture text' not in text
        return stream('测试','回复')
    w.open_stream=reply
    w.post('send',{'id':d['id'],'text':'summarize','file_ids':[selected]})
    try: w.post('send',{'id':d['id'],'text':'duplicate'})
    except ValueError: pass
    else: raise AssertionError('concurrent generation accepted')
    wait(w)
    d=w.get('session?id='+d['id'])
    assert d['messages'][-1]['content']=='测试回复'
    assert d['messages'][-1]['status']=='done'
    restored=Workbench(root/'sessions',root/'model.json',lambda:{})
    assert restored.get('session?id='+d['id'])['messages'][-1]['content']=='测试回复'
    w.open_stream=lambda model,payload: stream(*(['token']*100))
    w.post('send',{'id':d['id'],'text':'cancel test'})
    w.post('stop',{'id':d['id']});wait(w)
    assert w.get('session?id='+d['id'])['messages'][-1]['status']=='cancelled'
    def denied(model,payload): raise urllib.error.HTTPError(model['base_url'],401,'Unauthorized',{},None)
    w.open_stream=denied
    w.post('send',{'id':d['id'],'text':'failure test'});wait(w)
    d=w.get('session?id='+d['id'])
    assert d['messages'][-1]['status']=='error'
    assert '401' in d['messages'][-1]['error']
    assert 'test-key-not-real' not in json.dumps(d)
    d['messages'][-1]['status']='streaming';w.save(d)
    restored=Workbench(root/'sessions',root/'model.json',lambda:{})
    assert restored.get('session?id='+d['id'])['messages'][-1]['status']=='streaming'
    restored.recover()
    assert restored.get('session?id='+d['id'])['messages'][-1]['status']=='interrupted'
print('PASS: model configuration, credential redaction, changed-host guard, traversal rejection, explicit attachment selection, streaming accumulation, persistence, concurrent request rejection, cancellation, upstream errors, restart recovery')
