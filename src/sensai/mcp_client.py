"""Small MCP 2025-11-25 stdio client; every exchange runs in tool isolation."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from sensai.core.ports import ToolCall, ToolDefinition, ToolResult
from sensai.tools import ToolRegistry

PROTOCOL = "2025-11-25"
# Older versions use the same initialize, tools/list and tools/call subset.
PROTOCOLS = (PROTOCOL, "2025-06-18", "2025-03-26", "2024-11-05")
TIMEOUT = 30.0
MAX_MESSAGE = 1024 * 1024
MAX_OUTPUT = 10_000  # As for run_python: a result goes to the model and into the saved session.
GUIDE_URL = "https://omarcodes022.github.io/Sensai/user-guide/mcp/"
EXAMPLE_CONFIG = """{
  "mcpServers": {
    "sensai": {"command": "python", "args": ["-m", "sensai.mcp_server"]},
    "time": {"command": "uvx", "args": ["mcp-server-time==2026.10.28"]}
  }
}
"""


@dataclass(frozen=True)
class Server:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


class MCPError(ValueError):
    """A diagnostic written by this client, never raw server data."""


class Connection:
    def __init__(self, server):
        self.process = subprocess.Popen([server.command, *server.args], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        env={**os.environ, **server.env})
        self.id = 0

    def send(self, message):
        self.process.stdin.write((json.dumps(message, allow_nan=False) + "\n").encode())
        self.process.stdin.flush()

    def request(self, method, params):
        self.id += 1
        self.send({"jsonrpc": "2.0", "id": self.id, "method": method, "params": params})
        while True:
            line = self.process.stdout.readline(MAX_MESSAGE + 1)
            if not line or len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
                raise MCPError("MCP server closed or sent an oversized message")
            message = json.loads(line)
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise MCPError("invalid MCP response")
            if "method" in message:
                if "id" in message:
                    self.send({"jsonrpc": "2.0", "id": message["id"], "result": {}} if message["method"] == "ping"
                              else {"jsonrpc": "2.0", "id": message["id"], "error": {
                                  "code": -32601, "message": "Client method not supported"}})
                continue
            if message.get("id") != self.id:
                raise MCPError("MCP response id mismatch")
            if "error" in message:
                raise MCPError("MCP JSON-RPC request failed")
            result = message.get("result")
            if not isinstance(result, dict):
                raise MCPError("invalid MCP result")
            return result

    def initialize(self):
        result = self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                              "clientInfo": {"name": "sensai", "version": "0.1.0"}})
        if result.get("protocolVersion") not in PROTOCOLS:
            raise MCPError("unsupported MCP protocol version (expected " + PROTOCOL + " or older)")
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def close(self):
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self.process.wait(timeout=.2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()


def exchange(server, tool, arguments, cancellation=None):
    connection = None
    try:
        connection = Connection(server)
        connection.initialize()
        if tool is None:
            tools, cursors, cursor = [], set(), None
            while True:
                result = connection.request("tools/list", {"cursor": cursor} if cursor else {})
                page = result.get("tools")
                if not isinstance(page, list):
                    raise MCPError("invalid MCP tools list")
                tools.extend(page)
                cursor = result.get("nextCursor")
                if cursor is None:
                    break
                if not isinstance(cursor, str) or not cursor or cursor in cursors:
                    raise MCPError("invalid MCP pagination cursor")
                cursors.add(cursor)
            return ToolResult(json.dumps(tools, allow_nan=False))
        result = connection.request("tools/call", {"name": tool, "arguments": dict(arguments)})
        content = result.get("content")
        if not isinstance(content, list):
            raise MCPError("invalid MCP tool content")
        parts = [item["text"] for item in content if isinstance(item, dict)
                 and item.get("type") == "text" and isinstance(item.get("text"), str)]
        text = "\n".join(parts)
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + "\n(output truncated)"
        if result.get("isError") is True:
            return ToolResult("", text or "MCP tool failed")
        if not parts:
            return ToolResult("", "MCP tool returned no supported text content")
        return ToolResult(text)
    except MCPError as exc:
        return ToolResult("", f"{exc}; fix configuration and reload MCP")
    except FileNotFoundError:
        return ToolResult("", "MCP executable not found; fix configuration and reload MCP")
    except OSError:
        return ToolResult("", "MCP process or transport failed; fix configuration and reload MCP")
    except (ValueError, TypeError, KeyError, RecursionError):
        return ToolResult("", "Invalid MCP response; fix configuration and reload MCP")
    finally:
        if connection is not None:
            connection.close()


def _valid_schema(schema):
    if not isinstance(schema, dict):
        return False
    properties, required = schema.get("properties", {}), schema.get("required", [])
    if (not isinstance(properties, dict) or not isinstance(required, list)
            or not all(isinstance(name, str) for name in required)):
        return False
    for name, prop in properties.items():
        if not isinstance(name, str):
            return False
        if type(prop) is bool:
            continue
        if not isinstance(prop, dict):
            return False
        kind = prop.get("type")
        if kind is not None and not (isinstance(kind, str) or isinstance(kind, list)
                                    and kind and all(isinstance(k, str) for k in kind)):
            return False
    return True


_SECRET_NAME = re.compile(r"token|secret|password|passwd|api_?key|credential|auth", re.I)


def _trust_file():
    """Outside any project, and not a setting: a folder's own .env must not choose it."""
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "sensai" / "trusted-mcp.json"


def _read_trusted():
    try:
        trusted = json.loads(_trust_file().read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    return trusted if isinstance(trusted, dict) else {}


def _describe(name, spec):
    """One escaped line for a trust question, with what really decides the program that runs.

    Values such as PATH or LD_PRELOAD change that program, so only secret-looking ones are hidden.
    """
    if not isinstance(spec, dict) or not isinstance(spec.get("command"), str):
        line = f"{name}: (invalid entry)"
    else:
        command, args = spec["command"], spec.get("args", [])
        line = f"{name}: {shlex.join([command, *map(str, args if isinstance(args, list) else [])])}"
        env = spec.get("env") if isinstance(spec.get("env"), dict) else {}
        found = shutil.which(command, path=str(env.get("PATH", os.environ.get("PATH", ""))))
        if found and os.path.abspath(found) != command:
            line += f" (program: {os.path.abspath(found)})"
        if env:
            line += " (sets " + ", ".join(
                f"{key}=<hidden>" if _SECRET_NAME.search(str(key)) else f"{key}={value}" for key, value in env.items()) + ")"
    return line.encode("unicode_escape").decode("ascii")


def _discover(name, spec):
    """One server's tools and status; it starts the server and asks for its tool list."""
    failure = "Invalid server configuration"
    try:
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name)
                or not isinstance(spec, dict) or not isinstance(spec.get("command"), str)
                or not spec["command"].strip()
                or not isinstance(spec.get("args", []), list)
                or not all(isinstance(arg, str) for arg in spec.get("args", []))
                or not isinstance(spec.get("env", {}), dict)
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in spec.get("env", {}).items())):
            raise ValueError()
        server = Server(name, spec["command"], tuple(spec.get("args", [])), spec.get("env", {}))
        discovery = ToolRegistry()
        discovery.register(ToolDefinition("discover", "", {}), partial(exchange, server, None))
        result = discovery.execute(ToolCall("discover", {}))
        if result.error:
            failure = result.error.removesuffix("; fix configuration and reload MCP")
            raise ValueError()
        failure = "Invalid MCP tool schema or duplicate tool name"
        found, names = [], set()
        for tool in json.loads(result.output):
            if (not isinstance(tool, dict) or not isinstance(tool.get("name"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+", tool["name"]) or tool["name"] in names
                    or not isinstance(tool.get("description", ""), str)
                    or not _valid_schema(tool.get("inputSchema"))):
                raise ValueError()
            names.add(tool["name"])
            definition = ToolDefinition(f"{name}.{tool['name']}", tool.get("description", ""), tool["inputSchema"])
            found.append((definition, partial(exchange, server, tool["name"])))
        return found, {"name": name, "count": len(found), "error": None}
    except (ValueError, TypeError):
        return [], {"name": name, "count": 0, "error": failure + "; fix configuration and reload MCP"}


class Catalogue:
    def __init__(self, path="mcp.json"):
        self.path = path
        self.tools = []
        self.servers = []
        self.error = None
        self.untrusted = None  # {"digest", "commands"} while the file waits for the user's trust.
        self.trust_error = None
        self._accepted = set()

    def _trust_key(self):
        """The launch folder counts: servers start there, and relative commands and `python -m` load from it.

        The path is not resolved, so a folder's symlink to an accepted file is a new question.
        """
        return f"{os.getcwd()}\0{os.path.abspath(self.path)}"

    def _trusted(self, digest):
        key = self._trust_key()
        return (key, digest) in self._accepted or _read_trusted().get(key) == digest

    def trust(self, digest):
        """Remember the file content the user was shown; the next reload then runs it."""
        if not self.untrusted or digest != self.untrusted["digest"]:
            return False
        key, self.trust_error = self._trust_key(), None
        self._accepted.add((key, digest))
        target = _trust_file()
        try:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            partial_file = target.with_suffix(".tmp")
            partial_file.touch(mode=0o600)
            partial_file.write_text(json.dumps({**_read_trusted(), key: digest}), encoding="utf-8")
            partial_file.replace(target)
        except OSError:
            self.trust_error = "Could not save MCP trust; Sensai will ask again next time"
        return True

    def config_path(self):
        return str(Path(self.path).resolve())

    def config_found(self):
        return Path(self.path).is_file()

    def definitions(self):
        return tuple(definition for definition, handler in self.tools)

    def register(self, registry):
        for definition, handler in self.tools:
            registry.register(definition, handler, timeout=TIMEOUT, confirm=True)

    def reload(self):
        self.untrusted = None
        try:
            try:
                raw = Path(self.path).read_bytes()
            except FileNotFoundError:
                raw = b'{"mcpServers": {}}'
            config = json.loads(raw.decode("utf-8"))
            if not isinstance(config, dict) or not isinstance(config.get("mcpServers"), dict):
                raise ValueError()
        except (OSError, ValueError, TypeError, RecursionError):
            self.error = "Invalid MCP configuration; fix it and reload MCP"
            return False
        digest = hashlib.sha256(raw).hexdigest()
        if config["mcpServers"] and not self._trusted(digest):
            self.tools, self.servers, self.error = [], [], None
            self.untrusted = {"digest": digest, "folder": os.getcwd(), "commands": [
                _describe(name, spec) for name, spec in config["mcpServers"].items()]}
            return True
        # In parallel: one hung server costs one timeout, not one per server.
        with ThreadPoolExecutor(max_workers=max(1, len(config["mcpServers"]))) as pool:
            results = list(pool.map(lambda item: _discover(*item), config["mcpServers"].items()))
        tools = [pair for found, status in results for pair in found]
        statuses = [status for found, status in results]
        self.tools, self.servers, self.error = tools, statuses, None
        return True

    def notices(self):
        lines = [f"MCP: {s['name']} ({s['count']} tool{'' if s['count'] == 1 else 's'})" if not s["error"] else
                 f"MCP server {s['name']} unavailable: {s['error']}" for s in self.servers]
        return [message for message in (self.error, self.trust_error) if message] + lines
