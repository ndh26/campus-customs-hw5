"""Campus Customs MCP server.

Ticket tools:
  stock_tracker              - in/out of stock for a SKU + size, with delivery ETA when out
  invoice_reminder_and_payer - what's due and when, with an autopay toggle
  bulk_order_discount        - bulk pricing from competitor comparables and a margin floor

Shared tools for the agent suite:
  list_open_tickets, get_ticket, update_ticket, get_lease, list_vendors, get_inventory,
  request_human_approval  - queues a payment or price override for a person; moves no money
  draft_customer_message  - saves a draft for review; nothing is ever sent

Human-only tools (called by backend/main.py; no agent is given them):
  get_cash_balance, list_approval_requests,
  approve_payment         - a person approves a queued payment and it is paid from checking

Run (stdio):  py mcp_server/server.py
The server works on data/campus_customs_new.db; the original campus_customs.db is never touched.
Set CAMPUS_DB to point at a different file (e.g. for tests).
"""

import json
import os
import re
import sqlite3
import statistics
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastmcp import FastMCP

HW_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("CAMPUS_DB", HW_DIR / "data" / "campus_customs_new.db"))
COMPETITORS_PATH = HW_DIR / "data" / "competitor_bulk_discounts.json"

# Which vendor restocks which product line (matched on SKU prefix), and who delivers to the customer.
RESTOCK_VENDOR_BY_PREFIX = {
    "CC-HOOD": "Bulldog Print Co",
    "CC-TEE": "Bulldog Print Co",
    "CC-HAT": "Bulldog Print Co",
    "CC-MUG": "Elm City Gifts",
}
DELIVERY_VENDOR = "QuickShip CT"

# Autopay never drains checking below this amount.
MIN_CASH_RESERVE = 0.0

# Ticket statuses agents may set. Nothing here closes out money: payments and price
# overrides stay 'waiting_approval' until a human acts on the approval_requests row.
TICKET_STATUSES = {"open", "in_progress", "waiting_approval", "resolved"}

# Internal-only terms that must never appear in a message drafted for a customer.
CUSTOMER_BLOCKLIST = ("unit cost", "unit_cost", "margin", "gross profit", "invoice", "autopay",
                      "checking", "cash balance", "overdue", "landlord", "rent")

mcp = FastMCP("campus-customs")


# ---------- helpers ----------

@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open the shop database for one tool call: commit on success, roll back on error, always close."""
    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_tables(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS autopay_settings (
               id INTEGER PRIMARY KEY CHECK (id = 1),
               enabled INTEGER NOT NULL,
               set_by TEXT NOT NULL,
               set_at TEXT NOT NULL
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS approval_requests (
               id INTEGER PRIMARY KEY,
               ticket_id INTEGER NOT NULL,
               kind TEXT NOT NULL,
               ref_id INTEGER,
               sku TEXT,
               qty INTEGER,
               amount REAL NOT NULL,
               details TEXT NOT NULL,
               requested_by TEXT NOT NULL,
               status TEXT NOT NULL DEFAULT 'pending',
               created_at TEXT NOT NULL,
               FOREIGN KEY (ticket_id) REFERENCES tickets(id)
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS customer_outbox (
               id INTEGER PRIMARY KEY,
               ticket_id INTEGER NOT NULL,
               to_name TEXT NOT NULL,
               subject TEXT NOT NULL,
               body TEXT NOT NULL,
               drafted_by TEXT NOT NULL,
               status TEXT NOT NULL DEFAULT 'draft',
               created_at TEXT NOT NULL,
               FOREIGN KEY (ticket_id) REFERENCES tickets(id)
           )"""
    )
    # Databases created before purchases were supported lack these columns.
    have = {r[1] for r in conn.execute("PRAGMA table_info(approval_requests)")}
    for column, sql_type in (("sku", "TEXT"), ("qty", "INTEGER")):
        if column not in have:
            conn.execute(f"ALTER TABLE approval_requests ADD COLUMN {column} {sql_type}")


def shop_today(conn: sqlite3.Connection) -> date:
    """The shop's 'today' comes from the desk table, not the wall clock."""
    row = conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    return date.fromisoformat(row["date_today"]) if row else date.today()


def vendor(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    return conn.execute("SELECT * FROM vendors WHERE name = ?", (name,)).fetchone()


def restock_vendor_for(conn: sqlite3.Connection, sku: str) -> sqlite3.Row | None:
    for prefix, name in RESTOCK_VENDOR_BY_PREFIX.items():
        if sku.startswith(prefix):
            return vendor(conn, name)
    return None


def open_restock_invoice(conn: sqlite3.Connection, sku: str, size: str) -> sqlite3.Row | None:
    """An unpaid vendor invoice that covers restocking this SKU/size (e.g. #501 for the size S tee)."""
    for inv in conn.execute("SELECT * FROM invoices WHERE status != 'paid'"):
        desc = (inv["description"] or "").split()
        if sku in desc and size in desc:
            return inv
    return None


def restock_eta(conn: sqlite3.Connection, sku: str, size: str) -> dict:
    """Days until a customer could have the item: vendor restock lead + local delivery."""
    today = shop_today(conn)
    restocker = restock_vendor_for(conn, sku)
    courier = vendor(conn, DELIVERY_VENDOR)
    restock_days = restocker["lead_days"] if restocker else None
    delivery_days = courier["lead_days"] if courier else 0
    blocking = open_restock_invoice(conn, sku, size)

    if restock_days is None:
        return {"estimate_available": False, "reason": f"No restock vendor on file for {sku}."}

    total = restock_days + delivery_days
    eta = {
        "estimate_available": True,
        "restock_vendor": restocker["name"],
        "restock_days": restock_days,
        "delivery_vendor": courier["name"] if courier else None,
        "delivery_days": delivery_days,
        "total_days": total,
        "estimated_delivery_date": (today + timedelta(days=total)).isoformat(),
    }
    if blocking:
        overdue = (today - date.fromisoformat(blocking["due_date"])).days
        eta["blocked_by_invoice"] = {
            "invoice_id": blocking["id"],
            "amount": blocking["amount"],
            "due_date": blocking["due_date"],
            "days_overdue": max(overdue, 0),
        }
        eta["note"] = (
            f"Restock is waiting on unpaid invoice #{blocking['id']} (${blocking['amount']:,.2f}). "
            f"The estimate assumes it is paid today; each day it stays unpaid pushes delivery back a day."
        )
    return eta


def add_month(d: date) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(d)


# ---------- tool 1: stock tracker ----------

def check_stock(conn: sqlite3.Connection, sku: str, size: str, qty: int) -> dict:
    """Stock status for a SKU/size, with restock ETA when short. Shared by both customer-facing tools."""
    row = conn.execute(
        "SELECT * FROM inventory WHERE sku = ? AND size = ?", (sku, size)
    ).fetchone()
    if row is None:
        sizes = [r["size"] for r in conn.execute("SELECT size FROM inventory WHERE sku = ?", (sku,))]
        if not sizes:
            return {"error": f"Unknown SKU {sku}."}
        return {"error": f"{sku} doesn't come in size {size}.", "available_sizes": sizes}

    on_hand = row["qty"]
    result = {
        "sku": sku,
        "name": row["name"],
        "size": size,
        "requested_qty": qty,
        "on_hand": on_hand,
        "in_stock": on_hand >= qty,
    }
    if on_hand >= qty:
        result["message"] = f"{row['name']} in size {size} is in stock ({on_hand} available)."
        return result

    eta = restock_eta(conn, sku, size)
    result["shortfall"] = qty - on_hand
    result["restock"] = eta
    if on_hand == 0:
        lead = "Out of stock"
    else:
        lead = f"Only {on_hand} in stock, short {qty - on_hand}"
    if eta.get("estimate_available"):
        result["message"] = (
            f"{lead} for {row['name']} in size {size}. Estimated delivery: "
            f"{eta['estimated_delivery_date']} (about {eta['total_days']} days: "
            f"{eta['restock_days']} to restock + {eta['delivery_days']} to deliver)."
        )
    else:
        result["message"] = f"{lead} for {row['name']} in size {size}. No restock estimate available."
    return result


@mcp.tool
def stock_tracker(sku: str, size: str, qty: int = 1) -> dict:
    """Check whether a product is in stock in the size the customer picked.

    Call this when a customer selects a product and size. If the size is out of stock
    (or there aren't enough for the requested qty), returns an estimated delivery date
    that includes vendor restock time plus local delivery.

    Args:
        sku: Product SKU, e.g. "CC-TEE-WHITE".
        size: Size code: S, M, L, XL, or OS (one size).
        qty: How many the customer wants. Defaults to 1.
    """
    if qty < 1:
        return {"error": "qty must be at least 1."}
    with connect() as conn:
        return check_stock(conn, sku.strip().upper(), size.strip().upper(), qty)


# ---------- tool 2: invoice reminder and payer ----------

@mcp.tool
def invoice_reminder_and_payer(
    days_ahead: int = 7,
    autopay: bool | None = None,
    employee: str | None = None,
) -> dict:
    """List bills that are overdue or due soon, and optionally turn autopay on or off.

    For employees, not customers. Covers open vendor invoices and lease rent. When autopay
    is on, everything in the window is paid oldest-due first, as long as checking stays
    above the cash reserve; anything that doesn't fit is left unpaid and flagged.

    Args:
        days_ahead: Include bills due within this many days of the shop's today. Overdue bills are always included.
        autopay: True to turn autopay on, False to turn it off, omit to leave it as is.
        employee: Name of the employee changing the autopay setting. Required when autopay is set.
    """
    with connect() as conn:
        today = shop_today(conn)
        horizon = today + timedelta(days=days_ahead)

        if autopay is not None:
            if not employee or not employee.strip():
                return {"error": "An employee name is required to change autopay."}
            conn.execute(
                "INSERT OR REPLACE INTO autopay_settings (id, enabled, set_by, set_at) VALUES (1, ?, ?, ?)",
                (int(autopay), employee.strip(), datetime.now().isoformat(timespec="seconds")),
            )
        setting = conn.execute("SELECT * FROM autopay_settings WHERE id = 1").fetchone()
        autopay_on = bool(setting and setting["enabled"])

        due = []
        for inv in conn.execute(
            "SELECT i.*, v.name AS vendor FROM invoices i JOIN vendors v ON v.id = i.vendor_id "
            "WHERE i.status != 'paid' AND i.due_date <= ?",
            (horizon.isoformat(),),
        ):
            due.append({
                "kind": "invoice", "ref_id": inv["id"], "payee": inv["vendor"],
                "amount": inv["amount"], "due_date": inv["due_date"], "description": inv["description"],
            })
        for lease in conn.execute("SELECT * FROM leases WHERE next_due <= ?", (horizon.isoformat(),)):
            due.append({
                "kind": "rent", "ref_id": lease["id"], "payee": lease["landlord"],
                "amount": lease["monthly_rent"], "due_date": lease["next_due"],
                "description": f"Rent for {lease['space_name']}",
            })
        due.sort(key=lambda b: b["due_date"])
        for b in due:
            days = (date.fromisoformat(b["due_date"]) - today).days
            b["days_until_due"] = days
            b["status"] = "overdue" if days < 0 else "due today" if days == 0 else "upcoming"

        account = conn.execute("SELECT * FROM cash_accounts WHERE name = 'checking'").fetchone()
        balance = account["balance"]
        total_due = sum(b["amount"] for b in due)

        paid, skipped = [], []
        if autopay_on:
            approver = f"autopay (enabled by {setting['set_by']})"
            for b in due:
                if balance - b["amount"] < MIN_CASH_RESERVE:
                    skipped.append({**b, "reason": f"Would take checking below ${MIN_CASH_RESERVE:,.2f} reserve."})
                    continue
                balance -= b["amount"]
                conn.execute(
                    "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
                    "VALUES (?, ?, ?, 'checking', ?, ?)",
                    (b["kind"], b["ref_id"], b["amount"], today.isoformat(), approver),
                )
                if b["kind"] == "invoice":
                    conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (b["ref_id"],))
                else:
                    next_due = add_month(date.fromisoformat(b["due_date"]))
                    conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (next_due.isoformat(), b["ref_id"]))
                paid.append(b)
            conn.execute(
                "UPDATE cash_accounts SET balance = ?, date = ? WHERE name = 'checking'",
                (balance, today.isoformat()),
            )

        lines = [f"{len(due)} bill(s) due by {horizon.isoformat()}, totaling ${total_due:,.2f}."]
        for b in due:
            when = (f"{-b['days_until_due']} day(s) overdue" if b["days_until_due"] < 0
                    else "due today" if b["days_until_due"] == 0
                    else f"due in {b['days_until_due']} day(s)")
            lines.append(f"- {b['payee']}: ${b['amount']:,.2f}, {when} ({b['due_date']}).")
        if autopay_on:
            lines.append(f"Autopay paid {len(paid)}, skipped {len(skipped)}. Checking is now ${balance:,.2f}.")
        else:
            left = account["balance"] - total_due
            lines.append(f"Autopay is off. Checking is ${account['balance']:,.2f}; ${left:,.2f} left if all are paid.")

        return {
            "shop_today": today.isoformat(),
            "autopay": {
                "enabled": autopay_on,
                "set_by": setting["set_by"] if setting else None,
                "set_at": setting["set_at"] if setting else None,
            },
            "bills": due,
            "total_due": total_due,
            "checking_balance": balance,
            "paid": paid,
            "skipped": skipped,
            "notification": "\n".join(lines),
        }


# ---------- tool 3: bulk order discount ----------

def competitor_comparables(qty: int, order_value: float) -> dict:
    data = json.loads(COMPETITORS_PATH.read_text(encoding="utf-8"))
    matches, context = [], []
    for comp in data["competitors"]:
        best = None
        for tier in comp["tiers"]:
            if qty >= tier.get("min_qty", 0) and order_value >= tier.get("min_order_value", 0):
                if best is None or tier["discount_pct"] > best["discount_pct"]:
                    best = tier
        if best is None:
            continue
        entry = {"name": comp["name"], "discount_pct": best["discount_pct"], "url": comp["url"], "note": comp["note"]}
        (matches if comp["bulk"] else context).append(entry)
    pcts = [m["discount_pct"] for m in matches]
    return {
        "benchmark_discount_pct": round(statistics.median(pcts), 1) if pcts else None,
        "comparables": matches,
        "not_bulk_context": context,
    }


@mcp.tool
def bulk_order_discount(
    sku: str,
    size: str,
    qty: int,
    margin_threshold_pct: float,
    requested_discount_pct: float | None = None,
) -> dict:
    """Price a customer's bulk order from two sources, for an employee to approve.

    Source 1 (competitors): the median bulk discount that comparable sellers publish for an
    order of this size. Source 2 (margin floor): the deepest discount that still keeps the
    gross margin at or above the employee's threshold. The recommendation is the competitor
    benchmark, capped by the margin floor. Nothing is written; an employee approves the final price.

    Args:
        sku: Product SKU, e.g. "CC-HOOD-NAVY".
        size: Size code: S, M, L, XL, or OS.
        qty: Number of units in the bulk order.
        margin_threshold_pct: Minimum gross margin the employee will accept, e.g. 50 for 50%.
        requested_discount_pct: The discount the customer asked for, if any, to check against both sources.
    """
    if qty < 1:
        return {"error": "qty must be at least 1."}
    if not 0 <= margin_threshold_pct < 100:
        return {"error": "margin_threshold_pct must be between 0 and 100."}
    sku, size = sku.strip().upper(), size.strip().upper()
    with connect() as conn:
        price = conn.execute("SELECT * FROM pricing WHERE sku = ?", (sku,)).fetchone()
        if price is None:
            return {"error": f"No pricing on file for {sku}."}
        stock = check_stock(conn, sku, size, qty)
        if "error" in stock:
            return stock

    list_price, unit_cost = price["list_price"], price["unit_cost"]
    order_value = list_price * qty

    # Source 1: competitors
    comp = competitor_comparables(qty, order_value)

    # Source 2: margin floor. margin = (p - cost) / p  =>  p_floor = cost / (1 - m)
    m = margin_threshold_pct / 100
    floor_price = unit_cost / (1 - m)
    max_discount_pct = max(0.0, (1 - floor_price / list_price) * 100)
    margin_source = {
        "unit_cost": unit_cost,
        "list_price": list_price,
        "list_margin_pct": round((list_price - unit_cost) / list_price * 100, 1),
        "margin_threshold_pct": margin_threshold_pct,
        "floor_unit_price": round(floor_price, 2),
        "max_discount_pct": round(max_discount_pct, 1),
    }

    def quote(discount_pct: float) -> dict:
        unit = list_price * (1 - discount_pct / 100)
        return {
            "discount_pct": round(discount_pct, 1),
            "unit_price": round(unit, 2),
            "order_total": round(unit * qty, 2),
            "gross_margin_pct": round((unit - unit_cost) / unit * 100, 1) if unit else None,
            "gross_profit": round((unit - unit_cost) * qty, 2),
        }

    bench = comp["benchmark_discount_pct"]
    if floor_price >= list_price:
        rec_pct, why = 0.0, "List price is already at or below the margin threshold; no discount available."
    elif bench is None:
        rec_pct, why = max_discount_pct, "No competitor comparables apply; using the margin floor."
    elif bench <= max_discount_pct:
        rec_pct, why = bench, "Matches the competitor benchmark, which stays above the margin threshold."
    else:
        rec_pct, why = max_discount_pct, "Competitor benchmark would break the margin threshold; capped at the margin floor."

    result = {
        "sku": sku,
        "size": size,
        "qty": qty,
        "order_value_at_list": round(order_value, 2),
        "source_competitors": comp,
        "source_margin_floor": margin_source,
        "recommended": {**quote(rec_pct), "reason": why},
        "stock": {
            "on_hand": stock.get("on_hand"),
            "can_fill_now": stock.get("in_stock"),
            "shortfall": stock.get("shortfall", 0),
            "restock": stock.get("restock"),
        },
        "requires_employee_approval": True,
    }
    if requested_discount_pct is not None:
        req = quote(requested_discount_pct)
        req["within_margin_threshold"] = requested_discount_pct <= max_discount_pct + 1e-9
        req["vs_competitor_benchmark"] = (
            None if bench is None else
            "above" if requested_discount_pct > bench else "at or below"
        )
        result["requested"] = req
    return result


# ---------- shared tools for the agent suite ----------

@mcp.tool
def list_open_tickets(include_resolved: bool = False) -> list[dict]:
    """List every ticket that isn't resolved, oldest first. Short fields only; use get_ticket for detail.

    Args:
        include_resolved: Also include resolved tickets. Defaults to False.
    """
    where = "" if include_resolved else "WHERE status != 'resolved' "
    with connect() as conn:
        return [
            {k: r[k] for k in ("id", "type", "requester", "subject", "status", "created_at")}
            for r in conn.execute(f"SELECT * FROM tickets {where}ORDER BY created_at")
        ]


@mcp.tool
def get_ticket(ticket_id: int) -> dict:
    """Full detail for one ticket, plus the lease or invoice it links to and any approvals or drafts already filed.

    Args:
        ticket_id: The ticket number, e.g. 101.
    """
    with connect() as conn:
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return {"error": f"No ticket #{ticket_id}."}
        out = dict(t)
        out["shop_today"] = shop_today(conn).isoformat()
        if t["lease_id"]:
            out["lease"] = dict(conn.execute("SELECT * FROM leases WHERE id = ?", (t["lease_id"],)).fetchone())
        if t["invoice_id"]:
            out["invoice"] = dict(conn.execute(
                "SELECT i.*, v.name AS vendor FROM invoices i JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?",
                (t["invoice_id"],),
            ).fetchone())
        out["approval_requests"] = [dict(r) for r in conn.execute(
            "SELECT id, kind, amount, status, requested_by FROM approval_requests WHERE ticket_id = ?", (ticket_id,))]
        out["customer_drafts"] = [dict(r) for r in conn.execute(
            "SELECT id, subject, status, drafted_by FROM customer_outbox WHERE ticket_id = ?", (ticket_id,))]
        return out


@mcp.tool
def update_ticket(ticket_id: int, agent: str, note: str, status: str | None = None) -> dict:
    """Add a note to a ticket and optionally change its status. Notes are appended, never overwritten.

    Args:
        ticket_id: The ticket number.
        agent: Name of the agent writing the note, e.g. "boss".
        note: One or two sentences on what was done or decided.
        status: Optional new status: open, in_progress, waiting_approval, or resolved.
    """
    if status is not None and status not in TICKET_STATUSES:
        return {"error": f"status must be one of {sorted(TICKET_STATUSES)}."}
    with connect() as conn:
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return {"error": f"No ticket #{ticket_id}."}
        if status == "resolved":
            pending = conn.execute(
                "SELECT COUNT(*) FROM approval_requests WHERE ticket_id = ? AND status = 'pending'", (ticket_id,)
            ).fetchone()[0]
            if pending:
                return {"error": f"Ticket #{ticket_id} has {pending} pending approval(s); use waiting_approval instead."}
        stamp = datetime.now().isoformat(timespec="seconds")
        notes = ((t["notes"] or "") + f"\n[{stamp} {agent}] {note.strip()}").strip()
        new_status = status or t["status"]
        conn.execute("UPDATE tickets SET notes = ?, status = ? WHERE id = ?", (notes, new_status, ticket_id))
        return {"ticket_id": ticket_id, "status": new_status, "note_added": note.strip()}


@mcp.tool
def get_lease(lease_id: int) -> dict:
    """Lease terms for a space: landlord, monthly rent, next due date, and days until due.

    Args:
        lease_id: The lease number, e.g. 1.
    """
    with connect() as conn:
        lease = conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
        if lease is None:
            return {"error": f"No lease #{lease_id}."}
        out = dict(lease)
        out["days_until_due"] = (date.fromisoformat(lease["next_due"]) - shop_today(conn)).days
        return out


@mcp.tool
def list_vendors() -> list[dict]:
    """All vendors with their specialty and lead time in days."""
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM vendors")]


@mcp.tool
def get_inventory(sku: str | None = None) -> list[dict]:
    """Stock on hand by SKU and size, with list price. Leave sku empty for the whole shop.

    Args:
        sku: Optional SKU to filter to, e.g. "CC-HOOD-NAVY".
    """
    with connect() as conn:
        q = ("SELECT i.sku, i.name, i.size, i.qty, i.location, p.list_price "
             "FROM inventory i LEFT JOIN pricing p ON p.sku = i.sku")
        rows = conn.execute(q + " WHERE i.sku = ?", (sku.strip().upper(),)) if sku else conn.execute(q)
        return [dict(r) for r in rows]


@mcp.tool
def request_human_approval(
    ticket_id: int,
    kind: str,
    details: str,
    requested_by: str,
    amount: float = 0.0,
    ref_id: int | None = None,
    sku: str | None = None,
    qty: int | None = None,
) -> dict:
    """File a request for a human to approve a payment, purchase, or price override. No money moves and no price changes.

    Agents cannot pay bills, buy stock, or change prices themselves; they file one of these
    and set the ticket to waiting_approval. Payment requests are checked against the actual
    bill, and purchase totals are calculated from the shop's unit cost.

    Args:
        ticket_id: The ticket this is for.
        kind: "invoice_payment", "rent_payment", "purchase", or "price_override".
        details: What the human is approving and why, in one or two sentences.
        requested_by: Name of the agent filing the request.
        amount: Dollars: the bill amount for payments, or the quoted order total for a price override.
            Leave at 0 for a purchase; the server works it out.
        ref_id: Invoice id for invoice_payment, lease id for rent_payment. Not needed otherwise.
        sku: For a purchase: the SKU to restock, e.g. "CC-HOOD-NAVY".
        qty: For a purchase: how many units to buy.
    """
    if kind not in {"invoice_payment", "rent_payment", "purchase", "price_override"}:
        return {"error": "kind must be invoice_payment, rent_payment, purchase, or price_override."}
    with connect() as conn:
        if conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            return {"error": f"No ticket #{ticket_id}."}
        if kind == "purchase":
            if not sku or not qty or qty < 1:
                return {"error": "A purchase needs sku and a qty of at least 1."}
            sku = sku.strip().upper()
            price = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
            if price is None:
                return {"error": f"No pricing on file for {sku}."}
            supplier = restock_vendor_for(conn, sku)
            if supplier is None:
                return {"error": f"No restock vendor on file for {sku}."}
            ref_id, amount = supplier["id"], round(price["unit_cost"] * qty, 2)
            details = f"{details.strip()} [{qty} x {sku} from {supplier['name']}, " \
                      f"{supplier['lead_days']}-day lead time]"
        if kind == "invoice_payment":
            bill = conn.execute("SELECT amount, status FROM invoices WHERE id = ?", (ref_id,)).fetchone()
            if bill is None:
                return {"error": f"No invoice #{ref_id}."}
            if bill["status"] == "paid":
                return {"error": f"Invoice #{ref_id} is already paid."}
            if abs(bill["amount"] - amount) > 0.005:
                return {"error": f"Amount ${amount:,.2f} doesn't match invoice #{ref_id} (${bill['amount']:,.2f})."}
        if kind == "rent_payment":
            lease = conn.execute("SELECT monthly_rent FROM leases WHERE id = ?", (ref_id,)).fetchone()
            if lease is None:
                return {"error": f"No lease #{ref_id}."}
            if abs(lease["monthly_rent"] - amount) > 0.005:
                return {"error": f"Amount ${amount:,.2f} doesn't match lease #{ref_id} rent (${lease['monthly_rent']:,.2f})."}
        dup = conn.execute(
            "SELECT id FROM approval_requests WHERE ticket_id = ? AND kind = ? AND IFNULL(ref_id, -1) = IFNULL(?, -1) "
            "AND IFNULL(sku, '') = IFNULL(?, '') AND status = 'pending'", (ticket_id, kind, ref_id, sku),
        ).fetchone()
        if dup:
            return {"approval_request_id": dup["id"], "status": "pending", "note": "Already filed; not duplicated."}
        cur = conn.execute(
            "INSERT INTO approval_requests (ticket_id, kind, ref_id, sku, qty, amount, details, requested_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, kind, ref_id, sku if kind == "purchase" else None, qty if kind == "purchase" else None,
             amount, details.strip(), requested_by, datetime.now().isoformat(timespec="seconds")),
        )
        out = {"approval_request_id": cur.lastrowid, "status": "pending", "amount": amount}
        if kind != "price_override":
            balance = conn.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()["balance"]
            committed = conn.execute(
                "SELECT IFNULL(SUM(amount), 0) FROM approval_requests WHERE status = 'pending' AND kind != 'price_override'"
            ).fetchone()[0]
            out["checking_balance"] = balance
            out["pending_payments_total"] = committed
            out["checking_if_all_approved"] = balance - committed
        return out


@mcp.tool
def draft_customer_message(ticket_id: int, to_name: str, subject: str, body: str, drafted_by: str) -> dict:
    """Save a reply to a customer as a draft for a human to review. Nothing is ever sent.

    Drafts that mention internal details (costs, margins, invoices, cash, rent) are rejected.

    Args:
        ticket_id: The ticket this reply is for.
        to_name: The customer's name exactly as it appears on the ticket.
        subject: Email subject line.
        body: The message, in the Campus Customs voice. Plain text.
        drafted_by: Name of the agent drafting it.
    """
    lowered = f"{subject} {body}".lower()
    leaked = [w for w in CUSTOMER_BLOCKLIST if re.search(rf"\b{re.escape(w)}\b", lowered)]
    if leaked:
        return {"error": f"Draft mentions internal details ({', '.join(leaked)}). Rewrite it without them."}
    with connect() as conn:
        t = conn.execute("SELECT requester FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return {"error": f"No ticket #{ticket_id}."}
        if to_name.strip().lower() != t["requester"].lower():
            return {"error": f"Ticket #{ticket_id} is from {t['requester']}; drafts can only go to the requester."}
        cur = conn.execute(
            "INSERT INTO customer_outbox (ticket_id, to_name, subject, body, drafted_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticket_id, t["requester"], subject.strip(), body.strip(), drafted_by,
             datetime.now().isoformat(timespec="seconds")),
        )
        return {"draft_id": cur.lastrowid, "status": "draft", "note": "Saved for human review. Not sent."}


# ---------- human-only tools (used by the backend API, never given to agents) ----------

@mcp.tool
def get_cash_balance() -> list[dict]:
    """Balance of every cash account, as of the date recorded on the account."""
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT name, balance, date FROM cash_accounts")]


@mcp.tool
def list_approval_requests(status: str | None = "pending") -> list[dict]:
    """Approval requests filed by agents, newest first.

    Args:
        status: "pending", "approved", or omit/null for all.
    """
    with connect() as conn:
        q = "SELECT * FROM approval_requests"
        rows = conn.execute(q + " WHERE status = ? ORDER BY id DESC", (status,)) if status \
            else conn.execute(q + " ORDER BY id DESC")
        return [dict(r) for r in rows]


@mcp.tool
def approve_payment(approval_request_id: int, approved_by: str) -> dict:
    """HUMAN ONLY. Approve a pending request: pay a payment or purchase, or sign off a price override.

    Payments and purchases: records the payment with the approver's name, marks the invoice
    paid (or moves the lease's next due date forward a month; or, for a purchase, pays the
    vendor), lowers the checking balance, marks the request approved, and notes the ticket.
    Refuses anything that would take checking below the cash reserve.
    Price overrides: records the sign-off on the request and the ticket. No cash moves.

    Args:
        approval_request_id: The id from approval_requests.
        approved_by: The name of the person approving.
    """
    if not approved_by or not approved_by.strip():
        return {"error": "approved_by (the approving person's name) is required."}
    approved_by = approved_by.strip()
    with connect() as conn:
        req = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_request_id,)).fetchone()
        if req is None:
            return {"error": f"No approval request #{approval_request_id}."}
        if req["status"] != "pending":
            return {"error": f"Approval request #{approval_request_id} is already {req['status']}."}
        stamp = datetime.now().isoformat(timespec="seconds")
        if req["kind"] == "price_override":
            balance = conn.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()["balance"]
            conn.execute("UPDATE approval_requests SET status = 'approved' WHERE id = ?", (approval_request_id,))
            t = conn.execute("SELECT notes FROM tickets WHERE id = ?", (req["ticket_id"],)).fetchone()
            note = (f"[{stamp} {approved_by}] Signed off request #{approval_request_id}: price override "
                    f"(order total ${req['amount']:,.2f}). No cash moved.")
            conn.execute("UPDATE tickets SET notes = ? WHERE id = ?", (((t["notes"] or "") + "\n" + note).strip(), req["ticket_id"]))
            return {"approval_request_id": approval_request_id, "status": "approved", "paid": None,
                    "signed_off": {"kind": "price_override", "order_total": req["amount"], "approved_by": approved_by},
                    "checking_before": balance, "checking_after": balance, "ticket_id": req["ticket_id"]}
        if req["kind"] not in ("invoice_payment", "rent_payment", "purchase"):
            return {"error": f"Request #{approval_request_id} has unknown kind {req['kind']}."}

        today = shop_today(conn)
        if req["kind"] == "invoice_payment":
            bill = conn.execute("SELECT amount, status FROM invoices WHERE id = ?", (req["ref_id"],)).fetchone()
            if bill is None or bill["status"] == "paid":
                return {"error": f"Invoice #{req['ref_id']} is missing or already paid."}
            amount, kind = bill["amount"], "invoice"
        elif req["kind"] == "purchase":
            if conn.execute("SELECT 1 FROM vendors WHERE id = ?", (req["ref_id"],)).fetchone() is None:
                return {"error": f"Vendor #{req['ref_id']} not found."}
            amount, kind = req["amount"], "purchase"
        else:
            lease = conn.execute("SELECT monthly_rent, next_due FROM leases WHERE id = ?", (req["ref_id"],)).fetchone()
            if lease is None:
                return {"error": f"Lease #{req['ref_id']} not found."}
            amount, kind = lease["monthly_rent"], "rent"

        balance = conn.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()["balance"]
        if balance - amount < MIN_CASH_RESERVE:
            return {"error": f"Paying ${amount:,.2f} would take checking (${balance:,.2f}) below the "
                             f"${MIN_CASH_RESERVE:,.2f} reserve. Not paid."}

        new_balance = balance - amount
        conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, 'checking', ?, ?)",
            (kind, req["ref_id"], amount, today.isoformat(), approved_by),
        )
        if kind == "invoice":
            conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (req["ref_id"],))
        elif kind == "rent":
            next_due = add_month(date.fromisoformat(lease["next_due"]))
            conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (next_due.isoformat(), req["ref_id"]))
        conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = 'checking'",
                     (new_balance, today.isoformat()))
        conn.execute("UPDATE approval_requests SET status = 'approved' WHERE id = ?", (approval_request_id,))

        stamp = datetime.now().isoformat(timespec="seconds")
        t = conn.execute("SELECT notes FROM tickets WHERE id = ?", (req["ticket_id"],)).fetchone()
        note = f"[{stamp} {approved_by}] Approved request #{approval_request_id}: paid ${amount:,.2f} ({kind} #{req['ref_id']})."
        conn.execute("UPDATE tickets SET notes = ? WHERE id = ?",
                     (((t["notes"] or "") + "\n" + note).strip(), req["ticket_id"]))
        return {
            "approval_request_id": approval_request_id,
            "status": "approved",
            "paid": {"kind": kind, "ref_id": req["ref_id"], "amount": amount, "approved_by": approved_by},
            "checking_before": balance,
            "checking_after": new_balance,
            "ticket_id": req["ticket_id"],
        }


if __name__ == "__main__":
    mcp.run(show_banner=False)
