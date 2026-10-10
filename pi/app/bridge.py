#!/usr/bin/env python3
"""USB-only management plane. Subscription and proxy credentials stay on device."""
import concurrent.futures, contextlib, datetime, fcntl, hashlib, hmac, http.server, ipaddress, json, os
import pathlib, re, shutil, subprocess, threading, time, urllib.error, urllib.parse, urllib.request
import yaml
import workspace
import agent_broker
from key_rotation import KeyRotation
from wifi_manager import WifiManager, parse_saved_networks

ROOT = pathlib.Path('/var/lib/usb-ai-bridge')
SETTINGS = pathlib.Path('/etc/usb-ai-bridge/settings.json')
APP = pathlib.Path('/opt/usb-ai-bridge')
LOCK = threading.Lock()
WIFI_LOCK = threading.Lock()

@contextlib.contextmanager
def config_lock():
    with (ROOT / 'update.lock').open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def settings():
    return json.loads(SETTINGS.read_text())

AGENT = agent_broker.AgentBroker()
BENCH = workspace.Workbench(ROOT / 'workbench', SETTINGS.with_name('model.json'), settings, AGENT)

def atomic(path, data):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(data)
    tmp.chmod(0o600)
    tmp.replace(path)

def run(args, timeout=20, data=None):
    return subprocess.run(args, input=data, text=True, capture_output=True, timeout=timeout)

def control(path, method='GET', data=None, timeout=15):
    s = settings()
    req = urllib.request.Request('http://127.0.0.1:9090' + path, method=method,
        data=None if data is None else json.dumps(data).encode(),
        headers={'Authorization':'Bearer ' + s['controller_secret'], 'Content-Type':'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}

def download_subscription(url):
    if urllib.parse.urlsplit(url).scheme != 'https':
        raise ValueError('订阅地址必须使用 HTTPS')
    req = urllib.request.Request(url, headers={'User-Agent':'clash.meta'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=35) as r:
        raw = r.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('订阅超过 8 MB 限制')
    doc = yaml.safe_load(raw)
    if not isinstance(doc, dict) or not isinstance(doc.get('proxies'), list):
        raise ValueError('需要包含 proxies 的 Clash YAML 订阅')
    nodes = []
    seen = set()
    for node in doc['proxies']:
        if not isinstance(node, dict) or not all(k in node for k in ('name','type','server','port')):
            continue
        if node['name'] in seen or node['name'] in ('Agent-Proxy','DIRECT','REJECT','GLOBAL'):
            continue
        # Deliberately import nodes only; remote configs cannot override listeners or load files.
        if any(k in node for k in ('private-key-path','certificate','private-key','dialer-proxy')):
            if 'private-key-path' in node or 'dialer-proxy' in node:
                continue
        seen.add(node['name'])
        nodes.append(node)
    if not nodes:
        raise ValueError('订阅中没有可用的内联节点')
    return raw, nodes

def make_config(nodes, s):
    return {
        'mixed-port':7890, 'allow-lan':False, 'bind-address':'127.0.0.1',
        'lan-allowed-ips':['127.0.0.0/8', '172.31.240.0/24'],
        'authentication':[s['proxy_user'] + ':' + s['proxy_password']],
        'skip-auth-prefixes':[], 'mode':'rule', 'log-level':'warning', 'ipv6':False,
        'external-controller':'127.0.0.1:9090', 'secret':s['controller_secret'],
        'profile':{'store-selected':True}, 'find-process-mode':'off',
        'proxies':nodes,
        'proxy-groups':[{'name':'Agent-Proxy', 'type':'select', 'proxies':[n['name'] for n in nodes] or ['DIRECT']}],
        'rules':['MATCH,Agent-Proxy'],
    }

def update_subscription(url=None, first=False):
    with LOCK, config_lock():
        s = settings()
        url = url or s['subscription_url']
        raw, nodes = download_subscription(url)
        target = ROOT / 'config.yaml'
        candidate = ROOT / 'candidate.yaml'
        atomic(candidate, yaml.safe_dump(make_config(nodes,s), allow_unicode=True, sort_keys=False))
        checked = run(['/usr/local/bin/mihomo','-t','-d',str(ROOT),'-f',str(candidate)],timeout=40)
        if checked.returncode:
            raise ValueError('Mihomo 配置验证失败，已保留原配置')
        previous = target.read_text() if target.exists() else None
        if previous:
            atomic(ROOT / 'config.previous.yaml', previous)
        candidate.replace(target)
        if not first:
            try:
                control('/configs?force=true','PUT',{'path':str(target)})
            except Exception:
                if previous:
                    atomic(target, previous)
                    control('/configs?force=true','PUT',{'path':str(target)})
                raise ValueError('配置重载失败，已尝试恢复原配置')
        atomic(ROOT / 'subscription.yaml', raw.decode('utf-8-sig'))
        s['subscription_url'] = url
        s['updated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        s['node_count'] = len(nodes)
        atomic(SETTINGS,json.dumps(s))
        return {'ok':True,'node_count':len(nodes),'updated_at':s['updated_at']}

def status():
    s = settings()
    mem = dict((line.split(':',1)[0],line.split(':',1)[1].strip()) for line in pathlib.Path('/proc/meminfo').read_text().splitlines())
    udc = []
    for p in pathlib.Path('/sys/class/udc').glob('*'):
        udc.append({'name':p.name,'state':(p/'state').read_text().strip()})
    info = {'usb':udc,'usb_ip':s['usb_ip'],'proxy_port':7890,'node_count':s.get('node_count',0),
            'updated_at':s.get('updated_at'),'memory_available':mem['MemAvailable'],
            'wifi_ssid':run(['/usr/sbin/iwgetid','-r']).stdout.strip(),
            'addresses':run(['ip','-j','address']).stdout,'version':None,'selected':None}
    try:
        info['version'] = control('/version').get('version')
        info['selected'] = control('/proxies/Agent-Proxy').get('now')
        info['core']='running'
    except Exception:
        info['core']='unavailable'
    info['proxy_url'] = 'http://' + s['proxy_user'] + ':' + s['proxy_password'] + '@' + s['usb_ip'] + ':7890'
    return info

def test_exit():
    s = settings()
    cfg = 'proxy = "http://127.0.0.1:7890"\nproxy-user = "'+s['proxy_user']+':'+s['proxy_password']+'"\n'
    tests=[]
    for name,url in [('HTTPS','https://www.gstatic.com/generate_204'),('AI API','https://api.openai.com/v1/models')]:
        r=run(['curl','--config','-','--silent','--output','/dev/null','--write-out','%{http_code}',
               '--connect-timeout','8','--max-time','20',url],timeout=25,data=cfg)
        tests.append({'name':name,'http_status':r.stdout.strip(),'connected':r.returncode==0,
                      'note':'401 表示已到达接口，尚未提供模型 API 密钥' if r.stdout.strip()=='401' else ''})
    return {'tests':tests, 'selected':control('/proxies/Agent-Proxy').get('now')}

def wifi_text(value):
    data=bytearray()
    i=0
    while i < len(value):
        if value[i:i+2]=='\\x' and re.fullmatch('[0-9a-fA-F]{2}',value[i+2:i+4]):
            data.append(int(value[i+2:i+4],16));i+=4
        else:
            data.extend(value[i].encode());i+=1
    return data.decode('utf-8',errors='replace')

def wpa(*args):
    # wpa_supplicant must see the reply socket even with systemd PrivateTmp.
    return run(['/usr/sbin/wpa_cli','-s','/run/wpa_supplicant','-i','wlan0']+list(args),timeout=8).stdout.strip()

def saved_wifi():
    return parse_saved_networks(wpa('list_networks'), wifi_text)

def wifi_scan():
    accepted=wpa('scan')=='OK'
    if accepted: time.sleep(2)
    saved=saved_wifi()
    networks={}
    for line in wpa('scan_results').splitlines()[1:]:
        p=line.split('\t',4)
        if len(p)!=5 or not p[4]: continue
        name=wifi_text(p[4])
        signal=int(p[2])
        flags=p[3]
        security='企业认证' if 'EAP' in flags else 'WPA2' if 'WPA2-PSK' in flags else 'WPA3' if 'SAE' in flags else 'WPA' if 'WPA-PSK' in flags else '开放网络' if flags=='[ESS]' else '其他'
        entry={'ssid':name,'signal':signal,'quality':max(0,min(100,2*(signal+100))),
               'security':security,'saved_id':saved.get(name,{}).get('id'),
               'current':saved.get(name,{}).get('current',False),
               'supported':security=='WPA2' or name in saved}
        if name not in networks or networks[name]['signal']<signal: networks[name]=entry
    return {'networks':sorted(networks.values(),key=lambda n:n['signal'],reverse=True),
            'fresh':accepted,'message':'扫描完成' if accepted else '扫描正在进行，显示最近结果'}

WIFI = WifiManager(wpa, saved_wifi)

class Handler(http.server.BaseHTTPRequestHandler):
    server_version='USB-AI-Bridge/1.0'
    def log_message(self,*args): pass
    def send(self,code,obj,ctype='application/json; charset=utf-8'):
        raw=json.dumps(obj,ensure_ascii=False).encode() if not isinstance(obj,bytes) else obj
        self.send_response(code)
        self.send_header('Content-Type',ctype)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        self.end_headers()
        self.wfile.write(raw)
    def allowed(self):
        ip=ipaddress.ip_address(self.client_address[0])
        return ip.is_loopback or ip in ipaddress.ip_network('172.31.240.0/24')
    def auth(self):
        return hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+settings()['admin_token'])
    def do_GET(self):
        if not self.allowed(): return self.send(403,{'error':'仅允许 USB 管理连接'})
        if self.path=='/': return self.send(200,(APP/'index.html').read_bytes(),'text/html; charset=utf-8')
        if self.path=='/device': return self.send(200,(APP/'device.html').read_bytes(),'text/html; charset=utf-8')
        if self.path=='/workflows-ui.js': return self.send(200,(APP/'workflows-ui.js').read_bytes(),'text/javascript; charset=utf-8')
        if self.path=='/workbench.js': return self.send(200,(APP/'workbench.js').read_bytes(),'text/javascript; charset=utf-8')
        if self.path=='/workbench.css': return self.send(200,(APP/'workbench.css').read_bytes(),'text/css; charset=utf-8')
        if self.path in ('/markdown-it.min.js','/workbench-view.js','/workbench-sync.js'): return self.send(200,(APP/self.path[1:]).read_bytes(),'text/javascript; charset=utf-8')
        if self.path=='/health': return self.send(200,{'ok':True})
        if not self.auth(): return self.send(401,{'error':'需要管理密钥'})
        try:
            if self.path=='/api/wifi/status': return self.send(200,WIFI.status())
            if self.path=='/api/agent/status': return self.send(200,AGENT.status())
            if self.path=='/api/status': return self.send(200,status())
            if self.path.startswith('/api/workbench/'):
                return self.send(200,BENCH.get(self.path.removeprefix('/api/workbench/')))
            if self.path=='/api/nodes':
                p=control('/proxies')
                g=p['proxies']['Agent-Proxy']
                return self.send(200,{'selected':g['now'],'nodes':[{'name':n,'type':p['proxies'][n]['type'],'history':p['proxies'][n].get('history',[])} for n in g['all']]})
            return self.send(404,{'error':'不存在'})
        except ValueError as e: return self.send(400,{'error':str(e)})
        except Exception: return self.send(503,{'error':'读取状态失败，请检查服务'})
    def do_POST(self):
        if not self.allowed(): return self.send(403,{'error':'仅允许 USB 管理连接'})
        if not self.auth(): return self.send(401,{'error':'需要管理密钥'})
        origin=self.headers.get('Origin')
        if origin and origin != 'http://'+self.headers.get('Host',''):
            return self.send(403,{'error':'请求来源不匹配'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size < 0 or size > 400000: return self.send(413,{'error':'请求过大'})
            data=json.loads(self.rfile.read(size) or b'{}')
            if not isinstance(data,dict): raise ValueError('请求必须是对象')
            if self.path=='/api/security/key':
                with BENCH.lock, AGENT.lock, LOCK, config_lock():
                    busy=bool(BENCH.active) or any(j['status'] in ('queued','running','approval') for j in AGENT.status()['jobs'])
                    result=KeyRotation(SETTINGS).action(data,busy)
            elif self.path.startswith('/api/workbench/'):
                result=BENCH.post(self.path.removeprefix('/api/workbench/'),data)
            elif self.path=='/api/agent/register': result=AGENT.register(data)
            elif self.path=='/api/agent/poll': result=AGENT.poll(data)
            elif self.path=='/api/agent/result': result=AGENT.result(data)
            elif self.path=='/api/agent/control': result=AGENT.control(data)
            elif self.path=='/api/agent/approve': result=AGENT.approve(data)
            elif self.path=='/api/agent/job': result=AGENT.get_job(data.get('job_id'))
            elif self.path=='/api/agent/run': result=AGENT.submit(data.get('name'),data.get('arguments',{}))
            elif self.path=='/api/subscription': result=update_subscription(data.get('url'))
            elif self.path=='/api/select':
                g=control('/proxies/Agent-Proxy')
                if data.get('name') not in g['all']: raise ValueError('节点不存在')
                control('/proxies/Agent-Proxy','PUT',{'name':data['name']})
                result={'ok':True}
            elif self.path=='/api/test': result=test_exit()
            elif self.path=='/api/delay':
                name=data.get('name')
                if name not in control('/proxies/Agent-Proxy')['all']: raise ValueError('节点不存在')
                result=control('/proxies/'+urllib.parse.quote(name,safe='')+'/delay?'+urllib.parse.urlencode({'url':'https://www.gstatic.com/generate_204','timeout':8000}),timeout=12)
            elif self.path=='/api/wifi/scan': result=wifi_scan()
            elif self.path=='/api/wifi': result=WIFI.start(data.get('ssid',''),data.get('password',''),data.get('network_id'))
            else: return self.send(404,{'error':'不存在'})
            self.send(200,result)
        except ValueError as e: self.send(400,{'error':str(e)})
        except Exception: self.send(502,{'error':'操作失败；配置已保留。请检查网络、订阅或节点是否可用。'})

if __name__=='__main__':
    import sys
    if '--init' in sys.argv:
        print(json.dumps(update_subscription(first=True)))
    elif '--refresh' in sys.argv:
        print(json.dumps(update_subscription()))
    else:
        BENCH.recover()
        BENCH.workflows.start()
        http.server.ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
