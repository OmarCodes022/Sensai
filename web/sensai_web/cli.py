"""`sensai-web`: serve the page and its API on this machine."""
import sys
from collections.abc import Sequence

from sensai.cli.remote import RemoteError, RemoteSignal, check_remote, ssh_tunnel
from sensai.settings import Settings
from sensai_web.app import StartupError, WebApp
from sensai_web.config import parser, resolve
from sensai_web.server import WebServer


def build(argv: Sequence[str] | None = None, settings: Settings | None = None) -> WebServer:
    """Parse the options and return a server that has not started serving yet."""
    settings = settings or Settings()
    p = parser(settings)
    args = p.parse_args(argv)
    if not (args.model or settings.model):
        p.error("no model given: pass one or set SENSAI_MODEL in .env")
    cfg = resolve(args, settings)
    try:
        if cfg.ssh_host:
            check_remote(cfg.ssh_host, cfg.host)
        return WebServer(WebApp(cfg, settings))
    except (StartupError, RemoteError, ValueError, OSError) as exc:
        sys.exit(f"error: {exc}")


def serve(server: WebServer) -> None:
    cfg = server.app.cfg
    host = "[::1]" if cfg.bind == "::1" else cfg.bind
    where = f", remote Ollama via {cfg.ssh_host}" if cfg.ssh_host else ""
    print(f"Sensai is running at http://{host}:{server.server_address[1]}/  "
          f"(model {cfg.model}{where}, Ctrl+C to stop)")
    if server.app.mcp.untrusted:
        print("MCP config not trusted yet, so nothing from it has run: review it in the Tools view.")
    server.serve_forever()


def main(argv: Sequence[str] | None = None) -> int:
    server = build(argv)
    ssh_host = server.app.cfg.ssh_host
    try:
        if ssh_host:
            with ssh_tunnel(ssh_host):  # Closed again whatever ends the server.
                serve(server)
        else:
            serve(server)
        return 0
    except RemoteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except RemoteSignal as exc:
        return 128 + exc.signum
    except KeyboardInterrupt:
        print()
        return 130
    finally:
        server.shutdown_all()


if __name__ == "__main__":
    sys.exit(main())
