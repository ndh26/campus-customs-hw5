"""Run the Campus Customs agent suite on the open tickets.

Usage (from the HW 5 folder):
  py backend/run_suite.py              # boss works every open ticket
  py backend/run_suite.py --ticket 101 # boss works one ticket

Every step is appended to output/audit_trail.json as it happens.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime

from agents import (BOSS_LIMITS, DEFAULT_MODEL, MCP_CONFIG, SPECIALIST_LIMITS, SUITE_MAX_DELEGATIONS,
                    SUITE_MAX_TOKENS, build_suite, run_agent)
from audit import AUDIT_PATH, AuditTrail
from models import AgentDeps, SuiteBudget


async def main(ticket: int | None, model=None) -> dict:
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    audit = AuditTrail(run_id)
    budget = SuiteBudget(max_total_tokens=SUITE_MAX_TOKENS, max_delegations=SUITE_MAX_DELEGATIONS)
    boss, _, toolset = build_suite(model)

    audit.log("harness", "run_start", ticket_id=ticket,
              scope=f"ticket #{ticket}" if ticket else "all open tickets",
              model=getattr(model, "model_name", None) or os.getenv("AGENT_MODEL", DEFAULT_MODEL),
              mcp_config=str(MCP_CONFIG.name), database=os.getenv("CAMPUS_DB", "data/campus_customs_new.db"),
              budget={"suite_tokens": budget.max_total_tokens, "delegations": budget.max_delegations,
                      "boss_requests": BOSS_LIMITS.request_limit, "specialist_requests": SPECIALIST_LIMITS.request_limit})

    prompt = (f"Work ticket #{ticket} only." if ticket else "Work every open ticket.")
    deps = AgentDeps(agent="boss", run_id=run_id, budget=budget, audit=audit, ticket_id=ticket)
    status, report = "ok", None
    try:
        async with toolset:  # one MCP server process for the whole run
            report = await run_agent(boss, prompt, deps, BOSS_LIMITS)
    except Exception as exc:
        status = f"failed: {type(exc).__name__}: {exc}"
    audit.log("harness", "run_end", ticket_id=ticket, status=status,
              report=report.model_dump() if report else None,
              tokens_used=budget.tokens_used, delegations_used=budget.delegations_used)
    return {"run_id": run_id, "status": status, "report": report.model_dump() if report else None,
            "tokens_used": budget.tokens_used, "delegations_used": budget.delegations_used,
            "audit_trail": str(AUDIT_PATH)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticket", type=int, help="Only work this ticket number.")
    result = asyncio.run(main(parser.parse_args().ticket))
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)
