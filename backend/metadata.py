"""Public HTTPS metadata caches. Hash-checked, bounded; no video proxy/debrid."""
import asyncio
import httpx
import libtorrent as lt
from .engine import known_metadata

async def resolve(info_hash):
    body=known_metadata(info_hash)
    if body:return body,{'source':'developer-metadata-snapshot','snapshotDate':'2026-10-23/24','hashChecked':True,'freshNetworkResponse':False}
    urls=[('itorrents','https://itorrents.org/torrent/'+info_hash.upper()+'.torrent'),
          ('torrage','https://torrage.info/torrent.php?h='+info_hash.upper()),
          ('btcache','https://btcache.me/torrent/'+info_hash.upper()+'.torrent')]
    attempts=[]
    async with httpx.AsyncClient(timeout=6,follow_redirects=False,trust_env=True) as client:
        for name,url in urls:
            try:
                async with client.stream('GET',url) as r:
                    if r.status_code!=200:
                        attempts.append({'host':name,'http':r.status_code});continue
                    data=bytearray()
                    async for chunk in r.aiter_bytes():
                        data.extend(chunk)
                        if len(data)>4*1024**2:raise ValueError('TOO_LARGE')
                ti=lt.torrent_info(bytes(data))
                if str(ti.info_hashes().v1)!=info_hash:raise ValueError('HASH_MISMATCH')
                return bytes(data),{'source':name,'hashChecked':True,'freshNetworkResponse':True,'attempts':attempts}
            except httpx.RequestError:attempts.append({'host':name,'error':'NETWORK_OR_TIMEOUT'})
            except (ValueError,RuntimeError):attempts.append({'host':name,'error':'INVALID_OR_WRONG_HASH_TORRENT'})
    return None,{'source':'BEP9-required','httpsAttempts':attempts}
