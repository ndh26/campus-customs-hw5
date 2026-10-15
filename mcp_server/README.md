# Campus Customs MCP Server

An MCP server, built with [FastMCP](https://gofastmcp.com), that gives AI agents everything they need to work the Campus Customs shop's open tickets. It has 14 tools:

- **Three ticket tools:** checking stock, staying on top of bills, and pricing bulk orders. Each addresses one open ticket.
- **Eight shared tools:** used by the agent suite in `backend/` to read and update tickets, look up leases, vendors and inventory, queue payments for human approval, and draft customer replies.
- **Three human-only tools:** used by the back-office API (`backend/main.py`) to show cash and pending approvals, and to pay a bill once a person approves it. No agent is given these.

The agents get all shop data through this server; nothing else reads the database.

## Running it

```bash
pip install -r mcp_server/requirements.txt
py mcp_server/server.py
```

Run these from the `HW 5` folder. The server talks over stdio, so it's meant to be launched by an MCP client rather than used directly.

The connection is saved in the project's `.mcp.json` as the server `campus-customs`.
- **Claude Code** picks it up when opened from `HW 5`.
- **The agent suite** (`backend/agents.py`) connects through the same file.
- **`smoke_test.py`** connects the same way to run one tool at a time and log the result to `output/mcp_smoke.json`:

```bash
py mcp_server/smoke_test.py connect
py mcp_server/smoke_test.py stock_tracker '{"sku": "CC-TEE-WHITE", "size": "S"}' "Customer clicks size S"
```

## Database

| File | Role |
|---|---|
| `data/campus_customs_new.db` | The working database. Every tool reads from it. Four tools write to it: `invoice_reminder_and_payer` (autopay only), `update_ticket`, `request_human_approval` and `draft_customer_message`. |
| `data/campus_customs.db` | The original database as provided. The server never opens it, so it can always be used to reset the working copy. |
| `data/competitor_bulk_discounts.json` | Published bulk-discount policies from comparable sellers, with source links. Used by `bulk_order_discount`. |

To point the server at a different database file (for example, a scratch copy for testing), set the `CAMPUS_DB` environment variable.

The shop's "today" is read from the `desk` table (currently 2026-08-31), not from the computer's clock, so due dates and delivery estimates stay consistent with the data.

The tools use the shop's tables: `desk`, `inventory`, `pricing`, `vendors`, `invoices`, `leases`, `cash_accounts`, `payments` and `tickets`. The server also creates three tables of its own the first time a tool runs:

| Table | Purpose |
|---|---|
| `autopay_settings` | Whether autopay is on, who turned it on, and when |
| `approval_requests` | Payments and price overrides waiting for a person to approve |
| `customer_outbox` | Customer reply drafts. Nothing in it is ever sent. |

## Tools

| Tool | What it does | Tables (R = read, W = write) |
|---|---|---|
| `stock_tracker` | In or out of stock for a SKU and size, with delivery estimate when out | R: `inventory`, `vendors`, `invoices`, `desk` |
| `invoice_reminder_and_payer` | Bills overdue or due soon; employee-controlled autopay | R: `invoices`, `vendors`, `leases`, `cash_accounts`, `desk`, `autopay_settings`. W (autopay only): `payments`, `invoices`, `leases`, `cash_accounts`, `autopay_settings` |
| `bulk_order_discount` | Bulk price from competitor comparables and a margin floor | R: `pricing`, `inventory`, `vendors`, `invoices`, `desk` |
| `list_open_tickets` | Unresolved tickets, short fields | R: `tickets` |
| `get_ticket` | One ticket with its linked lease/invoice, approvals and drafts | R: `tickets`, `leases`, `invoices`, `vendors`, `approval_requests`, `customer_outbox`, `desk` |
| `update_ticket` | Append a note; optionally change status | R/W: `tickets`. R: `approval_requests` |
| `get_lease` | Lease terms and days until rent is due | R: `leases`, `desk` |
| `list_vendors` | Vendors, specialty, lead time | R: `vendors` |
| `get_inventory` | Stock by SKU and size with list price (no unit cost) | R: `inventory`, `pricing` |
| `request_human_approval` | Queue a payment, purchase or price override for a person | R: `tickets`, `invoices`, `leases`, `pricing`, `vendors`, `cash_accounts`. R/W: `approval_requests` |
| `draft_customer_message` | Save a customer reply as a draft | R: `tickets`. W: `customer_outbox` |
| `get_cash_balance` | Balance of every cash account (API only) | R: `cash_accounts` |
| `list_approval_requests` | Approval requests, pending by default (API only) | R: `approval_requests` |
| `approve_payment` | A person approves a queued payment or purchase (paid from checking) or signs off a price override (no cash) (API only) | R/W: `approval_requests`, `payments`, `invoices`, `leases`, `cash_accounts`, `tickets`. R: `vendors` |

## Ticket tools

### `stock_tracker` (Ticket #101)

Checks whether a product is in stock in the size the customer picked.

| Input | Description |
|---|---|
| `sku` | Product SKU, e.g. `CC-TEE-WHITE` |
| `size` | `S`, `M`, `L`, `XL`, or `OS` (one size) |
| `qty` | How many the customer wants (default 1) |

- **In stock:** returns how many are available.
- **Out of stock, or not enough on hand:** returns an estimated delivery date. The estimate is the vendor's restock time (Bulldog Print Co: 5 days for apparel; Elm City Gifts: 3 days for mugs) plus 1 day of delivery by QuickShip CT.
- **Restock waiting on payment:** if an unpaid vendor invoice covers that item, the tool flags it, because the restock won't ship until the invoice is paid.
- **Unknown product or size:** returns an error listing the sizes that exist.

Read-only.

### `invoice_reminder_and_payer` (Ticket #102)

For employees. Lists bills that are overdue or due soon and can pay them automatically.

| Input | Description |
|---|---|
| `days_ahead` | Include bills due within this many days (default 7). Overdue bills are always included. |
| `autopay` | `true` to turn autopay on, `false` to turn it off, or leave it out to keep the current setting |
| `employee` | Name of the employee changing autopay (required when `autopay` is set) |

- Covers open vendor invoices and lease rent, sorted oldest-due first.
- Returns each bill's payee, amount, due date and days until due, plus a plain-text notification for the employee.
- **With autopay on**, it pays each bill in order as long as checking stays above the cash reserve (`MIN_CASH_RESERVE` in `server.py`, currently $0). For each payment it:
  - records the payment in `payments`, crediting the employee who turned autopay on
  - marks the invoice paid, or moves the lease's next due date forward a month
  - lowers the checking balance
- Bills that would overdraw the account are skipped and reported.
- Turning autopay on also pays whatever is already due in that same call.

This is the only tool that moves money. The agent suite's harness blocks agents from setting `autopay`, so only an employee can turn it on.

### `bulk_order_discount` (Ticket #103)

Prices a bulk order using two sources, for an employee to approve.

| Input | Description |
|---|---|
| `sku`, `size`, `qty` | The order |
| `margin_threshold_pct` | The lowest gross margin the employee will accept, e.g. `50` for 50% |
| `requested_discount_pct` | Optional: the discount the customer asked for |

- **Competitor source:** the median discount from published bulk-discount policies that apply to an order this size, read from `data/competitor_bulk_discounts.json`. Student discounts and promotions are shown for context but don't count toward the benchmark.
- **Margin source:** the deepest discount that keeps the margin at or above the threshold:
  - floor price = unit cost ÷ (1 − threshold)
  - maximum discount = 1 − floor price ÷ list price
- **Recommendation:** the competitor discount, capped at the margin limit.
- Also returns how the customer's requested discount compares with both sources, and the stock on hand with a restock estimate for any shortfall.

Read-only. Every result is marked `requires_employee_approval`.

## Shared tools for the agent suite

### `list_open_tickets`

Optional input `include_resolved` (default false). Returns every ticket that isn't `resolved` (or every ticket, if set), oldest first, with only its id, type, requester, subject, status and creation time. Kept short to save tokens; use `get_ticket` for detail. Read-only.

### `get_ticket`

| Input | Description |
|---|---|
| `ticket_id` | e.g. `101` |

Returns the full ticket plus the shop's today, the linked lease or invoice (with vendor name), and any approval requests and customer drafts already filed for it. Read-only.

### `update_ticket`

| Input | Description |
|---|---|
| `ticket_id` | The ticket |
| `agent` | Who is writing the note |
| `note` | One or two sentences |
| `status` | Optional: `open`, `in_progress`, `waiting_approval` or `resolved` |

- Appends `[timestamp agent] note` to the ticket's notes; earlier notes are never overwritten.
- Refuses `resolved` while the ticket has a pending approval request.
- In the agent suite, only the boss may change status, and `agent` is always set to the real acting agent.

### `get_lease`

| Input | Description |
|---|---|
| `lease_id` | e.g. `1` |

Returns the lease (space, landlord, monthly rent, next due date, notes) plus days until rent is due. Read-only.

### `list_vendors`

No inputs. Returns every vendor's name, specialty and lead time in days. Read-only.

### `get_inventory`

| Input | Description |
|---|---|
| `sku` | Optional; leave out for the whole shop |

Returns stock by SKU and size with location and list price. Unit cost is deliberately left out. Read-only.

### `request_human_approval`

| Input | Description |
|---|---|
| `ticket_id` | The ticket this is for |
| `kind` | `invoice_payment`, `rent_payment`, `purchase` or `price_override` |
| `details` | What the person is approving and why |
| `requested_by` | The agent filing it |
| `amount` | The bill amount, or the quoted order total for a price override. Leave at 0 for a purchase. |
| `ref_id` | Invoice id for `invoice_payment`, lease id for `rent_payment` |
| `sku`, `qty` | For a `purchase`: what to restock and how many |

- Adds a `pending` row to `approval_requests`. **No money moves and no price changes.**
- Payment requests are checked first. The amount must match the real invoice or lease rent, and a bill that's already paid is refused.
- A purchase is priced by the server: unit cost × qty, assigned to the vendor that restocks that SKU. Example: 12 navy hoodies = 12 × $22 = $264 from Bulldog Print Co.
- The same pending request isn't filed twice.
- For payments and purchases, it returns the checking balance and what checking would be if every pending outflow were approved.

### `draft_customer_message`

| Input | Description |
|---|---|
| `ticket_id` | The ticket this reply is for |
| `to_name` | Must match the ticket's requester |
| `subject`, `body` | The message |
| `drafted_by` | The agent drafting it |

- Saves the message to `customer_outbox` with status `draft`. **Nothing is ever sent**; a person reviews it.
- Rejects any draft that mentions internal details: unit cost, margin, gross profit, invoices, autopay, checking or cash balance, overdue bills, the landlord or rent.
- Rejects any draft addressed to anyone other than the ticket's requester.

## Human-only tools (back-office API)

These are called by `backend/main.py` when a person uses the API. None of them is in any agent's tool list, and the agent harness blocks them.

### `get_cash_balance`

No inputs. Returns each account in `cash_accounts` with its balance and date. Read-only.

### `list_approval_requests`

| Input | Description |
|---|---|
| `status` | `pending` (default), `approved`, or null for all |

Returns approval requests, newest first. Read-only.

### `approve_payment`

| Input | Description |
|---|---|
| `approval_request_id` | The request to approve |
| `approved_by` | The name of the person approving |

- Pays a pending `invoice_payment`, `rent_payment` or `purchase` from checking.
- Records the payment in `payments` under the approver's name.
- Marks the invoice paid, or moves the lease's next due date forward a month. A purchase just pays the vendor.
- Lowers the checking balance, marks the request `approved`, and adds a note to the ticket.
- For a `price_override`, records the sign-off on the request and the ticket. No cash moves.
- Refuses requests that are already approved, and any payment that would take checking below the cash reserve.

## Files

| File | Purpose |
|---|---|
| `server.py` | The MCP server and all 14 tools |
| `smoke_test.py` | Connects through `.mcp.json`, runs one tool, and logs the prompt, tool and output to `output/mcp_smoke.json` |
| `requirements.txt` | Python dependencies (`fastmcp`) |
