"""Extract packaged executables into the instance's ephemeral filesystem."""
import gzip,os,pathlib,shutil,tempfile,threading

RUNTIME=pathlib.Path(__file__).resolve().parent/'runtime'
DEST=pathlib.Path(tempfile.gettempdir())/'test-video-bin'
_lock=threading.Lock()

def executable(name):
    if name not in ['node','ffprobe']:raise ValueError('Unsupported executable')
    packed=RUNTIME/(name+'.gz')
    if not packed.is_file():return None
    with _lock:
        DEST.mkdir(parents=True,exist_ok=True)
        target=DEST/name
        if not target.is_file():
            fd,temporary=tempfile.mkstemp(prefix=name+'-',dir=DEST)
            try:
                with os.fdopen(fd,'wb') as out,gzip.open(packed,'rb') as source:
                    shutil.copyfileobj(source,out,1024*1024)
                os.chmod(temporary,0o755);os.replace(temporary,target)
            finally:
                if os.path.exists(temporary):os.unlink(temporary)
        return str(target)
