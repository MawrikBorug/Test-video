import asyncio, base64, hashlib, hmac, json, os, pathlib, re, secrets, tempfile, time
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from .engine import Torrent, known_metadata
from .selection import Refusal
from .raw import start_raw
from .media import inspect, manifest, segment
from .metadata import resolve as resolve_metadata
from .discovery import discover

STREMIO_ENABLED=bool(os.environ.get('STREMIO_URL'))
if STREMIO_ENABLED:
    from .stremio import StremioTorrent as Torrent

ROOT=pathlib.Path(__file__).resolve().parents[1]
CATALOG=json.loads((ROOT/'web/catalog.json').read_text())
WORKS={w['key']:w for w in CATALOG}
PROVIDERS={'comet':'https://comet.feels.legal','torrentsdb':'https://torrentsdb.com'}
STORE=pathlib.Path(tempfile.mkdtemp(prefix='test-video-'))
SECRET=os.environ.get('PLAYBACK_SECRET','').encode() or secrets.token_bytes(32)
MAX_BYTES=int(os.environ.get('TORRENT_CACHE_BYTES',str(256*1024**2 if os.environ.get('VERCEL') else 12*1024**3)))
MAX_SESSIONS=max(1,int(os.environ.get('TORRENT_MAX_SESSIONS','1' if STREMIO_ENABLED else '2')))
engines={};logs=[];lock=asyncio.Lock();http_cooldowns={}
def engine_key(data):return f'{data["hash"]}:{data.get("season")}:{data.get("episode")}'

def event(code,**fields):
    row={'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'code':code,**fields}
    logs.append(row)
    if len(logs)>300:logs.pop(0)
    print(json.dumps(row),flush=True)
    return row

@asynccontextmanager
async def lifespan(app):
    async def retire_idle():
        while True:
            await asyncio.sleep(30)
            async with lock:
                for key,t in list(engines.items()):
                    if not t.tasks and time.monotonic()-t.last>300:
                        if getattr(t,'raw_server',None):t.raw_server.shutdown()
                        t.close();engines.pop(key,None)
                        event('IDLE_TORRENT_CLOSED',infoHash=t.hash)
    reaper=asyncio.create_task(retire_idle())
    yield
    reaper.cancel()
    try:await reaper
    except asyncio.CancelledError:pass
    for t in list(engines.values()):
        if getattr(t,'raw_server',None):t.raw_server.shutdown()
        t.close()

app=FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['https://mawrikborug.github.io','https://test-video-taupe.vercel.app','http://localhost:5173','http://127.0.0.1:5173'],allow_methods=['GET','POST','DELETE'],allow_headers=['Content-Type'],expose_headers=['Content-Length'])

@app.exception_handler(Refusal)
async def refused(request,error):
    event(error.code)
    return JSONResponse({'error':error.code,'diagnostics':getattr(error,'diagnostics',None)},status_code=422)

def work_query(key,season,episode):
    if key not in WORKS:raise Refusal('UNKNOWN_WORK')
    w=WORKS[key]
    if w['type']=='series':
        if not 1<=int(season)<=50 or not 1<=int(episode)<=2000:raise Refusal('INVALID_EPISODE')
        return w,f'{w["imdb"]}:{int(season)}:{int(episode)}'
    return w,w['imdb']

async def upstream(provider,work,season=1,episode=1):
    w,identity=work_query(work,season,episode)
    if provider not in PROVIDERS:raise Refusal('UNKNOWN_PROVIDER')
    if http_cooldowns.get(provider,0)>time.time():raise Refusal('UPSTREAM_COOLDOWN')
    async with httpx.AsyncClient(timeout=24,follow_redirects=True,trust_env=True) as c:
        try:r=await c.get(f'{PROVIDERS[provider]}/stream/{w["type"]}/{identity}.json',headers={'User-Agent':'Test-video/0.1 research playback stand'})
        except httpx.RequestError:raise Refusal('UPSTREAM_NETWORK')
        if r.status_code==429:
            http_cooldowns[provider]=time.time()+min(600,int(r.headers.get('Retry-After','60')) if r.headers.get('Retry-After','60').isdigit() else 60)
            raise Refusal('UPSTREAM_RATE_LIMIT')
        if r.status_code!=200:raise Refusal(f'UPSTREAM_HTTP_{r.status_code}')
        if len(r.content)>16*1024**2:raise Refusal('UPSTREAM_TOO_LARGE')
        try:j=r.json()
        except ValueError:raise Refusal('UPSTREAM_INVALID_JSON')
    if not isinstance(j.get('streams'),list):raise Refusal('UPSTREAM_INVALID_STREAMS')
    return j

@app.get('/api/health')
async def health():
    from .media import FFMPEG,FFPROBE
    stremio_ready=None
    if STREMIO_ENABLED:
        from .stremio import BASE
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r=await c.get(BASE+'/heartbeat');stremio_ready=r.is_success and r.json().get('success') is True
        except (httpx.HTTPError,ValueError):stremio_ready=False
    return {'version':'torrent-1','transport':'Stremio EngineFS TCP/UDP' if STREMIO_ENABLED else 'libtorrent TCP/UDP','transcoder':'FFmpeg H.264/AAC',
            'active':len(engines),'ffmpeg':pathlib.Path(FFMPEG).exists(),'ffprobe':pathlib.Path(FFPROBE).exists(),
            'cacheBytes':MAX_BYTES,'sessionLimit':MAX_SESSIONS,'serverless':bool(os.environ.get('VERCEL')),
            'engineReady':stremio_ready if STREMIO_ENABLED else True,
            'readiness':'runtime-present; torrent-egress-and-real-playback-require-a-probe'}

@app.get('/api/search/{provider}/{key}')
async def search(provider:str,key:str,season:int=1,episode:int=1):
    return await upstream(provider,key,season,episode)

@app.get('/api/episodes/{key}')
async def episodes(key:str):
    if key not in WORKS:raise Refusal('UNKNOWN_WORK')
    w=WORKS[key]
    async with httpx.AsyncClient(timeout=18,trust_env=True) as c:
        try:r=await c.get(f'https://v3-cinemeta.strem.io/meta/{w["type"]}/{w["imdb"]}.json');j=r.json()
        except (httpx.RequestError,ValueError):raise Refusal('EPISODE_CATALOG_UNAVAILABLE')
    return {'episodes':[{'season':e.get('season'),'episode':e.get('episode'),'title':e.get('title'),'released':e.get('released')} for e in j.get('meta',{}).get('videos',[]) if (e.get('season') or 0)>0]}

def encode(data):
    value=base64.urlsafe_b64encode(json.dumps(data,separators=(',',':')).encode()).decode().rstrip('=')
    sig=hmac.new(SECRET,value.encode(),hashlib.sha256).hexdigest()
    return value+'.'+sig

def decode(ticket):
    try:
        value,sig=ticket.rsplit('.',1)
        if not hmac.compare_digest(sig,hmac.new(SECRET,value.encode(),hashlib.sha256).hexdigest()):raise ValueError()
        d=json.loads(base64.urlsafe_b64decode(value+'='*((-len(value))%4)))
        if d['exp']<time.time():raise Refusal('PLAYBACK_TICKET_EXPIRED')
        return d
    except (ValueError,KeyError):raise Refusal('INVALID_PLAYBACK_TICKET')

async def load(data,probe=True):
    key=engine_key(data)
    async with lock:
        t=engines.get(key)
        if t and (t.closed or (not t.tasks and t.downloaded_bytes()>MAX_BYTES)):
            if getattr(t,'raw_server',None):t.raw_server.shutdown()
            t.close();engines.pop(key,None);t=None
        if not t:
            for oldkey,old in list(engines.items()):
                if time.monotonic()-old.last>300:
                    if getattr(old,'raw_server',None):old.raw_server.shutdown()
                    old.close();engines.pop(oldkey,None)
            if len(engines)>=MAX_SESSIONS:raise Refusal('EXECUTOR_CAPACITY')
            magnet='magnet:?xt=urn:btih:'+data['hash']
            for tr in ['udp://tracker.opentrackr.org:1337/announce','udp://open.stealth.si:80/announce','https://tracker.tamersunion.org:443/announce']:
                from urllib.parse import quote
                magnet+='&tr='+quote(tr,safe='')
            metadata,metadata_evidence=await resolve_metadata(data['hash'])
            t=Torrent(magnet,STORE,metadata=metadata)
            t.metadata_evidence=metadata_evidence
            event('TORRENT_METADATA_ROUTE',infoHash=t.hash,**metadata_evidence)
            engines[key]=t
    try:
        if not t.file:
            if not getattr(t,'uses_stremio',False) and not getattr(t,'https_discovery',None):
                reports=await discover(t)
                event('HTTPS_TRACKER_DISCOVERY',infoHash=t.hash,reports=reports)
            f=await t.select(data.get('season'),data.get('episode'),data.get('fileIdx'))
            if data.get('verifiedFile') is not None and f['index']!=data['verifiedFile']:raise Refusal('REHYDRATED_FILE_CHANGED')
            if not getattr(t,'uses_stremio',False):start_raw(t)
            event('TORRENT_FILE_VERIFIED',work=data.get('work'),season=data.get('season'),episode=data.get('episode'),fileIndex=f['index'],infoHash=t.hash)
        if not t.media and probe:await inspect(t)
        t.last=time.monotonic()
        return t
    except BaseException as error:
        if isinstance(error,Refusal):
            error.diagnostics=t.status()
            event('TORRENT_FAILURE_DIAGNOSTICS',**error.diagnostics)
        if getattr(t,'raw_server',None):t.raw_server.shutdown()
        t.close();engines.pop(key,None)
        raise

@app.post('/api/open')
async def open_source(request:Request):
    d=await request.json()
    if not re.fullmatch(r'[a-f0-9]{40}',d.get('hash','')):raise Refusal('INVALID_HASH')
    w,_=work_query(d.get('work'),d.get('season',1),d.get('episode',1))
    # A viewer may only start a torrent present in the selected upstream's fresh
    # work/episode response. Never expose a general arbitrary magnet downloader.
    j=await upstream(d.get('provider'),w['key'],d.get('season',1),d.get('episode',1))
    matches=[s for s in j['streams'] if s.get('infoHash','').lower()==d['hash']]
    if not matches:raise Refusal('HASH_NOT_IN_CURRENT_SEARCH')
    data={'hash':d['hash'],'work':w['key'],'season':d.get('season') if w['type']=='series' else None,
          'episode':d.get('episode') if w['type']=='series' else None,'fileIdx':d.get('fileIdx'),
          'exp':int(time.time()+12*3600)}
    t=await load(data)
    data['verifiedFile']=t.file['index']
    data['media']=t.media
    ticket=encode(data)
    event('TORRENT_MEDIA_INSPECTED',infoHash=t.hash,audioCount=len(t.media['audio']),duration=t.media['duration'],receivedBytes=t.status()['receivedBytes'])
    return {'ticket':ticket,'file':t.file,'media':t.media,'status':t.status()}

@app.post('/api/play')
async def play(request:Request):
    d=await request.json();data=decode(d['ticket']);media=data['media']
    if d.get('audio') not in [a['index'] for a in media['audio']]:raise Refusal('INVALID_AUDIO_TRACK')
    if d.get('height') not in media['qualities']:raise Refusal('INVALID_QUALITY')
    data.update({'audio':d['audio'],'height':d['height']})
    ticket=encode(data)
    return {'path':f'/api/play/{ticket}/index.m3u8','duration':media['duration']}

@app.get('/api/play/{ticket}/index.m3u8')
async def playlist(ticket:str):
    d=decode(ticket)
    return Response(manifest(ticket,d['media']['duration']),media_type='application/vnd.apple.mpegurl',headers={'Cache-Control':'no-store'})

@app.get('/api/play/{ticket}/{index}.ts')
async def ts(ticket:str,index:int):
    d=decode(ticket);t=await load(d,probe=False)
    if not t.media:t.media=d['media']
    try:body=await segment(t,index,d['audio'],d['height'],d['media']['duration'])
    except Refusal as e:
        event(e.code,segment=index,infoHash=t.hash);raise
    event('TORRENT_SEGMENT',infoHash=t.hash,segment=index,audio=d['audio'],height=d['height'],bytes=len(body),receivedBytes=t.status()['receivedBytes'])
    return Response(body,media_type='video/mp2t',headers={'Cache-Control':'private, max-age=1800'})

@app.post('/api/status')
async def status(request:Request):
    d=decode((await request.json())['ticket']);t=engines.get(engine_key(d))
    return t.status() if t else {'state':'cold; next segment rehydrates selected torrent','receivedBytes':None}

@app.post('/api/close')
async def close_source(request:Request):
    d=decode((await request.json())['ticket']);t=engines.pop(engine_key(d),None)
    if t:
        if getattr(t,'raw_server',None):t.raw_server.shutdown()
        t.close()
    return {'closed':True}

app.mount('/',StaticFiles(directory=ROOT/'dist',html=True,check_dir=False),name='web')
