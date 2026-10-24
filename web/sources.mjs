export const providers=[{id:'comet',name:'Comet',base:'https://comet.feels.legal'},{id:'torrentsdb',name:'TorrentsDB',base:'https://torrentsdb.com'}];
const voiceRE=/AniLibria|Anilibria|LostFilm|TVShows|AniBaza|Dream\s?Cast|JASKIER|AlexFilm|HDRezka|Дубляжная|Кубик в кубе|Студия СВ-Дубль|StudioBand/ig;
export function normalize(stream,work,provider){
 const hash=stream?.infoHash?.toLowerCase();
 if(!/^[a-f0-9]{40}$/.test(hash||''))return null;
 const title=[stream.name,stream.title,stream.description,stream.behaviorHints?.filename].filter(x=>typeof x==='string').join('\n');
 if(/configure|configuration required|not configured/i.test(title))return null;
 if(work.key==='deathnote'&&/2017|2015|live.action/i.test(title))return null;
 if(work.key==='hailmary'&&/audiobook|epub|fb2|аудиокниг/i.test(title))return null;
 if(work.key==='shrek'&&/shrek[ ._-]*[234]|shrek.*forever|шрек[ ._-]*[234]/i.test(title))return null;
 const resolution=title.match(/\b(2160p|1080p|720p|480p|4K)\b/i)?.[1]?.toLowerCase()||'unknown';
 const voices=[...new Set(title.match(voiceRE)||[])];
 const ru=/рус|russian|\brus\b|🇷🇺/i.test(title)||voices.length>0;
 return {key:hash+':'+(stream.fileIdx??'?'),hash,fileIdx:Number.isInteger(stream.fileIdx)?stream.fileIdx:null,
  title:title.slice(0,1300),provider:provider.id,providers:[provider.name],resolution,voices,ru,
  dataMode:'live',metadataVerified:false,state:'found'};
}
export function merge(candidates){
 const items=new Map();for(const c of candidates){const old=items.get(c.key);if(old)old.providers=[...new Set([...old.providers,...c.providers])];else items.set(c.key,c);}
 return [...items.values()].sort((a,b)=>Number(b.ru)-Number(a.ru)||Number(/1080|720/.test(b.resolution))-Number(/1080|720/.test(a.resolution)));
}
export function videoId(work,season,episode){return work.type==='series'?`${work.imdb}:${season}:${episode}`:work.imdb;}
export async function jsonRequest(url,{signal,method='GET',body,timeout=25000}={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort('TIMEOUT'),timeout);
 const abort=()=>controller.abort('CANCELLED');signal?.addEventListener('abort',abort,{once:true});
 try {
  const response=await fetch(url,{signal:controller.signal,cache:'no-store',method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
  if(response.status===429)throw new Error('RATE_LIMIT · Retry-After: '+(response.headers.get('Retry-After')||'unknown'));
  const text=await response.text();if(text.length>16*1024*1024)throw new Error('RESPONSE_TOO_LARGE');
  let data;try{data=JSON.parse(text)}catch{throw new Error('NON_JSON_HTTP_'+response.status)}
  if(!response.ok||data.error)throw new Error(data.error||'HTTP_'+response.status);
  return data;
 }catch(e){if(controller.signal.aborted)throw new Error(signal?.aborted?'CANCELLED':'TIMEOUT');throw e;}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',abort)}
}
