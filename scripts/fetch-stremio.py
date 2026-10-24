"""Fetch a pinned official EngineFS bundle; never download media or credentials."""
import hashlib, pathlib, urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
URL='https://dl.strem.io/server/v4.20.17/desktop/server.js'
SHA256='567a397bb11b788571bf1750fd05dd78927f97bec0c9ddeaa6d9cc1eccee3922'

def main():
    # The frontend package uses type=module; EngineFS is a CommonJS bundle.
    target=ROOT/'.runtime/bin/stremio-server.cjs'
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==SHA256:
        print('Stremio EngineFS 4.20.17: cached checksum verified');return
    with urllib.request.urlopen(URL,timeout=60) as response:body=response.read(12*1024**2)
    if hashlib.sha256(body).hexdigest()!=SHA256:raise RuntimeError('STREMIO_BUNDLE_CHECKSUM_MISMATCH')
    pending=target.with_suffix('.download');pending.write_bytes(body);pending.replace(target)
    print('Stremio EngineFS 4.20.17: official download checksum verified')

if __name__=='__main__':main()
