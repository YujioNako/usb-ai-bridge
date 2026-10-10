#!/usr/bin/env python3
"""Build Windows Full ZIP from reviewed source plus a verified dependency/runtime seed."""
from pathlib import Path
import argparse,hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seed',type=Path,help='An existing verified complete Windows ZIP');p.add_argument('--seed-sha256');p.add_argument('--runtime-dir',type=Path);p.add_argument('--dependencies-dir',type=Path);p.add_argument('--serial-worker',type=Path);p.add_argument('--version',required=True);p.add_argument('--out',type=Path,default=ROOT/'dist');a=p.parse_args()
 a.out.mkdir(parents=True,exist_ok=True);name='USB-AI-Windows-'+a.version+'-Full';dest=a.out/(name+'.zip');entries={}
 if a.seed:
  h=hashlib.sha256()
  with a.seed.open('rb') as f:
   for b in iter(lambda:f.read(1048576),b''):h.update(b)
  if not a.seed_sha256 or h.hexdigest()!=a.seed_sha256.lower():raise SystemExit('Seed ZIP digest mismatch')
  with zipfile.ZipFile(a.seed) as z:
   prefix=z.namelist()[0].split('/')[0]+'/'
   for n in z.namelist():
    rel=n.removeprefix(prefix)
    if rel.startswith('runtime/') or '/node_modules/' in rel or rel=='SerialWorker.exe':entries[rel]=z.read(n)
 else:
  if not all((a.runtime_dir,a.dependencies_dir,a.serial_worker)):raise SystemExit('Without a seed, supply --runtime-dir --dependencies-dir --serial-worker')
  for n in ('node.exe','LICENSE'):entries['runtime/'+n]=(a.runtime_dir/n).read_bytes()
  for f in a.dependencies_dir.rglob('*'):
   if f.is_file() and not f.is_symlink():entries['documents/node_modules/'+f.relative_to(a.dependencies_dir).as_posix()]=f.read_bytes()
 if a.serial_worker:entries['SerialWorker.exe']=a.serial_worker.read_bytes()
 for f in (ROOT/'windows').rglob('*'):
  if f.is_file() and '__pycache__' not in f.parts and 'node_modules' not in f.parts:entries[f.relative_to(ROOT/'windows').as_posix()]=f.read_bytes()
 # Build browser assets from the same readable source committed for Pi.
 app=ROOT/'pi/app';entries['panel/workbench.js']=("'use strict';\n"+'\n;\n'.join((app/n).read_text(encoding='utf-8-sig') for n in ['markdown-it.min.js','workbench-view.js','workbench.js','workbench-sync.js'])).encode()
 for n in ['index.html','device.html','workbench.css','workflows-ui.js','maintenance.html','maintenance.js','maintenance.css','xterm.js','xterm-fit.js','xterm.css','xterm.LICENSE','xterm-fit.LICENSE','markdown-it.LICENSE']:
  if (app/n).exists():entries['panel/'+n]=(app/n).read_bytes()
 html=entries['panel/index.html'].decode('utf-8-sig')
 for n in ['markdown-it.min.js','workbench-view.js','workbench-sync.js']:html=html.replace('<script src="/'+n+'"></script>','')
 entries['panel/index.html']=html.encode()
 for n in ('README.md','THIRD_PARTY.md'):entries[n]=(ROOT/n).read_bytes()
 for f in (ROOT/'docs').glob('*.md'):entries['docs/'+f.name]=f.read_bytes()
 manifest={'version':a.version,'platform':'windows-x64','contains_credentials':False,'files':[]}
 for n,b in sorted(entries.items()):
  if Path(n).name in ('device.json','auth.json','settings.json','model.json') or n.startswith('/') or '..' in Path(n).parts:raise SystemExit('Forbidden package member: '+n)
  manifest['files'].append({'path':n,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
 entries['package-manifest.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode()
 with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for n,b in sorted(entries.items()):z.writestr(name+'/'+n,b)
 with zipfile.ZipFile(dest) as z:
  assert z.testzip() is None
  for row in manifest['files']:assert hashlib.sha256(z.read(name+'/'+row['path'])).hexdigest()==row['sha256'],row['path']
 print(dest)
if __name__=='__main__':main()
