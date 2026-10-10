#!/usr/bin/env python3
"""First installation on Raspberry Pi OS Bullseye arm64; never enables USB networking."""
import argparse,datetime,getpass,gzip,hashlib,json,os,platform,re,secrets,shutil,subprocess,tarfile,tempfile,urllib.parse,urllib.request
from pathlib import Path
SOURCE=Path(__file__).resolve().parent
APP=Path('/opt/usb-ai-bridge');STATE=Path('/var/lib/usb-ai-bridge');ETC=Path('/etc/usb-ai-bridge')
CODEX_TAG='rust-v0.155.1'

def run(*args):return subprocess.run(list(args),check=True)
def write(path,text,mode=0o644):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.install-new');tmp.write_text(text,encoding='utf-8');tmp.chmod(mode);tmp.replace(p)
def api(url):
 req=urllib.request.Request(url,headers={'User-Agent':'usb-ai-bridge-installer','Accept':'application/vnd.github+json'})
 with urllib.request.urlopen(req,timeout=45) as r:return json.load(r)
def asset(release,name,dest):
 a=next((a for a in release['assets'] if a['name']==name),None)
 if not a:raise RuntimeError('Official release is missing asset: '+name)
 expected=a.get('digest','')
 if not re.fullmatch('sha256:[0-9a-f]{64}',expected):raise RuntimeError('No official SHA-256 digest: '+name)
 url=a['browser_download_url']
 if urllib.parse.urlsplit(url).hostname!='github.com':raise RuntimeError('Unexpected download host')
 req=urllib.request.Request(url,headers={'User-Agent':'usb-ai-bridge-installer'})
 h=hashlib.sha256()
 with urllib.request.urlopen(req,timeout=120) as r,Path(dest).open('wb') as f:
  for chunk in iter(lambda:r.read(262144),b''):h.update(chunk);f.write(chunk)
 if 'sha256:'+h.hexdigest()!=expected:raise RuntimeError('Download digest mismatch: '+name)
 return Path(dest)
def unpack_one(archive,target,names):
 with tarfile.open(archive) as t:
  candidates=[m for m in t.getmembers() if m.isfile() and Path(m.name).name in names]
  if len(candidates)!=1:raise RuntimeError('Unexpected executable archive layout')
  target.parent.mkdir(parents=True,exist_ok=True)
  with t.extractfile(candidates[0]) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)
 target.chmod(0o755)
def boot_text(text):
 if re.search(r'^\s*dtoverlay=dwc2(?:,.*)?$',text,re.M):
  if re.search(r'^\s*dtoverlay=dwc2,.*dr_mode=host',text,re.M):raise ValueError('dwc2 is configured as a USB host; review the boot configuration first')
  return text
 return text.rstrip()+'\n\n[all]\n# USB AI: serial gadget only\ndtoverlay=dwc2,dr_mode=peripheral\n'
def preflight(resume=False):
 if platform.system()!='Linux' or platform.machine()!='aarch64':raise SystemExit('Requires Raspberry Pi OS 64-bit (uname -m must be aarch64)')
 os_release=Path('/etc/os-release').read_text()
 if not re.search(r'^VERSION_CODENAME=[\"\x27]?bullseye[\"\x27]?$',os_release,re.M):raise SystemExit('This release supports Bullseye/wpa_supplicant only; Bookworm/Trixie/NetworkManager need porting')
 if not Path('/proc/device-tree/model').exists() or 'Raspberry Pi Zero 2' not in Path('/proc/device-tree/model').read_text():raise SystemExit('This installer currently targets Raspberry Pi Zero 2 W only')
 if subprocess.run(['systemctl','is-active','--quiet','NetworkManager']).returncode==0:raise SystemExit('Active NetworkManager is not supported; no network changes made')
 if (ETC/'settings.json').exists() and not (resume and (STATE/'install-incomplete').exists()):raise SystemExit('Existing installation found. Do not reinstall or reset credentials; see docs/UPGRADE.md')
 for p in [Path('/etc/modules'),Path('/boot/cmdline.txt'),Path('/etc/modules-load.d/usb-ai-gadget.conf')]:
  if p.exists() and any(x in p.read_text() for x in ('g_ether','g_multi','g_cdc')):raise SystemExit('Existing USB gadget configuration found; review it before installing')
 if not Path('/boot/config.txt').exists():raise SystemExit('Missing Bullseye /boot/config.txt')
 if shutil.disk_usage('/').free<700*1024*1024:raise SystemExit('Need at least 700 MiB free disk space')

def unit(execstart,after='network.target',extras='',writable=''):
 return '[Unit]\nDescription=USB AI Bridge\nAfter='+after+'\n[Service]\nExecStart='+execstart+'\nRestart=on-failure\nRestartSec=3\nUMask=0077\nNoNewPrivileges=true\nProtectSystem=strict\nProtectHome=true\nPrivateTmp=true\n'+('ReadWritePaths='+writable+'\n' if writable else '')+extras+'\n[Install]\nWantedBy=multi-user.target\n'

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--api-only',action='store_true',help='Skip official Codex runtime; API backend remains available');parser.add_argument('--resume',action='store_true',help='Resume an incomplete first installation');parser.add_argument('--check',action='store_true',help='Read-only compatibility check');args=parser.parse_args()
 preflight(args.resume)
 if args.check:print('Compatible: Zero 2 W, Bullseye arm64, wpa_supplicant. No changes made.');return
 if os.geteuid()!=0:raise SystemExit('Run with sudo python3 pi/install.py')
 print('Install packages, download verified upstream binaries, generate private settings, enable serial-only services. No reboot or desktop password changes.')
 previous=json.loads((ETC/'settings.json').read_text()) if (ETC/'settings.json').exists() else None
 subscription=previous.get('subscription_url','') if previous else getpass.getpass('Clash YAML subscription URL (hidden; Enter for direct connection): ').strip()
 if subscription and urllib.parse.urlsplit(subscription).scheme!='https':raise SystemExit('Subscription must be an HTTPS URL')
 run('apt-get','update');run('apt-get','install','-y','--no-install-recommends','python3','python3-yaml','curl','ca-certificates','openssh-server','wpasupplicant','wireless-tools','iproute2')
 backup=Path('/var/backups/usb-ai-bridge')/datetime.datetime.now().strftime('%Y%m%d-%H%M%S');backup.mkdir(parents=True,mode=0o700)
 shutil.copy2('/boot/config.txt',backup/'config.txt')
 for p in (APP,STATE,ETC):p.mkdir(parents=True,exist_ok=True,mode=0o700)
 write(STATE/'install-incomplete','incomplete first installation\n',0o600)
 s=previous or dict(admin_token=secrets.token_urlsafe(32),proxy_user='usbai',proxy_password=secrets.token_urlsafe(24),controller_secret=secrets.token_urlsafe(32),subscription_url=subscription,usb_ip='127.0.0.1',node_count=0)
 write(ETC/'settings.json',json.dumps(s),0o600)
 for p in (SOURCE/'app').iterdir():
  if p.is_file() and not p.name.startswith('test-'):shutil.copy2(p,APP/p.name);(APP/p.name).chmod(0o644)
 try:
  with tempfile.TemporaryDirectory(prefix='usbai-install-') as tmp:
   release=api('https://api.github.com/repos/MetaCubeX/mihomo/releases/latest');gz=asset(release,'mihomo-linux-arm64-'+release['tag_name']+'.gz',Path(tmp)/'mihomo.gz')
   with gzip.open(gz,'rb') as src,Path('/usr/local/bin/mihomo').open('wb') as dst:shutil.copyfileobj(src,dst)
   Path('/usr/local/bin/mihomo').chmod(0o755);run('/usr/local/bin/mihomo','-v')
   import sys
   sys.path.insert(0,str(APP));import bridge
   if subscription:bridge.update_subscription(first=True)
   else:
    import yaml
    config=bridge.make_config([],s);config['proxy-groups'][0]['proxies']=['DIRECT'];write(STATE/'config.yaml',yaml.safe_dump(config,allow_unicode=True),0o600)
   write('/etc/systemd/system/usb-ai-mihomo.service',unit('/usr/local/bin/mihomo -d /var/lib/usb-ai-bridge -f /var/lib/usb-ai-bridge/config.yaml',extras='Environment=GOMEMLIMIT=80MiB\nEnvironment=GOGC=50\nMemoryMax=180M\n',writable=str(STATE)))
   write('/etc/systemd/system/usb-ai-manager.service',unit('/usr/bin/python3 /opt/usb-ai-bridge/bridge.py',after='network.target usb-ai-mihomo.service',extras='MemoryMax=100M\n',writable='/var/lib/usb-ai-bridge /etc/usb-ai-bridge /etc/wpa_supplicant /run/wpa_supplicant'))
   run('systemctl','daemon-reload');run('systemctl','enable','--now','ssh','usb-ai-mihomo','usb-ai-manager')
   if not args.api_only:install_codex(s,Path(tmp))
  # Boot changes happen only after downloads and management setup succeed.
  write('/boot/config.txt',boot_text(Path('/boot/config.txt').read_text()))
  write('/etc/modules-load.d/usb-ai-gadget.conf','dwc2\ng_serial\n')
  serial=Path('/proc/device-tree/serial-number').read_text().strip('\x00\n')
  write('/etc/modprobe.d/usb-ai-serial.conf','options g_serial use_acm=1 iProduct="USB AI Serial" iSerialNumber='+serial+'\n')
  write('/etc/systemd/system/usb-ai-serial.service',unit('/usr/bin/python3 /opt/usb-ai-bridge/serial_service.py',after='usb-ai-manager.service',extras='ExecStartPre=/usr/sbin/modprobe g_serial\nMemoryMax=100M\n'))
  run('systemctl','daemon-reload');run('systemctl','enable','usb-ai-serial')
 except Exception:
  print('Installation stopped; some services/configuration may already be installed. Fix the reported error, then rerun with --resume. Credentials are preserved. See docs/TROUBLESHOOTING.md.')
  raise
 (STATE/'install-incomplete').unlink(missing_ok=True)
 print('Installed. Boot configuration backup:',backup)
 print('Your management key (save privately):',s['admin_token'])
 print('Run sudo reboot when ready, then connect the USB DATA port to Windows. Do not share the management key.')

def install_codex(settings,tmp):
 import pwd
 try:account=pwd.getpwnam('usb-ai-codex')
 except KeyError:
  run('useradd','--system','--home-dir','/var/lib/usb-ai-codex','--shell','/usr/sbin/nologin','usb-ai-codex');account=pwd.getpwnam('usb-ai-codex')
 dest=Path('/opt/usb-ai-codex');dest.mkdir(exist_ok=True)
 state=Path('/var/lib/usb-ai-codex')
 for p in (state,state/'workspace',state/'config'):
  p.mkdir(mode=0o700,parents=True,exist_ok=True);os.chown(p,account.pw_uid,account.pw_gid)
 config='cli_auth_credentials_store = "file"\nforced_login_method = "chatgpt"\napproval_policy = "on-request"\nsandbox_mode = "read-only"\nweb_search = "disabled"\n[features]\nshell_tool = false\ncode_mode_host = true\nbrowser_use = false\ncomputer_use = false\nmulti_agent = false\napps = false\nplugins = false\nview_image = false\nworkspace_dependencies = false\n'
 write(state/'config/config.toml',config,0o600);os.chown(state/'config/config.toml',account.pw_uid,account.pw_gid)
 proxy='http://'+urllib.parse.quote(settings['proxy_user'],safe='')+':'+urllib.parse.quote(settings['proxy_password'],safe='')+'@127.0.0.1:7890'
 # Downloads use the same explicitly configured Pi proxy; credentials never enter command arguments.
 urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({'http':proxy,'https':proxy})))
 release=api('https://api.github.com/repos/openai/codex/releases/tags/'+CODEX_TAG)
 for binary in ('codex','codex-code-mode-host','bwrap'):
  name=binary+'-aarch64-unknown-linux-musl';archive=asset(release,name+'.tar.gz',tmp/(binary+'.tar.gz'));unpack_one(archive,dest/binary,{binary,name})
 run(str(dest/'codex'),'--version')
 write('/etc/usb-ai-codex/proxy.env','\n'.join(k+'='+json.dumps(proxy) for k in ('HTTPS_PROXY','HTTP_PROXY','ALL_PROXY'))+'\nNO_PROXY=localhost,127.0.0.1\n',0o600)
 shutil.copy2(SOURCE/'codex/codex_gateway.py',dest/'codex_gateway.py');shutil.copy2(SOURCE/'codex/usb-ai-codex.service','/etc/systemd/system/usb-ai-codex.service')
 run('systemctl','daemon-reload');run('systemctl','enable','--now','usb-ai-codex')

if __name__=='__main__':main()
