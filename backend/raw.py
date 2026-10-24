"""Private loopback Range bridge from verified torrent pieces to ffmpeg."""
import http.server, threading
from .selection import byte_range, Refusal

def start_raw(torrent):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_HEAD(self):self.serve(False)
        def do_GET(self):self.serve(True)
        def serve(self,body):
            if self.path!=f'/{torrent.id}':self.send_error(404);return
            size=torrent.file['size']
            try:start,end,partial=byte_range(self.headers.get('Range'),size)
            except Refusal:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
            self.send_response(206 if partial else 200)
            self.send_header('Accept-Ranges','bytes');self.send_header('Content-Type','application/octet-stream')
            self.send_header('Content-Length',str(end-start+1))
            if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            if not body:return
            try:
                for block in torrent.read(start,end):self.wfile.write(block)
            except Refusal as e:
                torrent.last_read_error=e.code
                print('TORRENT_RANGE_READ_FAILED',e.code,flush=True)
                self.close_connection=True
            except (BrokenPipeError,ConnectionResetError):self.close_connection=True
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    torrent.raw_server=server
    torrent.raw_url=f'http://127.0.0.1:{server.server_port}/{torrent.id}'
    return torrent.raw_url
