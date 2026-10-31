"""Small subprocess peer for independent MCP acceptance checks; no network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    mode = os.environ.get("MCP_TEST_MODE", "normal")
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        if "id" not in message:
            continue
        result = {}
        if method == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "acceptance", "version": "1"}}
            if mode == "version":
                result["protocolVersion"] = "2099-01-01"
            if mode == "older":
                result["protocolVersion"] = "2025-06-18"
            if mode == "closed":
                return
        elif method == "tools/list":
            if mode == "ping":  # A server may ping mid-request; only an empty result is valid.
                print(json.dumps({"jsonrpc": "2.0", "id": "p", "method": "ping"}), flush=True)
                if json.loads(sys.stdin.readline()).get("result") != {}:
                    return
            cursor = message.get("params", {}).get("cursor")
            result = {"tools": [{"name": "second" if cursor else "first",
                                 "description": "acceptance tool", "inputSchema": {"type": "object"}}]}
            if mode == "nullable":
                result["tools"][0]["inputSchema"]["properties"] = {"value": {"type": ["string", "null"]}}
            if mode == "malformed-schema":
                result["tools"][0]["inputSchema"]["properties"] = []
            if mode == "boolean-schema":
                result["tools"][0]["inputSchema"]["properties"] = {"allowed": True, "forbidden": False}
            if not cursor:
                result["nextCursor"] = "page-two"
        elif method == "tools/call":
            marker = os.environ.get("MCP_TEST_MARKER")
            if marker:
                Path(marker).write_text("called", encoding="utf-8")
            if mode in ("hang", "descendant"):
                child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
                Path(os.environ["MCP_TEST_PID"]).write_text(str(child.pid), encoding="utf-8")
                if mode == "hang":
                    time.sleep(60)
            result = {"content": [{"type": "text", "text": "x" * 50_000 if mode == "large" else "fixture value"}],
                      "isError": mode == "tool-error"}
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)


if __name__ == "__main__":
    main()
