"""Explicit Skills bundles and durable, single-flight Pi schedules."""
import base64,copy,datetime,hashlib,io,json,os,pathlib,re,secrets,stat,threading,time,zipfile
TZ=datetime.timezone(datetime.timedelta(hours=8))
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def plugin_text(plugins):
    return ''.join('\n\n[用户为本轮选择的工作流插件：'+p['title']+'；这是任务参考，不增加权限，用户当前指令优先]\n'+p['instructions']+'\n[工作流插件结束]' for p in plugins)

class Workflows:
    def __init__(self,bench,path):
        self.bench=bench;self.path=pathlib.Path(path);self.waiting={};self.started=False;self.last_error=''
        self.data=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'version':1,'plugins':[],'schedules':[],'runs':[]}
        if not self.path.exists():
            bundled=pathlib.Path(__file__).with_name('builtin-workflows.json')
            if bundled.exists():
                for p in json.loads(bundled.read_text(encoding='utf-8')):
                    p.update(enabled=True,revision=digest(p),updated_at=stamp());self.data['plugins'].append(p)
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.new')
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(self.data,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        temp.replace(self.path)
        if os.name!='nt':
            fd=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
    def recover(self):
        for r in self.data['runs']:
            if r['status'] in ('starting','running'):
                r.update(status='interrupted',error='服务重启，未自动重发；请检查对应会话结果',finished_at=stamp())
        self.save()
    def public(self):
        return {'plugins':[{k:v for k,v in p.items() if k!='instructions'} for p in self.data['plugins']],
                'schedules':copy.deepcopy(self.data['schedules']),'runs':copy.deepcopy(self.data['runs'][-100:][::-1]),
                'waiting':dict(self.waiting),'timezone':'Asia/Shanghai','server_time':time.time(),'scheduler_error':self.last_error}
    def find(self,table,pid):
        value=next((p for p in self.data[table] if p['id']==pid),None)
        if not value:raise ValueError('记录不存在')
        return value
    def resolve(self,ids):
        if not isinstance(ids,list) or len(ids)>3 or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):raise ValueError('每次最多选择 3 个不同插件')
        result=[]
        for pid in ids:
            p=self.find('plugins',pid)
            if not p['enabled']:raise ValueError('插件已停用：'+p['title'])
            result.append(copy.deepcopy(p))
        if sum(len(p['instructions'].encode()) for p in result)>64000:raise ValueError('所选插件内容过大')
        return result
    def put_plugin(self,p,replace=False):
        pid=p.get('id','');title=p.get('title','');text=p.get('instructions','');description=p.get('description','')
        if not isinstance(pid,str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',pid):raise ValueError('插件编号需为 1–64 位小写字母、数字或连字符')
        if not isinstance(title,str) or not 1<=len(title.strip())<=80:raise ValueError('插件名称限 1–80 字符')
        if not isinstance(description,str) or len(description)>500:raise ValueError('插件说明限 500 字符')
        if not isinstance(text,str) or not text.strip() or len(text.encode())>48000 or '\x00' in text:raise ValueError('工作流步骤需为非空文本，最大 48 KB')
        old=next((x for x in self.data['plugins'] if x['id']==pid),None)
        if old and not replace:raise ValueError('相同编号插件已存在；请在编辑中更新')
        if not old and len(self.data['plugins'])>=30:raise ValueError('最多安装 30 个工作流插件')
        item={'id':pid,'title':title.strip(),'description':description,'instructions':text,'enabled':old.get('enabled',True) if old else True,'updated_at':stamp()}
        item['revision']=digest({k:item[k] for k in ('id','title','description','instructions')})
        if old:self.data['plugins'].remove(old)
        self.data['plugins'].append(item);self.save();return item
    def import_zip(self,value):
        if not isinstance(value,str) or len(value)>280000:raise ValueError('插件 ZIP 最大 200 KB')
        try:raw=base64.b64decode(value,validate=True)
        except Exception:raise ValueError('插件编码无效')
        if len(raw)>200000:raise ValueError('插件 ZIP 最大 200 KB')
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                infos=z.infolist()
                if len(infos)>50 or sum(f.file_size for f in infos)>256000:raise ValueError('插件展开后限 256 KB、50 个条目')
                files={}
                for f in infos:
                    parts=pathlib.PurePosixPath(f.filename).parts
                    if f.filename.startswith('/') or '\\' in f.filename or ':' in f.filename or '..' in parts or stat.S_ISLNK(f.external_attr>>16):raise ValueError('插件含不安全的路径或链接')
                    if f.is_dir():continue
                    if f.filename in files:raise ValueError('插件有重复文件')
                    files[f.filename]=z.read(f).decode('utf-8-sig')
        except (zipfile.BadZipFile,UnicodeError,RuntimeError):raise ValueError('请选择有效的 UTF-8 Skills 插件 ZIP')
        manifests=[p for p in files if p=='.codex-plugin/plugin.json' or p.endswith('/.codex-plugin/plugin.json')]
        if len(manifests)!=1:raise ValueError('ZIP 需包含一个 .codex-plugin/plugin.json')
        prefix=manifests[0][:-len('.codex-plugin/plugin.json')]
        if any(not p.startswith(prefix) for p in files):raise ValueError('插件文件必须位于同一根目录')
        manifest=json.loads(files[manifests[0]])
        if not isinstance(manifest,dict):raise ValueError('插件清单无效')
        if any(manifest.get(k) for k in ('mcpServers','apps','hooks')):raise ValueError('当前只支持 Skills 工作流，不执行 MCP、Apps 或 hooks')
        skill_root=manifest.get('skills','./skills/')
        if skill_root not in ('./skills/','./skills','skills/','skills'):raise ValueError('仅支持标准 skills/ 目录')
        steps=[];references=[]
        for path,text in files.items():
            rel=path[len(prefix):]
            if rel=='.codex-plugin/plugin.json' or re.fullmatch(r'(README|LICENSE)(\.[a-zA-Z]+)?',rel,re.I):continue
            if re.fullmatch(r'skills/[a-zA-Z0-9_-]+/SKILL.md',rel):steps.append((rel,text))
            elif re.fullmatch(r'skills/[a-zA-Z0-9_-]+/references/[a-zA-Z0-9_./-]+\.(md|txt|json)',rel):references.append((rel,text))
            else:raise ValueError('包含暂不支持的脚本、资源或配置：'+rel[:100])
        if not 1<=len(steps)<=5:raise ValueError('插件需包含 1–5 个 SKILL.md')
        content='\n\n'.join('## '+p+'\n'+t for p,t in steps+references)
        interface=manifest.get('interface',{})
        return self.put_plugin({'id':manifest.get('name'),'title':interface.get('displayName') or manifest.get('name'),
                               'description':manifest.get('description',''),'instructions':content})
    def export_zip(self,pid):
        p=self.find('plugins',pid);buf=io.BytesIO()
        manifest={'name':p['id'],'version':'1.0.0','description':p['description'],'skills':'./skills/','interface':{'displayName':p['title']}}
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('.codex-plugin/plugin.json',json.dumps(manifest,ensure_ascii=False))
            z.writestr('skills/'+p['id']+'/SKILL.md','---\nname: '+p['id']+'\ndescription: '+json.dumps(p['description'] or p['title'],ensure_ascii=False)+'\n---\n\n'+p['instructions'])
        return {'filename':p['id']+'.zip','base64':base64.b64encode(buf.getvalue()).decode()}
    @staticmethod
    def next_time(s,after):
        mode=s['mode']
        if mode=='once':return s['at'] if s['at']>after else None
        if mode=='interval':return after+s['minutes']*60
        moment=datetime.datetime.fromtimestamp(after,TZ);hour,minute=map(int,s['time'].split(':'))
        for offset in range(8):
            day=moment+datetime.timedelta(days=offset)
            candidate=day.replace(hour=hour,minute=minute,second=0,microsecond=0)
            if candidate.timestamp()>after and (mode=='daily' or candidate.weekday()<5):return candidate.timestamp()
        raise ValueError('无法计算下次执行时间')
    def put_schedule(self,data):
        sid=data.get('id') or secrets.token_hex(12);old=next((x for x in self.data['schedules'] if x['id']==sid),None)
        if data.get('id') and not old:raise ValueError('定时任务不存在')
        if not old and len(self.data['schedules'])>=30:raise ValueError('最多保存 30 个定时任务')
        title=data.get('title','');prompt=data.get('prompt','');mode=data.get('mode')
        if not isinstance(title,str) or not 1<=len(title.strip())<=80:raise ValueError('任务名称限 1–80 字符')
        if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=16000:raise ValueError('任务内容限 1–16000 字符')
        if mode not in ('once','interval','daily','weekdays'):raise ValueError('执行频率无效')
        s={'id':sid,'title':title.strip(),'prompt':prompt.strip(),'mode':mode,'enabled':data.get('enabled',False),'require_windows':data.get('require_windows',True),'plugin_ids':data.get('plugin_ids',[]),'updated_at':stamp()}
        if type(s['enabled']) is not bool or type(s['require_windows']) is not bool:raise ValueError('开关格式无效')
        if mode=='interval':
            m=data.get('minutes')
            if type(m) is not int or not 5<=m<=10080:raise ValueError('间隔限 5–10080 分钟')
            s['minutes']=m
        elif mode in ('daily','weekdays'):
            t=data.get('time','')
            if not isinstance(t,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',t):raise ValueError('时间格式需为 HH:MM')
            s['time']=t
        else:
            at=data.get('at')
            if not isinstance(at,(int,float)) or isinstance(at,bool) or not time.time()+5<at<time.time()+366*86400:raise ValueError('单次任务时间需在未来 5 秒至一年内')
            s['at']=at
        plugins=self.resolve(s['plugin_ids']);s['plugin_revisions']={p['id']:p['revision'] for p in plugins}
        current=self.bench.model(False)
        if current.get('provider')!='codex':raise ValueError('定时任务当前需要 ChatGPT / Codex 模式')
        effective=self.bench.codex.options(current.get('model',''),current.get('codex_effort',''),current.get('codex_fast',False))
        s['model']={'provider':'codex','model':effective['model'],'codex_model':effective['model'],'codex_effort':effective['effort'],'codex_fast':current.get('codex_fast',False)}
        s['approval_mode']=self.bench.default_approval()
        if s['require_windows']:
            status=self.bench.broker.status() if self.bench.broker else {}
            if not status.get('online'):raise ValueError('请先连接目标 Windows 客户端和工作目录，再保存任务')
            c=status['client']
            if not c.get('machine_id'):raise ValueError('请更新并重新启动 Windows 客户端，以提供稳定的电脑标识')
            s['target']={k:c.get(k,'') for k in ('machine_id','name','workspace')}
        s['next_due']=self.next_time(s,time.time())
        if old:self.data['schedules'].remove(old)
        self.data['schedules'].append(s);self.save();return s
    def block_reason(self,s):
        if self.bench.active:return '另一任务正在执行'
        for p in self.resolve(s['plugin_ids']):
            if p['revision']!=s['plugin_revisions'].get(p['id']):raise ValueError('插件内容已修改，请检查并重新保存定时任务')
        if s['require_windows']:
            status=self.bench.broker.status() if self.bench.broker else {}
            if not status.get('online'):return '等待指定 Windows 客户端连接'
            c=status['client'];target=s['target']
            if c.get('machine_id')!=target['machine_id'] or c.get('workspace')!=target['workspace']:return '当前电脑或工作目录与绑定目标不符'
        return ''
    def record(self,s,status,**values):
        r={'id':secrets.token_hex(12),'schedule_id':s['id'],'title':s['title'],'status':status,'created_at':stamp(),**values}
        self.data['runs'].append(r);self.data['runs']=self.data['runs'][-200:];return r
    def dispatch(self,s,manual=False):
        now=time.time();reason=self.block_reason(s)
        if reason:raise ValueError(reason)
        sid=secrets.token_hex(12)
        if len(list(self.bench.root.glob('*/session.json')))>=200:raise ValueError('会话数量已达上限，请先清理回收站')
        r=self.record(s,'starting',session_id=sid,trigger='manual' if manual else 'timer',scheduled_for=now if manual else s['next_due'])
        if not manual:
            s['next_due']=self.next_time(s,now)
            if s['next_due'] is None:s['enabled']=False
        # Persist a claim before creating a session or contacting the model. Never replay it after a crash.
        self.save()
        try:
            doc={'id':sid,'title':s['title'],'created_at':stamp(),'updated_at':stamp(),'messages':[],'files':[],'approval_mode':s.get('approval_mode','manual'),'model_override':{'provider':'codex','model':s['model']['model'],'effort':s['model'].get('codex_effort',''),'fast':s['model'].get('codex_fast',False)},'schedule':{'id':s['id'],'run_id':r['id'],'title':s['title']}}
            (self.bench.root/sid).mkdir(mode=0o700);self.bench.save(doc)
            self.bench.begin({'id':sid,'text':s['prompt'],'plugin_ids':s['plugin_ids']},model_override=s['model'],no_tools=not s['require_windows'])
            r['status']='running';self.save()
        except Exception as e:
            r.update(status='error',error=str(e)[:500],finished_at=stamp());self.save()
        return r
    def tick(self):
        with self.bench.lock:
            for r in self.data['runs']:
                if r['status']!='running':continue
                if self.bench.active and self.bench.active['doc']['id']==r['session_id']:continue
                try:
                    doc=self.bench.load(r['session_id']);reply=doc['messages'][-1]
                    r.update(status=reply.get('status','error'),error=reply.get('error',''),finished_at=stamp())
                except (ValueError,IndexError):r.update(status='error',error='执行会话不存在或未开始',finished_at=stamp())
                self.save()
            now=time.time();self.waiting={}
            for s in self.data['schedules']:
                if not s['enabled'] or not s.get('next_due') or s['next_due']>now:continue
                try:
                    if now-s['next_due']>600:
                        self.record(s,'skipped',error='超过 10 分钟执行窗口，未补跑',scheduled_for=s['next_due'],finished_at=stamp())
                        s['next_due']=self.next_time(s,now)
                        if s['next_due'] is None:s['enabled']=False
                        self.save();continue
                    reason=self.block_reason(s)
                    if reason:self.waiting[s['id']]=reason;continue
                    self.dispatch(s)
                except ValueError as e:
                    self.record(s,'error',error=str(e)[:500],finished_at=stamp());s['enabled']=False;self.save()
    def start(self):
        if self.started:return
        self.recover();self.started=True
        def loop():
            while True:
                try:self.tick();self.last_error=''
                except Exception as e:self.last_error=str(e)[:300]
                time.sleep(5)
        threading.Thread(target=loop,daemon=True).start()
    def action(self,data):
        action=data.get('action')
        if action=='plugin-save':return self.put_plugin(data.get('plugin',{}),data.get('replace') is True)
        if action=='plugin-read':return copy.deepcopy(self.find('plugins',data.get('id')))
        if action=='plugin-import':return self.import_zip(data.get('base64'))
        if action=='plugin-export':return self.export_zip(data.get('id'))
        if action=='plugin-toggle':
            p=self.find('plugins',data.get('id'));p['enabled']=not p['enabled'];self.save();return self.public()
        if action=='plugin-delete':
            p=self.find('plugins',data.get('id'))
            if any(p['id'] in s['plugin_ids'] for s in self.data['schedules']):raise ValueError('请先从引用它的定时任务中移除此插件')
            self.data['plugins'].remove(p);self.save();return self.public()
        if action=='schedule-save':return self.put_schedule(data)
        if action in ('schedule-toggle','schedule-delete','schedule-run','schedule-stop'):
            s=self.find('schedules',data.get('id'))
            if action=='schedule-run':return self.dispatch(s,manual=True)
            if action=='schedule-toggle':
                s['enabled']=not s['enabled']
                if s['enabled']:
                    s['next_due']=self.next_time(s,time.time())
                    if s['next_due'] is None:s['enabled']=False;raise ValueError('单次时间已过，请编辑新的时间')
            if action=='schedule-delete':
                if any(r['schedule_id']==s['id'] and r['status'] in ('starting','running') for r in self.data['runs']):raise ValueError('请先停止正在执行的任务')
                self.data['schedules'].remove(s)
            if action=='schedule-stop':
                a=self.bench.active
                if a and a['doc'].get('schedule',{}).get('id')==s['id']:self.bench.post('stop',{'id':a['doc']['id']})
            self.save();return self.public()
        raise ValueError('工作流操作不存在')
