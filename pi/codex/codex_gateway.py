"""Private UNIX-socket facade for the official Codex stdio app-server."""
import collections,http.server,json,os,pathlib,queue,socketserver,subprocess,threading,time,uuid

class Runtime:
    def __init__(self,command):
        self.lock=threading.RLock();self.write_lock=threading.Lock();self.pending={};self.seq=0
        self.events=collections.deque();self.event_bytes=0;self.epoch=uuid.uuid4().hex;self.requests=set()
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=None,text=True,bufsize=1)
        threading.Thread(target=self.read,daemon=True).start()
        self.rpc('initialize',{'clientInfo':{'name':'usb_ai_bridge','version':'0.3.0'},'capabilities':{'experimentalApi':True}})
        self.write({'method':'initialized','params':{}})
    def write(self,message):
        with self.write_lock:
            self.process.stdin.write(json.dumps(message,ensure_ascii=False)+'\n');self.process.stdin.flush()
    def read(self):
        try:
            for line in self.process.stdout:
                message=json.loads(line)
                with self.lock:
                    if 'method' not in message:
                        waiter=self.pending.get(message.get('id'))
                        if waiter:waiter.put(message)
                    else:
                        if 'id' in message:self.requests.add(message['id'])
                        self.seq+=1;size=len(line.encode());self.events.append({'seq':self.seq,'message':message,'bytes':size});self.event_bytes+=size
                        while self.event_bytes>2000000 and len(self.events)>1:self.event_bytes-=self.events.popleft()['bytes']
        finally:
            with self.lock:
                for waiter in self.pending.values():waiter.put({'error':{'message':'Codex process exited'}})
            os._exit(1)  # systemd restarts the complete runtime; clients detect epoch change.
    def rpc(self,method,params):
        rid=uuid.uuid4().hex;waiter=queue.Queue()
        with self.lock:self.pending[rid]=waiter
        try:
            self.write({'id':rid,'method':method,'params':params})
            result=waiter.get(timeout=45)
            if 'error' in result:raise ValueError(result['error'].get('message','Codex request failed'))
            return result.get('result',{})
        finally:
            with self.lock:self.pending.pop(rid,None)
    def handle(self,path,data):
        if path=='/events':
            with self.lock:
                after=int(data.get('after',0))
                if self.events and after and after<self.events[0]['seq']-1:raise ValueError('Codex event history expired')
                selected=[e for e in self.events if e['seq']>after][:80] if not data.get('snapshot') else []
                return {'epoch':self.epoch,'cursor':selected[-1]['seq'] if selected else self.seq,'events':selected}
        if path=='/reply':
            with self.lock:
                rid=data.get('id')
                if rid not in self.requests:raise ValueError('Unknown server request')
                self.requests.remove(rid)
            self.write({'id':rid,**({'error':data['error']} if 'error' in data else {'result':data['result']})});return {'ok':True}
        if path=='/rpc':
            if data.get('method') not in {'account/read','account/login/start','account/login/cancel','account/logout','account/rateLimits/read','model/list','thread/start','thread/resume','thread/archive','thread/unarchive','thread/delete','thread/fork','turn/start','turn/interrupt','turn/steer'}:
                raise ValueError('Unsupported Codex method')
            return self.rpc(data['method'],data.get('params',{}))
        raise ValueError('Unknown runtime endpoint')

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=3000000:raise ValueError('Invalid request size')
            data=json.loads(self.rfile.read(size));result=self.server.runtime.handle(self.path,data);status=200
        except Exception as e:result={'error':str(e)[:1000]};status=400
        raw=json.dumps(result,ensure_ascii=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
class Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):daemon_threads=True
if __name__=='__main__':
    socket_path='/run/usb-ai-codex/runtime.sock';pathlib.Path(socket_path).unlink(missing_ok=True)
    runtime=Runtime(['/opt/usb-ai-codex/codex','app-server'])
    with Server(socket_path,Handler) as server:
        os.chmod(socket_path,0o600);server.runtime=runtime;server.serve_forever()
