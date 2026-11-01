"""X3 public link: one campaign section as a read-only page anyone on the local network can open.

    python -m sensai.share            # serves shares/ on port 8766; only /s/<token> answers

A share is a snapshot: checked by the guardrails, shown with its URL, written only after the creator
says yes, never changed by later edits. DM replies are never shared (they come from customer messages).
"""
import html
import os
import re
import secrets
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sensai.campaign.models import Campaign

SHAREABLE = ("posts", "report", "calendar")
DEFAULT_DIR = "shares"
DEFAULT_PORT = 8766  # sensai-web uses 8765
TOKEN = re.compile(r"[A-Za-z0-9_-]{22}\Z")  # secrets.token_urlsafe(16)


class ShareError(ValueError):
    """The section cannot be shared; nothing was created."""


def section_text(doc: Campaign, section: str) -> str:
    """The plain text of one section: what the page shows, and what the creator approves."""
    if section == "replies":
        raise ShareError("DM replies are never shared: they come from customer messages.")
    if section not in SHAREABLE:
        raise ShareError(f"unknown section {section!r}: share posts, report or calendar")
    s, head = doc.sections, f"Serein Studio · week {doc.week} ({doc.start} to {doc.end})"
    if section == "posts":
        lines = [f"{p.id} · {p.channel}: {p.caption}" for p in s.posts.items]
    elif section == "calendar":
        lines = [f"{e.date} {e.time} · {e.channel} · {e.post_id} {e.theme}"
                 for e in sorted(s.calendar.items, key=lambda e: (e.date, e.time))]
    else:
        r = s.report.item
        lines = [] if r is None else [f"Period: {r.period_start} to {r.period_end} ({r.timezone})", f"Source: {r.source}",
                                      f"Accounts reached: {r.accounts_reached}", f"Accounts engaged: {r.accounts_engaged}",
                                      f"Engagement rate: {r.engagement_rate}", *([r.interpretation] if r.interpretation else [])]
    if not lines:
        raise ShareError(f"the {section} section is empty: nothing to share")
    return "\n".join([f"{head} · {section}", *lines])


def page(text: str) -> str:
    """A standalone page: every character escaped, no script, no link to anything else."""
    title, *lines = text.split("\n")
    items = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>'
            '<style>body{font-family:system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem;line-height:1.5}'
            'li{margin:.5rem 0}footer{color:#666;font-size:.85rem}</style></head>'
            f'<body><h1>{html.escape(title)}</h1><ul>{items}</ul>'
            '<footer>Shared from Sensai: a read-only snapshot.</footer></body></html>\n')


def _rank(address: str) -> int:
    """Home and office networks first: a VPN tunnel (often 10.x or 100.x) is not where a phone is."""
    a, b = (int(part) for part in address.split(".")[:2])
    return 0 if (a, b) == (192, 168) else 1 if a == 172 and 16 <= b <= 31 else 2 if a == 10 else 3


def lan_host(addresses=None) -> str:
    """This computer's address on the local network, else localhost (SENSAI_SHARE_HOST overrides it)."""
    if addresses is None:
        addresses = set()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:  # A UDP connect sends nothing.
                s.connect(("10.255.255.255", 1))
                addresses.add(s.getsockname()[0])
        except OSError:
            pass
        try:
            addresses |= {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
        except OSError:
            pass
    usable = [a for a in addresses if not a.startswith(("127.", "169.254."))]
    return min(usable, key=lambda a: (_rank(a), a)) if usable else "127.0.0.1"


class Shares:
    def __init__(self, folder: str = DEFAULT_DIR, host: str | None = None, port: int = DEFAULT_PORT):
        self.folder, self.host, self.port = folder, host, port

    def url(self, token: str) -> str:
        return f"http://{self.host or lan_host()}:{self.port}/s/{token}"

    def propose(self, guard, doc: Campaign, section: str) -> tuple[str, str, str]:
        """(token, url, approved text) after the guardrails' check; nothing is written yet."""
        text = section_text(doc, section)
        if guard is not None:
            for line in text.split("\n"):
                decision = guard.inspect(line, "output")
                if not decision.allowed:
                    raise ShareError(f"refused by the guardrails ({decision.reason}): nothing was shared")
                text = text.replace(line, decision.text, 1)
        token = secrets.token_urlsafe(16)
        return token, self.url(token), text

    def publish(self, token: str, text: str) -> str:
        os.makedirs(self.folder, exist_ok=True)
        path = os.path.join(self.folder, f"{token}.html")
        with open(path, "x", encoding="utf-8") as f:  # A token is never reused.
            f.write(page(text))
        return path

    def remove(self, token: str) -> bool:
        if not TOKEN.match(token or ""):
            return False
        try:
            os.remove(os.path.join(self.folder, f"{token}.html"))
        except FileNotFoundError:
            return False
        return True

    def list(self) -> list[str]:
        if not os.path.isdir(self.folder):
            return []
        return sorted(n[:-5] for n in os.listdir(self.folder) if n.endswith(".html") and TOKEN.match(n[:-5]))


def handler(folder: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            match = re.fullmatch(r"/s/([A-Za-z0-9_-]{22})", self.path)
            path = os.path.join(folder, f"{match[1]}.html") if match else None
            if path is None or not os.path.isfile(path):
                self.send_error(404)
                return
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            for name, value in (("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))),
                                ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'"),
                                ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer")):
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # The requests are not logged.
            pass
    return Handler


def main(argv: list[str] | None = None) -> int:
    from sensai.settings import Settings
    settings = Settings()
    try:
        server = ThreadingHTTPServer(("0.0.0.0", settings.share_port), handler(settings.shares_dir))
    except OSError as exc:
        print(f"error: cannot listen on port {settings.share_port} ({exc.strerror}); set SENSAI_SHARE_PORT to a free port")
        return 1
    print(f"Sharing {settings.shares_dir}/ at http://{lan_host()}:{settings.share_port}/s/<token> on the local network. "
          "Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShare server stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
