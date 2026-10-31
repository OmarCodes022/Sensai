"""Small MCP 2025-11-25 stdio client; every exchange runs in tool isolation."""
from dataclasses import dataclass, field
from functools import partial
import json
import os
from pathlib import Path
import re
import subprocess

from sensai.core.ports import ToolCall, ToolDefinition, ToolResult
from sensai.tools import ToolRegistry

PROTOCOL = "2025-11-25"
TIMEOUT = 30.0
MAX_MESSAGE = 1024 * 1024
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
                    self.send({"jsonrpc": "2.0", "id": message["id"], "error": {
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
        if result.get("protocolVersion") != PROTOCOL:
            raise MCPError("unsupported MCP protocol version (expected " + PROTOCOL + ")")
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


class Catalogue:
    def __init__(self, path="mcp.json"):
        self.path = path
        self.tools = []
        self.servers = []
        self.error = None

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
        try:
            try:
                config = json.loads(Path(self.path).read_text(encoding="utf-8"))
            except FileNotFoundError:
                config = {"mcpServers": {}}
            if not isinstance(config, dict) or not isinstance(config.get("mcpServers"), dict):
                raise ValueError()
        except (OSError, ValueError, TypeError, RecursionError):
            self.error = "Invalid MCP configuration; fix it and reload MCP"
            return False
        tools, statuses = [], []
        for name, spec in config["mcpServers"].items():
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
                tools.extend(found)
                statuses.append({"name": name, "count": len(found), "error": None})
            except (ValueError, TypeError):
                statuses.append({"name": name, "count": 0, "error": failure + "; fix configuration and reload MCP"})
        self.tools, self.servers, self.error = tools, statuses, None
        return True

    def notices(self):
        lines = [f"MCP: {s['name']} ({s['count']} tool{'' if s['count'] == 1 else 's'})" if not s["error"] else
                 f"MCP server {s['name']} unavailable: {s['error']}" for s in self.servers]
        return ([self.error] if self.error else []) + lines
