"""Sensai's read-only weekly engagement MCP server (stdio, 2025-11-25)."""
import csv
from datetime import date, timedelta
from importlib.resources import files
import json
import os
import sys

PROTOCOL = "2025-11-25"
TOOL = {"name": "weekly_engagement", "description": "Read weekly engagement figures, grouped by channel.",
        "inputSchema": {"type": "object", "properties": {"week_start": {"type": "string"}},
                        "required": ["week_start"], "additionalProperties": False}}


def weekly_engagement(week_start):
    start = date.fromisoformat(week_start)
    if start.isoformat() != week_start or start.weekday() != 0:
        raise ValueError("week_start must be an ISO Monday date")
    days = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    period = f"{days[0]}/{days[-1]}"
    path = os.environ.get("SENSAI_ENGAGEMENT_CSV")
    source = open(path, encoding="utf-8-sig", newline="") if path else files("sensai").joinpath("engagement_demo.csv").open(encoding="utf-8", newline="")
    channels, seen = {}, set()
    with source:
        reader = csv.DictReader(source)
        if not {"date", "channel", "accounts_reached", "accounts_engaged"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV is missing required columns")
        for row in reader:
            label, channel = row["date"], row["channel"]
            if label != period and label not in days:
                continue
            if not channel or (label, channel) in seen:
                raise ValueError("CSV contains blank channels or duplicate rows")
            seen.add((label, channel))
            reach, engaged = int(row["accounts_reached"]), int(row["accounts_engaged"])
            if reach < 0 or engaged < 0 or engaged > reach:
                raise ValueError("CSV contains invalid engagement counts")
            channels.setdefault(channel, {})[label] = (reach, engaged)
    if not channels:
        raise ValueError("No engagement data for this week")
    results = []
    for channel, rows in channels.items():
        weekly = period in rows
        selected = [rows[period]] if weekly else [rows[d] for d in days if d in rows]
        reach, engaged = (sum(r[i] for r in selected) for i in (0, 1))
        missing = [] if weekly else [d for d in days if d not in rows]
        results.append({"channel": channel, "week_start": week_start, "accounts_reached": reach,
                        "accounts_engaged": engaged, "engagement_rate": round(engaged / reach * 100, 2) if reach else "n/a",
                        "basis": "weekly unique accounts" if weekly else "daily totals, not unique accounts",
                        "incomplete": bool(missing), "missing_days": missing})
    return json.dumps(results, ensure_ascii=False)


def main():
    initialized = False
    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise ValueError("Invalid JSON-RPC request")
            request_id = request.get("id")
            method, params = request.get("method"), request.get("params", {})
            if method == "notifications/initialized":
                initialized = True
                continue
            if "id" not in request:
                continue
            if method == "initialize":
                result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "sensai-engagement", "version": "0.1.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list" and initialized:
                result = {"tools": [TOOL]}
            elif method == "tools/call" and initialized:
                try:
                    arguments = params.get("arguments", {})
                    if params.get("name") != TOOL["name"] or set(arguments) != {"week_start"}:
                        raise ValueError("Expected weekly_engagement(week_start)")
                    output = weekly_engagement(arguments["week_start"])
                    result = {"content": [{"type": "text", "text": output}], "isError": False}
                except (OSError, ValueError, TypeError, KeyError, OverflowError, csv.Error):
                    result = {"content": [{"type": "text", "text": "Cannot read engagement: check the ISO Monday date and CSV data"}], "isError": True}
            else:
                print(json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not supported"}}), flush=True)
                continue
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except (ValueError, TypeError, AttributeError):
            response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid request"}}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
