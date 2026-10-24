"""A separate, standard HTTPS announce path when native trackers fail.
No peer addresses enter logs. No proxy tunnelling or access-policy workaround.
"""
import asyncio, secrets, socket, struct
from urllib.parse import quote_from_bytes
import httpx,libtorrent as lt

async def discover(torrent):
    reports=[]
    peer_id=b'-TV0001-'+secrets.token_bytes(12)
    query='info_hash='+quote_from_bytes(bytes.fromhex(torrent.hash),safe='')+'&peer_id='+quote_from_bytes(peer_id,safe='')
    query+='&port='+str(torrent.session.listen_port())+'&uploaded=0&downloaded=0&left=16384&compact=1&numwant=30&event=started'
    async with httpx.AsyncClient(timeout=7,follow_redirects=False,trust_env=True) as client:
        async def one(host):
            try:
                r=await client.get('https://'+host+'/announce?'+query)
                result={'host':host,'http':r.status_code,'peersReported':None}
                if r.status_code==200 and len(r.content)<256*1024:
                    try:j=lt.bdecode(r.content)
                    except RuntimeError:return {**result,'error':'NON_BENCODE'}
                    peers=j.get(b'peers') if isinstance(j,dict) else None
                    if isinstance(peers,bytes) and len(peers)%6==0:
                        result['peersReported']=len(peers)//6
                        for i in range(0,len(peers),6):
                            ip=socket.inet_ntoa(peers[i:i+4]);port=struct.unpack('!H',peers[i+4:i+6])[0]
                            import ipaddress
                            if ipaddress.ip_address(ip).is_global and port:torrent.handle.connect_peer((ip,port))
                    else:result['error']='NO_COMPACT_PEER_LIST'
                return result
            except httpx.RequestError:return {'host':host,'error':'HTTP_NETWORK_OR_TIMEOUT','peersReported':None}
        reports=await asyncio.gather(one('tracker.tamersunion.org'),one('tracker.gbitt.info'))
    torrent.https_discovery=reports
    return reports
