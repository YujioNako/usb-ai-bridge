#!/usr/bin/env python3
"""Local LCD HAT buttons only. No network, USB gadget or display output."""
import argparse, json, os, pathlib, signal, struct, time

PINS={'UP':6,'DOWN':19,'LEFT':5,'RIGHT':26,'PRESS':13,'KEY1':21,'KEY2':20,'KEY3':16}
# Physical pin labels stay unchanged; the installed display is rotated 180 degrees.
DIRECTIONS={'UP':108,'DOWN':103,'LEFT':106,'RIGHT':105}
KEYBOARD={**DIRECTIONS,'PRESS':28,'KEY1':1,'KEY2':15,'KEY3':139}
MOUSE={'PRESS':272,'KEY1':273,'KEY2':28,'KEY3':1}

class Debouncer:
    def __init__(self, initial, now):
        self.stable=initial.copy();self.candidate=initial.copy()
        self.changed={key:now for key in initial};self.armed={key:not value for key,value in initial.items()}
    def update(self, sample, now):
        events=[]
        for key,value in sample.items():
            if value!=self.candidate[key]: self.candidate[key]=value;self.changed[key]=now
            if value!=self.stable[key] and now-self.changed[key]>=.03:
                self.stable[key]=value
                if not value:self.armed[key]=True
                if self.armed[key]:events.append((key,value))
        return events
    def down(self,key):return self.stable[key] and self.armed[key]

class UInput:
    def __init__(self,name,keys,relative=False):
        import fcntl
        self.fd=os.open('/dev/uinput',os.O_WRONLY|os.O_NONBLOCK);self.held=set()
        try:
            fcntl.ioctl(self.fd,0x40045564,1)  # UI_SET_EVBIT / EV_KEY
            for code in keys:fcntl.ioctl(self.fd,0x40045565,code)
            if relative:
                fcntl.ioctl(self.fd,0x40045564,2)  # EV_REL
                for code in (0,1):fcntl.ioctl(self.fd,0x40045566,code)
            setup=struct.pack('HHHH80sI',6,1,1,1,name.encode(),0)  # BUS_VIRTUAL
            assert len(setup)==92
            fcntl.ioctl(self.fd,0x405c5503,setup)  # UI_DEV_SETUP
            fcntl.ioctl(self.fd,0x5501)  # UI_DEV_CREATE
        except Exception:os.close(self.fd);raise
    def emit(self,kind,code,value):os.write(self.fd,struct.pack('llHHi',0,0,kind,code,value))
    def key(self,code,down):
        if down and code not in self.held:self.held.add(code);self.emit(1,code,1);self.emit(0,0,0)
        elif not down and code in self.held:self.held.remove(code);self.emit(1,code,0);self.emit(0,0,0)
    def move(self,x,y):
        if x:self.emit(2,0,x)
        if y:self.emit(2,1,y)
        if x or y:self.emit(0,0,0)
    def close(self):
        import fcntl
        for code in list(self.held):self.key(code,False)
        try:fcntl.ioctl(self.fd,0x5502)
        finally:os.close(self.fd)

class Controller:
    def __init__(self,mode,initial,now,key,move):
        self.mode=mode;self.debounce=Debouncer(initial,now);self.key=key;self.move=move
        self.motion_since=None;self.last_motion=now;self.repeat={};self.counts={k:0 for k in PINS}
    def update(self,sample,now):
        events=self.debounce.update(sample,now)
        mapping=KEYBOARD if self.mode=='keyboard' else MOUSE
        for name,down in events:
            if down:self.counts[name]+=1
            if name in mapping:self.key(mapping[name],down)
            if self.mode=='keyboard' and name in DIRECTIONS:
                if down:self.repeat[name]=now+.45
                else:self.repeat.pop(name,None)
        if self.mode=='keyboard':
            for name,deadline in list(self.repeat.items()):
                if now>=deadline:
                    self.key(KEYBOARD[name],False);self.key(KEYBOARD[name],True);self.repeat[name]=now+.08
        else:
            x=int(self.debounce.down('LEFT'))-int(self.debounce.down('RIGHT'))
            y=int(self.debounce.down('UP'))-int(self.debounce.down('DOWN'))
            if not (x or y):self.motion_since=None
            else:
                if self.motion_since is None:self.motion_since=now
                age=now-self.motion_since;step=1 if age<.4 else 2 if age<1.2 else 4
                if now-self.last_motion>=.02:self.move(x*step,y*step);self.last_motion=now
        return events

def main():
    import fcntl, RPi.GPIO as GPIO
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['mouse','keyboard'],default='mouse')
    parser.add_argument('--monitor',type=float,default=0,help='Read buttons without generating input for N seconds')
    args=parser.parse_args()
    runtime=pathlib.Path('/run/lcd-hat-buttons');runtime.mkdir(exist_ok=True)
    lock=(runtime/'lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    GPIO.setmode(GPIO.BCM)
    # All eight inputs must be free; never change a display/output pin into an input.
    for pin in PINS.values():
        if GPIO.gpio_function(pin)!=GPIO.IN:raise RuntimeError('Button GPIO is not an input: '+str(pin))
    GPIO.setup(list(PINS.values()),GPIO.IN,pull_up_down=GPIO.PUD_UP)
    time.sleep(.1)
    sample=lambda:{name:GPIO.input(pin)==GPIO.LOW for name,pin in PINS.items()}
    mouse=keyboard=None;running=True
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    start=time.monotonic();deadline=start+args.monitor if args.monitor else float('inf')
    try:
        if not args.monitor:
            keyboard=UInput('LCD HAT Buttons Keyboard',[1,15,28,103,108,105,106,139])
            if args.mode=='mouse':mouse=UInput('LCD HAT Joystick Mouse',[272,273],True)
        def key(code,down):
            if not args.monitor:(mouse if code>=272 else keyboard).key(code,down)
        controller=Controller(args.mode,sample(),start,key,lambda x,y:mouse.move(x,y) if mouse else None)
        print('LCD HAT buttons ready: '+('monitor only' if args.monitor else args.mode),flush=True)
        next_status=0
        while running and time.monotonic()<deadline:
            now=time.monotonic();raw=sample();events=controller.update(raw,now)
            if args.monitor:
                for name,down in events:print(name+(' pressed' if down else ' released'),flush=True)
            if now>=next_status:
                temp=runtime/'status.new'
                temp.write_text(json.dumps({'mode':args.mode,'monitor':bool(args.monitor),'time':time.time(),
                    'pressed':[name for name in PINS if controller.debounce.down(name)],'press_counts':controller.counts}))
                temp.replace(runtime/'status.json');next_status=now+1
            time.sleep(.005)
    finally:
        if mouse:mouse.close()
        if keyboard:keyboard.close()
        # Leave inputs pulled up after stopping. Only these eight GPIOs were configured.
        lock.close()

if __name__=='__main__':main()
