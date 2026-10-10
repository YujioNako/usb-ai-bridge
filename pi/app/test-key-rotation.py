import json,pathlib,tempfile,unittest,sys,time,uuid
sys.path.insert(0,str(pathlib.Path(__file__).parent))
from key_rotation import KeyRotation
class Tests(unittest.TestCase):
 def test_rotation(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'settings.json';p.write_text(json.dumps({'admin_token':'original-fixture-key','proxy_password':'unrelated-secret'}));r=KeyRotation(p);rid=uuid.uuid4().hex
   with self.assertRaises(ValueError):r.action({'action':'prepare','id':rid,'new_key':'short'})
   with self.assertRaises(ValueError):r.action({'action':'prepare','id':rid,'new_key':'new-fixture-key-123'},busy=True)
   r.action({'action':'prepare','id':rid,'new_key':'new-fixture-key-123'})
   self.assertEqual(json.loads(p.read_text())['admin_token'],'original-fixture-key')
   self.assertNotIn('new_key',r.action({'action':'status'}))
   # Restart between phases reads persisted pending state, then commits once.
   r=KeyRotation(p);r.action({'action':'commit','id':rid});r.action({'action':'commit','id':rid})
   s=json.loads(p.read_text());self.assertEqual(s['admin_token'],'new-fixture-key-123');self.assertEqual(s['proxy_password'],'unrelated-secret');self.assertNotIn('key_pending',s)
   rid=uuid.uuid4().hex;r.action({'action':'prepare','id':rid,'new_key':'third-fixture-key-123'});r.action({'action':'cancel','id':rid})
   self.assertEqual(json.loads(p.read_text())['admin_token'],'new-fixture-key-123')
 def test_expiry(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'settings.json';p.write_text(json.dumps({'admin_token':'original-fixture-key','key_pending':{'id':'a'*32,'new_key':'new-fixture-key-123','expires':time.time()-1}}))
   r=KeyRotation(p)
   with self.assertRaises(ValueError):r.action({'action':'commit','id':'a'*32})
   self.assertEqual(json.loads(p.read_text())['admin_token'],'original-fixture-key')
if __name__=='__main__':unittest.main()
