import hashlib,importlib.util,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('installer',Path(__file__).resolve().parents[1]/'pi/install.py');i=importlib.util.module_from_spec(spec);spec.loader.exec_module(i)
class InstallerTests(unittest.TestCase):
 def test_boot_append_is_idempotent_and_preserves_screen(self):
  src='[all]\ndtoverlay=vc4-fkms-v3d\ndisplay_rotate=2\n';new=i.boot_text(src)
  self.assertIn(src.strip(),new);self.assertIn('dr_mode=peripheral',new);self.assertEqual(i.boot_text(new),new)
 def test_reject_usb_host_mode(self):
  with self.assertRaises(ValueError):i.boot_text('[all]\ndtoverlay=dwc2,dr_mode=host\n')
 def test_unit_does_not_remove_sandbox(self):
  unit=i.unit('/usr/bin/python3 /opt/usb-ai-bridge/serial_service.py')
  self.assertIn('NoNewPrivileges=true',unit);self.assertIn('ProtectHome=true',unit);self.assertNotIn('g_ether',unit)
 def test_official_asset_hash(self):
  data=b'fixture-executable';entry={'name':'test.gz','browser_download_url':'https://github.com/example/repo/releases/download/v1/test.gz','digest':'sha256:'+hashlib.sha256(data).hexdigest()}
  with tempfile.TemporaryDirectory() as d,patch.object(i.urllib.request,'urlopen',return_value=io.BytesIO(data)):
   dest=i.asset({'assets':[entry]},'test.gz',Path(d)/'download');self.assertEqual(dest.read_bytes(),data)
 def test_refuse_missing_digest_or_wrong_download_host(self):
  for url,digest in [('https://github.com/x',''),('https://untrusted.invalid/x','sha256:'+'0'*64)]:
   with self.assertRaises(RuntimeError):i.asset({'assets':[{'name':'x','browser_download_url':url,'digest':digest}]},'x',Path('unused'))
 def test_refuse_corrupt_download(self):
  with tempfile.TemporaryDirectory() as d,patch.object(i.urllib.request,'urlopen',return_value=io.BytesIO(b'wrong')):
   with self.assertRaises(RuntimeError):i.asset({'assets':[{'name':'x','browser_download_url':'https://github.com/x','digest':'sha256:'+'0'*64}]},'x',Path(d)/'bad')
 def test_atomic_config_permissions_and_content(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'config/settings';i.write(p,'fixture',0o600);self.assertEqual(p.read_text(),'fixture');self.assertFalse(p.with_name('settings.install-new').exists())
if __name__=='__main__':unittest.main()
