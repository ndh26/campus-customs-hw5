# Agent Harness

This file summarizes the controls around the Campus Customs agent suite. It is a plain-English description of the system, not a code listing. Sections:

- **Data:** the database tables
- **Agents:** the five agents
- **MCP tools:** all 14 tools and the tables each one uses
- **Back-office API:** the routes
- **Dashboard:** the React board
- **Audit trail**
- **Stopping rules**
- **Safety**
- **Final run:** results of the full three-ticket run

## Data

- `data/campus_customs.db`: the original database as provided. Nothing ever opens it; it's the reset copy.
- `data/campus_customs_new.db`: the working copy. All shop data reaches the agents from this file, through the MCP server only.

### Tables

The database is the operations back office for a small Yale merchandise shop. The shop's "today" is 2026-08-31.

| Table | What's in it | Purpose |
|---|---|---|
| `desk` | 1 row: today's date (2026-08-31) and notes | Gives the agents a fixed "today" for working out due dates. |
| `inventory` | 10 rows of SKU × size: quantity and aisle | Stock on hand. The hoodie and tee come in S–XL; the cap and mug are one size (OS). The tee in size S and the mug are both out of stock. |
| `pricing` | 4 SKUs: unit cost and list price | Margins: hoodie $22 → $58, tee $8 → $28, cap $6 → $22, mug $3.50 → $14. Used to judge discount requests. |
| `vendors` | Bulldog Print Co (5-day lead), Elm City Gifts (3-day), QuickShip CT (1-day) | Suppliers with lead times, for reordering and delivery. |
| `leases` | Chapel Street shop, $2,400/month, due 2026-09-02 | Rent the shop owes. |
| `cash_accounts` | Checking: $3,400 | How much cash is available to pay bills. |
| `payments` | Empty | Record of payments made. Each one requires an `approved_by` value, so payments need a sign-off. |
| `invoices` | #501: Bulldog Print Co, $840, due 2026-08-28, status open | Bills owed. This one is 3 days overdue and pays for reprinting the out-of-stock size S tee. |
| `tickets` | 3 open requests | The agents' work queue (see below). |

The MCP server adds three tables of its own the first time it runs:

| Table | Purpose |
|---|---|
| `autopay_settings` | Whether autopay is on, who turned it on, and when. Only an employee can change it. |
| `approval_requests` | Payments and price overrides waiting for a person to approve. Agents file these instead of moving money. |
| `customer_outbox` | Customer replies drafted by agents. Every row stays a draft; nothing is sent. |

### Open tickets

- **#101 (customer_order):** Tauhid Zaman wants 1 Classic Bulldog Tee in size S, which is out of stock. The ticket is linked to invoice #501, the reprint that would restock it.
- **#102 (rent_notice):** Elm City Properties says rent of $2,400 is due in 2 days (lease #1).
- **#103 (price_override):** Yale AI Club wants 20 size M hoodies at a bulk discount, but only 8 are in stock.

### Cash tension

These tickets compete for the same money. Rent ($2,400) plus the overdue invoice ($840) comes to $3,240 against $3,400 in checking, which leaves $160. The agents need to prioritize correctly, avoid overspending, and get approval before paying anything or overriding a price.

## Agents

The suite lives in `backend/`. Run it from the `HW 5` folder with `py backend/run_suite.py` (all open tickets) or `py backend/run_suite.py --ticket 101` (one ticket). Every agent uses PydanticAI with `gpt-5.6-luna` through the course's Portkey gateway. Each agent's instructions are in `backend/prompts/<agent>.md`, and its structured output type is in `backend/models.py`.

| Agent | Role | MCP tools it can see | Returns |
|---|---|---|---|
| **boss** | Reads the open tickets, decides which specialist handles each, passes facts between them, sets ticket status, and writes the final report. The only agent that can change a ticket's status. | `list_open_tickets`, `get_ticket`, `update_ticket`, plus the local `delegate` tool | `BossReport`: run summary and one outcome per ticket |
| **inventory** | Stock levels, restock timing, and which vendor supplies what. Files restock purchases for a person to approve. | `get_ticket`, `get_inventory`, `stock_tracker`, `list_vendors`, `request_human_approval` (purchases only), `update_ticket` (notes only) | `SpecialistReport` |
| **accounting** | Bills due, payment approvals, and bulk-order pricing. | `get_ticket`, `invoice_reminder_and_payer` (no autopay), `bulk_order_discount`, `request_human_approval`, `update_ticket` (notes only) | `SpecialistReport` |
| **facilities** | The lease and the shop space: rent terms, due dates, landlord. | `get_ticket`, `get_lease`, `list_vendors`, `update_ticket` (notes only) | `SpecialistReport` |
| **customer_service** | Customer-facing answers: in or out of stock, delivery dates, reply drafts. | `get_ticket`, `stock_tracker`, `draft_customer_message`, `update_ticket` (notes only) | `SpecialistReport` |

**How the loop works:**
1. The boss lists the open tickets.
2. For each ticket it calls `delegate(specialist, ticket_id, task)`, which runs that specialist as its own agent with only its own tools.
3. The specialist returns a `SpecialistReport` to the boss. The report covers what it found, what it changed, any approval or draft IDs, and whether a person needs to act.
4. When one ticket needs two specialists, the boss passes the first report's facts into the second task. For example, accounting's quote goes to customer_service to draft the reply.
5. The boss sets each ticket's status and returns a `BossReport`.

`delegate` is the boss's only non-MCP tool. It runs another agent and never reads or writes shop data itself.

**Data types (`backend/models.py`):**
- `SpecialistReport` and `BossReport` / `TicketOutcome`: the agents' structured outputs.
- `AgentDeps`: who is acting, the run ID and the shared budget.
- `SuiteBudget`: token and delegation limits shared by every agent in a run.
- `AuditEvent`: one entry in the audit trail.

## MCP tools

All tools live in the FastMCP server `mcp_server/server.py`, which is connected to the project through `.mcp.json`. The agents connect through that same file. There is no other path to shop data.

R = reads, W = writes. Every tool also creates the three harness tables if they don't exist yet.

| Tool | What it does | Tables | Used by | Ticket |
|---|---|---|---|---|
| `stock_tracker` | In or out of stock for a SKU and size. When out, gives estimated delivery = vendor restock time + 1-day delivery, and flags an unpaid restock invoice. | R: `inventory`, `vendors`, `invoices`, `desk` | inventory, customer_service | #101 |
| `invoice_reminder_and_payer` | Lists overdue and upcoming bills with amounts and days until due. An employee can toggle autopay. | R: `invoices`, `vendors`, `leases`, `cash_accounts`, `desk`, `autopay_settings`. W (only when autopay is on): `payments`, `invoices`, `leases`, `cash_accounts`, `autopay_settings` | accounting (autopay blocked) | #102 |
| `bulk_order_discount` | Bulk price from two sources: a competitor benchmark and a margin floor. Recommends the lower discount and checks stock. | R: `pricing`, `inventory`, `vendors`, `invoices`, `desk`, plus `data/competitor_bulk_discounts.json` | accounting | #103 |
| `list_open_tickets` | Short list of unresolved tickets, oldest first. | R: `tickets` | boss | all |
| `get_ticket` | One ticket in full, with its linked lease or invoice and any approvals or drafts already filed. | R: `tickets`, `leases`, `invoices`, `vendors`, `approval_requests`, `customer_outbox`, `desk` | all agents | all |
| `update_ticket` | Appends a note, stamped with time and agent name, and optionally changes status. Notes are never overwritten. It won't set `resolved` while an approval is pending. | R/W: `tickets`. R: `approval_requests` | all agents (status: boss only) | all |
| `get_lease` | Lease terms and days until rent is due. | R: `leases`, `desk` | facilities | #102 |
| `list_vendors` | Vendors, their specialty and lead time. | R: `vendors` | inventory, facilities | #101, #103 |
| `get_inventory` | Stock by SKU and size with list price. It deliberately leaves out unit cost. | R: `inventory`, `pricing` (list price only) | inventory | #101, #103 |
| `request_human_approval` | Files a payment, purchase or price override for a person to approve. Payments are checked against the real bill; already-paid bills are refused. A purchase (SKU + qty) is priced by the server at unit cost and assigned to the right vendor. No duplicates. Returns what checking would be if every pending outflow were approved. **No money moves.** | R: `tickets`, `invoices`, `leases`, `pricing`, `vendors`, `cash_accounts`. R/W: `approval_requests` | accounting (all kinds), inventory (purchases only) | #101, #102, #103 |
| `draft_customer_message` | Saves a customer reply as a draft for review. Rejects drafts that mention internal details, and only addresses the ticket's own requester. **Nothing is sent.** | R: `tickets`. W: `customer_outbox` | customer_service | #101, #103 |
| `get_cash_balance` | Balance of every cash account. | R: `cash_accounts` | API only (no agent) | all |
| `list_approval_requests` | Approval requests the agents filed, pending by default. | R: `approval_requests` | API only (no agent) | all |
| `approve_payment` | **Human only.** Approves a pending request. **Payments and purchases** are paid from checking: the payment is recorded under the approver's name, the invoice is marked paid or rent's due date moves forward (a purchase just pays the vendor), checking drops, the request is marked approved, and the ticket gets a note. **Price overrides** are signed off with no cash moving. Refuses requests already approved and anything that would go below the cash reserve. | R/W: `approval_requests`, `payments`, `invoices`, `leases`, `cash_accounts`, `tickets`. R: `vendors` | API only (no agent) | #101, #102, #103 |

The last three tools are called only by the back-office API (`backend/main.py`). No agent's tool list includes them, and the guard blocks any agent that tries, so the only way cash leaves checking is a person approving through the API (or an employee-enabled autopay).

`list_open_tickets` also takes `include_resolved` (default false), which the API uses to show every ticket.

### Ticket tools: why each one is relevant

| Tool | Ticket | Why it's relevant |
|---|---|---|
| `stock_tracker` | **#101:** Tauhid Zaman wants a Classic Bulldog Tee in size S | Size S has 0 in stock, so the agent can't simply fill the order. The tool tells the customer it's out of stock and gives a real delivery date: Bulldog Print Co's 5-day reprint plus 1-day QuickShip delivery. It also shows that the restock depends on overdue invoice #501, which links this ticket to the shop's cash problem. |
| `invoice_reminder_and_payer` | **#102:** Elm City Properties says rent of $2,400 is due in 2 days | Rent isn't the only bill. Invoice #501 ($840) is already 3 days overdue, and together they leave only $160 of the $3,400 in checking. The tool puts every bill that's due in front of an employee, oldest first, so nothing is missed. Autopay only runs when an employee turns it on, every payment records who approved it (as the `payments` table requires), and it won't overdraw checking. |
| `bulk_order_discount` | **#103:** Yale AI Club wants 20 size M hoodies at a bulk discount | A discount request is a pricing decision the agent shouldn't make alone. The tool gives the employee two sources: what comparable sellers offer for bulk orders, and the deepest discount that keeps the margin above the employee's threshold. It recommends the safer of the two and shows that only 8 of the 20 hoodies are in stock. It never changes prices, so the final call stays with a person. |

### Ticket tool details

**`stock_tracker`**
- **Inputs:** `sku`, `size`, `qty` (default 1).
- **Out-of-stock logic:** estimated delivery = restock vendor lead time + local delivery (QuickShip CT, 1 day). Apparel restocks through Bulldog Print Co (5 days); mugs through Elm City Gifts (3 days).
- **Blocked restocks:** if an unpaid invoice covers that SKU and size (invoice #501 for the size S tee), the result shows the invoice and notes that the estimate assumes it's paid today.
- **Example:** size S tee is out of stock, with estimated delivery 2026-09-06 (5 + 1 days), blocked on invoice #501.

**`invoice_reminder_and_payer`**
- **Inputs:** `days_ahead` (default 7), `autopay` (true/false/omitted), `employee` (required when changing autopay).
- **Reminder:** lists open invoices and lease rent due by today + `days_ahead` (overdue items always included), oldest first, plus a plain-text notification.
- **When autopay is on:** pays oldest-due first. It records each payment in `payments` with `approved_by = "autopay (enabled by <employee>)"`, marks invoices paid, moves the lease's `next_due` forward one month, and lowers the checking balance. It skips any bill that would take checking below the cash reserve (`MIN_CASH_RESERVE`, currently $0).
- **Example:** invoice #501 ($840, 3 days overdue) and rent ($2,400, due in 2 days), totaling $3,240, which leaves $160.

**`bulk_order_discount`**
- **Inputs:** `sku`, `size`, `qty`, `margin_threshold_pct` (set by the employee), optional `requested_discount_pct`.
- **Source 1, competitors:** the median of published bulk discounts that apply to an order this size. Sources are cited in the JSON file; non-bulk student discounts are shown for context but excluded.
- **Source 2, margin floor:** floor price = unit cost ÷ (1 − threshold), and maximum discount = 1 − floor ÷ list price.
- **Recommendation:** the competitor benchmark, capped at the margin floor. It's always marked `requires_employee_approval`.
- **Example:** 20 size M hoodies at a 30% margin threshold. Competitors suggest 17.5% and the floor allows 45.8%, so it quotes 17.5%: $47.85 each, $957 total, 54% margin. Only 8 are in stock; the other 12 take about 6 days.

## Back-office API

`backend/main.py` (FastAPI). Start it from `backend/` with `uvicorn main:app --reload --port 8000`. Every route that needs shop data calls the MCP server.

- `GET /tickets`: every ticket and whether it's open or resolved.
- `POST /tickets/{ticket_id}/run`: runs the agent team (boss + specialists) on that one ticket and returns the boss's report.
- `GET /activity?run_id=&ticket_id=&since_seq=&full=`: recent agent events for the latest (or a chosen) run: what each agent said and which tools it used. `since_seq` returns only newer events so the board can poll; `full=true` returns raw events.
- `GET /approvals?status=pending`: the approval requests agents have filed for a person to act on.
- `POST /approvals/{approval_id}/approve` (body `{"approved_by": "<name>"}`): a person approves a pending request. A payment or purchase leaves checking; a price sign-off moves no cash. When the ticket has nothing left pending, it's marked `resolved`. This is the only route that changes cash.
- `GET /cash`: current balance of each account in `cash_accounts`.
- `POST /reset`: restores `campus_customs_new.db` from `campus_customs.db` for a fresh run. The audit trail is kept.

Approvals, resets and auto-resolves are written to the audit trail as `human_action` events. CORS allows requests from any `localhost` port, so the React dashboard can call the API from the browser; other origins are refused.

The API keeps one MCP connection open while it runs. On shutdown, closing it is capped at 3 seconds so a stuck subprocess can't hang a restart.

`--reload` restarts the server by sending it Ctrl+C, which only works when it runs in a normal terminal window. If it's launched in the background with no console, the reload never finishes; restart it by hand instead.

## Dashboard

`frontend/` (React + Vite + TypeScript). Start it from `frontend/` with `npm run dev` (http://localhost:5173). It calls the API at `http://localhost:8000`. The full design write-up is in `output/design.md`.

| Area | What it shows | API used |
|---|---|---|
| Tickets (left) | All three tickets with status pills (Open, Needs approval, ✓ Resolved), plus "N awaiting your approval". Clicking a ticket dispatches the team. | `GET /tickets`, `POST /tickets/{id}/run` |
| Stage (centre) | The cinematic: a letterbox title card, then the five agents as human figures huddle and split to their stations. While working, the active agent glows, a beam links the boss to whoever it delegated to, tool chips light up, and speech bubbles show what each agent said. | `GET /activity?since_seq=` polled about every second |
| Live feed (centre) | Every step in order: what agents said, tools used, delegations, and calls the harness blocked. | `GET /activity` |
| What each agent did (centre) | The boss's report and a "your move" to-do for the human, plus a card per agent with its final summary, tools used and blocked calls. | `GET /activity`, run result |
| Approvals (right) | Each queued request with amount, reason and "Checking after", and an **Approve & pay** button (payments and purchases) or **Sign off** (price overrides). | `GET /approvals`, `POST /approvals/{id}/approve` |
| Top bar | Checking balance, which flashes when it changes; the **Blind Box Dash** Labubu game for while agents work; Reset. | `GET /cash`, `POST /reset` |

Only one run can happen at a time; the other tickets are disabled while one runs. The approver's name is remembered in the browser.

## Audit trail

Every step of every run is appended to `output/audit_trail.json` as it happens. The file is a JSON array. Each run adds to the end of it, and earlier runs are never removed or rewritten. Each write goes to a temporary file that is then swapped in, so a crash can't corrupt earlier runs.

Every event records `run_id`, `seq` (order within the run), `timestamp`, `agent`, `parent_agent` (who delegated), `ticket_id`, `step`, `event`, `detail`, and `usage` (tokens) where relevant.

| Event | What's recorded |
|---|---|
| `run_start` | Scope (all tickets or one), model, MCP config, database, budgets |
| `agent_start` | The exact prompt the agent was given, its allowed tools, its limits |
| `model_request` | What went back to the model this step: tool results, retry messages |
| `model_response` | What the model decided: each tool call with its arguments, any text, and tokens for that step |
| `tool_call` | One MCP call: final arguments (after the guard), full result, whether it succeeded, duration in ms |
| `guard_block` | A call the harness stopped before it reached MCP, and the rule that stopped it |
| `delegation` | The boss handing a ticket to a specialist, with the task text |
| `agent_end` | The agent's structured output, its token usage, and the suite total so far |
| `error` | What failed and the error message |
| `run_end` | Final status, the boss's report, total tokens and delegations used |
| `human_action` | A person acting through the API: approving a payment or resetting the database |

Long tool results are clipped at 4,000 characters so the file stays readable.

## Stopping rules

- **Specialists:** each run stops after 6 model requests, 8 tool calls, or 25,000 tokens, whichever comes first.
- **Boss:** stops after 15 model requests, 20 tool calls, or 60,000 tokens.
- **Whole run:** has a shared budget of 150,000 tokens and 8 delegations. Once either is used up, `delegate` refuses and tells the boss to wrap up with what it has.
- **Failed specialist:** if a specialist errors or hits a limit, the boss gets an error back instead of a report and carries on with the other tickets.
- **Ticket status:** a ticket can't be marked `resolved` while it has a pending approval; it stays `waiting_approval`.
- **Tool errors:** a tool's error message (for example, an amount that doesn't match the bill) goes back to the agent so it can fix its call. If an MCP tool crashes outright, the agent's run stops instead of retrying in a loop.
- **Malformed calls:** each agent gets at most 1 retry for malformed output or an unknown tool name.

## Safety

Following the HW 4 approach, every rule below is either **asked of the model in a prompt** or **enforced in code**. Anything involving money or customers is enforced in code, so it holds even if a model ignores its prompt or a ticket contains text designed to mislead it.

### In the prompts (`backend/prompts/*.md` plus the line added to every agent)

- **All agents:** every shop fact must come from a tool; never guess a number.
- **Boss:**
  - Don't send the same ticket to the same specialist twice.
  - Only mark a ticket `resolved` when nothing is left for anyone to do.
  - Spell out what the human still has to do.
- **Accounting:**
  - It can't pay anything or turn autopay on or off.
  - File approval requests with exact amounts.
  - Say plainly when paying would leave cash dangerously low.
  - Recommend the tool's discount, not the customer's ask.
- **Inventory:** report quantities and dates exactly; it can't pay vendors or approve its own purchases.
- **Facilities:** don't contact the landlord or make promises for the shop; a person handles that conversation.
- **Customer service:**
  - Never tell a customer about costs, margins, invoices, cash or rent.
  - Never promise a date, price or discount that a tool or the boss didn't provide.
  - Every draft is reviewed by a person.

### Enforced in code: protecting real customers

- **Nothing is sent.** `draft_customer_message` only writes a `draft` row to `customer_outbox`, and there is no send tool. A person reviews and sends every message.
- **Internal details are blocked.** The server rejects any draft that mentions unit cost, margin, gross profit, invoices, autopay, the checking or cash balance, overdue bills, the landlord or rent. The match is on whole words.
- **Drafts go only to the requester.** The recipient must match the ticket's requester, so an agent can't write to another customer or mix up two customers' details.
- **Least data:**
  - customer_service sees only the ticket, stock and its draft tool.
  - `get_inventory` returns list price, never unit cost.
  - Facts such as stock, dates and prices are calculated server-side, so the model can't invent a delivery date or a price.
- **Honest dates:** `stock_tracker` says when a delivery date depends on an unpaid invoice, so the shop doesn't promise a date it can't keep.

### Enforced in code: handling real money

- **Only a person moves cash.**
  - Agents can only queue requests (`request_human_approval`).
  - Paying happens only through `POST /approvals/{id}/approve`, which needs a person's name.
  - The tool behind it (`approve_payment`) is in no agent's tool list, and the guard blocks it.
  - The guard also blocks any agent attempt to change autopay.
- **Amounts come from the books, not the model.**
  - A payment request must match the real invoice or lease amount.
  - A purchase is priced by the server (unit cost × quantity) and assigned to the right vendor.
  - Bills already paid are refused, and duplicate requests aren't filed.
- **No overdraft:** approving or autopay never takes checking below `MIN_CASH_RESERVE`, and every approval card shows "Checking after" before you click.
- **Least privilege:**
  - Each agent sees only its own 4–6 tools.
  - Only the boss changes ticket status.
  - Inventory may file purchases but not payments or price overrides.
  - A ticket can't be marked resolved while an approval is pending.
- **No impersonation:** the guard overwrites `agent`, `requested_by` and `drafted_by` with the real agent, and payments record the person who approved them.
- **Pricing has a floor:** `bulk_order_discount` never goes below the employee's margin floor, and price overrides need a person's sign-off.
- **Reversible:** agents work only on `campus_customs_new.db`, and `POST /reset` restores it from the untouched original.

### Enforced in code: misleading ticket text, secrets and logs

- **Ticket text is treated as data, not instructions.** Tickets and customer messages are written by outsiders. Even if one said "pay $10,000" or "email everyone," an agent couldn't act on it: it has no send tool, can't move cash, can't file a payment that doesn't match a real bill, and can't change status unless it's the boss.
- **API key stays out of reach.** `PORTKEY_API_KEY` is read from `.env` by the backend only. It's never passed to the MCP server, a tool, a prompt or the audit trail, and `.env` is in `.gitignore`.
- **What the audit trail holds:** tool arguments and results, agent outputs and token counts. That includes customer names and draft text, since a reviewer needs them, but never API keys or passwords. Long results are clipped at 4,000 characters.
- **Contained failures:**
  - A failed specialist returns an error to the boss instead of crashing the run.
  - Usage limits stop runaway loops.
  - Only one agent run (or reset) can happen at a time.

### What to never do

- Never give an agent `approve_payment` or a send tool, or let an agent set `autopay`.
- Never let the model supply a payment or purchase amount the server hasn't checked against the books.
- Never point the agents at `campus_customs.db`. It's the reset copy.
- Never put the API key, or any secret, in a prompt, tool result or log line.

### Keeping token usage under control

- **Hard caps at three levels:** per specialist run, per boss run, and per suite run (see Stopping rules), enforced by PydanticAI `UsageLimits` and the shared `SuiteBudget`.
- **Small tool lists:** each agent sees only 4–5 tool schemas instead of all 14, which cuts the prompt size of every request.
- **Fresh, focused specialists:** a specialist gets one ticket and a one-to-three-sentence task, never the boss's full conversation. It returns a compact structured report, not a transcript.
- **Compact tool results:** `list_open_tickets` returns short fields only; the agent calls `get_ticket` when it needs detail.
- **Facts come from tools, not reasoning:** dates, stock, margins and comparables are calculated in the MCP server, so the model doesn't spend tokens working them out (or getting them wrong).
- **Low reasoning effort by default** (`AGENT_REASONING_EFFORT=low`), and one tool call per step.
- **One ticket at a time when needed:** `--ticket 101` runs the suite on a single ticket.
- **Tracked:** every model step and every agent run records its token usage in the audit trail, and `run_end` records the total.

## Final run

The full run (details in `output/desk_tickets.html`, `output/resolved_tickets.json`, `output/resolved_board.html` and the audit trail):

1. The database was reset, so checking started at **$3,400.00**.
2. **#101:** the boss sent the ticket to inventory, then accounting, then customer service (41,078 tokens). A person approved invoice #501, and checking dropped **$840 → $2,560**. The ticket resolved.
3. **#102:** the first run used facilities only and queued nothing to approve. On a second run the boss sent it to accounting, which queued the rent (34k tokens in total). A person approved the rent, and checking dropped **$2,400 → $160**. The ticket resolved.
4. **#103:** the boss sent it to accounting only (21,457 tokens). A person signed off the $957 quote, and **no cash moved**. The ticket resolved.
5. The run ended at **$160.00**, which matches `cash_accounts` in the working database.

What the run showed:
- **The guard works.** Every specialist tried to set ticket status and was blocked (1 attempt each), then fell back to adding a note.
- **The boss sometimes delegates too little.** It skipped facilities' hand-off to accounting on #102's first run, and inventory and customer service on #103. Customer replies and the 12-hoodie restock for #103 are still to do.
- **Cash is too tight for the restock.** The $264 restock wouldn't fit in the $160 left, so the overdraft guard would have refused it.
