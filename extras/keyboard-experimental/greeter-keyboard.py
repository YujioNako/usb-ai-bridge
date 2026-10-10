#!/usr/bin/python3
"""Start a visible Onboard in the *current* greeter's X11 session."""
import os, pathlib, pwd, signal, subprocess, time

GREETERS={'pi-greeter','lightdm-gtk-greeter','slick-greeter'}
SETTINGS=[('org.gnome.desktop.interface','toolkit-accessibility','true'),
 ('org.onboard','layout','Compact'),('org.onboard','start-minimized','false'),
 ('org.onboard.auto-show','enabled','false'),
 ('org.onboard.keyboard','key-synth','XTest'),
 ('org.onboard.keyboard','input-event-source','GTK'),
 ('org.onboard.window','docking-enabled','true'),
 ('org.onboard.window','docking-shrink-workarea','true'),
 ('org.onboard.window','force-to-top','true'),
 ('org.onboard.window.landscape','dock-height','180'),
 ('org.onboard.window.portrait','dock-height','180'),
 ('org.onboard.icon-palette','in-use','true'),
 ('org.onboard.typing-assistance.word-suggestions','enabled','false'),
 ('org.onboard.typing-assistance.word-suggestions','auto-learn','false')]

def greeter():
    for p in pathlib.Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            cmd=(p/'cmdline').read_bytes().split(b'\0')[0].decode()
            if pathlib.Path(cmd).name not in GREETERS:continue
            user=pwd.getpwuid(p.stat().st_uid)
            if user.pw_uid==0:continue
            raw=dict(x.split('=',1) for x in (p/'environ').read_text().split('\0') if '=' in x)
            if not all(raw.get(k) for k in ('DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS')):continue
            env={k:raw[k] for k in ('DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','XDG_RUNTIME_DIR','LANG') if k in raw}
            env.update(HOME=user.pw_dir,USER=user.pw_name,LOGNAME=user.pw_name,PATH='/usr/local/bin:/usr/bin:/bin',GTK_MODULES='gail:atk-bridge',NO_AT_BRIDGE='0')
            return (int(p.name),user.pw_name,env)
        except (OSError,KeyError,UnicodeError):continue
    return None

def run(user,env,args,timeout=8):
    return subprocess.run(['/usr/sbin/runuser','-u',user,'--']+args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)

def stop(child):
    if child and child.poll() is None:
        try:os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=5)
        except ProcessLookupError:pass
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()

def main():
    child=None;owner=None;running=True;retry=0
    def finish(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,finish);signal.signal(signal.SIGINT,finish)
    try:
        while running:
            session=greeter();pid=session[0] if session else None
            if pid!=owner:stop(child);child=None;owner=pid;retry=0
            if session and (child is None or child.poll() is not None) and time.monotonic()>=retry:
                retry=time.monotonic()+8
                try:
                    _,user,env=session
                    if run(user,env,['/usr/bin/xwininfo','-root']).returncode:
                        time.sleep(1);continue
                    for schema,key,value in SETTINGS:
                        r=run(user,env,['gsettings','set',schema,key,value])
                        if r.returncode:raise RuntimeError('Cannot configure '+schema+'.'+key)
                    child=subprocess.Popen(['/usr/sbin/runuser','-u',user,'--','/usr/bin/onboard'],env=env,start_new_session=True)
                    print('Keyboard started for greeter PID',pid,flush=True)
                except (OSError,subprocess.TimeoutExpired,RuntimeError) as e:print('Keyboard retry:',str(e),flush=True)
            time.sleep(1)
    finally:stop(child)

if __name__=='__main__':main()


