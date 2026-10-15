"""Campus Customs back-office API.

Start from the backend folder:  uvicorn main:app --reload --port 8000

Every route that needs shop data gets it from the campus-customs MCP server (via the
project's .mcp.json), the same way the agents do. The only direct file work here is
reading our own audit trail and restoring the working database from the original copy.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import Client
from pydantic import BaseModel, Field

import run_suite
from agents import HW_DIR, MCP_CONFIG, MCP_SERVER
from audit import AUDIT_PATH, AuditTrail

ORIGINAL_DB = HW_DIR / "data" / "campus_customs.db"
WORKING_DB = Path(os.environ.get("CAMPUS_DB", HW_DIR / "data" / "campus_customs_new.db"))

run_lock = asyncio.Lock()  # one agent run (or reset) at a time
mcp: Client | None = None


def mcp_client() -> Client:
    config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    server = config["mcpServers"][MCP_SERVER]
    server["cwd"] = str(HW_DIR)
    if os.getenv("CAMPUS_DB"):
        server.setdefault("env", {})["CAMPUS_DB"] = os.environ["CAMPUS_DB"]
    return Client(config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp
    mcp = mcp_client()
    await mcp.__aenter__()
    try:
        yield
    finally:
        # Closing the stdio MCP subprocess can hang on Windows, which stalls --reload; cap it.
        try:
            await asyncio.wait_for(mcp.__aexit__(None, None, None), timeout=3)
        except Exception:
            pass


app = FastAPI(title="Campus Customs back office", lifespan=lifespan)

# Let the React dashboard (Vite dev server, any localhost port) call these routes from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


async def call(tool: str, **args: Any) -> Any:
    """Call one MCP tool; turn tool-level errors into HTTP 400s."""
    result = await mcp.call_tool(tool, args, raise_on_error=False)
    data = result.data if result.data is not None else [getattr(b, "text", str(b)) for b in result.content]
    if result.is_error:
        raise HTTPException(502, f"MCP tool {tool} failed: {data}")
    if isinstance(data, dict) and "error" in data:
        raise HTTPException(400, data["error"])
    return data


def human_log(action: str, **detail: Any) -> None:
    AuditTrail(f"human-{datetime.now():%Y%m%d-%H%M%S}").log("human", "human_action", action=action, **detail)


def read_audit() -> list[dict]:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8")) if AUDIT_PATH.exists() else []


# --- routes -----------------------------------------------------------------


@app.get("/tickets")
async def tickets():
    """Every ticket and whether it's resolved."""
    rows = await call("list_open_tickets", include_resolved=True)
    for t in rows:
        t["resolved"] = t["status"] == "resolved"
    return {
        "resolved": sum(t["resolved"] for t in rows),
        "unresolved": sum(not t["resolved"] for t in rows),
        "tickets": rows,
    }


@app.post("/tickets/{ticket_id}/run")
async def run_ticket(ticket_id: int):
    """Run the agent team (boss + specialists) on one ticket."""
    await call("get_ticket", ticket_id=ticket_id)  # 400 if the ticket doesn't exist
    if run_lock.locked():
        raise HTTPException(409, "An agent run or reset is already in progress.")
    async with run_lock:
        result = await run_suite.main(ticket_id)
    if result["status"] != "ok":
        raise HTTPException(500, result)
    return result


def summarize(e: dict) -> dict | None:
    """One audit event as a dashboard line: who, what kind, what they said or did. None = skip."""
    d, kind = e["detail"], e["event"]
    line = {"seq": e["seq"], "time": e["timestamp"], "agent": e["agent"], "ticket_id": e["ticket_id"], "type": kind}
    if kind == "model_response":
        said = " ".join(p["content"] for p in d.get("parts", []) if p["type"] == "text").strip()
        if not said:
            return None  # a step that only called tools; the tool_call line covers it
        return {**line, "type": "said", "text": said}
    if kind == "tool_call":
        return {**line, "tool": d["tool"], "arguments": d["arguments"], "ok": d["ok"], "result": d["result"]}
    if kind == "guard_block":
        return {**line, "tool": d["tool"], "text": f"Blocked: {d['reason']}"}
    if kind == "delegation":
        return {**line, "text": f"Handed #{e['ticket_id']} to {d['specialist']}: {d['task']}"}
    if kind == "agent_start" and e["agent"] != "boss":
        return {**line, "text": d["prompt"]}
    if kind == "agent_end":
        out = d.get("output") or {}
        return {**line, "type": "said", "text": out.get("summary") or out.get("run_summary") or "Finished.",
                "output": out}
    if kind in ("run_start", "run_end", "error", "human_action"):
        return {**line, "text": d.get("status") or d.get("scope") or d.get("message") or d.get("action")}
    return None  # model_request / boss agent_start: available with ?full=true


@app.get("/activity")
async def activity(run_id: str | None = None, ticket_id: int | None = None,
                   since_seq: int = Query(0, description="Only events after this seq, so the board can poll."),
                   full: bool = Query(False, description="Return raw audit events instead of the summary.")):
    """Recent agent events: what each agent said and which tools it used. Defaults to the latest agent run."""
    events = read_audit()
    agent_runs = list(dict.fromkeys(e["run_id"] for e in events if e["event"] == "run_start"))
    if not agent_runs:
        return {"run_id": None, "recent_runs": [], "agents": {}, "events": []}
    run_id = run_id or agent_runs[-1]
    picked = [e for e in events if e["run_id"] == run_id and e["seq"] > since_seq
              and (ticket_id is None or e["ticket_id"] in (ticket_id, None))]
    if not picked and since_seq == 0:
        raise HTTPException(404, f"No audit events for run {run_id}.")
    if full:
        return {"run_id": run_id, "events": picked}

    lines = [s for e in picked if (s := summarize(e))]
    agents: dict[str, dict] = {}
    for s in lines:
        if s["agent"] in ("harness", "human"):
            continue
        a = agents.setdefault(s["agent"], {"tools_used": [], "said": [], "blocked": 0})
        if s["type"] == "tool_call" and s["tool"] not in a["tools_used"]:
            a["tools_used"].append(s["tool"])
        elif s["type"] == "said":
            a["said"].append(s["text"])
        elif s["type"] == "guard_block":
            a["blocked"] += 1
    end = next((e for e in picked if e["event"] == "run_end"), None)
    return {
        "run_id": run_id,
        "recent_runs": agent_runs[-10:],
        "finished": end is not None,
        "tokens_used": end["detail"]["tokens_used"] if end else None,
        "last_seq": picked[-1]["seq"] if picked else since_seq,
        "agents": agents,
        "events": lines,
    }


@app.get("/approvals")
async def approvals(status: str | None = "pending"):
    """Approval requests the agents have filed (pending by default; ?status= for all)."""
    return await call("list_approval_requests", status=status or None)


class Approval(BaseModel):
    approved_by: str = Field(min_length=1, description="Name of the person approving the payment.")


@app.post("/approvals/{approval_id}/approve")
async def approve(approval_id: int, body: Approval):
    """A person approves a pending payment or purchase; the cash leaves checking."""
    result = await call("approve_payment", approval_request_id=approval_id, approved_by=body.approved_by)
    human_log("approve_payment", ticket_id=result["ticket_id"], approval_request_id=approval_id,
              approved_by=body.approved_by, result=result)

    # Once a ticket has nothing left waiting on a person's approval, close it out.
    ticket = await call("get_ticket", ticket_id=result["ticket_id"])
    still_pending = [a for a in ticket["approval_requests"] if a["status"] == "pending"]
    result["ticket_status"] = ticket["status"]
    if not still_pending and ticket["status"] == "waiting_approval":
        await call("update_ticket", ticket_id=ticket["id"], agent=body.approved_by,
                   note="All approvals done; ticket resolved.", status="resolved")
        result["ticket_status"] = "resolved"
        human_log("resolve_ticket", ticket_id=ticket["id"], approved_by=body.approved_by)
    return result


@app.get("/cash")
async def cash():
    """Current balance of each cash account."""
    accounts = await call("get_cash_balance")
    return {"accounts": accounts, "total": sum(a["balance"] for a in accounts)}


@app.post("/reset")
async def reset():
    """Restore campus_customs_new.db from the original so the next run starts fresh. The audit trail is kept."""
    if run_lock.locked():
        raise HTTPException(409, "An agent run is in progress; reset after it finishes.")
    async with run_lock:
        shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    human_log("reset_database", restored_from=ORIGINAL_DB.name, restored_to=WORKING_DB.name)
    return {"reset": True, "database": WORKING_DB.name, "restored_from": ORIGINAL_DB.name,
            "note": "Audit trail kept; new runs append to it."}
