"""Local sign-in window: the password goes from the browser to this process only."""
import hmac
import html
import os
import secrets
import shutil
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from .auth import AuthError, create_auth_session, save_auth_session

MAX_BODY_BYTES = 8192
MAX_ATTEMPTS = 5
APP_BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser", "microsoft-edge")
MAC_APP_BROWSERS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"

STYLE = """
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;
background:#eef2ef;color:#1b2a22;font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{width:100%;max-width:360px;background:#fff;border-radius:14px;padding:28px;box-shadow:0 8px 30px #1b2a2222}
h1{font-size:20px;margin:0;text-align:center}h1 span{color:#2f7d4f}
p{margin:8px 0 0;text-align:center;color:#56655c;font-size:13px}label{display:block;margin-top:16px;font-size:13px;font-weight:600}
input{width:100%;margin-top:5px;padding:10px 12px;border:1px solid #c9d3cc;border-radius:8px;font:inherit}
input:focus{outline:2px solid #2f7d4f;outline-offset:1px}
button{width:100%;margin-top:18px;padding:11px;border:0;border-radius:8px;background:#1f3a2d;color:#fff;font:inherit;font-weight:600;cursor:pointer}
button.quiet{margin-top:6px;background:none;color:#56655c;font-weight:400}.error{color:#a32626;font-weight:600}
"""


def _document(body):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Sign in to deadtrees.earth</title><style>{STYLE}</style></head>"
            f"<body><main><h1>dead<span>trees</span>.earth</h1>{body}</main></body></html>").encode()


def _form(error="", email=""):
    message = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    return _document(f"""<p>Your AI assistant never sees your password.</p>{message}
<form method="post"><label>Email<input name="email" type="email" autocomplete="username" required autofocus value="{html.escape(email, quote=True)}"></label>
<label>Password<input name="password" type="password" autocomplete="current-password" required></label>
<button name="action" value="sign_in">Sign in</button>
<button class="quiet" name="action" value="cancel" formnovalidate>Cancel</button></form>""")


def _notice(text):
    return _document(f"<p>{html.escape(text)}</p>")


class _LoginServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, token, api_url, supabase_url, supabase_key):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.token = token
        self.api_url = api_url
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.attempts = 0
        self.result = None
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.origin_host = f"127.0.0.1:{self.server_address[1]}"

    @property
    def url(self):
        return f"http://{self.origin_host}/{self.token}"


class _Handler(BaseHTTPRequestHandler):
    timeout = 20
    server_version = "deadtrees-upload"
    sys_version = ""

    def log_message(self, format, *args):
        pass

    def _send(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cache-Control", "no-store")
        # no-referrer would make browsers send "Origin: null" and fail the origin check.
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _allowed(self):
        if self.headers.get("Host") != self.server.origin_host:
            return False
        return hmac.compare_digest(self.path.encode(), f"/{self.server.token}".encode())

    def do_GET(self):
        if not self._allowed():
            return self._send(404, _notice("Not found."))
        if self.server.result:
            return self._send(410, _notice("This sign-in window has closed."))
        self._send(200, _form())

    def do_POST(self):
        origin_ok = self.headers.get("Origin") == f"http://{self.server.origin_host}"
        form_ok = self.headers.get("Content-Type", "").split(";")[0].strip() == "application/x-www-form-urlencoded"
        if not (self._allowed() and origin_ok and form_ok):
            return self._send(403, _notice("Request refused."))
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._send(411, _notice("Request refused."))
        if not 0 < length <= MAX_BODY_BYTES:
            return self._send(413, _notice("Request refused."))
        fields = parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True)
        email = fields.get("email", [""])[0].strip()
        password = fields.get("password", [""])[0]
        with self.server.lock:
            if self.server.result:
                return self._send(410, _notice("This sign-in window has closed."))
            if fields.get("action", [""])[0] == "cancel":
                return self._finish("cancelled", "Sign-in cancelled. You can close this window.")
            if not email or not password:
                return self._send(400, _form("Enter your email and password.", email))
            self.server.attempts += 1
            try:
                session = create_auth_session(email, password, self.server.supabase_url, self.server.supabase_key)
            except AuthError:
                if self.server.attempts >= MAX_ATTEMPTS:
                    return self._finish("too_many_attempts", "Too many attempts. Ask your assistant to start sign-in again.")
                return self._send(401, _form("That didn't work. Check your email and password.", email))
            try:
                save_auth_session(session, self.server.api_url)
            except OSError:
                return self._finish("save_failed", "Signed in, but the session could not be saved on this computer.")
            self._finish("signed_in", "You're signed in. You can close this window and return to your assistant.")

    def _finish(self, result, message):
        self.server.result = result
        try:
            self._send(200, _notice(message))
        finally:
            self.server.finished.set()


def has_display():
    if sys.platform.startswith("linux"):
        return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
    return True


def open_login_window(url):
    """Open a compact app window when a Chromium browser exists, else a browser window."""
    if not has_display():
        return False
    candidates = [path for path in MAC_APP_BROWSERS if os.path.exists(path)] if sys.platform == "darwin" else []
    candidates += [path for path in map(shutil.which, APP_BROWSERS) if path]
    for browser in candidates:
        try:
            subprocess.Popen([browser, f"--app={url}", "--window-size=460,620"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except OSError:
            continue
    try:
        return bool(webbrowser.open(url, new=1))
    except webbrowser.Error:
        return False


def run_browser_login(api_url, supabase_url, supabase_key, timeout=300, opener=open_login_window, on_link=None):
    """Serve one sign-in on loopback and return its outcome; never returns credentials."""
    server = _LoginServer(secrets.token_urlsafe(32), api_url, supabase_url, supabase_key)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        if not opener(server.url):
            if on_link is None:
                return "browser_unavailable"
            on_link(server.url)
        server.finished.wait(timeout)
        with server.lock:
            if not server.result:
                server.result = "timed_out"
            return server.result
    finally:
        server.shutdown()
        server.server_close()
