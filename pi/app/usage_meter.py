"""Reported usage first; explicit estimates otherwise. No billing/account claims."""
import copy,datetime,json,math,pathlib,re,urllib.parse
DATE='2026-09-24'
API_SOURCE='https://developers.openai.com/api/docs/pricing'
PLAN_SOURCE='https://learn.chatgpt.com/docs/pricing'
FIELDS=('input','cached','cache_write','output','reasoning')
# Verified standard USD / million tokens. Unknown model IDs never inherit a price.
BUILTIN={
 'gpt-6-sol':(2,.2,2.5,10,272000),
 'gpt-6-astra':(10,1,12.5,50,272000),
 'gpt-6-luna':(.1,.01,.125,.5,272000),
 'gpt-5.3-codex':(1.75,.175,1.75,14,0),
}
CREDITS={'gpt-6-sol':(50,5,250),'gpt-6-astra':(250,25,1250),'gpt-6-luna':(2.5,.25,12.5),
 'gpt-5.6-sol':(100,10,500),'gpt-5.6-terra':(50,5,300),'gpt-5.6-luna':(5,.5,30),
 'gpt-5.5':(125,12.5,750),'gpt-5.4':(62.5,6.25,375),'gpt-5.4-mini':(18.75,1.875,113)}

def count(value):
    if type(value) is not int or value<0:return None
    return min(value,10**12)

def normalized(raw,codex=False):
    if not isinstance(raw,dict):return None
    i=count(raw.get('inputTokens' if codex else 'prompt_tokens'))
    o=count(raw.get('outputTokens' if codex else 'completion_tokens'))
    if i is None or o is None:return None
    details=raw.get('prompt_tokens_details') or {};out=raw.get('completion_tokens_details') or {}
    cached=count(raw.get('cachedInputTokens') if codex else details.get('cached_tokens')) or 0
    write=count(raw.get('cacheWriteInputTokens') if codex else details.get('cache_write_tokens')) or 0
    reasoning=count(raw.get('reasoningOutputTokens') if codex else out.get('reasoning_tokens')) or 0
    cached=min(i,cached);write=min(i-cached,write)
    return {'input':i,'cached':cached,'cache_write':write,'output':o,'reasoning':min(o,reasoning),'total':i+o}

def estimate(value):
    # Exclude embedded media, not millions of base64 characters counted as text.
    def clean(x):
        if isinstance(x,dict):return {k:clean(v) for k,v in x.items() if k not in ('image_url','image','url')}
        if isinstance(x,list):return [clean(v) for v in x]
        if isinstance(x,str) and x.startswith('data:image/'):return '[图片未估算]'
        return x
    text=value if isinstance(value,str) else json.dumps(clean(value),ensure_ascii=False,separators=(',',':'))
    text=re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+','[图片未估算]',text)
    wide=sum(1 for c in text if ord(c)>127)
    return max(0,math.ceil(wide+(len(text)-wide)/4))

def estimated(inp,out):
    i=estimate(inp);o=estimate(out)
    return {'input':i,'cached':0,'cache_write':0,'output':o,'reasoning':0,'total':i+o}

def custom_rates(value):
    if not isinstance(value,list) or len(value)>40:raise ValueError('最多保存 40 条模型单价')
    rows=[];seen=set()
    for x in value:
        if not isinstance(x,dict):raise ValueError('价格格式无效')
        provider=x.get('provider');model=x.get('model','');tier=x.get('tier','standard');endpoint=x.get('endpoint','')
        if not isinstance(endpoint,str):raise ValueError('API 地址格式无效')
        endpoint=endpoint.rstrip('/')
        if provider not in ('api','codex') or not isinstance(model,str) or not model.strip() or len(model)>200 or tier not in ('standard','priority'):raise ValueError('请填写连接方式、模型标识和速度档位')
        if provider=='api':
            p=urllib.parse.urlsplit(endpoint)
            if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment:raise ValueError('单价需绑定不含凭据的 HTTPS API 地址')
        else:endpoint=''
        key=(provider,endpoint,model.strip(),tier)
        if key in seen:raise ValueError('同一服务、模型和速度档位不能重复')
        seen.add(key)
        row=dict(provider=provider,endpoint=endpoint,model=model.strip(),tier=tier,currency=x.get('currency','USD'))
        if row['currency'] not in ('USD','CNY'):raise ValueError('币种仅支持 USD / CNY')
        for f in ('input','cached','cache_write','output'):
            v=x.get(f)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=100000:raise ValueError('单价必须为 0–100000 的有限数值（每百万 token）')
            row[f]=v
        row.update(source='用户自定义',date=datetime.date.today().isoformat());rows.append(row)
    return rows

def pricing(book,provider,model,endpoint='',fast=False,long=False):
    tier='priority' if fast else 'standard'
    custom=next((r for r in book if (r['provider'],r['endpoint'],r['model'],r['tier'])==(provider,endpoint.rstrip('/') if provider=='api' else '',model,tier)),None)
    result={'model':model,'tier':tier,'date':DATE,'currency':'USD','rates':None,'credits':None,'source':API_SOURCE}
    if custom:result.update(currency=custom['currency'],date=custom['date'],source='用户自定义',rates={k:custom[k] for k in ('input','cached','cache_write','output')})
    elif model in BUILTIN and (provider=='codex' or endpoint.rstrip('/')=='https://api.openai.com/v1'):
        i,c,w,o,threshold=BUILTIN[model];mult=2 if fast else 1
        if long and threshold:i*=2;c*=2;w*=2;o*=1.5
        result['rates']={'input':i*mult,'cached':c*mult,'cache_write':w*mult,'output':o*mult}
        result['long_context']=bool(long and threshold)
    if provider=='codex' and model in CREDITS:
        # Credit pricing is not API Priority pricing and has no cache-write fee.
        mult=2.5 if fast and model in ('gpt-6-sol','gpt-6-astra','gpt-6-luna','gpt-5.5') else 2 if fast and model=='gpt-5.4' else 1
        if fast and model not in ('gpt-6-sol','gpt-6-astra','gpt-6-luna','gpt-5.5','gpt-5.4'):result['credits']=None
        else:result['credits']={k:v*mult for k,v in zip(('input','cached','output'),CREDITS[model])}
    return result

def fee(tokens,price):
    rates=price.get('rates');credits=price.get('credits');i=tokens['input'];c=tokens['cached'];w=tokens['cache_write'];o=tokens['output']
    return {'amount':round(((i-c-w)*rates['input']+c*rates['cached']+w*rates['cache_write']+o*rates['output'])/1e6,9) if rates else None,
            'currency':price['currency'],
            'credits':round(((i-c)*credits['input']+c*credits['cached']+o*credits['output'])/1e6,9) if credits else None}

def create(provider):return {'version':1,'provider':provider,'records':[],'notes':[]}
def note(meter,text):
    if text not in meter['notes']:meter['notes'].append(text)

def put(meter,key,tokens,price,source='reported',scope='main',add=False):
    record=next((r for r in meter['records'] if r['key']==key),None)
    if record and add:tokens={k:record['tokens'][k]+tokens[k] for k in (*FIELDS,'total')}
    new={'key':key,'scope':scope,'source':source,'tokens':tokens,'price':price,'fee':fee(tokens,price)}
    if record:record.clear();record.update(new)
    else:meter['records'].append(new)

def codex_event(meter,state,value,book,model,fast,scope='main'):
    total=normalized(value.get('total'),True);last=normalized(value.get('last'),True)
    if total is None:return
    previous=state.get('previous')
    if previous is None:
        delta=last or total
        note(meter,'部分 Codex 历史基线缺失，仅计收到的请求用量。')
    elif any(total[k]<previous[k] for k in FIELDS):
        delta=last or total;note(meter,'Codex 累计计数发生重置，该段按最近请求计入，可能不完整。')
    else:delta={k:total[k]-previous[k] for k in (*FIELDS,'total')}
    state['previous']=total
    if not any(delta[k] for k in FIELDS):return
    # Cumulative counters may publish cache detail after input; clamp each delta.
    delta['cached']=min(delta['input'],delta['cached']);delta['cache_write']=min(delta['input']-delta['cached'],delta['cache_write']);delta['reasoning']=min(delta['output'],delta['reasoning']);delta['total']=delta['input']+delta['output']
    long=bool(last and last['input']>BUILTIN.get(model,(0,0,0,0,0))[4] and BUILTIN.get(model,(0,0,0,0,0))[4])
    price=pricing(book,'codex',model,fast=fast,long=long)
    put(meter,scope+':codex:'+model+':'+str(long),delta,price,scope=scope,add=True)

def summarize(meter):
    totals={k:sum(r['tokens'][k] for r in meter['records']) for k in (*FIELDS,'total')}
    currencies={};references={};unknown=0;credits=0;credit_known=False;review_tokens=0
    for r in meter['records']:
        f=r['fee']
        if f['amount'] is None:unknown+=1
        else:
            target=references if meter['provider']=='api' and r['scope']!='main' else currencies
            target[f['currency']]=target.get(f['currency'],0)+f['amount']
        if f['credits'] is not None:credits+=f['credits'];credit_known=True
        if r['scope']!='main':review_tokens+=r['tokens']['total']
    return {'provider':meter['provider'],'tokens':totals,'estimated':any(r['source']!='reported' for r in meter['records']),
            'amounts':{k:round(v,9) for k,v in currencies.items()},'reference_amounts':{k:round(v,9) for k,v in references.items()},'unpriced':unknown,
            'credits':round(credits,9) if credit_known else None,'credit_unpriced':sum(r['fee']['credits'] is None for r in meter['records']),'review_tokens':review_tokens,
            'notes':meter['notes'],'records':meter['records']}

def decorate(doc,book):
    """Legacy history gets an explicitly labelled estimate; never overwrite disk."""
    previous=None;context_tokens=0
    for message in doc.get('messages',[]):
        if message.get('role')=='assistant':
            meter=message.get('meter')
            if meter is None:
                provider=message.get('settings_snapshot',{}).get('provider',doc.get('provider','api'));meter=create(provider)
                model=message.get('model','');fast=message.get('settings',{}).get('serviceTier')=='priority' or message.get('settings_snapshot',{}).get('fast',False)
                if message.get('token_usage'):
                    state={'previous':previous};codex_event(meter,state,message['token_usage'],book,model,fast);previous=state.get('previous')
                    note(meter,'历史记录按当前参考单价估算；旧版未完整记录审批和各请求的计价上下文。')
                if not meter['records'] and message.get('status') not in ('streaming','stopping'):
                    tokens=estimated('',message.get('content',''));tokens['input']=context_tokens;tokens['total']+=context_tokens
                    put(meter,'legacy',tokens,pricing(book,provider,model,fast=fast),'estimate')
                    note(meter,'历史可见文本粗估；不含隐藏推理、图片和未留存的工具上下文，不能作为完整账单。')
            elif message.get('token_usage'):previous=normalized(message['token_usage'].get('total'),True)
            if not any(r['scope']=='main' for r in meter['records']) and message.get('status') not in ('streaming','stopping'):
                provider=meter['provider'];tokens=estimated('',message.get('content',''));tokens['input']=context_tokens;tokens['total']+=context_tokens
                put(meter,'recovered-estimate',tokens,pricing(book,provider,message.get('model','')),'estimate')
                note(meter,'中断记录未保存主模型用量，按可见文本粗估，不代表完整账单。')
            message['usage_display']=summarize(meter)
        context_tokens+=estimate({'role':message.get('role'),'content':message.get('content',''),'attachments':message.get('attachments',[])})
    return doc
