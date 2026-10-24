"""Bounded diagnostics for this deployment, with no credentials or peer IPs."""
import asyncio,json,os,pathlib,shutil,socket,ssl,subprocess,time
import httpx

_cached=None
_lock=asyncio.Lock()
HOST='comet.feels.legal'

def native_tls():
    started=time.monotonic()
    try:
        addresses=socket.getaddrinfo(HOST,443,type=socket.SOCK_STREAM)
        counts={'ipv4':sum(a[0]==socket.AF_INET for a in addresses),
                'ipv6':sum(a[0]==socket.AF_INET6 for a in addresses)}
        with socket.create_connection((HOST,443),timeout=3) as raw:
            with ssl.create_default_context().wrap_socket(raw,server_hostname=HOST) as conn:
                conn.settimeout(3)
                conn.sendall(b'HEAD /manifest.json HTTP/1.1\r\nHost: comet.feels.legal\r\nConnection: close\r\n\r\n')
                line=conn.recv(100).split(b'\r\n',1)[0].decode('ascii',errors='replace')
        return {'result':'CONNECTED_TLS','dnsAddressCounts':counts,'httpStatusLine':line,
                'elapsedSeconds':round(time.monotonic()-started,3)}
    except OSError as e:
        return {'result':'FAILED','errorType':type(e).__name__,'errno':e.errno,
                'elapsedSeconds':round(time.monotonic()-started,3)}

async def check():
    global _cached
    async with _lock:
        if _cached and time.monotonic()-_cached[0]<120:return _cached[1]
        proxy=any(os.environ.get(k) for k in ['HTTPS_PROXY','HTTP_PROXY','https_proxy','http_proxy'])
        p=pathlib.Path('/etc/codex/network-policy.json')
        policy={'present':p.is_file()}
        if p.is_file():
            try:
                j=json.loads(p.read_text());tcp=j.get('tcp_network_access',{})
                policy.update({'version':j.get('version'),'tcpDomainGrants':len(tcp.get('domains',[])),
                    'tcpIpRangeGrants':len(tcp.get('ip_ranges',[]))})
            except (OSError,ValueError):policy['readable']=False
        node=shutil.which('node')
        version=None
        if node:
            try:version=(await asyncio.to_thread(subprocess.check_output,[node,'--version'],timeout=3,text=True)).strip()
            except (OSError,subprocess.SubprocessError):version='UNAVAILABLE'
        result={'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'kind':'DEPLOYED_RUNTIME_NETWORK_CHECK','serverless':bool(os.environ.get('VERCEL')),
            'proxyConfigured':proxy,'managedNetworkPolicy':policy,
            'nodePresent':bool(node),'nodeVersion':version,'videoPlayback':'NOT_TESTED_BY_THIS_DIAGNOSTIC'}
        if policy['present']:
            result['nativeTcp']={'result':'SKIPPED_MANAGED_NETWORK_POLICY','reason':'Raw TCP requires configured destination grants; this endpoint does not bypass the proxy.'}
        elif proxy:
            result['nativeTcp']={'result':'SKIPPED_CONFIGURED_HTTP_PROXY'}
        elif os.environ.get('VERCEL'):
            try:result['nativeTcp']=await asyncio.wait_for(asyncio.to_thread(native_tls),timeout=9)
            except TimeoutError:result['nativeTcp']={'result':'TIMEOUT'}
        else:result['nativeTcp']={'result':'SKIPPED_UNRECOGNIZED_HOST'}
        try:
            async with httpx.AsyncClient(timeout=6,trust_env=True) as c:
                r=await c.get('https://'+HOST+'/manifest.json')
                result['httpClient']={'http':r.status_code,'bytes':len(r.content)}
        except httpx.HTTPError as e:result['httpClient']={'errorType':type(e).__name__}
        _cached=(time.monotonic(),result)
        return result
