"""Codex subscription backend. Only fixed local runtime and existing Windows broker."""
import copy,http.client,json,socket,threading,time
import agent_broker
import usage_meter
from workflows import plugin_text

class CodexConnectionError(ValueError):pass

class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(self.timeout)
        self.sock.connect('/run/usb-ai-codex/runtime.sock')

class CodexBackend:
    def __init__(self):
        self.lock=threading.RLock();self.login={'state':'idle'};self.cached={};self.cached_at=0;self.attempt=None
    def transport(self,path,data):
        connection=UnixHTTP('localhost',timeout=8 if path=='/events' else 50)
        try:
            connection.request('POST',path,json.dumps(data).encode(),{'Content-Type':'application/json'})
            r=connection.getresponse();value=json.loads(r.read(3000001))
            if r.status!=200:raise ValueError(value.get('error','Codex runtime error'))
            return value
        except (OSError,http.client.HTTPException,json.JSONDecodeError) as e:raise CodexConnectionError('Codex 服务连接失败：'+str(e)[:300]) from e
        finally:connection.close()
    def rpc(self,method,params=None):return self.transport('/rpc',{'method':method,'params':params or {}})
    def status(self,refresh=False):
        with self.lock:
            if not refresh and time.monotonic()-self.cached_at<5:return copy.deepcopy(self.cached)
        try:
            value=self.rpc('account/read',{'refreshToken':False});account=value.get('account') or {}
            with self.lock:pending=copy.deepcopy(self.login)
            if not account and pending.get('state')=='waiting':
                packet=self.transport('/events',{'after':pending.get('cursor',0)})
                failure=None
                if packet['epoch']!=pending.get('epoch'):failure='登录服务已重启，请重新生成设备码'
                for e in packet['events']:
                    message=e['message'];p=message.get('params',{})
                    if message['method']=='account/login/completed' and p.get('loginId')==pending.get('login_id') and not p.get('success'):
                        failure=p.get('error') or '登录未完成，请重新生成设备码'
                with self.lock:
                    if self.login.get('login_id')==pending.get('login_id'):
                        self.login['cursor']=packet['cursor']
                        if failure:self.login={'state':'error','error':str(failure)[:400]}
            result={'available':True,'logged_in':account.get('type')=='chatgpt','account':{k:account[k] for k in ('type','email','planType') if k in account}}
            with self.lock:
                if result['logged_in']:self.login={'state':'complete'}
                elif self.login.get('expires',0) and time.time()>self.login['expires']:self.login={'state':'expired','error':'授权码已过期，请重新登录'}
                result['login']=copy.deepcopy(self.login)
        except ValueError as e:result={'available':False,'logged_in':False,'error':str(e),'login':copy.deepcopy(self.login)}
        with self.lock:self.cached=result;self.cached_at=time.monotonic()
        return copy.deepcopy(result)
    def start_login(self):
        with self.lock:
            if self.login['state'] in ('starting','waiting') and self.login.get('expires',time.time()+1)>time.time():return copy.deepcopy(self.login)
            self.login={'state':'starting'};attempt=object();self.attempt=attempt
        def start():
            try:
                snapshot=self.transport('/events',{'snapshot':True})
                result=self.rpc('account/login/start',{'type':'chatgptDeviceCode'})
                url=result.get('verificationUrl','')
                if not url.startswith('https://auth.openai.com/'):raise ValueError('Unexpected authorization URL')
                with self.lock:
                    cancelled=self.attempt is not attempt
                    if not cancelled:
                        self.login={'state':'waiting','url':url,'code':result['userCode'],'login_id':result['loginId'],'expires':time.time()+900,'cursor':snapshot['cursor'],'epoch':snapshot['epoch']};self.cached_at=0
                if cancelled:self.rpc('account/login/cancel',{'loginId':result['loginId']})
            except Exception as e:
                with self.lock:self.login={'state':'error','error':str(e)[:400]};self.cached_at=0
        threading.Thread(target=start,daemon=True).start();return {'state':'starting'}
    def action(self,data):
        action=data.get('action','status')
        if action=='status':return self.status()
        if action=='login':return self.start_login()
        if action=='logout':
            with self.lock:pending=self.login.get('login_id');self.attempt=None
            if pending:self.rpc('account/login/cancel',{'loginId':pending})
            self.rpc('account/logout');self.login={'state':'idle'};self.cached_at=0;return self.status(True)
        if action=='models':
            result=self.rpc('model/list',{'limit':100})
            return {'models':[{k:m[k] for k in ('id','model','displayName','description','isDefault','supportedReasoningEfforts','defaultReasoningEffort','serviceTiers','defaultServiceTier') if k in m} for m in result.get('data',[])]}
        if action=='limits':return self.rpc('account/rateLimits/read')
        raise ValueError('Codex 操作不存在')
    def options(self,model,effort='',fast=False):
        models=self.action({'action':'models'})['models']
        selected=next((m for m in models if m['model']==model),None) if model else next((m for m in models if m.get('isDefault')),None)
        if not selected:raise ValueError('模型已不可用，请刷新模型列表')
        efforts={v['reasoningEffort'] for v in selected.get('supportedReasoningEfforts',[])}
        if effort and (effort not in efforts or effort not in ('low','medium','high','xhigh','max')):raise ValueError('当前模型不支持所选思考强度')
        if fast and not any(t.get('id')=='priority' for t in selected.get('serviceTiers',[])):raise ValueError('当前模型未提供快速模式')
        return {'model':selected['model'],'effort':effort or selected.get('defaultReasoningEffort','medium'),'serviceTier':'priority' if fast else 'default'}
    def run(self,bench,active,model):
        doc=active['doc'];reply=doc['messages'][-1];thread_id=None;turn_id=None
        meter=reply.setdefault('meter',usage_meter.create('codex'))
        baseline=usage_meter.normalized(doc.get('token_usage',{}).get('total'),True)
        state={'previous':baseline if doc.get('codex_thread') else {k:0 for k in (*usage_meter.FIELDS,'total')}}
        try:
            snapshot=self.transport('/events',{'snapshot':True});cursor=snapshot['cursor'];epoch=snapshot['epoch']
            caps=bench.broker.status()['client'].get('capabilities',[]) if bench.broker and bench.broker.online() and not active.get('no_tools') else []
            specs=[{'type':'function','name':'windows_'+f['function']['name'],'description':f['function']['description'],'inputSchema':f['function']['parameters']} for f in agent_broker.tools() if f['function']['name'] in caps]
            instruction=bench.payload(doc,model)['messages'][0]['content']+' 你运行在树莓派上，但用户任务的目标是 Windows。只能通过 windows_ 前缀工具操作 Windows，不要操作树莓派本地文件或运行本地命令。'
            params={'cwd':'/var/lib/usb-ai-codex/workspace','approvalPolicy':'on-request','sandbox':'read-only','developerInstructions':instruction}
            if model.get('model'):params['model']=model['model']
            if doc.get('codex_thread'):
                params['threadId']=doc['codex_thread'];result=self.rpc('thread/resume',params)
            else:
                params['dynamicTools']=specs;result=self.rpc('thread/start',params)
            thread_id=result['thread']['id']
            with bench.lock:reply['model']=result.get('model') or result['thread'].get('model') or model.get('model') or 'Codex';doc['codex_thread']=thread_id;doc['codex_epoch']=epoch;bench.save(doc)
            # Send only this user message; Codex persists its own history across turns.
            user=doc['messages'][-2];text=user['content']
            text+=plugin_text(user.get('plugins',[]))
            for f in user.get('attachments',[]):
                if f.get('kind')=='image':continue
                text+='\n\n['+('Windows 文件引用（必须通过 windows_files read 读取，不是文件正文）' if f.get('kind')=='file' else '用户附加文件')+'：'+f['name']+']\n'+f['content']+'\n[文件结束]'
            options=self.options(model.get('model',''),model.get('codex_effort',''),model.get('codex_fast',False)) if 'codex_effort' in model or 'codex_fast' in model else {}
            started=self.rpc('turn/start',{'threadId':thread_id,'input':[{'type':'text','text':text}]+[{'type':'image','url':f['content']} for f in user.get('attachments',[]) if f.get('kind')=='image'],**options})
            turn_id=started['turn']['id'];deadline=time.monotonic()+1800;interrupted=False;last_save=0;parts={};lost_since=None;retry_count=0
            with bench.lock:
                active.update(thread_id=thread_id,turn_id=turn_id,questions={});reply.update(turn_id=turn_id,settings=options,activity='thinking');bench.save(doc)
            while time.monotonic()<deadline:
                if active['stop'].is_set() and not interrupted:
                    self.rpc('turn/interrupt',{'threadId':thread_id,'turnId':turn_id});interrupted=True;deadline=min(deadline,time.monotonic()+12)
                try:packet=self.transport('/events',{'after':cursor})
                except CodexConnectionError:
                    if lost_since is None:lost_since=time.monotonic()
                    if time.monotonic()-lost_since>90:raise ValueError('Codex 状态连接超过 90 秒未恢复，已保留当前内容；请恢复连接后手动继续')
                    retry_count+=1
                    with bench.lock:reply['activity']='reconnecting';bench.save(doc)
                    active['stop'].wait(min(3,.4*retry_count));continue
                if lost_since is not None:
                    with bench.lock:reply['activity']='thinking'
                    lost_since=None;retry_count=0
                if packet['epoch']!=epoch:raise ValueError('Codex 服务重启，本次任务已中断；不会自动重发')
                cursor=packet['cursor']
                # Usage can follow completion within the same event batch.
                for event in packet['events']:
                    m=event['message'];p=m.get('params',{})
                    if m.get('method')=='thread/tokenUsage/updated' and p.get('threadId')==thread_id and (not p.get('turnId') or p['turnId']==turn_id):
                        with bench.lock:
                            doc['token_usage']=p.get('tokenUsage',{});reply['token_usage']=p.get('tokenUsage',{})
                            usage_meter.codex_event(meter,state,p.get('tokenUsage',{}),active.get('price_book',[]),reply.get('model',model.get('model','')),model.get('codex_fast',False))
                for event in packet['events']:
                    message=event['message'];method=message['method'];p=message.get('params',{})
                    if p.get('threadId')!=thread_id:continue
                    if p.get('turnId') and p['turnId']!=turn_id:continue
                    if 'id' in message:
                        if method=='item/tool/call':output=self.tool(bench,active,p,caps)
                        elif method in ('item/commandExecution/requestApproval','item/fileChange/requestApproval'):output={'decision':'decline'}
                        elif method=='item/permissions/requestApproval':output={'permissions':{}}
                        elif method=='item/tool/requestUserInput':
                            with bench.lock:
                                rid=str(message['id']);active['questions'][rid]=message['id']
                                reply.setdefault('questions',[]).append({'id':rid,'questions':p.get('questions',[]),'status':'waiting'})
                                bench.save(doc)
                            continue
                        else:
                            self.transport('/reply',{'id':message['id'],'error':{'code':-32601,'message':'Unsupported client interaction; ask user in chat'}});continue
                        self.transport('/reply',{'id':message['id'],'result':output})
                    elif method=='item/agentMessage/delta':
                        iid=p.get('itemId','message');parts[iid]=parts.get(iid,'')+p.get('delta','')
                        with bench.lock:reply['content']='\n\n'.join(parts.values());reply['activity']='writing'
                    elif method=='item/completed' and p.get('item',{}).get('type')=='agentMessage':
                        item=p['item'];parts[item['id']]=item.get('text','')
                        with bench.lock:reply['content']='\n\n'.join(parts.values());reply['activity']='thinking'
                    elif method=='item/started':
                        kind=p.get('item',{}).get('type')
                        with bench.lock:reply['activity']='thinking' if kind=='reasoning' else 'writing' if kind=='agentMessage' else 'working'
                    elif method=='error':
                        if p.get('willRetry'):
                            with bench.lock:reply['activity']='reconnecting'
                        else:raise ValueError((p.get('error') or {}).get('message','模型连接已中断，已有内容已保留'))
                    elif method=='turn/plan/updated':
                        with bench.lock:reply['plan']=p.get('plan',[]);reply['plan_explanation']=p.get('explanation')
                    elif method=='thread/tokenUsage/updated':
                        pass
                    elif method=='thread/compacted':
                        with bench.lock:reply['notice']='较早的上下文已由 Codex 压缩'
                    elif method=='turn/completed':
                        turn=p['turn']
                        for item in turn.get('items',[]):
                            if item.get('type')=='agentMessage' and isinstance(item.get('text'),str):parts[item['id']]=item['text']
                        if parts:
                            with bench.lock:reply['content']='\n\n'.join(parts.values())
                        if turn.get('status')=='failed':raise ValueError((turn.get('error') or {}).get('message','Codex 生成失败'))
                        if turn.get('status')=='interrupted':active['stop'].set()
                        return
                if time.monotonic()-last_save>.7:
                    with bench.lock:bench.save(doc)
                    last_save=time.monotonic()
                time.sleep(.12)
            raise ValueError('Codex 本次任务超时，已停止；请检查结果后继续')
        except Exception as e:
            if thread_id and turn_id:
                try:self.rpc('turn/interrupt',{'threadId':thread_id,'turnId':turn_id})
                except Exception:pass
            reply['error']=str(e)[:600]
        finally:
            for rid in list(active.get('questions',{}).values()):
                try:self.transport('/reply',{'id':rid,'result':{'answers':{}}})
                except Exception:pass
            if bench.broker and active.get('job_id'):bench.broker.cancel(active['job_id'])
            with bench.lock:
                for q in reply.get('questions',[]):
                    if q['status']=='waiting':q['status']='closed'
                reply['status']='cancelled' if active['stop'].is_set() else 'error' if reply.get('error') else 'done'
                reply.pop('activity',None)
                if active['stop'].is_set():reply.pop('error',None)
                bench.finish_meter(active,model)
                bench.save(doc)
                if bench.active is active:bench.active=None
    def tool(self,bench,active,params,caps):
        name=params.get('tool','');args=params.get('arguments',{});reply=active['doc']['messages'][-1]
        trace={'name':name,'arguments':args,'status':'preparing','call_id':params.get('callId','')}
        with bench.lock:reply.setdefault('tools',[]).append(trace);reply['activity']='working'
        try:
            if not name.startswith('windows_') or name[8:] not in caps:raise ValueError('Windows 工具未启用')
            if active['stop'].is_set():raise ValueError('任务已停止')
            if not bench.broker or bench.broker.status()['client'].get('id')!=active['client_id']:raise ValueError('Windows 客户端已变更，请重新发起任务')
            job=bench.submit_job(active,name[8:],args,trace)
            trace.update(job_id=job['id'],status=job['status'])
            while job['status'] in ('approval','queued','running'):
                if active['stop'].wait(.25):bench.broker.cancel(job['id'])
                job=bench.broker.get_job(job['id']);trace['status']=job['status']
            result=job.get('result',{'error':'工具未返回结果'});trace['status']=job['status']
        except Exception as e:result={'error':str(e)[:300]};trace['status']='error'
        finally:active.pop('job_id',None)
        with bench.lock:trace['result']=result;reply['activity']='thinking';bench.save(active['doc'])
        content=[{'type':'inputText','text':json.dumps({k:v for k,v in result.items() if k!='image'},ensure_ascii=False)}]
        if result.get('image','').startswith('data:image/jpeg;base64,'):content.append({'type':'inputImage','imageUrl':result['image']})
        return {'contentItems':content,'success':trace['status']=='done'}
