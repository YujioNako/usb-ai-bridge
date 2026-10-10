import base64,time,unittest
import ssh_terminal as t
class Tests(unittest.TestCase):
 def setUp(self):
  self.m=t.TerminalManager(lambda u,d:['/bin/sh','-c','stty -echo; exec /bin/cat']);self.sid='ab'*32
  self.call('open',user='fixture',cols=80,rows=24);time.sleep(.2)
 def tearDown(self):self.m.close()
 def call(self,action,**kw):return self.m.action(dict(action=action,session=self.sid,**kw),'fixture')
 def test_dedup(self):
  b=base64.b64encode('串口\n'.encode()).decode();self.call('input',seq=1,data=b);self.call('input',seq=1,data=b);time.sleep(.2)
  r=self.call('poll');self.assertEqual(base64.b64decode(r['data']).decode(),'串口\r\n');self.assertEqual(self.call('poll')['data'],r['data'])
  self.assertEqual(self.call('poll',offset=r['offset'])['data'],'')
  with self.assertRaises(ValueError):self.call('input',seq=1,data='YQ==')
  with self.assertRaises(ValueError):self.call('input',seq=3,data=b)
  self.call('resize',cols=100,rows=30);self.call('close');self.assertTrue(self.call('open',user='fixture')['closed'])
 def test_auth(self):
  with self.assertRaises(ValueError):self.m.action(dict(action='poll',session=self.sid),'other')
  with self.assertRaises(ValueError):self.call('resize',cols=999,rows=24)
  with self.assertRaises(ValueError):self.call('open',user='other')
  with self.assertRaises(ValueError):self.call('input',seq=1,data='!')
 def test_limits(self):
  s=self.m.sessions[self.sid][2]
  with s.lock:s.buffer=bytearray(b'a'*t.BUFFER);s.start=100;s.end=t.BUFFER+100
  r=self.call('poll');self.assertTrue(r['truncated']);self.assertEqual(r['offset'],32868)
  s.contact-=t.LEASE+1;self.m.reap();self.assertTrue(s.reason);self.assertIsNotNone(s.proc.poll())
 def test_idle(self):
  s=self.m.sessions[self.sid][2];s.input_at-=t.IDLE+1;self.m.reap();self.assertIn('15',s.reason)
 def test_username(self):
  import tempfile
  with tempfile.TemporaryDirectory() as d:
   for u in ['root','nobody','-oProxyCommand=x','u@host','x;id','']:
    with self.assertRaises(ValueError):t.ssh_command(u,d)
if __name__=='__main__':unittest.main()
