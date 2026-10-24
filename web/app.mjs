import Hls from 'hls.js';
import catalog from './catalog.json';
import './style.css';
import {providers,normalize,merge,videoId,jsonRequest} from './sources.mjs';
const $=id=>document.getElementById(id),video=$('video');
const state={work:catalog[0],season:1,episode:1,episodes:[],candidates:[],generation:0,controller:null,ready:false,ticket:null,hls:null,running:false,active:null,log:[],limit:20,statusTimer:null,stallTimer:null,lastProgress:0,played:false,queue:[],trying:false,dataMode:'live',failing:false};
const paintLog=()=>{$('log').replaceChildren(...state.log.slice(-70).reverse().map(row=>{const el=document.createElement('div');el.className='logrow'+(/FAIL|ERROR|TIMEOUT|BLOCK|UNAVAILABLE|MISMATCH/.test(row.code)?' bad':'');const time=document.createElement('time');time.textContent=row.at.slice(11,19);const text=document.createElement('span');text.textContent=row.code+' '+JSON.stringify(row.details);el.append(time,text);return el}));};
function log(code,details={}){state.log.push({at:new Date().toISOString(),code,mode:state.dataMode,details});if(state.log.length>350)state.log.shift();paintLog();try{localStorage.setItem('test-video.log.v1',JSON.stringify(state.log))}catch{}}
function status(text){$('status').textContent=text;}
const explanations={METADATA_TIMEOUT:'Не получены metadata у пиров и HTTPS-кэшей.',PIECE_TIMEOUT:'Файл определён, но требуемые торрент-части не получены.',RUSSIAN_AUDIO_NOT_VERIFIED:'В файле не подтверждена русская дорожка.',EXECUTOR_CAPACITY:'У исполнителя заняты разрешённые сессии.',EPISODE_UNRESOLVED:'Не удалось однозначно сопоставить сезон и серию с файлом.',MEDIA_PROCESS_FAILED:'FFmpeg не смог прочитать или подготовить видео.',TORRENT_HASH_MISMATCH:'Metadata не соответствуют выбранному infohash.'};
function resetSteps(){for(const s of ['search','file','audio','video'])step(s,'');}
const safeError=e=>String(e.message||e).replace(/https?:\/\/\S+/g,'[URL]').replace(/[A-Za-z0-9_\-]{64,}/g,'[скрыто]').slice(0,220);
function step(id,value){$('step-'+id).className=value;}
let executorBase='';try{executorBase=localStorage.getItem('test-video.executor.v1')||''}catch{}
function api(path){return executorBase?executorBase+path:path;}
async function request(path,options={}){return jsonRequest(api(path),options);}
function selection(){return {work:state.work.key,season:state.season,episode:state.episode};}
function option(value,label){const el=document.createElement('option');el.value=value;el.textContent=label;return el;}
function controls(){
 const series=state.work.type==='series';$('episode-controls').hidden=!series;
 const seasons=[...new Set(state.episodes.map(e=>e.season))].sort((a,b)=>a-b);
 // Fallback is a labelled query choice, never claimed to be a provider episode.
 if(!seasons.length)seasons.push(...[...new Set(state.work.queries.filter(q=>q[0]).map(q=>q[0]))]);
 $('season').replaceChildren(...seasons.map(s=>option(s,String(s))));$('season').value=state.season;
 const episodes=state.episodes.filter(e=>e.season===state.season).sort((a,b)=>a.episode-b.episode);
 if(!episodes.length)episodes.push(...Array.from({length:state.work.key==='deathnote'?37:state.work.key==='slovo'?8:28},(_,i)=>({episode:i+1,title:'номер для запроса; каталог не получен'})));
 $('episode').replaceChildren(...episodes.map(e=>option(e.episode,`${e.episode} · ${e.title||'Серия'}`)));$('episode').value=state.episode;
}
async function stop({invalidate=true}={}){
 if(invalidate){state.generation++;state.controller?.abort();}
 state.running=false;state.trying=false;clearInterval(state.statusTimer);clearTimeout(state.stallTimer);state.hls?.destroy();state.hls=null;
 video.pause();video.removeAttribute('src');video.load();video.style.display='none';$('empty-player').hidden=false;$('play-options').hidden=true;$('stop').disabled=true;$('resume').hidden=true;$('stats').textContent='';
 if(state.ticket){const ticket=state.ticket;state.ticket=null;request('/api/close',{method:'POST',body:{ticket},timeout:5000}).catch(()=>{});}
}
async function selectWork(work){
 await stop();state.work=work;state.season=1;state.episode=1;state.episodes=[];state.candidates=[];state.active=null;state.queue=[];
 for(const el of $('works').children){const selected=el.dataset.key===work.key;el.classList.toggle('active',selected);el.setAttribute('aria-pressed',String(selected));}
 $('work-title').textContent=(state.dataMode==='live'?'':'КОНТРОЛЬ · ')+work.ru;$('work-meta').textContent=`${work.type==='series'?'СЕРИАЛ':'ФИЛЬМ'} / ${work.year} / ${work.imdb}`;$('work-note').textContent=work.note||work.title;
 $('search').disabled=false;
 for(const s of ['search','file','audio','video'])step(s,'');controls();renderCandidates();$('auto').disabled=true;status('Выберите сезон и серию, затем найдите источники.');
 const generation=state.generation;
 try{const data=state.ready?await request('/api/episodes/'+work.key):await jsonRequest(`https://v3-cinemeta.strem.io/meta/${work.type}/${work.imdb}.json`).then(j=>({episodes:(j.meta?.videos||[]).filter(e=>e.season>0)}));if(generation!==state.generation)return;state.episodes=data.episodes.filter(e=>Number.isInteger(e.episode)&&Number.isInteger(e.season));controls();log('EPISODE_CATALOG',{work:work.key,episodes:state.episodes.length});}
 catch(e){if(generation===state.generation)log('EPISODE_CATALOG_UNAVAILABLE',{work:work.key,error:safeError(e)});}
}
const colors=[['#5f493e','#182824'],['#496b62','#1a2625'],['#4b5057','#151b23'],['#695c44','#171c25'],['#625b3b','#262e27'],['#3f6255','#172721'],['#6a3d42','#1f2830'],['#4b5f68','#191c2b'],['#5e7043','#222e1d'],['#555c6b','#242431']];
catalog.forEach((w,i)=>{const b=document.createElement('button');b.className='work';b.dataset.key=w.key;b.setAttribute('aria-label',`${w.ru}, ${w.year}`);b.setAttribute('aria-pressed','false');const art=document.createElement('div');art.className='art';art.style.setProperty('--a',colors[i][0]);art.style.setProperty('--b',colors[i][1]);const num=document.createElement('small');num.textContent=String(i+1).padStart(2,'0');const initial=document.createElement('span');initial.textContent=w.ru.split(/\s/).map(s=>s[0]).slice(0,2).join('');art.append(initial,num);const txt=document.createElement('div');txt.className='worktext';const title=document.createElement('strong');title.textContent=w.ru;const meta=document.createElement('small');meta.textContent=`${w.year} · ${w.type==='series'?'Сериал':'Фильм'}`;txt.append(title,meta);b.append(art,txt);b.onclick=()=>selectWork(w);$('works').append(b);});
async function changeEpisode(){await stop();state.season=Number($('season').value)||1;state.episode=Number($('episode').value)||1;controls();resetSteps();state.candidates=[];state.queue=[];renderCandidates();$('auto').disabled=true;status('Серия изменена. Выполните новый поиск.');}
$('season').onchange=async()=>{const season=Number($('season').value)||1;await stop();state.season=season;state.episode=1;controls();resetSteps();state.candidates=[];state.queue=[];renderCandidates();$('auto').disabled=true;status('Сезон изменён. Выполните новый поиск.');};$('episode').onchange=changeEpisode;
function visibleCandidates(){return state.candidates.filter(c=>($('voice-filter').value==='all'||c.ru)&&($('source-quality').value==='all'||c.resolution===$('source-quality').value));}
function renderCandidates(){
 $('count').textContent=String(state.candidates.length);const items=visibleCandidates();$('source-list').replaceChildren(...items.slice(0,state.limit).map(c=>{const el=document.createElement('div');el.className='candidate'+(c.state==='failed'?' failed':'');const body=document.createElement('div');const title=document.createElement('p');title.textContent=c.title.split('\n').slice(0,3).join(' · ');const detail=document.createElement('small');detail.textContent=`${c.providers.join(' + ')} · ${c.resolution} · fileIdx ${c.fileIdx??'?'} · ${c.state==='failed'?c.error:'metadata ещё не проверены'}`;body.append(title,detail);const b=document.createElement('button');b.textContent=c.state==='failed'?'Повторить':'Проверить';b.disabled=!state.ready||state.trying;const gen=state.generation;b.onclick=()=>{if(gen===state.generation)startQueue([c,...items.filter(x=>x!==c)])};el.append(body,b);return el}));
 if(!items.length){const p=document.createElement('p');p.className='muted';p.textContent=state.candidates.length?'Метки русской озвучки не найдены. Выберите «Все»: сервер проверит реальные дорожки.':'Источники пока не найдены.';$('source-list').append(p)}
 $('more').hidden=items.length<=state.limit;
}
$('more').onclick=()=>{state.limit+=20;renderCandidates()};for(const id of ['voice-filter','source-quality'])$(id).onchange=()=>{state.limit=20;renderCandidates()};
async function search(){
 await stop();const generation=state.generation;const controller=new AbortController();state.controller=controller;state.candidates=[];state.limit=20;state.queue=[];resetSteps();$('auto').disabled=true;renderCandidates();step('search','busy');status('Запрашиваем Comet и TorrentsDB…');
 for(const p of providers){
  try{
   const url=state.ready?api(`/api/search/${p.id}/${state.work.key}?season=${state.season}&episode=${state.episode}`):`${p.base}/stream/${state.work.type}/${videoId(state.work,state.season,state.episode)}.json`;
   const j=await jsonRequest(url,{signal:controller.signal});if(generation!==state.generation)return;
   if(!Array.isArray(j.streams))throw new Error('STREAMS_INVALID');
   const normalized=j.streams.map(s=>normalize(s,state.work,p)).filter(Boolean);
   state.candidates=merge([...state.candidates,...normalized]);renderCandidates();
   log('LIVE_SEARCH',{provider:p.name,...selection(),reported:j.streams.length,torrentCandidates:normalized.length,unique:state.candidates.length});
   status(`Найдено ${state.candidates.length} раздач. ${p.id==='comet'?'Проверяем резерв TorrentsDB…':''}`);
  }catch(e){if(generation!==state.generation)return;log('SEARCH_FAILED',{provider:p.name,error:safeError(e)});}
 }
 if(generation!==state.generation)return;step('search',state.candidates.length?'done':'');$('auto').disabled=!state.ready||!state.candidates.length;
 status(state.candidates.length?(state.ready?'Выберите раздачу или нажмите «Проверить и запустить». При отказе будет проверена следующая.':'Поиск выполнен, но торрент-исполнитель недоступен. Воспроизведение пока заблокировано.'):'Оба поставщика не вернули пригодных торрент-источников. Подробности в журнале.');
}
$('search').onclick=search;$('auto').onclick=()=>startQueue(visibleCandidates().length?visibleCandidates():state.candidates);$('stop').onclick=()=>{stop();status('Получение видео остановлено. Журнал сохранён.');log('USER_STOP')};
async function startQueue(items){
 await stop();const generation=state.generation;state.controller=new AbortController();state.queue=items.slice(0,8);state.running=true;state.trying=true;$('stop').disabled=false;$('auto').disabled=true;renderCandidates();
 await nextCandidate(generation);
}
async function nextCandidate(generation){
 if(generation!==state.generation||!state.running)return;
 const c=state.queue.shift();if(!c){state.trying=false;state.running=false;renderCandidates();status('Очередь проверена. Видеодоставка не подтверждена. '+(state.lastFailure||'Подробности в журнале.'));$('auto').disabled=false;log('QUEUE_EXHAUSTED');return;}
 state.active=c;state.played=false;step('file','busy');status(`Проверяем файл и доступность пиров: ${c.providers.join(' + ')} · ${c.resolution}. До 150 секунд на metadata, байты и дорожки.`);
 log('TORRENT_OPEN',{...selection(),hash:c.hash,fileIdxClaimed:c.fileIdx,provider:c.provider});
 try{
  const result=await request('/api/open',{method:'POST',body:{...selection(),provider:c.provider,hash:c.hash,fileIdx:c.fileIdx},signal:state.controller.signal,timeout:160000});
  if(generation!==state.generation){request('/api/close',{method:'POST',body:{ticket:result.ticket}}).catch(()=>{});return;}
  state.ticket=result.ticket;state.media=result.media;c.metadataVerified=true;step('file','done');
  log('FILE_AND_TRACKS_VERIFIED',{file:result.file,media:result.media,torrent:result.status});
  const russian=result.media.audio.filter(a=>a.russian);
  if(!russian.length)throw new Error('RUSSIAN_AUDIO_NOT_VERIFIED');
  $('audio').replaceChildren(...result.media.audio.map(a=>option(a.index,`${a.russian?'RU · ':a.language+' · '}${a.title} / ${a.codec} ${a.channels||''}`)));$('audio').value=russian[0].index;
  $('quality').replaceChildren(...result.media.qualities.map(h=>option(h,`${h}p · H.264`)));$('quality').value=result.media.qualities.includes(720)?720:Math.max(...result.media.qualities);
  step('audio','done');$('play-options').hidden=false;state.trying=false;renderCandidates();
  state.statusTimer=setInterval(async()=>{if(generation!==state.generation||!state.ticket)return;try{const s=await request('/api/status',{method:'POST',body:{ticket:state.ticket},timeout:8000});if(generation!==state.generation)return;$('stats').textContent=`${s.peers??'?'} пиров · ${s.receivedBytes===null?'байты неизвестны':(s.receivedBytes/1048576).toFixed(1)+' МиБ получено'} · TCP/UDP`; }catch{}},6000);
  await playAt(0,generation);
 }catch(e){if(generation!==state.generation)return;if(e.diagnostics)log('TORRENT_FAILURE_DIAGNOSTICS',e.diagnostics);await failCandidate(safeError(e),generation);}
}
async function failCandidate(error,generation){
 if(generation!==state.generation||state.failing)return;state.failing=true;
 const c=state.active;c.state='failed';c.error=error;state.lastFailure=explanations[error]||error;log('SOURCE_FAILED',{hash:c.hash,error,explanation:state.lastFailure});$('play-options').hidden=true;
 clearInterval(state.statusTimer);clearTimeout(state.stallTimer);state.hls?.destroy();state.hls=null;video.pause();video.removeAttribute('src');video.load();
 if(state.ticket){const ticket=state.ticket;state.ticket=null;await request('/api/close',{method:'POST',body:{ticket},timeout:6000}).catch(()=>{});}
 state.failing=false;if(generation!==state.generation)return;state.trying=true;renderCandidates();status('Источник отказал. Проверяем следующую раздачу…');await nextCandidate(generation);
}
async function playAt(position=video.currentTime||0,generation=state.generation){
 const result=await request('/api/play',{method:'POST',body:{ticket:state.ticket,audio:Number($('audio').value),height:Number($('quality').value)},signal:state.controller.signal});if(generation!==state.generation)return;
 state.hls?.destroy();state.hls=null;video.pause();video.removeAttribute('src');video.load();step('video','busy');video.style.display='block';$('empty-player').hidden=true;
 const src=api(result.path);log('VIDEO_LOAD',{audio:Number($('audio').value),height:Number($('quality').value),position});
 const begin=async()=>{if(generation!==state.generation)return;if(position>0)video.currentTime=Math.min(position,result.duration-1);try{await video.play();$('resume').hidden=true;}catch(e){if(e.name==='NotAllowedError'){$('resume').hidden=false;status('Видео подготовлено. Нажмите «Продолжить воспроизведение» — Safari требует нажатия.');log('USER_GESTURE_REQUIRED');}else throw e;}};
 if(Hls.isSupported()){
  const hls=new Hls({maxBufferLength:18,maxMaxBufferLength:30,backBufferLength:0,startPosition:position,fragLoadingTimeOut:140000,manifestLoadingTimeOut:30000,fragLoadingMaxRetry:1,enableWorker:true});state.hls=hls;
  hls.on(Hls.Events.ERROR,(_,data)=>{if(generation!==state.generation||state.hls!==hls)return;if(data.fatal){state.hls=null;hls.destroy();failCandidate('HLS_'+data.details,generation).catch(console.error)}});
  hls.on(Hls.Events.FRAG_LOADED,(_,d)=>{if(generation!==state.generation||state.hls!==hls)return;log('VIDEO_SEGMENT_BYTES',{bytes:d.frag.stats?.total||d.payload?.byteLength||null,segment:d.frag.sn})});
  hls.loadSource(src);hls.attachMedia(video);hls.on(Hls.Events.MANIFEST_PARSED,()=>begin().catch(e=>failCandidate(safeError(e),generation)));
 }else if(video.canPlayType('application/vnd.apple.mpegurl')){video.src=src;video.addEventListener('loadedmetadata',()=>begin().catch(e=>failCandidate(safeError(e),generation)),{once:true});}
 else throw new Error('HLS_NOT_SUPPORTED');
}
$('audio').onchange=$('quality').onchange=()=>{const p=video.currentTime||0;log('USER_TRACK_OR_QUALITY',{position:p});playAt(p).catch(e=>failCandidate(safeError(e),state.generation))};
$('resume').onclick=()=>video.play().then(()=>{$('resume').hidden=true}).catch(e=>log('PLAY_FAILED',{error:safeError(e)}));
for(const name of ['playing','pause','seeking','seeked','ended','error','waiting','stalled','loadedmetadata'])video.addEventListener(name,event=>{
 if(!state.running||!state.ticket)return;
 const detail={time:Number(video.currentTime.toFixed(3)),duration:Number.isFinite(video.duration)?Number(video.duration.toFixed(3)):null,width:video.videoWidth,height:video.videoHeight,trusted:event.isTrusted};
 if(name==='error')detail.error=video.error?.code;
 log('VIDEO_'+name.toUpperCase(),detail);
 if(name==='playing'){state.played=true;state.lastProgress=performance.now();clearTimeout(state.stallTimer);step('video','done');status(`Воспроизводится: ${state.work.ru}${state.work.type==='series'?' · S'+state.season+'E'+state.episode:''}. ${$('audio').selectedOptions[0]?.textContent||''}`);}
 if(['waiting','stalled'].includes(name)&&!video.paused){clearTimeout(state.stallTimer);const gen=state.generation;state.stallTimer=setTimeout(()=>{if(gen===state.generation&&state.running&&!video.paused)failCandidate('PLAYBACK_STALL_90S',gen)},90000)}
 if(name==='ended'){clearTimeout(state.stallTimer);log('FULL_FILE_ENDED_EVENT',{...selection(),duration:video.duration});}
});
video.addEventListener('timeupdate',()=>{if(!state.running||!state.ticket)return;state.lastProgress=performance.now();clearTimeout(state.stallTimer);const k=`test-video.position.${state.work.key}.${state.season}.${state.episode}`;try{localStorage.setItem(k,JSON.stringify({time:video.currentTime,duration:video.duration,hash:state.active.hash,at:new Date().toISOString()}))}catch{}});
$('export').onclick=()=>{const report={schemaVersion:1,build:__BUILD_SHA__,exportedAt:new Date().toISOString(),platform:{userAgent:navigator.userAgent,standalone:matchMedia('(display-mode: standalone)').matches},selection:selection(),checks:{physicalIPhone:'NOT_RUN_BY_DEVELOPER',pwa:'NOT_RUN_BY_DEVELOPER'},events:state.log};const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='test-video-'+new Date().toISOString().replaceAll(':','-')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
$('executor-url').value=executorBase;
$('executor-save').onclick=async()=>{const value=$('executor-url').value.trim().replace(/\/$/,'');try{if(value){const u=new URL(value);if(u.protocol!=='https:'||u.username||u.password||u.search||u.hash||u.pathname!=='/')throw new Error('Нужен HTTPS-адрес корня сервера без пароля и параметров.')}await stop();executorBase=value;localStorage.setItem('test-video.executor.v1',value);$('health').replaceChildren();await init();}catch(e){status(safeError(e))}};
async function init(){
 const initialGeneration=state.generation;
 $('build').textContent=__BUILD_SHA__.slice(0,8);try{state.log=JSON.parse(localStorage.getItem('test-video.log.v1')||'[]').slice(-200)}catch{}
 try{const h=await request('/api/health',{timeout:12000});state.dataMode=h.control?'CONTROL_SYNTHETIC_SEARCH_REAL_TCP_MEDIA':'live';state.ready=!!h.ffmpeg&&!!h.ffprobe&&h.engineReady!==false;$('connection').textContent=h.control?'Контрольный исполнитель':state.ready?'Исполнитель доступен':'Движок недоступен';$('connection').className='badge '+(state.ready?'ok':'warn');$('overall').textContent=state.ready?'Торрент-исполнитель запущен':'Исполнитель не готов';$('environment').textContent=state.ready?'Библиотеки готовы. Получение байтов и просмотр проверяются отдельно для каждой раздачи.':'Нужна работающая серверная среда с libtorrent и FFmpeg.';for(const text of [h.control?'CONTROL · своё видео / синтетическая выдача':'LIVE · настоящие поставщики',h.transport,h.transcoder,'Кэш: '+(h.cacheBytes/1048576).toFixed(0)+' МиБ',h.serverless?'Vercel Function · cold start возможен':'Серверный процесс']){const span=document.createElement('span');span.textContent=text;$('health').append(span)}log('EXECUTOR_RUNTIME',h);}
 catch(e){$('connection').textContent='Исполнитель недоступен';$('connection').className='badge warn';$('overall').textContent='Видео пока заблокировано';$('environment').textContent='Поиск можно проверить. Сервер получения торрентов не ответил: причина в диагностике.';log('EXECUTOR_UNAVAILABLE',{error:safeError(e)});}
 try{const v=await jsonRequest('./verification.json',{timeout:5000});$('last-verification').textContent=`Последняя приёмка: ${v.commercialTitlesWithVerifiedPlayback}/${v.requiredTitles} произведений с подтверждённым воспроизведением. Поиск: ${v.liveSearchResponsesWithCandidates}/${v.liveSearchRequests}. Дата: ${v.at.slice(0,16).replace('T',' ')} UTC. Контрольный ролик учтён отдельно.`;if(!v.selectionPlaybackAccepted&&state.ready){$('overall').textContent='Просмотр подборки не подтверждён';$('environment').textContent='Библиотеки сервера запущены. В последнем прогоне обязательной подборки в Vercel видеобайты от пиров не получены. Контрольные ролики учитываются отдельно.'}}catch{}
 if(state.generation===initialGeneration)await selectWork(state.work);
 if('serviceWorker'in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>{});
}
init();
