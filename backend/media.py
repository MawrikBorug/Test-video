import asyncio, json, math, os, pathlib, shutil
from .selection import Refusal, audio_label

ROOT=pathlib.Path(__file__).resolve().parents[1]
FFMPEG=os.environ.get('FFMPEG_BIN') or shutil.which('ffmpeg') or str(ROOT/'node_modules/ffmpeg-static/ffmpeg')
FFPROBE=os.environ.get('FFPROBE_BIN') or shutil.which('ffprobe') or str(ROOT/'node_modules/ffprobe-static/bin/linux/x64/ffprobe')
SEGMENT=6

async def command(args, timeout=100):
    p=await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:out,err=await asyncio.wait_for(p.communicate(),timeout)
    except (TimeoutError,asyncio.CancelledError):
        p.kill();await p.communicate();raise Refusal('MEDIA_PROCESS_TIMEOUT')
    if p.returncode:raise Refusal('MEDIA_PROCESS_FAILED',err.decode(errors='replace')[-700:])
    return out

async def inspect(torrent):
    try:
        raw=await command([FFPROBE,'-v','error','-rw_timeout','65000000','-probesize','4000000',
            '-analyzeduration','5000000','-show_streams','-show_format','-of','json',torrent.raw_url],100)
    except Refusal:
        if getattr(torrent,'last_read_error',None):raise Refusal(torrent.last_read_error)
        raise
    try:j=json.loads(raw)
    except:raise Refusal('PROBE_INVALID_JSON')
    videos=[s for s in j.get('streams',[]) if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic')]
    audios=[audio_label(s) for s in j.get('streams',[]) if s.get('codec_type')=='audio']
    if not videos or not audios:raise Refusal('MISSING_VIDEO_OR_AUDIO')
    v=videos[0]
    duration=float(j.get('format',{}).get('duration') or v.get('duration') or 0)
    if not 60<duration<30000:raise Refusal('INVALID_FULL_LENGTH_DURATION')
    heights=[h for h in [480,720,1080] if h<=v.get('height',0)+16]
    if not heights:heights=[min(v.get('height',360),480)]
    torrent.media={'duration':duration,'video':{'index':v['index'],'codec':v.get('codec_name'),
        'width':v.get('width'),'height':v.get('height')},'audio':audios,'qualities':heights,'tracksInspected':True}
    return torrent.media

def manifest(ticket,duration):
    rows=['#EXTM3U','#EXT-X-VERSION:3','#EXT-X-TARGETDURATION:6','#EXT-X-MEDIA-SEQUENCE:0','#EXT-X-PLAYLIST-TYPE:VOD']
    for i in range(math.ceil(duration/SEGMENT)):
        if i:rows.append('#EXT-X-DISCONTINUITY')
        rows.extend([f'#EXTINF:{min(SEGMENT,duration-i*SEGMENT):.6f},',f'{i}.ts'])
    return '\n'.join(rows+['#EXT-X-ENDLIST',''])

async def segment(torrent, index, audio, height, duration):
    if not 0<=index<math.ceil(duration/SEGMENT):raise Refusal('SEGMENT_OUT_OF_RANGE')
    key=(index,audio,height)
    if key in torrent.segments:return torrent.segments[key]
    if key in torrent.tasks:return await torrent.tasks[key]
    async def generate():
        out=await command([FFMPEG,'-nostdin','-hide_banner','-v','error','-threads','2',
            '-rw_timeout','65000000','-ss',str(index*SEGMENT),'-i',torrent.raw_url,
            '-t',str(min(SEGMENT,duration-index*SEGMENT)),
            '-map',f'0:{torrent.media["video"]["index"]}','-map',f'0:{audio}',
            '-vf',f'scale=-2:{height}', '-c:v','libx264','-preset','ultrafast','-crf','23',
            '-maxrate','3500k','-bufsize','7000k','-pix_fmt','yuv420p','-g','48',
            '-c:a','aac','-b:a','160k','-ac','2','-sn','-dn','-f','mpegts','pipe:1'],110)
        if len(out)<188:raise Refusal('EMPTY_MEDIA_SEGMENT')
        torrent.segments[key]=out
        while len(torrent.segments)>4:torrent.segments.pop(next(iter(torrent.segments)))
        return out
    task=asyncio.create_task(generate());torrent.tasks[key]=task
    try:return await task
    finally:torrent.tasks.pop(key,None)
