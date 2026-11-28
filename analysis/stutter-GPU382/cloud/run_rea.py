"""One persistent REA MCP session; retain complete tool responses, no target execution."""
import json,subprocess,time
from pathlib import Path
R=Path.cwd();O=R/'artifacts/rea-GPU382';O.mkdir(parents=True,exist_ok=True)
log=(O/'rea-stderr.log').open('wb')
p=subprocess.Popen([str(R/'build/rea/node_modules/.bin/rea'),'--mcp'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log)
number=0
def send(value):p.stdin.write((json.dumps(value)+'\n').encode());p.stdin.flush()
def rpc(method,params):
    global number
    number+=1;ident=number;send(dict(jsonrpc='2.0',id=ident,method=method,params=params))
    while True:
        line=p.stdout.readline()
        if not line:raise RuntimeError('REA exited: '+str(p.poll()))
        response=json.loads(line)
        if response.get('id')==ident:return response
def tool(name,args,label):
    began=time.monotonic();print('Starting',name,label,flush=True)
    value=rpc('tools/call',dict(name=name,arguments=args))
    (O/(label+'.json')).write_text(json.dumps(value,indent=2)+'\n')
    print('Finished',label,round(time.monotonic()-began,2),'s',flush=True)
    if 'error' in value or value.get('result',{}).get('isError'):raise RuntimeError('REA failure retained in '+label+'.json')
    return value
opened=False
try:
    init=rpc('initialize',dict(protocolVersion='2024-11-05',capabilities={},clientInfo=dict(name='nabu-gpu382-analysis',version='1')))
    (O/'initialize.json').write_text(json.dumps(init,indent=2)+'\n');send(dict(jsonrpc='2.0',method='notifications/initialized'))
    listing=rpc('tools/list',{});(O/'tools.json').write_text(json.dumps(listing,indent=2)+'\n')
    names={x['name'] for x in listing['result']['tools']}
    for name in ['open_binary','analyze_function','close_binary']:assert name in names
    tool('open_binary',dict(path=str(R/'build/rea-analysis/frontend-symbols.dylib'),provider_id='ghidra'),'open');opened=True
    for name in ['_nmb_encoder_end','_nmb_render_encoder_new','_nmb_command_buffer_wait_scheduled']:
        tool('analyze_function',dict(procedure=name,detail='complete'),name.lstrip('_'))
    (O/'complete.json').write_text(json.dumps(dict(passed=True,input='GPU382 original object relink; 29 file-backed sections match tested library',target_executed=False,functions=3),indent=2)+'\n')
finally:
    if opened:
        try:tool('close_binary',{},'close')
        except Exception as e:print('Close result',str(e),flush=True)
    if p.poll() is None:p.stdin.close()
    try:p.wait(timeout=30)
    except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=15)
    log.close()
