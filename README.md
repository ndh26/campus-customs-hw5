# Campus Customs: Agent Back Office (HW 5)

A five-agent team (boss, inventory, accounting, facilities, customer service) that works the open tickets for Campus Customs, a small Yale merch shop. All shop data comes from a SQLite database through an MCP server. A FastAPI backend runs the agents and lets a person approve payments. A React dashboard shows the agents at work.

## Run it

```bash
# 1. Python deps (MCP server + backend)
pip install -r requirements.txt

# 2. API key: copy .env.example to .env and set PORTKEY_API_KEY

# 3. Backend API (http://localhost:8000)
cd backend
uvicorn main:app --reload --port 8000

# 4. Dashboard (http://localhost:5173), in a second terminal
cd frontend
npm install
npm run dev
```

On the dashboard:
- Click a ticket to dispatch the agents.
- Approve queued payments or price sign-offs on the right.
- Use **Reset** to restore the database for a fresh run.

## Layout

| Path | What it is |
|---|---|
| `.mcp.json` | Connects the `campus-customs` MCP server to the project (used by Claude Code and by the agents) |
| `data/campus_customs.db` | The original shop database. Never modified; used for resets. |
| `data/campus_customs_new.db` | The working copy the agents use (left in its state after the final run) |
| `mcp_server/server.py` | FastMCP server with 14 tools: stock, bills, bulk pricing, tickets, approvals, drafts |
| `backend/main.py` | FastAPI routes: tickets, run a ticket, activity, approvals, cash, reset |
| `backend/agents.py`, `models.py` | Agent wiring, the safety guard, and data types |
| `backend/prompts/` | One prompt per agent |
| `frontend/` | React + Vite + TypeScript dashboard |
| `output/harness.md` | Full write-up: tables, tools, agents, routes, dashboard, safety, final run |
| `output/desk_tickets.html` | Expected vs. actual for each ticket, plus the cash ledger |
| `output/resolved_tickets.json`, `resolved_board.html` | Final outcome of each ticket |
| `output/audit_trail.json` | Append-only log of every agent step and human approval |
| `output/mcp_smoke.json` | Evidence from running each MCP tool through `.mcp.json` |
| `output/design.md` | Dashboard design choices |

## Safety in one paragraph

Agents can't move money or contact anyone. They queue payments, purchases and price changes for a person to approve, and the server checks every amount against the books. Customer replies are saved as drafts only, and drafts that mention internal details are rejected. Each agent sees only its own tools, and a guard blocks anything outside its role. Details are in `output/harness.md`.
