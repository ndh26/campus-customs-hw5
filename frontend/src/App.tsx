import { useCallback, useEffect, useRef, useState } from "react";
import type { ActivityEvent, AgentName, AgentSummary, Approval, Cash, RunResult, Ticket } from "./api";
import { AGENTS, AGENT_INFO, api, money } from "./api";
import AgentFigure from "./components/AgentFigure";
import AgentStage from "./components/AgentStage";
import LabubuGame, { Labubu } from "./components/LabubuGame";

const STATUS_LABEL: Record<string, string> = {
  open: "Open", in_progress: "In progress", waiting_approval: "Needs approval", resolved: "Resolved",
};
const KIND_LABEL: Record<Approval["kind"], string> = {
  invoice_payment: "Invoice payment", rent_payment: "Rent payment", purchase: "Restock purchase", price_override: "Price sign-off",
};

// Tickets, approvals and cash in one go; null if the backend is unreachable.
async function loadBoard() {
  try {
    const [t, approvals, cash] = await Promise.all([api.tickets(), api.approvals(), api.cash()]);
    return { tickets: t.tickets, approvals, cash };
  } catch {
    return null;
  }
}

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [cash, setCash] = useState<Cash | null>(null);
  const [offline, setOffline] = useState(false);

  const [selected, setSelected] = useState<Ticket | null>(null);
  const [running, setRunning] = useState(false);
  const [runKey, setRunKey] = useState(0);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [summaries, setSummaries] = useState<Partial<Record<AgentName, AgentSummary>>>({});
  const [result, setResult] = useState<RunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const [approver, setApprover] = useState(() => localStorage.getItem("approver") ?? "");
  const [toast, setToast] = useState<string | null>(null);
  const [gameOpen, setGameOpen] = useState(false);
  const feedEnd = useRef<HTMLDivElement>(null);

  const applyBoard = useCallback((board: Awaited<ReturnType<typeof loadBoard>>) => {
    if (!board) { setOffline(true); return; }
    setTickets(board.tickets); setApprovals(board.approvals); setCash(board.cash); setOffline(false);
  }, []);
  const refresh = useCallback(async () => applyBoard(await loadBoard()), [applyBoard]);

  useEffect(() => {
    let live = true;
    loadBoard().then(board => { if (live) applyBoard(board); });
    return () => { live = false; };
  }, [applyBoard]);
  useEffect(() => { feedEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [events.length]);
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(null), 4500); return () => clearTimeout(t); }, [toast]);

  async function dispatch(ticket: Ticket) {
    if (running) return;
    const prior = (await api.activity().catch(() => ({ recent_runs: [] as string[] }))).recent_runs;
    setSelected(ticket); setRunning(true); setRunKey(k => k + 1);
    setEvents([]); setSummaries({}); setResult(null); setRunError(null);
    setToast("🎬 Agents dispatched. Fancy a round of Blind Box Dash while you wait?");

    let runId: string | null = null, lastSeq = 0, stopped = false;
    const poll = async () => {
      while (!stopped) {
        try {
          const act = runId ? await api.activity({ run_id: runId, since_seq: lastSeq }) : await api.activity();
          if (!runId && act.run_id && !prior.includes(act.run_id)) runId = act.run_id;
          if (runId && act.run_id === runId && act.events.length) {
            const fresh = act.events;
            lastSeq = act.last_seq ?? lastSeq;
            setEvents(prev => (prev.length && fresh[0].seq <= prev.at(-1)!.seq ? prev : [...prev, ...fresh]));
          }
        } catch { /* backend busy; try again */ }
        await new Promise(r => setTimeout(r, 1100));
      }
    };
    poll();

    try {
      const res = await api.run(ticket.id);
      setResult(res);
      runId = res.run_id;
    } catch (e) {
      setRunError((e as Error).message.slice(0, 200));
    } finally {
      stopped = true;
      if (runId) {
        const full = await api.activity({ run_id: runId }).catch(() => null);
        if (full) { setEvents(full.events); setSummaries(full.agents); }
      }
      await refresh();
      setRunning(false);
    }
  }

  async function approve(a: Approval) {
    if (!approver.trim()) { setToast("Enter your name in “Approving as” first."); return; }
    localStorage.setItem("approver", approver.trim());
    try {
      const r = await api.approve(a.id, approver.trim());
      setToast((a.kind === "price_override" ? `✅ Signed off the ${money(a.amount)} quote. No cash moved.`
        : `✅ Paid ${money(a.amount)}. Checking is now ${money(r.checking_after)}.`) +
        (r.ticket_status === "resolved" ? ` Ticket #${a.ticket_id} resolved.` : ""));
      await refresh();
    } catch (e) { setToast(`⚠️ ${(e as Error).message}`); }
  }

  async function reset() {
    if (running || !confirm("Reset the shop database to its original state? (The audit trail is kept.)")) return;
    await api.reset();
    setSelected(null); setEvents([]); setSummaries({}); setResult(null); setRunKey(0);
    await refresh();
    setToast("Database reset. Fresh start.");
  }

  const outcome = result?.report?.tickets.find(t => t.ticket_id === selected?.id);
  const outcomeText = outcome ? `${STATUS_LABEL[outcome.status] ?? outcome.status}` : selected ? STATUS_LABEL[tickets.find(t => t.id === selected.id)?.status ?? "open"] : null;
  const pendingByTicket = (id: number) => approvals.filter(a => a.ticket_id === id).length;
  const checking = cash?.accounts.find(a => a.name === "checking");

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand__crest">Y</div>
          <div>
            <h1>Campus Customs</h1>
            <span>Back Office · Agent Desk</span>
          </div>
        </div>
        <div className="topbar__right">
          <div className="cash" key={checking?.balance}>
            <span>Checking</span>
            <strong>{checking ? money(checking.balance) : "n/a"}</strong>
            {checking && <small>as of {checking.date}</small>}
          </div>
          <button className={`gamebtn ${running ? "gamebtn--pulse" : ""}`} onClick={() => setGameOpen(true)} title="Play Blind Box Dash">
            <Labubu size={30} /> Play
          </button>
          <button className="ghost" onClick={reset} disabled={running}>Reset</button>
        </div>
      </header>

      {offline && <div className="banner">Can't reach the backend at localhost:8000. Start it with <code>uvicorn main:app --reload --port 8000</code> in <code>backend/</code>.</div>}

      <main className="grid">
        {/* ---------------- tickets ---------------- */}
        <aside className="panel tickets">
          <h3 className="panel__title">Tickets</h3>
          <p className="muted small">Click a ticket to dispatch the agents.</p>
          {tickets.map(t => (
            <button
              key={t.id}
              className={`ticket ticket--${t.status} ${selected?.id === t.id ? "ticket--selected" : ""}`}
              onClick={() => dispatch(t)}
              disabled={running}
            >
              <div className="ticket__top">
                <span className="ticket__id">#{t.id}</span>
                <span className={`pill pill--${t.status}`}>{t.resolved ? "✓ " : ""}{STATUS_LABEL[t.status]}</span>
              </div>
              <strong>{t.subject}</strong>
              <span className="muted small">{t.requester} · {t.type.replace("_", " ")}</span>
              {pendingByTicket(t.id) > 0 && <span className="ticket__flag">{pendingByTicket(t.id)} awaiting your approval</span>}
              {running && selected?.id === t.id && <span className="ticket__working"><i /> agents at work</span>}
            </button>
          ))}
        </aside>

        {/* ---------------- stage + feed ---------------- */}
        <section className="center">
          <AgentStage key={runKey} ticket={selected} runKey={runKey} running={running} events={events}
                      outcome={outcomeText ?? null} error={runError} />

          {(events.length > 0 || running) && (
            <div className="panel feed">
              <h3 className="panel__title">Live feed {running && <span className="live">● live</span>}</h3>
              <div className="feed__list">
                {events.filter(e => e.type !== "agent_start").map(e => (
                  <div key={e.seq} className={`feed__row feed__row--${e.type}`}>
                    <span className="feed__agent" style={{ color: AGENT_INFO[e.agent as AgentName]?.color }}>
                      {AGENT_INFO[e.agent as AgentName]?.title ?? (e.agent === "harness" ? "Desk" : "You")}
                    </span>
                    <span className="feed__text">
                      {e.type === "tool_call" ? <>used <code>{e.tool}</code>{e.ok === false && <em> (error)</em>}</>
                        : e.type === "guard_block" ? <>⛔ {e.text}</>
                        : e.type === "run_start" ? <>Run started on {e.text}</>
                        : e.type === "run_end" ? <>Run finished: {e.text}</>
                        : e.text}
                    </span>
                  </div>
                ))}
                {running && <div className="feed__row feed__typing"><span /><span /><span /></div>}
                <div ref={feedEnd} />
              </div>
            </div>
          )}

          {!running && Object.keys(summaries).length > 0 && (
            <div className="panel">
              <h3 className="panel__title">What each agent did</h3>
              {result?.report && (
                <div className="report">
                  <p>{result.report.run_summary}</p>
                  {result.report.tickets.map(o => o.human_action_needed && (
                    <div key={o.ticket_id} className="report__todo">📝 <b>Your move on #{o.ticket_id}:</b> {o.human_action_needed}</div>
                  ))}
                  <span className="muted small">{result.tokens_used.toLocaleString()} tokens · {result.delegations_used} hand-offs</span>
                </div>
              )}
              <div className="summaries">
                {AGENTS.filter(a => summaries[a]).map(a => {
                  const s = summaries[a]!;
                  return (
                    <article key={a} className="summary" style={{ ["--c" as string]: AGENT_INFO[a].color }}>
                      <div className="summary__head">
                        <div className="summary__avatar"><AgentFigure agent={a} mood="done" /></div>
                        <div><strong>{AGENT_INFO[a].title}</strong><span className="muted small">{AGENT_INFO[a].role}</span></div>
                      </div>
                      <p>{s.said.at(-1) ?? "No summary."}</p>
                      <div className="chips">{s.tools_used.map(t => <span key={t} className="chip">{t}</span>)}</div>
                      {s.blocked > 0 && <span className="muted small">⛔ {s.blocked} call(s) stopped by the harness</span>}
                    </article>
                  );
                })}
              </div>
            </div>
          )}
        </section>

        {/* ---------------- approvals ---------------- */}
        <aside className="panel approvals">
          <h3 className="panel__title">Approvals</h3>
          <label className="approver">
            <span>Approving as</span>
            <input value={approver} onChange={e => setApprover(e.target.value)} placeholder="Your name" />
          </label>
          {approvals.length === 0 && <p className="muted small">Nothing waiting on you. Agents file payments and purchases here; only a person can release cash.</p>}
          {approvals.map(a => {
            const cashOut = a.kind !== "price_override";
            const after = checking ? checking.balance - a.amount : null;
            return (
              <div key={a.id} className={`approval approval--${a.kind}`}>
                <div className="approval__top">
                  <span className="pill">{KIND_LABEL[a.kind]}</span>
                  <span className="muted small">#{a.ticket_id} · by {a.requested_by}</span>
                </div>
                <div className="approval__amount">{money(a.amount)}</div>
                <p className="small">{a.details}</p>
                {cashOut ? (
                  <>
                    {after !== null && <span className={`small ${after < 500 ? "warn" : "muted"}`}>Checking after: {money(after)}</span>}
                    <button className="primary" onClick={() => approve(a)}>Approve &amp; pay</button>
                  </>
                ) : (
                  <>
                    <span className="muted small">Pricing sign-off for the customer quote. No cash leaves the account.</span>
                    <button className="primary" onClick={() => approve(a)}>Sign off</button>
                  </>
                )}
              </div>
            );
          })}
        </aside>
      </main>

      {toast && <div className="toast" onClick={() => setToast(null)}>{toast}</div>}
      {gameOpen && <LabubuGame onClose={() => setGameOpen(false)} agentsBusy={running} />}
    </div>
  );
}
