"""USB application messages only; never an IP interface, SOCKS proxy or TCP tunnel."""
import base64, collections, concurrent.futures, hmac, http.client, json, os
import pathlib, re, select, threading, time

MAX_FRAME = 6_000_000
MAX_RESPONSE = 4_000_000
GET = {'/api/status', '/api/nodes', '/api/wifi/status', '/api/agent/status',
       '/api/workbench/workflows','/api/workbench/model', '/api/workbench/sessions'}
POST = {'/api/maintenance', '/api/security/key', '/api/wifi', '/api/wifi/scan', '/api/subscription', '/api/select', '/api/test', '/api/delay'}
POST.update('/api/agent/'+x for x in ('register','poll','result','control','approve','job','run'))
POST.update('/api/workbench/'+x for x in ('model','sessions','rename','files','send','stop','codex','session-action','steer','answer','workflows'))

def allowed(method, route):
    return isinstance(route, str) and ((method == 'GET' and
        (route in GET or re.fullmatch(r'/api/workbench/session\?id=[a-f0-9]{24}', route)))
        or (method == 'POST' and route in POST))

class Dispatcher:
    def __init__(self, token, call=None):
        self.source, self.call = token, call

    @property
    def token(self):return self.source() if callable(self.source) else self.source

    def local_call(self, method, route, body, token):
        if method == 'POST' and route == '/api/maintenance':
            from ssh_terminal import MANAGER
            try:
                return 200, json.dumps(MANAGER.action(json.loads(body), token)).encode()
            except ValueError as error:
                return 400, json.dumps({'error': str(error)}, ensure_ascii=False).encode()
        conn = http.client.HTTPConnection('127.0.0.1', 8765, timeout=65)
        try:
            conn.request(method, route, body=body, headers={
                'Authorization':'Bearer '+token, 'Content-Type':'application/json'})
            response = conn.getresponse()
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE: raise ValueError('Response exceeds serial message limit')
            return response.status, data
        finally: conn.close()

    def handle(self, frame):
        rid = frame.get('id') if isinstance(frame, dict) else None
        if not isinstance(rid, str) or not re.fullmatch(r'[a-f0-9-]{36}', rid):
            raise ValueError('Invalid request id')
        status, body = 400, b'{"error":"Invalid serial request"}'
        try:
            if frame.get('v') != 1: raise ValueError('Unsupported protocol')
            token = frame.get('token', '')
            if not isinstance(token,str) or not hmac.compare_digest(token, self.token):
                status, body = 401, b'{"error":"Device authentication failed"}'
            elif frame.get('method') == 'HELLO':
                status, body = 200, b'{"protocol":"usb-ai-serial","version":1}'
            elif not allowed(frame.get('method'), frame.get('path')):
                status, body = 403, b'{"error":"Application endpoint not allowed"}'
            else:
                raw = base64.b64decode(frame.get('body', ''), validate=True)
                if len(raw) > 400000: raise ValueError('Request too large')
                if frame['method'] == 'POST' and not isinstance(json.loads(raw or b'{}'),dict):
                    raise ValueError('Request body must be an object')
                status, body = self.call(frame['method'],frame['path'],raw) if self.call else self.local_call(frame['method'],frame['path'],raw,token)
        except (ValueError, TypeError): pass
        except Exception:
            status, body = 502, b'{"error":"Pi management service unavailable"}'
        return {'v':1,'id':rid,'status':status,'body':base64.b64encode(body).decode('ascii')}

class FrameReader:
    def __init__(self): self.buffer=bytearray();self.discard=False
    def feed(self, chunk):
        out=[]
        for part in chunk.splitlines(keepends=True):
            end=part.endswith(b'\n')
            if not self.discard:
                self.buffer.extend(part)
                if len(self.buffer)>MAX_FRAME: self.buffer.clear();self.discard=True
            if end:
                if not self.discard:
                    try:
                        frame=json.loads(self.buffer)
                        if isinstance(frame,dict): out.append(frame)
                    except (ValueError,UnicodeError): pass
                self.buffer.clear();self.discard=False
        return out

def serve(device='/dev/ttyGS0'):
    import fcntl, termios, tty
    def token():return json.loads(pathlib.Path('/etc/usb-ai-bridge/settings.json').read_text())['admin_token']
    dispatcher=Dispatcher(token)
    fd=os.open(device,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    tty.setraw(fd,termios.TCSANOW)
    lock=threading.Lock();write_lock=threading.Lock();pending=set();cache=collections.OrderedDict()
    slots=threading.BoundedSemaphore(8)
    def emit(response):
        wire=(json.dumps(response,separators=(',',':'))+'\n').encode('ascii')
        with write_lock:
            offset=0;deadline=time.monotonic()+30
            while offset<len(wire):
                if time.monotonic()>deadline: return
                if select.select([], [fd], [], .5)[1]:
                    try: offset+=os.write(fd,wire[offset:offset+16384])
                    except (BlockingIOError, OSError): return
    def process(frame):
        try:
            result=dispatcher.handle(frame)
            with lock:
                cache[frame['id']]=result
                while len(cache)>16 or sum(len(x['body']) for x in cache.values())>8_000_000:
                    cache.popitem(last=False)
            emit(result)
        except ValueError: pass
        finally:
            with lock: pending.discard(frame.get('id'))
            slots.release()
    reader=FrameReader()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            while True:
                if not select.select([fd],[],[],1)[0]: continue
                try: chunk=os.read(fd,16384)
                except OSError: time.sleep(.5);continue
                if not chunk: time.sleep(.2);continue
                for frame in reader.feed(chunk):
                    rid=frame.get('id')
                    if not isinstance(rid,str) or not re.fullmatch(r'[a-f0-9-]{36}',rid): continue
                    # Authenticate before looking up a cached response (which can contain private data).
                    auth=frame.get('token','')
                    if not isinstance(auth,str) or not hmac.compare_digest(auth,token()):
                        emit({'v':1,'id':rid,'status':401,'body':base64.b64encode(b'{"error":"Unauthorized"}').decode()});continue
                    with lock:
                        cached=cache.get(rid);inflight=rid in pending
                    if cached: emit(cached);continue
                    if inflight: continue
                    if not slots.acquire(blocking=False):
                        emit({'v':1,'id':rid,'status':503,'body':base64.b64encode(b'{"error":"Serial request queue full"}').decode()});continue
                    with lock: pending.add(rid)
                    pool.submit(process,frame)
    finally: os.close(fd)

if __name__=='__main__': serve()
