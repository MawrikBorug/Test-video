"""Lazy private EngineFS process for a warm serverless Python instance."""
import asyncio,json,os,pathlib,subprocess
import httpx
from .selection import Refusal

RUNTIME=pathlib.Path(__file__).resolve().parent/'runtime'
_lock=asyncio.Lock()
_process=None

async def heartbeat(base):
    try:
        async with httpx.AsyncClient(timeout=1) as c:
            r=await c.get(base+'/heartbeat')
            return r.is_success and r.json().get('success') is True
    except (httpx.HTTPError,ValueError):return False

async def ensure(base,state):
    global _process
    if await heartbeat(base):return
    async with _lock:
        if await heartbeat(base):return
        node=RUNTIME/'node';bundle=RUNTIME/'stremio-server.cjs'
        if not node.is_file() or not bundle.is_file():raise Refusal('STREMIO_RUNTIME_NOT_BUNDLED')
        if base!='http://127.0.0.1:11470':raise Refusal('EXTERNAL_STREMIO_UNAVAILABLE')
        from .media import FFMPEG,FFPROBE
        state.mkdir(parents=True,exist_ok=True)
        settings={'cacheRoot':str(state),'cacheSize':0,'localAddonEnabled':False,'remoteHttps':False,
            'btMaxConnections':55,'btDownloadSpeedSoftLimit':8388608,'btDownloadSpeedHardLimit':10485760,
            'transcodeHardwareAccel':False,'allTranscodeProfiles':[]}
        (state/'server-settings.json').write_text(json.dumps(settings))
        if not _process or _process.poll() is not None:
            env={**os.environ,'APP_PATH':str(state),'FFMPEG_BIN':FFMPEG,'FFPROBE_BIN':FFPROBE,
                 'CASTING_DISABLED':'1','NO_CORS':'1','HLS_V2_DISABLED':'1'}
            try:
                with (state/'engine.log').open('wb') as log:
                    _process=subprocess.Popen([str(node),str(bundle)],stdin=subprocess.DEVNULL,
                        stdout=log,stderr=subprocess.STDOUT,env=env)
            except OSError:raise Refusal('STREMIO_PROCESS_EXEC_FAILED')
        for _ in range(50):
            if _process.poll() is not None:raise Refusal('STREMIO_PROCESS_EXITED')
            if await heartbeat(base):return
            await asyncio.sleep(.12)
        raise Refusal('STREMIO_START_TIMEOUT')

def diagnostics():
    data={'bundled':(RUNTIME/'node').is_file() and (RUNTIME/'stremio-server.cjs').is_file(),
        'ownedProcessRunning':bool(_process and _process.poll() is None),
        'exitCode':_process.poll() if _process else None}
    try:data['bundle']=json.loads((RUNTIME/'runtime-info.json').read_text())
    except (OSError,ValueError):pass
    return data
