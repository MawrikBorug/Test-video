"""Private Stremio EngineFS adapter. The public browser API stays in main.py.

Stremio downloads the torrent; our existing verified file selection, ffprobe,
FFmpeg, player, diagnostics and source-failure queue remain responsible for
delivery. No Stremio application, iframe or arbitrary media URL is involved.
"""
import asyncio, os, pathlib, re, secrets, shutil, time
from urllib.parse import urlparse,parse_qs
import httpx
import libtorrent as lt
from .engine import verified_file
from .selection import Refusal

BASE=os.environ.get('STREMIO_URL','http://127.0.0.1:11470').rstrip('/')
STATE=pathlib.Path(os.environ.get('STREMIO_STATE_PATH','.runtime/stremio')).resolve()

class StremioTorrent:
    uses_stremio=True

    def __init__(self,magnet,root,*,metadata=None):
        self.hash=magnet.split('urn:btih:',1)[-1][:40].lower()
        if not re.fullmatch('[a-f0-9]{40}',self.hash):raise Refusal('INVALID_HASH')
        if metadata and str(lt.torrent_info(metadata).info_hashes().v1)!=self.hash:
            raise Refusal('TORRENT_HASH_MISMATCH')
        self.id=secrets.token_hex(16);self.metadata_blob=metadata
        self.trackers=parse_qs(urlparse(magnet).query).get('tr',[])
        self.last=time.monotonic();self.closed=False;self.file=None;self.media=None
        self.upload_slots=None
        self.segments={};self.tasks={};self._stats=None;self._last_stats=0
        self.cache=STATE/'stremio-cache'/self.hash

    async def select(self,season=None,episode=None,claimed=None):
        # A supplied snapshot is always checked above. Without one Stremio
        # obtains BEP9 metadata; re-read its full cached info dictionary below
        # and independently verify the infohash and complete file ordering.
        async with httpx.AsyncClient(timeout=50) as client:
            try:
                if self.metadata_blob:
                    self.cache.mkdir(parents=True,exist_ok=True)
                    pending=self.cache/'cache.download'
                    pending.write_bytes(self.metadata_blob);pending.replace(self.cache/'cache')
                # EngineFS reads its own metadata cache before requesting BEP9.
                # Explicit options also prevent unbounded upload on free hosts.
                sources=['tracker:udp://tracker.opentrackr.org:1337/announce',
                    'tracker:udp://open.stealth.si:80/announce','dht:'+self.hash]
                sources=['tracker:'+url for url in self.trackers]+sources
                if self.metadata_blob:
                    sources=[('tracker:'+t.url) for t in lt.torrent_info(self.metadata_blob).trackers()]+sources
                r=await client.post(f'{BASE}/{self.hash}/create',json={'path':str(self.cache),'uploads':0,
                    'peerSearch':{'min':20,'max':80,'sources':sources},'connections':55})
                r.raise_for_status();j=r.json()
            except httpx.TimeoutException:raise Refusal('METADATA_TIMEOUT')
            except (httpx.HTTPError,ValueError):raise Refusal('STREMIO_ENGINE_UNAVAILABLE')
        if not isinstance(j,dict) or j.get('infoHash')!=self.hash:raise Refusal('TORRENT_HASH_MISMATCH')
        self.upload_slots=j.get('opts',{}).get('uploads')
        if self.upload_slots!=0:raise Refusal('STREMIO_UPLOAD_POLICY_NOT_APPLIED')
        self._stats=j;self._last_stats=time.monotonic()
        for _ in range(40):
            if self.closed:raise Refusal('CANCELLED')
            if (self.cache/'cache').is_file():break
            await asyncio.sleep(.05)
        try:
            blob=(self.cache/'cache').read_bytes()
            if len(blob)>16*1024**2:raise Refusal('STREMIO_METADATA_TOO_LARGE')
            ti=lt.torrent_info(blob)
        except (OSError,RuntimeError):raise Refusal('STREMIO_METADATA_NOT_VERIFIED')
        if str(ti.info_hashes().v1)!=self.hash:raise Refusal('TORRENT_HASH_MISMATCH')
        fs=ti.files()
        files=[{'index':i,'path':fs.file_path(i),'size':fs.file_size(i)} for i in range(fs.num_files())]
        api_files=j.get('files',[])
        if len(api_files)!=len(files):raise Refusal('STREMIO_FILE_MAP_MISMATCH')
        for expected,actual in zip(files,api_files):
            if expected['path']!=actual.get('path') or expected['size']!=actual.get('length'):
                raise Refusal('STREMIO_FILE_MAP_MISMATCH')
        self.file=verified_file(files,self.hash,ti.name(),season,episode,claimed)
        self.raw_url=f'{BASE}/{self.hash}/{self.file["index"]}'
        self.metadata_evidence={**getattr(self,'metadata_evidence',{}),
            'stremioCachedInfoHashChecked':True,'stremioFileOrderChecked':True}
        return self.file

    def status(self):
        self.last=time.monotonic()
        if not self.closed:
            try:
                r=httpx.get(f'{BASE}/{self.hash}/stats.json',timeout=2)
                j=r.json()
                if r.is_success and isinstance(j,dict) and j.get('infoHash')==self.hash:
                    self._stats=j;self._last_stats=time.monotonic()
            except (httpx.HTTPError,ValueError):pass
        j=self._stats or {}
        return {'infoHash':self.hash,'peers':j.get('peers'),'seeds':None,
            'receivedBytes':j.get('downloaded'),'downloadBytesPerSecond':j.get('downloadSpeed'),
            'uploadedBytes':j.get('uploaded'),'uploadSlotsAppliedAtCreation':self.upload_slots,
            'metadataVerified':bool(self.file),'file':self.file,
            'metadataEvidence':getattr(self,'metadata_evidence',None),
            'connectionTries':j.get('connectionTries'),'queuedPeers':j.get('queued'),
            'statisticsAgeSeconds':round(time.monotonic()-self._last_stats,2) if self._stats else None,
            'pieceVerification':'Stremio torrent-stream SHA-1',
            'transport':'BitTorrent TCP/UDP → Stremio EngineFS → FFmpeg → HLS'}

    def downloaded_bytes(self):return (self._stats or {}).get('downloaded',0)

    def close(self):
        if self.closed:return
        self.closed=True
        for task in list(self.tasks.values()):
            if not task.done():task.cancel()
        try:r=httpx.get(f'{BASE}/{self.hash}/remove',timeout=3)
        except httpx.HTTPError:return
        if r.is_success:shutil.rmtree(self.cache,ignore_errors=True)
