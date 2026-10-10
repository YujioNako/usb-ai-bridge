import datetime,json,os,pathlib,shutil,subprocess,time
src=pathlib.Path(__file__).parent
if os.geteuid()!=0:raise SystemExit('Run: sudo python3 install.py')
subprocess.run(['python3',str(src/'test-buttons.py')],check=True)
subprocess.run(['python3','-m','py_compile',str(src/'buttons.py')],check=True)
subprocess.run(['python3','-c','import RPi.GPIO'],check=True)
app=pathlib.Path('/opt/lcd-hat-buttons');app.mkdir(exist_ok=True)
service=pathlib.Path('/etc/systemd/system/lcd-hat-buttons.service')
backup=pathlib.Path('/var/lib/lcd-hat-buttons')/('backup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,mode=0o700)
targets=[app/'buttons.py',service];manifest=[]
for index,p in enumerate(targets):
    manifest.append({'path':str(p),'existed':p.exists(),'backup':str(index)})
    if p.exists():shutil.copy2(p,backup/str(index))
(backup/'manifest.json').write_text(json.dumps(manifest))
try:
    shutil.copy2(src/'buttons.py',targets[0]);targets[0].chmod(0o644)
    shutil.copy2(src/'lcd-hat-buttons.service',service);service.chmod(0o644)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','lcd-hat-buttons'],check=True)
    subprocess.run(['systemctl','restart','lcd-hat-buttons'],check=True)
    time.sleep(2)
    subprocess.run(['systemctl','is-active','--quiet','lcd-hat-buttons'],check=True)
    state=json.loads(pathlib.Path('/run/lcd-hat-buttons/status.json').read_text())
    if state['mode']!='mouse' or state['monitor'] or abs(time.time()-state['time'])>4:raise RuntimeError('Buttons health check failed')
    print('Buttons installed and running. Backup:',backup)
except Exception:
    subprocess.run(['systemctl','stop','lcd-hat-buttons'])
    for item in manifest:
        p=pathlib.Path(item['path'])
        if item['existed']:shutil.copy2(backup/item['backup'],p)
        else:p.unlink(missing_ok=True)
    if not manifest[1]['existed']:subprocess.run(['systemctl','disable','lcd-hat-buttons'],capture_output=True)
    subprocess.run(['systemctl','daemon-reload'])
    if manifest[1]['existed']:subprocess.run(['systemctl','restart','lcd-hat-buttons'])
    raise
