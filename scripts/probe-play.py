"""Live commercial torrent probes: metadata -> bytes -> decoded HLS segments.
No source URL/ticket/media files enter evidence or Git.
"""
import json,pathlib,re,subprocess,sys,time,math,tempfile,os
from scripts.probe_live import request,BASE

ROOT=pathlib.Path(__file__).resolve().parents[1]
rows=json.loads((ROOT/'scratch/live-candidates.json').read_text());known={p.stem for p in (ROOT/'backend/metadata').glob('*.torrent')}
keys=sys.argv[1:] or ['slovo','fallout']
for key in keys:
 row=next(r for r in rows if r['work']==key and r['season'] in (None,1) and r['episode'] in (None,1))
 cs=list({c['hash']:c for c in row['candidates']}.values())
 def rank(c):
  t=c['title'];ru=bool(re.search(r'рус|russian|\brus\b|🇷🇺',t,re.I));preferred=bool(re.search(r'1080p|720p',t,re.I))
  return (c['hash'] in known and (ru or key=='slovo'),ru and preferred,ru,preferred)
 cs.sort(key=rank,reverse=True)
 prefix=os.environ.get('PROBE_EVIDENCE_PREFIX','live-play-')
 if not re.fullmatch(r'[a-z0-9-]+',prefix):raise ValueError('Invalid evidence prefix')
 report_file=ROOT/'evidence'/(prefix+key+'.json')
 reports=json.loads(report_file.read_text()) if report_file.exists() else []
 for candidate in cs[:int(os.environ.get('PROBE_LIMIT','2'))]:
  body={'work':key,'season':row['season'] or 1,'episode':row['episode'] or 1,**{k:candidate[k] for k in ['hash','provider','fileIdx']}}
  print('OPEN',key,candidate['hash'],candidate['title'][:150].replace('\n',' / '),flush=True)
  started=time.time();status,j=request('/api/open',body,timeout=170);ticket=j.pop('ticket',None)
  report={'base':BASE,'sourceBuild':request('/build-info.json')[1],'kind':'LIVE_DEPLOYED_TORRENT','at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'request':body,'http':status,'elapsedSeconds':round(time.time()-started,2),'result':j,'segments':[],'playbackInBrowser':'NOT_RUN','physicalIPhone':'NOT_RUN'}
  if ticket:
   try:
    m=j['media'];audio=next((a['index'] for a in m['audio'] if a['russian']),None)
    if audio is None:report['result']['error']='RUSSIAN_AUDIO_NOT_VERIFIED'
    else:
     h=min(m['qualities'],key=lambda h:abs(h-720));st,play=request('/api/play',{'ticket':ticket,'audio':audio,'height':h},timeout=20)
     if st!=200:raise RuntimeError('play configuration '+str(st))
     path=play['path'].rsplit('/',1)[0]
     for n in [0,int(m['duration']*.6//6),max(0,int((m['duration']-12)//6))]:
      file=pathlib.Path(tempfile.mktemp(suffix='.ts'));t=time.time()
      args=['curl','-sS','--max-time','145','-w','%{http_code}','-o',str(file),BASE+path+'/'+str(n)+'.ts']
      proc=subprocess.run(args,capture_output=True,text=True)
      entry={'segment':n,'timeSeconds':n*6,'http':proc.stdout,'bytes':file.stat().st_size if file.exists() else 0,'elapsedSeconds':round(time.time()-t,2)}
      if proc.stdout=='200':
       q=subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(file)],capture_output=True,text=True)
       try:entry['decodedStreams']=[{'codec':s.get('codec_name'),'type':s.get('codec_type'),'width':s.get('width'),'height':s.get('height')} for s in json.loads(q.stdout).get('streams',[])]
       except:entry['decode']='FAILED'
      file.unlink(missing_ok=True);report['segments'].append(entry);print('SEGMENT',key,json.dumps(entry),flush=True)
      if proc.stdout!='200':break
   finally:request('/api/close',{'ticket':ticket},timeout=15)
  reports.append(report);report_file.write_text(json.dumps(reports,ensure_ascii=False,indent=2))
  print('RESULT',key,json.dumps(report,ensure_ascii=False),flush=True)
  if report['segments'] and all(e.get('decodedStreams') for e in report['segments']):break
