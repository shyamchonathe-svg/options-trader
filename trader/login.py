"""Daily Kite login: one tap on a Telegram link, the token is caught by a tiny local web receiver.

  Telegram prompt (login link carrying a one-time `state`)  ->  you log in at Zerodha (2FA)
  -> Zerodha redirects the browser to https://<your-domain>/redirect?request_token=..&state=..
  -> Caddy (HTTPS, only /redirect is forwarded) -> LoginServer on 127.0.0.1 -> LoginManager -> KiteProvider.login()

Checks on every request: status=success, a request_token, a `state` that WE issued, unused and < 15 min old, and
(in the provider) that the Zerodha user id is ours. Anything else is refused and reported on Telegram.
The web thread never touches the database: it queues the request and the main loop (daemon step) handles it.
Python 3.6 compatible, stdlib only."""
import binascii
import datetime
import http.server
import os
import queue
import threading
import time

STATE_TTL_S = 15 * 60
MAX_PER_MINUTE = 20
WAIT_S = 25

PAGE = ("<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head>"
        "<body style='font-family:sans-serif;margin:2em'><h2>%s</h2><p>%s</p></body></html>")


class LoginManager(object):
    def __init__(self, store, provider, notify, clock):
        self.store, self.provider, self.notify, self.clock = store, provider, notify, clock
        self.q = queue.Queue()
        self._hits = []

    # ------------------------------------------------------------------ small helpers
    def _say(self, text):
        try:
            self.notify("info", {"text": text})
        except Exception:
            pass

    def _day(self):
        return self.clock().strftime("%Y-%m-%d")

    def login_at(self, day=None):
        """'HH:MM:SS' of the first successful login of the day, or None."""
        return self.store.kv_get("d:%s:login_at" % (day or self._day()))

    def _record(self):
        k = "d:%s:login_at" % self._day()
        if not self.store.kv_get(k):
            self.store.kv_set(k, self.clock().strftime("%H:%M:%S"))
        self.store.event("INFO", "login", "token saved")

    def logged_in_today(self):
        if self.login_at():
            return True
        try:
            if self.provider.token_ok():
                self._record()          # token saved before this build existed: first seen now
                return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------ links
    def link(self):
        """A fresh login URL; its `state` is valid once for 15 minutes."""
        nonce = binascii.hexlify(os.urandom(12)).decode()
        self.store.kv_set("login:state:" + nonce, str(int(time.time()) + STATE_TTL_S))
        return self.provider.login_url(nonce)

    def _consume(self, nonce):
        k = "login:state:" + nonce
        exp = self.store.kv_get(k)
        if not exp:
            return False
        self.store.kv_set(k, "")                       # single use, win or lose
        try:
            return int(exp) >= time.time()
        except ValueError:
            return False

    # ------------------------------------------------------------------ the two ways in
    def handle(self, params):
        """Process one redirect (main thread). Returns (ok, title, text)."""
        if params.get("status", "success") != "success" or not params.get("request_token"):
            self._say("Login failed at Zerodha (status=%s). Send /login for a new link." % params.get("status", "?"))
            return False, "Login not completed", "Nothing was saved."
        if not self._consume(params.get("state", "")):
            self._say("Login REJECTED: unknown, reused or expired state. If this was not you, ignore it. Send /login for a new link.")
            return False, "Link not valid", "This login link is unknown, already used or expired."
        ok, msg, _ = self.provider.login(params["request_token"])
        if ok:
            self._record()
        self._say(msg)
        return (ok, "Login OK" if ok else "Login failed", "You can close this page." if ok else msg)

    def manual(self, text):
        """/token <request_token or redirect URL> hook (fallback)."""
        msg = self.provider.exchange_token(text)
        if "login OK" in msg or "Kite login OK" in msg:
            self._record()
        return msg

    # ------------------------------------------------------------------ web thread -> main thread
    def submit(self, params):
        """Called from the web thread: queue and wait for the main loop to answer."""
        now = time.time()
        self._hits = [t for t in self._hits if now - t < 60]
        if len(self._hits) >= MAX_PER_MINUTE:
            return False, "Too many requests", "Try again in a minute."
        self._hits.append(now)
        ev, box = threading.Event(), []
        self.q.put((params, ev, box))
        if not ev.wait(WAIT_S):
            return False, "Busy", "The trader did not answer in time; send /login for a new link."
        return box[0]

    def pump(self):
        """Main thread, every step: answer queued web requests."""
        for _ in range(10):
            try:
                params, ev, box = self.q.get_nowait()
            except queue.Empty:
                return
            try:
                box.append(self.handle(params))
            except Exception as e:
                self.store.event("ERROR", "login", "%s" % type(e).__name__)
                box.append((False, "Error", "Login could not be processed."))
            ev.set()


class _Handler(http.server.BaseHTTPRequestHandler):
    manager = None
    server_version = "x"
    sys_version = ""

    def log_message(self, *a):          # never log URLs: they carry the request_token
        pass

    def _send(self, code, title, text):
        body = (PAGE % (title, text)).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path != "/redirect":
            return self._send(404, "Not found", "")
        import urllib.parse
        params = dict((k, v[0]) for k, v in urllib.parse.parse_qs(query).items())
        ok, title, text = self.manager.submit(params)
        self._send(200 if ok else 400, title, text)

    do_POST = do_PUT = do_DELETE = lambda self: self._send(404, "Not found", "")


class LoginServer(object):
    def __init__(self, manager, host="127.0.0.1", port=8001):
        handler = type("H", (_Handler,), {"manager": manager})
        self.httpd = http.server.ThreadingHTTPServer((host, port), handler) \
            if hasattr(http.server, "ThreadingHTTPServer") else _threading_server(host, port, handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="login-web")
        self.thread.daemon = True

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _threading_server(host, port, handler):        # Python 3.6 has no ThreadingHTTPServer
    import socketserver

    class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
    return S((host, port), handler)
