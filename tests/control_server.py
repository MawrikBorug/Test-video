"""Test harness only: synthetic search metadata + actual owned TCP torrent.
Never imported by production API. No commercial content or delivery fixtures.
"""
import asyncio,json,os,pathlib,subprocess,tempfile,time
import libtorrent as lt
import uvicorn
from backend import main
from backend.engine import Torrent

os.environ['TEST_VIDEO_CONTROL']='1'
root=pathlib.Path(tempfile.mkdtemp(prefix='test-video-browser-'));seed=root/'seed';seed.mkdir();pack=seed/'CONTROL';pack.mkdir()
f=pack/'CONTROL.S01E02.mkv'
subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=24:duration=150','-f','lavfi','-i','sine=frequency=440:duration=150','-f','lavfi','-i','sine=frequency=880:duration=150','-map','0','-map','1','-map','2','-c:v','libx264','-preset','ultrafast','-crf','31','-c:a','aac','-metadata:s:a:0','language=eng','-metadata:s:a:0','title=CONTROL EN','-metadata:s:a:1','language=rus','-metadata:s:a:1','title=CONTROL RU',str(f)],check=True)
fs=lt.file_storage();lt.add_files(fs,str(pack));ct=lt.create_torrent(fs,512*1024);lt.set_piece_hashes(ct,str(seed));meta=lt.bencode(ct.generate());ti=lt.torrent_info(meta);info_hash=str(ti.info_hashes().v1)
seed_session=lt.session({'listen_interfaces':'127.0.0.1:0','enable_dht':False,'enable_lsd':False,'enable_upnp':False,'enable_natpmp':False})
sh=seed_session.add_torrent({'ti':ti,'save_path':str(seed)})
for _ in range(100):
 if sh.status().is_seeding:break
 time.sleep(.1)
class ControlTorrent(Torrent):
 def __init__(self,magnet,root,**kwargs):
  super().__init__(magnet,root,metadata=meta,network=False)
  self.handle.connect_peer(('127.0.0.1',seed_session.listen_port()))
main.Torrent=ControlTorrent
async def synthetic_search(*args,**kwargs):
 return {'dataMode':'CONTROL_SYNTHETIC_SEARCH_REAL_TCP_MEDIA','streams':[{'infoHash':info_hash,'fileIdx':0,'name':'CONTROL · owned generated video','title':'CONTROL S01E02 RUS 360p'}]}
main.upstream=synthetic_search
original_health=main.health
async def health():return {**await original_health(),'control':True}
for route in main.app.routes:
 if getattr(route,'path',None)=='/api/health':route.endpoint=health;route.dependant.call=health
uvicorn.run(main.app,host='127.0.0.1',port=8000,access_log=False)
