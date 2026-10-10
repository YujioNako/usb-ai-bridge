import io, json, pathlib, tempfile, threading, time
from agent_broker import AgentBroker
from workspace import Workbench
from wifi_manager import WifiManager, parse_saved_networks

saved_raw='network id / ssid / bssid / flags\n0\tcoco\tany\t[CURRENT]\n1\tcoco_ext\tany\t\n'
assert parse_saved_networks(saved_raw.strip()) == {
    'coco': {'id':0,'current':True}, 'coco_ext': {'id':1,'current':False}}
assert parse_saved_networks('1\tcoco_ext\tany\t[DISABLED]')['coco_ext']['id'] == 1
assert parse_saved_networks('unexpected output') == {}
print('PASS: saved Wi-Fi final row with empty flags survives trimmed command output')

def wait(w):
    deadline=time.monotonic()+8
    while w.active and time.monotonic()<deadline: time.sleep(.02)
    assert w.active is None,'generation stuck'

class Stream(io.BytesIO):
    headers={'Content-Type':'text/event-stream'}

def chunks(events):
    return Stream(b''.join(('data: '+json.dumps(e)+'\n\n').encode() for e in events)+b'data: [DONE]\n\n')

b=AgentBroker()
try: b.submit('files',{'op':'list'})
except ValueError: pass
else: raise AssertionError('offline tools accepted')
key=b.register({'id':'fixture','workspace':'test workspace','capabilities':['files','shell','system']})['client_key']
identity={'id':'fixture','client_key':key}
j=b.submit('shell',{'command':'fixture'})
assert j['status']=='approval'
b.approve({'job_id':j['id'],'allow':False})
assert b.get_job(j['id'])['status']=='denied'
j=b.submit('files',{'op':'read','path':'fixture'})
delivered=b.poll(identity)['job'];assert delivered['id']==j['id']
b.result({**identity,'job_id':j['id'],'result':{'content':'fixture'}})
b.result({**identity,'job_id':j['id'],'result':{'content':'wrong duplicate'}})
assert b.get_job(j['id'])['result']['content']=='fixture'
j=b.submit('files',{'op':'write','path':'cancelled','content':'no'})
b.cancel(j['id']);assert j['id'] in b.control(identity)['cancelled']
try: b.result({'id':'other','client_key':'wrong','job_id':j['id'],'result':{}})
except ValueError: pass
else: raise AssertionError('wrong client accepted')
print('PASS: companion identity, approval denial, cancellation and duplicate result idempotency')

with tempfile.TemporaryDirectory() as tmp:
    w=Workbench(pathlib.Path(tmp)/'sessions',pathlib.Path(tmp)/'model.json',lambda:{},b)
    w.configure({'base_url':'https://fixture.example/v1','model':'fixture','api_key':'not-real'})
    doc=w.post('sessions',{})
    count=[0]
    def model(_,payload):
        count[0]+=1
        if count[0]==1:
            assert any(t['function']['name']=='files' for t in payload['tools'])
            return chunks([
                {'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call_fixture','type':'function','function':{'name':'files','arguments':'{"op":"read",'}}]}}]},
                {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'"path":"fixture.txt"}'}}]},'finish_reason':'tool_calls'}]}])
        assert payload['messages'][-1]['role']=='tool'
        assert 'actual tool output' in payload['messages'][-1]['content']
        return chunks([{'choices':[{'delta':{'content':'工具调用完成'},'finish_reason':'stop'}]}])
    w.open_stream=model
    def companion():
        job=b.poll(identity)['job'];assert job['arguments']['path']=='fixture.txt'
        b.result({**identity,'job_id':job['id'],'result':{'content':'actual tool output'}})
    t=threading.Thread(target=companion);t.start()
    w.post('send',{'id':doc['id'],'text':'read fixture'})
    wait(w);t.join(2)
    reply=w.load(doc['id'])['messages'][-1]
    assert reply['status']=='done',reply
    assert reply['tools'][0]['status']=='done'
    assert count[0]==2
    assert [m['role'] for m in reply['protocol']]==['assistant','tool']
    # Approval cancellation must never hand the terminal command to the companion.
    w.open_stream=lambda *_: chunks([{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'cancel','type':'function','function':{'name':'shell','arguments':'{"command":"do not execute"}'}}]},'finish_reason':'tool_calls'}]}])
    w.post('send',{'id':doc['id'],'text':'cancel test'})
    deadline=time.monotonic()+2
    while not w.active.get('job_id') and time.monotonic()<deadline: time.sleep(.01)
    job_id=w.active['job_id'];w.post('stop',{'id':doc['id']});wait(w)
    assert b.get_job(job_id)['status']=='cancelled'
    assert w.load(doc['id'])['messages'][-1]['status']=='cancelled'
print('PASS: fragmented streaming tool calls, result-to-model loop, persistent tool trace and cancellation during approval')

class Wifi:
    def __init__(self,connect=True,dhcp=True):self.current='0';self.connect=connect;self.dhcp=dhcp;self.removed=[];self.saved=False
    def __call__(self,*a):
        if a[0]=='status':
            state='COMPLETED' if self.current=='0' or self.connect else 'SCANNING'
            return 'id='+self.current+'\nwpa_state='+state+'\nssid=fixture\n'+('ip_address=192.0.2.2' if self.dhcp else '')
        if a[0]=='add_network': return '1'
        if a[0]=='select_network': self.current=a[1]
        if a[0]=='remove_network': self.removed.append(a[1])
        if a[0]=='save_config':self.saved=True
        return 'OK'

wifi=Wifi();m=WifiManager(wifi,lambda:{},timeout=.1)
m.connect('fixture','password123',None)
assert m.status()['state']=='connected' and wifi.saved
wifi=Wifi(False);m=WifiManager(wifi,lambda:{},timeout=.01)
m.connect('fixture','wrong-password',None)
assert m.status()['state']=='failed' and m.status()['restored'] and wifi.current=='0' and '1' in wifi.removed
wifi=Wifi(True,False);m=WifiManager(wifi,lambda:{},timeout=.01)
m.connect('fixture','password123',None)
assert m.status()['state']=='failed' and 'DHCP' in m.status()['error']
wifi=Wifi();m=WifiManager(wifi,lambda:{},timeout=.1)
started=time.monotonic();job=m.start('fixture','password123')
assert time.monotonic()-started<.2 and job['state']=='queued' and wifi.current=='0'
try:m.start('fixture','password123')
except ValueError:pass
else:raise AssertionError('concurrent Wi-Fi change accepted')
time.sleep(.9);assert m.status()['state']=='connected'
print('PASS: asynchronous Wi-Fi acknowledgement, connected/IP result, authentication timeout rollback, DHCP timeout and single-flight guard')
