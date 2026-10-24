"""Pure selection rules. Never use a season-pack's largest file as an episode."""
import re

class Refusal(Exception):
    def __init__(self, code, detail=""):
        self.code, self.detail = code, detail
        super().__init__(code + (': '+detail if detail else ''))

def video_files(files):
    return [f for f in files if re.search(r'\.(mkv|mp4|m4v|avi|ts|webm)$', f['path'], re.I)
            and not re.search(r'(^|[/_. -])(sample|trailer|extra|bonus|ncop|nced)([/_. -]|$)', f['path'], re.I)]

def choose_file(files, season=None, episode=None, claimed=None):
    videos = video_files(files)
    if not videos:
        raise Refusal('NO_VIDEO_FILES')
    if season is None:
        if len(videos) != 1:
            raise Refusal('AMBIGUOUS_MOVIE_COLLECTION')
        return videos[0]
    exact = []
    for f in videos:
        name=f['path']
        pairs=re.findall(r'(?i)S(\d{1,2})[ ._-]*E(\d{1,3})|(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)', name)
        if any((int(a or c), int(b or d)) == (season, episode) for a,b,c,d in pairs):
            exact.append(f)
    if len(exact)==1:
        return exact[0]
    # Explicit season folder + episode filename is acceptable. Mere ordinal in
    # arbitrary collection or "claimed fileIdx" without filename evidence is not.
    if not exact:
        for f in videos:
            path=f['path'];name=path.rsplit('/',1)[-1]
            sm=re.search(r'(?i)(?:season[ ._-]*|S)(\d{1,2})(?!\d)|(?:сезон[ ._-]*)(\d{1,2})(?!\d)', path)
            if sm and int(sm[1] or sm[2])==season:
                em=re.search(r'(?i)(?:^|[ ._-])(?:E|EP|Episode[ ._-]*)?(\d{1,3})(?:[ ._-]|\.(?:mkv|mp4)$)', name)
                if em and int(em[1])==episode:exact.append(f)
    if len(exact)!=1:
        raise Refusal('EPISODE_UNRESOLVED' if not exact else 'EPISODE_AMBIGUOUS')
    return exact[0]

def audio_label(stream):
    tags=stream.get('tags', {})
    return {'index': stream['index'], 'language':tags.get('language','und'),
            'title':tags.get('title') or tags.get('handler_name') or 'Без названия',
            'codec':stream.get('codec_name','unknown'),'channels':stream.get('channels'),
            'russian': bool(re.search(r'(?i)^(rus|ru)$',tags.get('language','')) or re.search(r'(?i)рус|russian',tags.get('title','')))}

def byte_range(value, size):
    if not value:return 0,size-1,False
    m=re.fullmatch(r'bytes=(\d*)-(\d*)',value)
    if not m or not any(m.groups()):raise Refusal('INVALID_RANGE')
    a,b=m.groups()
    if not a:
        start=max(0,size-int(b));end=size-1
    else:
        start=int(a);end=min(size-1,int(b)) if b else size-1
    if start>=size or end<start:raise Refusal('INVALID_RANGE')
    return start,end,True
