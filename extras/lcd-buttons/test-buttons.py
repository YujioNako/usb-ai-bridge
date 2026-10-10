import unittest
from buttons import Controller, Debouncer, PINS
class Tests(unittest.TestCase):
    def test_bounce_and_startup_hold(self):
        d=Debouncer({'key':False},0)
        self.assertEqual(d.update({'key':True},.01),[])
        self.assertEqual(d.update({'key':False},.02),[])
        d.update({'key':True},.03)
        self.assertEqual(d.update({'key':True},.065),[('key',True)])
        d=Debouncer({'key':True},0)
        self.assertFalse(d.down('key'))
        d.update({'key':False},.1);d.update({'key':False},.14)
        d.update({'key':True},.2);self.assertEqual(d.update({'key':True},.24),[('key',True)])
    def test_mouse_direction_and_buttons(self):
        events=[];moves=[];raw={k:False for k in PINS}
        c=Controller('mouse',raw,0,lambda *a:events.append(a),lambda *a:moves.append(a))
        raw['UP']=True;c.update(raw,.01);c.update(raw,.05)
        self.assertEqual(moves[-1],(0,1))
        c.update(raw,1.5);self.assertEqual(moves[-1],(0,4))
        raw['DOWN']=True;c.update(raw,1.6);c.update(raw,1.64);count=len(moves)
        c.update(raw,1.7);self.assertEqual(len(moves),count)
        for i,name in enumerate(['PRESS','KEY1','KEY2','KEY3']):
            t=2+i*.2;raw[name]=True;c.update(raw,t);c.update(raw,t+.04)
            raw[name]=False;c.update(raw,t+.08);c.update(raw,t+.12)
        self.assertEqual(events,[(272,True),(272,False),(273,True),(273,False),(28,True),(28,False),(1,True),(1,False)])
    def test_keyboard_repeat_only_directions(self):
        events=[];raw={k:False for k in PINS};c=Controller('keyboard',raw,0,lambda *a:events.append(a),lambda *_:None)
        raw['KEY2']=True;c.update(raw,.01);c.update(raw,.05);c.update(raw,2)
        self.assertEqual(events,[(15,True)])
        raw['RIGHT']=True;c.update(raw,2.1);c.update(raw,2.14);c.update(raw,2.7)
        self.assertEqual(events[-3:],[(105,True),(105,False),(105,True)])
if __name__=='__main__':unittest.main()
