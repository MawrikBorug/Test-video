"""Bounded live probes of deployed torrent executor. Never stores play tickets."""
import concurrent.futures,json,pathlib,subprocess,time,sys
BASE=sys.argv[1] if __name__=='__main__' and len(sys.argv)>1 else 'https://test-video-taupe.vercel.app'
ROOT=pathlib.Path(__file__).resolve().parents[1]
works=json.loads((ROOT/'web/catalog.json').read_text());out=ROOT/'evidence';out.mkdir(exist_ok=True)
def request(path,body=None,timeout=32):
 args=['curl','-sS','--max-time',str(timeout),'-w','\n%{http_code}',BASE+path]
 if body is not None:args+=['-X','POST','-H','Content-Type: application/json','--data-binary','@-']
 p=subprocess.run(args,input=json.dumps(body) if body is not None else None,text=True,capture_output=True)
 text,_,status=p.stdout.rpartition('\n')
 try:return int(status),json.loads(text)
 except:return int(status or 0),{'error':'NON_JSON_OR_NETWORK','clientError':p.stderr[:160]}

def query(item):
 w,s,e,provider=item;t=time.time();path=f'/api/search/{provider}/{w["key"]}?season={s or 1}&episode={e or 1}'
 status,j=request(path)
 streams=j.get('streams',[])
 rows=[x for x in streams if isinstance(x.get('infoHash'),str) and len(x['infoHash'])==40]
 result={'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'work':w['key'],'season':s,'episode':e,'provider':provider,'http':status,'elapsedSeconds':round(time.time()-t,2),'streams':len(streams),'torrentCandidates':len(rows),'error':j.get('error')}
 print(json.dumps(result),flush=True)
 return result,rows

if __name__=='__main__':
 items=[(w,s,e,p) for w in works for s,e in w['queries'] for p in ['comet','torrentsdb']]
 matrix=[];candidates={}
 with concurrent.futures.ThreadPoolExecutor(2) as pool:
  for (w,s,e,p),(row,rows) in zip(items,pool.map(query,items)):
   matrix.append(row)
   for st in rows:
    title='\n'.join(str(st.get(k,'')) for k in ['title','description','name'])
    candidates.setdefault((w['key'],s,e),[]).append({'hash':st['infoHash'].lower(),'provider':p,'fileIdx':st.get('fileIdx'),'title':title[:1800]})
 (out/'live-search-matrix.json').write_text(json.dumps({'base':BASE,'kind':'LIVE_DEPLOYED_SEARCH','checks':matrix},indent=2,ensure_ascii=False))
 # Locators are torrent infohash, not signed HTTP media URLs. Only bounded
 # per-title candidate samples are retained for reproducible follow-up.
 rows=[{'work':k[0],'season':k[1],'episode':k[2],'candidates':v[:300]} for k,v in candidates.items()]
 (ROOT/'scratch').mkdir(exist_ok=True);(ROOT/'scratch/live-candidates.json').write_text(json.dumps(rows,ensure_ascii=False))
