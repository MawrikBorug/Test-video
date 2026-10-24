"""Ordinary BitTorrent (libtorrent TCP/UDP), verified pieces and random reads."""
import asyncio, collections, hashlib, pathlib, secrets, threading, time, json
import libtorrent as lt
from .selection import Refusal, choose_file

ROOT=pathlib.Path(__file__).resolve().parent

class Torrent:
    def __init__(self, magnet, root, *, metadata=None, network=True):
        self.id=secrets.token_hex(16);self.root=pathlib.Path(root)/self.id;self.root.mkdir(parents=True)
        self.hash=magnet.split('urn:btih:',1)[-1][:40].lower()
        settings={'listen_interfaces':'0.0.0.0:0','enable_dht':network,
                  'enable_lsd':False,'enable_upnp':False,'enable_natpmp':False,
                  'connections_limit':60,'active_downloads':2,'alert_mask':int(lt.alert.category_t.all_categories),
                  'upload_rate_limit':128*1024}
        self.session=lt.session(settings)
        if network:
            for host in ['router.bittorrent.com','router.utorrent.com','dht.transmissionbt.com']:
                self.session.add_dht_router(host,6881)
        params=lt.parse_magnet_uri(magnet)
        params.save_path=str(self.root)
        params.flags &= ~lt.torrent_flags.auto_managed
        params.flags &= ~lt.torrent_flags.paused
        params.flags |= lt.torrent_flags.default_dont_download
        if metadata:
            ti=lt.torrent_info(metadata)
            if str(ti.info_hashes().v1)!=self.hash:raise Refusal('TORRENT_HASH_MISMATCH')
            params.ti=ti
        self.handle=self.session.add_torrent(params)
        self.closed=False;self.last=time.monotonic();self.received=0;self._cache=collections.OrderedDict()
        self._events={};self._lock=threading.Lock();self.error=None
        self.alert_counts={};self.tracker_errors=[]
        self.thread=threading.Thread(target=self._alerts,daemon=True);self.thread.start()
        self.file=None;self.media=None;self.segments={};self.tasks={};self.selected_at=None

    def _alerts(self):
        while not self.closed:
            for a in self.session.pop_alerts():
                name=type(a).__name__;self.alert_counts[name]=self.alert_counts.get(name,0)+1
                if isinstance(a,lt.tracker_error_alert):
                    self.tracker_errors.append({'code':a.error.value(),'message':a.error.message()[:120]})
                    self.tracker_errors=self.tracker_errors[-6:]
                if isinstance(a,lt.read_piece_alert):
                    with self._lock:
                        if a.error.value()==0:
                            self._cache[a.piece]=bytes(a.buffer)
                            while len(self._cache)>48:self._cache.popitem(last=False)
                        e=self._events.get(a.piece)
                        if e:e.set()
                elif isinstance(a,lt.torrent_error_alert):self.error='TORRENT_STORAGE_OR_IO_ERROR'
            time.sleep(.025)

    async def metadata(self, timeout=45):
        start=time.monotonic()
        while not self.handle.has_metadata():
            if self.closed:raise Refusal('CANCELLED')
            if self.error:raise Refusal(self.error)
            if time.monotonic()-start>timeout:raise Refusal('METADATA_TIMEOUT')
            await asyncio.sleep(.15)
        ti=self.handle.torrent_file()
        if str(ti.info_hashes().v1)!=self.hash:raise Refusal('TORRENT_HASH_MISMATCH')
        self.ti=ti;self.fs=ti.files();self.piece_length=ti.piece_length()
        # Stop all bulk downloading, request only the pieces read by ffprobe/FFmpeg.
        self.handle.prioritize_files([0]*self.fs.num_files())
        return [{'index':i,'path':self.fs.file_path(i),'size':self.fs.file_size(i)} for i in range(self.fs.num_files())]

    async def select(self, season=None, episode=None, claimed=None):
        files=await self.metadata()
        mapping=json.loads((ROOT/'episode-map.json').read_text())
        matches=[m for row in mapping if row['season']==season and row['episode']==episode for m in row['matches'] if m['infohash']==self.hash]
        if matches:
            m=matches[0]
            # Research paths may be relative to info.name; libtorrent includes
            # that exact verified root. Strip only this root, never arbitrary
            # folders or a basename that could collide inside a collection.
            prefix=self.ti.name()+'/'
            f=next((f for f in files if f['index']==m['fileIdx'] and
                    (f['path']==m['filePath'] or f['path'].removeprefix(prefix)==m['filePath']) and f['size']==m['length']),None)
            if not f:raise Refusal('RESEARCH_FILE_MAP_MISMATCH')
            self.file=f
        else:self.file=choose_file(files,season,episode,claimed)
        priorities=[0]*self.fs.num_files();priorities[self.file['index']]=1
        self.handle.prioritize_files(priorities)
        self.handle.set_flags(lt.torrent_flags.sequential_download)
        self.offset=self.fs.file_offset(self.file['index']);self.selected_at=time.time()
        return self.file

    def piece(self,index, timeout=55):
        self.last=time.monotonic()
        with self._lock:
            if index in self._cache:return self._cache[index]
        self.handle.piece_priority(index,7)
        self.handle.set_piece_deadline(index,0)
        until=time.monotonic()+timeout
        while not self.handle.have_piece(index):
            if self.closed:raise Refusal('CANCELLED')
            if self.error:raise Refusal(self.error)
            if time.monotonic()>until:raise Refusal('PIECE_TIMEOUT')
            if self.handle.status().total_payload_download>12*1024**3:raise Refusal('DISK_BUDGET_EXCEEDED')
            time.sleep(.05)
        with self._lock:
            if index in self._cache:return self._cache[index]
            event=self._events.setdefault(index,threading.Event())
        self.handle.read_piece(index)
        if not event.wait(max(1,until-time.monotonic())):raise Refusal('PIECE_READ_TIMEOUT')
        with self._lock:
            data=self._cache.get(index)
        if data is None:raise Refusal('PIECE_READ_FAILED')
        # libtorrent hash-checks every received piece before have_piece/read_piece.
        if hashlib.sha1(data).digest()!=self.ti.hash_for_piece(index):
            raise Refusal('PIECE_HASH_MISMATCH')
        self.handle.piece_priority(index,1)
        return data

    def read(self,start,end):
        absolute=self.offset+start;stop=self.offset+end+1
        while absolute<stop:
            idx,within=divmod(absolute,self.piece_length)
            data=self.piece(idx);take=min(len(data)-within,stop-absolute)
            if take<=0:raise Refusal('INVALID_PIECE_LENGTH')
            yield data[within:within+take];absolute+=take

    def status(self):
        s=self.handle.status()
        return {'infoHash':self.hash,'peers':s.num_peers,'seeds':s.num_seeds,
                'receivedBytes':s.total_payload_download,'downloadBytesPerSecond':s.download_rate,
                'verifiedPieces':s.num_pieces,'metadataVerified':self.handle.has_metadata(),
                'file':self.file,'dhtNodes':self.session.status().dht_nodes,'listenPortReady':self.session.listen_port()>0,
                'alertCounts':self.alert_counts.copy(),'trackerErrors':self.tracker_errors[:],
                'transport':'BitTorrent TCP/UDP → libtorrent → FFmpeg → HLS'}

    def close(self):
        if self.closed:return
        self.closed=True
        self.session.remove_torrent(self.handle)
        self.thread.join(1)
        import shutil
        shutil.rmtree(self.root,ignore_errors=True)

def known_metadata(info_hash):
    p=ROOT/'metadata'/f'{info_hash}.torrent'
    return p.read_bytes() if p.is_file() else None
