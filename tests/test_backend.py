import asyncio, json, pathlib, subprocess, tempfile, time, unittest
import libtorrent as lt
from backend.selection import choose_file, byte_range, Refusal
from backend.engine import Torrent
from backend.raw import start_raw
from backend.media import inspect, segment, manifest

class Selection(unittest.TestCase):
    def test_correct_episode_not_provider_index_or_largest(self):
        files=[{'index':0,'path':'S01E01.sample.mp4','size':99999999},{'index':1,'path':'readme.txt','size':6},
               {'index':2,'path':'Series.S01E02.mkv','size':900},{'index':3,'path':'Series.S01E01.mkv','size':800}]
        self.assertEqual(choose_file(files,1,2,3)['index'],2)
        with self.assertRaises(Refusal):choose_file(files,2,1,2)
    def test_collection_refused(self):
        with self.assertRaises(Refusal):choose_file([{'path':'Shrek.2001.mkv'},{'path':'Shrek.2.mkv'}])
    def test_ranges(self):
        self.assertEqual(byte_range('bytes=-10',100),(90,99,True))
        self.assertEqual(byte_range('bytes=20-299',100),(20,99,True))
        with self.assertRaises(Refusal):byte_range('bytes=100-',100)

class TorrentPipeline(unittest.IsolatedAsyncioTestCase):
    async def test_real_tcp_torrent_to_hls(self):
        # Owned generated control. This proves the transport/codec pipeline;
        # it cannot prove availability of any of the ten commercial titles.
        root=pathlib.Path(tempfile.mkdtemp(prefix='torrent-control-'));seed=root/'seed';seed.mkdir();pack=seed/'control';pack.mkdir()
        video=pack/'Control.S01E02.mkv'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24:duration=150',
            '-f','lavfi','-i','sine=frequency=440:duration=150','-f','lavfi','-i','sine=frequency=880:duration=150',
            '-map','0','-map','1','-map','2','-c:v','libx264','-preset','ultrafast','-crf','30','-c:a','aac',
            '-metadata:s:a:0','language=eng','-metadata:s:a:0','title=CONTROL EN',
            '-metadata:s:a:1','language=rus','-metadata:s:a:1','title=CONTROL RU',str(video)],check=True)
        (pack/'notes.txt').write_text('CONTROL, not a production source')
        fs=lt.file_storage();lt.add_files(fs,str(pack));ct=lt.create_torrent(fs,64*1024);lt.set_piece_hashes(ct,str(seed));meta=lt.bencode(ct.generate());ti=lt.torrent_info(meta)
        seed_session=lt.session({'listen_interfaces':'127.0.0.1:0','enable_dht':False,'enable_lsd':False,'enable_upnp':False,'enable_natpmp':False})
        sh=seed_session.add_torrent({'ti':ti,'save_path':str(seed)})
        for _ in range(100):
            if sh.status().is_seeding:break
            await asyncio.sleep(.1)
        self.assertTrue(sh.status().is_seeding)
        magnet='magnet:?xt=urn:btih:'+str(ti.info_hashes().v1)
        t=Torrent(magnet,root/'receive',metadata=meta,network=False)
        t.handle.set_download_limit(512*1024)
        try:
            t.handle.connect_peer(('127.0.0.1',seed_session.listen_port()))
            selected=await t.select(1,2,claimed=1)
            self.assertEqual(selected['path'],'control/Control.S01E02.mkv')
            start_raw(t);media=await inspect(t)
            self.assertGreater(media['duration'],149)
            self.assertEqual(len(media['audio']),2)
            self.assertTrue(media['audio'][1]['russian'])
            first=await segment(t,0,media['audio'][1]['index'],180,media['duration'])
            received_at_start=t.status()['receivedBytes']
            self.assertGreater(received_at_start,0)
            self.assertLess(received_at_start,video.stat().st_size)
            far=await segment(t,20,media['audio'][1]['index'],180,media['duration'])
            self.assertNotEqual(first,far)
            for name,body in [('first',first),('seek120',far)]:
                p=root/(name+'.ts');p.write_bytes(body)
                probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(p)]))
                self.assertTrue(any(s['codec_name']=='h264' for s in probe['streams']))
                self.assertTrue(any(s['codec_name']=='aac' for s in probe['streams']))
            report={'kind':'CONTROL_REAL_TCP_TORRENT','fixture':'owned generated S01E02, 150 seconds, two tagged audio streams',
                'hash':t.hash,'selectedFile':selected,'media':media,'firstSegmentBytes':len(first),'seek120SegmentBytes':len(far),
                'receivedAtFirstSegment':received_at_start,'fileSize':video.stat().st_size,'beforeFullDownload':received_at_start<video.stat().st_size,
                'torrentStatus':t.status(),'commercialTitlesVerified':False}
            pathlib.Path('evidence').mkdir(exist_ok=True);pathlib.Path('evidence/local-torrent-control.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
            self.assertIn('#EXT-X-ENDLIST',manifest('ticket',150))
        finally:
            if getattr(t,'raw_server',None):t.raw_server.shutdown()
            t.close();seed_session.remove_torrent(sh)

if __name__=='__main__':unittest.main()
