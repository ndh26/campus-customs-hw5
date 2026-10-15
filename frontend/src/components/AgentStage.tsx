// The cinematic stage: letterbox title card, the team walks in and huddles around the
// ticket, then splits off to their own stations and works live from the audit trail.
import { useEffect, useMemo, useState } from "react";
import type { ActivityEvent, AgentName, Ticket } from "../api";
import { AGENTS, AGENT_INFO } from "../api";
import AgentFigure from "./AgentFigure";

type Phase = "empty" | "intro" | "assemble" | "split" | "working" | "done";

const HUDDLE: Record<AgentName, [number, number]> = {
  boss: [50, 60], inventory: [41, 64], accounting: [59, 64], facilities: [45, 69], customer_service: [55, 69],
};
const STATION: Record<AgentName, [number, number]> = {
  boss: [50, 42], inventory: [13, 86], accounting: [37, 93], facilities: [63, 93], customer_service: [87, 86],
};

interface Props {
  ticket: Ticket | null;
  runKey: number;          // bumps each time a run starts; restarts the choreography
  running: boolean;
  events: ActivityEvent[];
  outcome: string | null;  // final ticket status / summary once the run ends
  error: string | null;
}

function lastLine(e: ActivityEvent): string {
  if (e.type === "tool_call") return `🔧 ${e.tool}${e.ok === false ? " (error)" : ""}`;
  if (e.type === "guard_block") return `⛔ ${e.text?.replace("Blocked: ", "")}`;
  if (e.type === "delegation") return e.text ?? "";
  return e.text ?? "";
}

// The parent remounts the stage (key={runKey}) for each run, so the choreography starts fresh.
export default function AgentStage({ ticket, runKey, running, events, outcome, error }: Props) {
  const [step, setStep] = useState<Phase>(runKey ? "intro" : "empty");

  useEffect(() => {
    if (!runKey) return;
    const t = [
      setTimeout(() => setStep("assemble"), 1700),
      setTimeout(() => setStep("split"), 3600),
      setTimeout(() => setStep("working"), 5000),
    ];
    return () => t.forEach(clearTimeout);
  }, [runKey]);

  // Once the agents are at their stations and the run has ended, it's a wrap.
  const phase: Phase = runKey && !running && (step === "working" || step === "split") ? "done" : step;

  const agentEvents = events.filter((e): e is ActivityEvent & { agent: AgentName } => AGENTS.includes(e.agent as AgentName));
  const latest = useMemo(() => {
    const m: Partial<Record<AgentName, ActivityEvent>> = {};
    for (const e of agentEvents) if (e.type !== "agent_start") m[e.agent] = e;
    return m;
  }, [agentEvents]);
  const tools = useMemo(() => {
    const m: Partial<Record<AgentName, string[]>> = {};
    for (const e of agentEvents)
      if (e.type === "tool_call" && e.tool) m[e.agent] = [...new Set([...(m[e.agent] ?? []), e.tool])];
    return m;
  }, [agentEvents]);
  const involved = new Set(agentEvents.map(e => e.agent));
  const lastEvent = agentEvents.at(-1);
  const active: AgentName | undefined = running ? lastEvent?.agent : undefined;
  const lastTool = lastEvent?.type === "tool_call" ? lastEvent.tool : undefined;

  if (phase === "empty") {
    return (
      <section className="stage stage--empty">
        <div className="stage__hint">
          <div className="stage__crest">Y</div>
          <h2>The team is standing by</h2>
          <p>Click a ticket to dispatch the agents.</p>
        </div>
      </section>
    );
  }

  const placed = phase === "split" || phase === "working" || phase === "done";
  const visible = phase !== "intro";

  return (
    <section className={`stage stage--${phase}`}>
      <div className="letterbox letterbox--top" />
      <div className="letterbox letterbox--bottom" />
      <div className="spotlight" />

      {ticket && (
        <div className="titlecard">
          <span className="titlecard__eyebrow">Now dispatching</span>
          <h2>Ticket #{ticket.id}</h2>
          <p>{ticket.subject} · {ticket.requester}</p>
        </div>
      )}

      {/* delegation beam from the boss to whoever is working right now */}
      {placed && active && active !== "boss" && (
        <svg className="beam" viewBox="0 0 100 100" preserveAspectRatio="none">
          <line x1={STATION.boss[0]} y1={STATION.boss[1] - 6} x2={STATION[active][0]} y2={STATION[active][1] - 12} />
        </svg>
      )}

      {placed && (
        <div className="desks">
          {AGENTS.map(a => (
            <div key={a} className="desk" style={{ left: `${STATION[a][0]}%`, top: `${STATION[a][1]}%` }} />
          ))}
        </div>
      )}

      {AGENTS.map((a, i) => {
        const [x, y] = placed ? STATION[a] : HUDDLE[a];
        const isActive = active === a;
        const standingBy = phase !== "split" && placed && !involved.has(a);
        const mood = phase === "done" ? "done"
          : phase === "assemble" || phase === "split" ? "walking"
          : isActive ? "working" : "idle";
        const bubble = latest[a] ? lastLine(latest[a]!) : standingBy ? "Standing by" : null;
        return (
          <div
            key={a}
            className={`agent ${visible ? "agent--in" : ""} ${isActive ? "agent--active" : ""} ${standingBy ? "agent--standby" : ""}`}
            style={{ left: `${x}%`, top: `${y}%`, transitionDelay: placed ? `${i * 90}ms` : `${i * 160}ms`, ["--c" as string]: AGENT_INFO[a].color }}
          >
            {placed && bubble && phase !== "split" && (
              <div className={`bubble ${isActive ? "bubble--live" : ""}`}>{bubble.length > 150 ? bubble.slice(0, 147) + "…" : bubble}</div>
            )}
            <AgentFigure agent={a} mood={mood} />
            <div className="agent__label">
              {placed && <strong>{AGENT_INFO[a].title}</strong>}
              {placed && (
                <span className="chips">
                  {(tools[a] ?? []).map(t => <span key={t} className={`chip ${isActive && t === lastTool ? "chip--hot" : ""}`}>{t}</span>)}
                </span>
              )}
            </div>
          </div>
        );
      })}

      {phase === "done" && (
        <div className={`curtain ${error ? "curtain--error" : ""}`}>
          {error ? <>⚠️ {error}</> : <>🎬 That's a wrap · {outcome}</>}
        </div>
      )}
    </section>
  );
}
