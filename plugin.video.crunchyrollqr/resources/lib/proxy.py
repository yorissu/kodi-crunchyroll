"""Local HTTP proxy for manifests on www.crunchyroll.com.

That host sits behind Cloudflare and needs the bearer token; inputstream.adaptive's own HTTP
client gets challenged, Python's urllib does not. Runs in the plugin process during playback.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

UPSTREAM = "https://www.crunchyroll.com"


def start(api):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            req = Request(UPSTREAM + self.path, headers={
                "User-Agent": api.ua, "Authorization": "Bearer " + api.access_token()})
            try:
                with urlopen(req, timeout=20) as r:
                    status, body, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
            except HTTPError as e:
                status, body, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
            except OSError:
                status, body, ctype = 502, b"", ""
            self.send_response(status)
            if ctype:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def proxied(server, url):
    if not url.startswith(UPSTREAM):
        return url
    return "http://127.0.0.1:{}{}".format(server.server_address[1], url[len(UPSTREAM):])
