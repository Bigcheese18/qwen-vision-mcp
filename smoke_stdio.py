#!/usr/bin/env python3
"""通过真实 MCP stdio 传输协议做冒烟测试（Claude Code 就是走这条通道）。"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

proc = subprocess.Popen(
    [sys.executable, str(HERE / "server.py")],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=HERE,
    encoding="utf-8",
    bufsize=1,
)


def send(msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def recv():
    line = proc.stdout.readline()
    return json.loads(line) if line else None


send(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "0.0.1"},
        },
    }
)
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

init = recv()
tools = recv()
print("initialize:", "OK" if init.get("id") == 1 else "FAILED")
if tools.get("id") == 2:
    names = [t["name"] for t in tools["result"]["tools"]]
    print("tools:", names)
    print("smoke:", "PASS" if "analyze_image" in names else "FAIL")
else:
    print("tools/list:", "FAILED")
    print(tools)

proc.stdin.close()
proc.terminate()
