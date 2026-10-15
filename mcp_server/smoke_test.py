"""Smoke-test the Campus Customs MCP server through the project's .mcp.json connection.

Usage (from the HW 5 folder):
  py mcp_server/smoke_test.py connect                     # connect, list tools, start a fresh evidence file
  py mcp_server/smoke_test.py <tool> '<json arguments>' "<prompt that triggered the run>"

e.g.
  py mcp_server/smoke_test.py stock_tracker '{"sku": "CC-TEE-WHITE", "size": "S"}' "Customer clicks size S on the tee"

Each tool run (prompt, tool name, arguments, output) is appended to output/mcp_smoke.json.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from fastmcp import Client

HW_DIR = Path(__file__).resolve().parent.parent
MCP_CONFIG = HW_DIR / ".mcp.json"
EVIDENCE = HW_DIR / "output" / "mcp_smoke.json"
SERVER = "campus-customs"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_evidence() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def save_evidence(evidence: dict) -> None:
    EVIDENCE.parent.mkdir(exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2), encoding="utf-8")


def client() -> Client:
    config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    # Run the server from HW 5 so the relative path in .mcp.json resolves.
    config["mcpServers"][SERVER]["cwd"] = str(HW_DIR)
    return Client(config)


async def connect() -> None:
    async with client() as c:
        tools = await c.list_tools()
    evidence = {
        "server": SERVER,
        "connection": {
            "config_file": ".mcp.json",
            "transport": "stdio",
            "command": "py mcp_server/server.py",
            "connected_at": now(),
            "tools_listed": [{"name": t.name, "description": (t.description or "").split("\n")[0]} for t in tools],
        },
        "database": "data/campus_customs_new.db",
        "runs": [],
    }
    save_evidence(evidence)
    print(json.dumps(evidence["connection"], indent=2))


async def run(tool: str, args: dict, prompt: str) -> None:
    async with client() as c:
        result = await c.call_tool(tool, args, raise_on_error=False)
    output = result.data if result.data is not None else [getattr(b, "text", str(b)) for b in result.content]
    entry = {
        "prompt": prompt,
        "tool": tool,
        "arguments": args,
        "ran_at": now(),
        "is_error": result.is_error,
        "passed": not result.is_error and not (isinstance(output, dict) and "error" in output),
        "tool_output": output,
    }
    evidence = load_evidence()
    evidence["runs"].append(entry)
    save_evidence(evidence)
    print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "connect":
        asyncio.run(connect())
    else:
        args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        prompt = sys.argv[3] if len(sys.argv) > 3 else ""
        asyncio.run(run(sys.argv[1], args, prompt))
