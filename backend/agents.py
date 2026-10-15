"""Agent wiring for the Campus Customs suite: boss + four specialists.

Every agent reaches shop data only through the campus-customs MCP server (connected via
the project's .mcp.json). Each agent sees a filtered subset of the MCP tools, and every
MCP call passes through `guard`, which enforces the harness rules and writes the call to
the audit trail. The boss's one local tool, `delegate`, just runs a specialist agent; it
never touches shop data itself.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastmcp import Client
from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import RetryPromptPart, TextPart, ThinkingPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from models import AgentDeps, AgentName, BossReport, SpecialistName, SpecialistReport

BACKEND_DIR = Path(__file__).resolve().parent
HW_DIR = BACKEND_DIR.parent
PROMPTS_DIR = BACKEND_DIR / "prompts"
MCP_CONFIG = HW_DIR / ".mcp.json"
MCP_SERVER = "campus-customs"

PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
DEFAULT_MODEL = "gpt-5.6-luna"

# --- which MCP tools each agent may see -------------------------------------

TOOLS_BY_AGENT: dict[AgentName, set[str]] = {
    "boss": {"list_open_tickets", "get_ticket", "update_ticket"},
    "inventory": {"get_ticket", "get_inventory", "stock_tracker", "list_vendors", "request_human_approval",
                  "update_ticket"},
    "accounting": {"get_ticket", "invoice_reminder_and_payer", "bulk_order_discount",
                   "request_human_approval", "update_ticket"},
    "facilities": {"get_ticket", "get_lease", "list_vendors", "update_ticket"},
    "customer_service": {"get_ticket", "stock_tracker", "draft_customer_message", "update_ticket"},
}
# get_cash_balance, list_approval_requests and approve_payment are deliberately in no
# agent's list: they're for the back-office API, where a person approves cash outflows.

# Which kinds of approval request each agent may file (others are blocked by the guard).
APPROVAL_KINDS = {"inventory": {"purchase"},
                  "accounting": {"invoice_payment", "rent_payment", "purchase", "price_override"}}

# Tool arguments that name the acting agent. The guard overwrites them with the real
# agent so no agent can file an approval or a note under someone else's name.
ATTRIBUTION_ARG = {"update_ticket": "agent", "request_human_approval": "requested_by",
                   "draft_customer_message": "drafted_by"}

# --- token controls ---------------------------------------------------------

BOSS_LIMITS = UsageLimits(request_limit=15, tool_calls_limit=20, total_tokens_limit=60_000)
SPECIALIST_LIMITS = UsageLimits(request_limit=6, tool_calls_limit=8, total_tokens_limit=25_000)
SUITE_MAX_TOKENS = int(os.getenv("SUITE_MAX_TOKENS", 150_000))
SUITE_MAX_DELEGATIONS = int(os.getenv("SUITE_MAX_DELEGATIONS", 8))
MODEL_SETTINGS = OpenAIResponsesModelSettings(
    openai_reasoning_effort=os.getenv("AGENT_REASONING_EFFORT", "low"),
    parallel_tool_calls=False,  # one call per step keeps the audit trail in order
)


def usage_dict(u: Any) -> dict[str, int]:
    return {
        "input_tokens": u.input_tokens or 0,
        "output_tokens": u.output_tokens or 0,
        "total_tokens": (u.input_tokens or 0) + (u.output_tokens or 0),
        **({"requests": u.requests} if hasattr(u, "requests") else {}),
        **({"tool_calls": u.tool_calls} if hasattr(u, "tool_calls") else {}),
    }


# --- model and MCP connection ----------------------------------------------


def build_model() -> Model:
    load_dotenv(HW_DIR / ".env")         # project .env (copy .env.example)
    load_dotenv(BACKEND_DIR / ".env")
    load_dotenv(HW_DIR.parent / ".env")  # course-root .env holds the shared PORTKEY_API_KEY
    key = os.getenv("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is missing; add it to backend/.env or the course-root .env")
    client = AsyncOpenAI(api_key=key, base_url=PORTKEY_BASE_URL, default_headers={"x-portkey-api-key": key})
    return OpenAIResponsesModel(os.getenv("AGENT_MODEL", DEFAULT_MODEL), provider=OpenAIProvider(openai_client=client))


async def guard(ctx: RunContext[AgentDeps], call_tool, name: str, args: dict[str, Any]) -> Any:
    """Every MCP call goes through here: enforce harness rules, then call MCP and log it."""
    deps, audit = ctx.deps, ctx.deps.audit
    args = dict(args)
    where = dict(parent=deps.parent, ticket_id=deps.ticket_id, step=ctx.run_step)

    block = None
    if name not in TOOLS_BY_AGENT[deps.agent]:
        block = f"{deps.agent} is not allowed to use {name}."
    elif name == "invoice_reminder_and_payer" and args.get("autopay") is not None:
        block = "Agents can't turn autopay on or off; only an employee can. Use request_human_approval for payments."
    elif name == "update_ticket" and args.get("status") and deps.agent != "boss":
        block = "Only the boss sets ticket status. Add a note without a status instead."
    elif name == "request_human_approval" and args.get("kind") not in APPROVAL_KINDS.get(deps.agent, set()):
        block = (f"{deps.agent} can only file {sorted(APPROVAL_KINDS.get(deps.agent, set()))} approval requests; "
                 f"leave {args.get('kind')} to accounting.")
    if block:
        audit.log(deps.agent, "guard_block", tool=name, arguments=args, reason=block, **where)
        return {"error": block}

    if name in ATTRIBUTION_ARG:
        args[ATTRIBUTION_ARG[name]] = deps.agent

    started = time.perf_counter()
    try:
        result = await call_tool(name, args)
    except Exception as exc:
        audit.log(deps.agent, "error", tool=name, arguments=args, message=str(exc), **where)
        raise
    audit.log(deps.agent, "tool_call", tool=name, arguments=args, result=result,
              ok=not (isinstance(result, dict) and "error" in result),
              duration_ms=round((time.perf_counter() - started) * 1000), **where)
    return result


def mcp_toolset() -> MCPToolset:
    """One connection to the campus-customs server, built from the project's .mcp.json."""
    config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    server = config["mcpServers"][MCP_SERVER]
    server["cwd"] = str(HW_DIR)  # .mcp.json paths are relative to HW 5
    if os.getenv("CAMPUS_DB"):
        server.setdefault("env", {})["CAMPUS_DB"] = os.environ["CAMPUS_DB"]
    return MCPToolset(Client(config), process_tool_call=guard, tool_error_behavior="error")


def load_prompt(agent: AgentName) -> str:
    text = (PROMPTS_DIR / f"{agent}.md").read_text(encoding="utf-8")
    if "PROMPT PENDING" in text:
        raise RuntimeError(f"backend/prompts/{agent}.md is still a placeholder; paste the {agent} prompt in first.")
    return text


def identity(agent: AgentName) -> str:
    return (f"You are the `{agent}` agent. Your tools: {', '.join(sorted(TOOLS_BY_AGENT[agent]))}. "
            "All shop facts must come from those tools; never guess numbers.")


# --- the agent loop (shared by boss and specialists) -----------------------


async def run_agent(agent: Agent, prompt: str, deps: AgentDeps, limits: UsageLimits) -> Any:
    """Run one agent step by step, logging every model request, model response, and the final output."""
    audit = deps.audit
    where = dict(parent=deps.parent, ticket_id=deps.ticket_id)
    audit.log(deps.agent, "agent_start", prompt=prompt, allowed_tools=sorted(TOOLS_BY_AGENT[deps.agent]),
              limits={"requests": limits.request_limit, "tool_calls": limits.tool_calls_limit,
                      "total_tokens": limits.total_tokens_limit}, **where)
    run = None
    try:
        async with agent.iter(prompt, deps=deps, usage_limits=limits) as run:
            step = 0
            async for node in run:
                if Agent.is_model_request_node(node):
                    step += 1
                    parts = []
                    for p in node.request.parts:
                        if isinstance(p, ToolReturnPart):
                            parts.append({"type": "tool_return", "tool": p.tool_name, "tool_call_id": p.tool_call_id})
                        elif isinstance(p, RetryPromptPart):
                            parts.append({"type": "retry", "tool": p.tool_name, "content": str(p.content)})
                        elif isinstance(p, UserPromptPart):
                            parts.append({"type": "user_prompt", "content": str(p.content)})
                    audit.log(deps.agent, "model_request", step=step, parts=parts, **where)
                elif Agent.is_call_tools_node(node):
                    resp = node.model_response
                    parts = []
                    for p in resp.parts:
                        if isinstance(p, ToolCallPart):
                            parts.append({"type": "tool_call", "tool": p.tool_name, "tool_call_id": p.tool_call_id,
                                          "arguments": p.args_as_dict()})
                        elif isinstance(p, TextPart):
                            parts.append({"type": "text", "content": p.content})
                        elif isinstance(p, ThinkingPart):
                            parts.append({"type": "reasoning", "chars": len(p.content or "")})
                    audit.log(deps.agent, "model_response", step=step, model=resp.model_name, parts=parts,
                              usage=usage_dict(resp.usage), **where)
        output = run.result.output
    except Exception as exc:
        used = usage_dict(run.usage) if run else None
        if used:
            deps.budget.tokens_used += used["total_tokens"]
        audit.log(deps.agent, "error", message=f"{type(exc).__name__}: {exc}", usage=used, **where)
        raise
    used = usage_dict(run.usage)
    deps.budget.tokens_used += used["total_tokens"]
    audit.log(deps.agent, "agent_end", output=output.model_dump() if hasattr(output, "model_dump") else output,
              usage=used, suite_tokens_used=deps.budget.tokens_used, **where)
    return output


# --- build the suite --------------------------------------------------------


def build_suite(model: Model | str | None = None) -> tuple[Agent, dict[SpecialistName, Agent], MCPToolset]:
    model = model or build_model()
    toolset = mcp_toolset()

    def tools_for(name: AgentName):
        allowed = TOOLS_BY_AGENT[name]
        return toolset.filtered(lambda ctx, tool_def: tool_def.name in allowed)

    specialists: dict[SpecialistName, Agent] = {
        name: Agent(model, name=name, deps_type=AgentDeps, output_type=SpecialistReport,
                    instructions=[load_prompt(name), identity(name)], toolsets=[tools_for(name)],
                    model_settings=MODEL_SETTINGS, retries=1)
        for name in ("inventory", "accounting", "facilities", "customer_service")
    }

    boss = Agent(model, name="boss", deps_type=AgentDeps, output_type=BossReport,
                 instructions=[load_prompt("boss"), identity("boss") + " You also have `delegate`."],
                 toolsets=[tools_for("boss")], model_settings=MODEL_SETTINGS, retries=1)

    @boss.tool
    async def delegate(ctx: RunContext[AgentDeps], specialist: SpecialistName, ticket_id: int, task: str) -> dict:
        """Hand one ticket to a specialist and get their report back.

        Specialists: inventory (stock, restock, vendors), accounting (bills, payments, bulk
        pricing, approval requests), facilities (lease and the shop space), customer_service
        (in/out of stock answers and customer reply drafts). Give a focused task and include
        any facts from earlier reports the specialist needs (e.g. a quote for a customer reply).

        Args:
            specialist: Who to hand the ticket to.
            ticket_id: The ticket number.
            task: What you need from them, in one to three sentences.
        """
        b, audit = ctx.deps.budget, ctx.deps.audit
        in_flight = b.tokens_used + ctx.usage.total_tokens
        if b.delegations_used >= b.max_delegations or in_flight >= b.max_total_tokens:
            reason = (f"Delegation budget used ({b.delegations_used}/{b.max_delegations})"
                      if b.delegations_used >= b.max_delegations
                      else f"Suite token budget used ({in_flight:,}/{b.max_total_tokens:,})")
            audit.log("boss", "guard_block", ticket_id=ticket_id, step=ctx.run_step, tool="delegate",
                      arguments={"specialist": specialist, "task": task}, reason=reason)
            return {"error": reason + ". Wrap up with what you have."}
        b.delegations_used += 1
        audit.log("boss", "delegation", ticket_id=ticket_id, step=ctx.run_step, specialist=specialist, task=task,
                  delegation_number=b.delegations_used)
        deps = AgentDeps(agent=specialist, run_id=ctx.deps.run_id, budget=b, audit=audit, parent="boss",
                         ticket_id=ticket_id)
        try:
            report = await run_agent(specialists[specialist], f"Ticket #{ticket_id}.\nTask from the boss: {task}",
                                     deps, SPECIALIST_LIMITS)
        except Exception as exc:
            return {"error": f"{specialist} could not finish: {type(exc).__name__}: {exc}"}
        return report.model_dump()

    return boss, specialists, toolset
