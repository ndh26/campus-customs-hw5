"""Data types for the Campus Customs agent suite.

The agents' structured outputs, the per-run dependencies passed to every agent, and
the shape of each audit-trail event. Shop data itself never lives here: agents only
see it through the MCP server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
SpecialistName = Literal["inventory", "accounting", "facilities", "customer_service"]
TicketStatus = Literal["open", "in_progress", "waiting_approval", "resolved"]


# --- agent outputs ----------------------------------------------------------


class SpecialistReport(BaseModel):
    """What a specialist hands back to the boss after working one ticket."""

    agent: SpecialistName
    ticket_id: int
    summary: str = Field(description="Two or three sentences on what you found and did.")
    actions_taken: list[str] = Field(default_factory=list, description="One line per MCP action that changed something.")
    approval_request_ids: list[int] = Field(default_factory=list, description="IDs returned by request_human_approval.")
    customer_draft_ids: list[int] = Field(default_factory=list, description="IDs returned by draft_customer_message.")
    needs_human: bool = Field(description="True if a person must approve or act before the ticket can close.")
    next_step: str = Field(description="The single next thing that should happen on this ticket.")


class TicketOutcome(BaseModel):
    """The boss's final word on one ticket."""

    ticket_id: int
    handled_by: list[SpecialistName]
    status: TicketStatus
    summary: str
    human_action_needed: str | None = Field(None, description="What a person needs to do, or null if nothing.")


class BossReport(BaseModel):
    """The boss's end-of-run report."""

    run_summary: str
    tickets: list[TicketOutcome]


# --- run dependencies -------------------------------------------------------


@dataclass
class SuiteBudget:
    """Token and delegation budget shared by every agent in one run."""

    max_total_tokens: int
    max_delegations: int
    tokens_used: int = 0
    delegations_used: int = 0

    @property
    def tokens_left(self) -> int:
        return self.max_total_tokens - self.tokens_used


@dataclass
class AgentDeps:
    """Passed to every agent run. Identifies who is acting so tool calls are attributed correctly."""

    agent: AgentName
    run_id: str
    budget: SuiteBudget
    audit: Any  # audit.AuditTrail; typed loosely to keep models.py free of runtime imports
    parent: AgentName | None = None
    ticket_id: int | None = None


# --- audit trail ------------------------------------------------------------

AuditEventType = Literal[
    "run_start",       # suite run begins: model, limits, tickets in scope
    "agent_start",     # an agent run begins: its prompt and allowed tools
    "model_request",   # what was sent back to the model this step (tool results, retries)
    "model_response",  # what the model decided this step: tool calls and/or text, with token usage
    "tool_call",       # one MCP call: exact arguments, result, duration
    "guard_block",     # a tool call stopped by a harness rule before reaching MCP
    "delegation",      # boss hands a ticket to a specialist
    "agent_end",       # an agent run finishes: structured output and usage
    "error",           # anything that went wrong, with the message
    "run_end",         # suite run ends: boss report and total usage
    "human_action",    # a person acted through the API: approved a payment, reset the database
]


class AuditEvent(BaseModel):
    """One line in output/audit_trail.json."""

    run_id: str
    seq: int
    timestamp: str
    agent: AgentName | Literal["harness", "human"]
    parent_agent: AgentName | None = None
    ticket_id: int | None = None
    step: int | None = None
    event: AuditEventType
    detail: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, int] | None = None
