// "Blind Box Dash": steer a Labubu-style monster to catch falling blind boxes while the
// agents work. Catch boxes (+1), the rare golden secret (+5), dodge overdue invoices (−1 life).
import { useCallback, useEffect, useRef, useState } from "react";

const W = 420, H = 320, CATCHER = 56;
type Kind = "box" | "secret" | "invoice";
interface Drop { id: number; x: number; y: number; vy: number; kind: Kind; }
interface View { x: number; drops: Drop[]; score: number; lives: number; ouch: number; }
const FRESH: View = { x: W / 2, drops: [], score: 0, lives: 3, ouch: 0 };

export function Labubu({ size = 56, mood = "happy" }: { size?: number; mood?: "happy" | "ouch" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-label="Labubu">
      {/* tall bunny ears */}
      <path d="M28 40 C20 8 30 0 36 4 C42 8 40 28 40 38 Z" fill="#c9a27e" />
      <path d="M31 36 C27 14 32 8 35 10 C38 13 37 26 37 34 Z" fill="#f4a6b8" />
      <path d="M72 40 C80 8 70 0 64 4 C58 8 60 28 60 38 Z" fill="#c9a27e" />
      <path d="M69 36 C73 14 68 8 65 10 C62 13 63 26 63 34 Z" fill="#f4a6b8" />
      {/* fuzzy head */}
      <ellipse cx="50" cy="62" rx="34" ry="30" fill="#c9a27e" />
      <ellipse cx="50" cy="66" rx="25" ry="21" fill="#f6e3cf" />
      {/* eyes */}
      {mood === "ouch" ? (
        <g stroke="#2b1d14" strokeWidth="3" strokeLinecap="round"><path d="M35 56 l8 6 M43 56 l-8 6" /><path d="M57 56 l8 6 M65 56 l-8 6" /></g>
      ) : (
        <g><ellipse cx="39" cy="58" rx="6" ry="7" fill="#2b1d14" /><ellipse cx="61" cy="58" rx="6" ry="7" fill="#2b1d14" />
          <circle cx="41" cy="55.5" r="2" fill="#fff" /><circle cx="63" cy="55.5" r="2" fill="#fff" /></g>
      )}
      {/* mischievous grin with the signature row of little teeth */}
      <path d="M33 70 Q50 86 67 70 Z" fill="#7a2e3a" />
      <path d="M33 70 l3 5 l3 -4 l3 5 l3 -4 l2.5 5 l2.5 -5 l3 4 l3 -5 l3 4 l3 -5 l3 5 Z" fill="#fff" />
      <ellipse cx="30" cy="68" rx="4" ry="2.5" fill="#f4a6b8" opacity=".7" />
      <ellipse cx="70" cy="68" rx="4" ry="2.5" fill="#f4a6b8" opacity=".7" />
    </svg>
  );
}

function DropSprite({ kind }: { kind: Kind }) {
  if (kind === "invoice")
    return (
      <svg width="30" height="36" viewBox="0 0 30 36"><rect x="2" y="2" width="26" height="32" rx="2" fill="#fff" stroke="#c0392b" strokeWidth="2" />
        <text x="15" y="16" fontSize="7" fill="#c0392b" textAnchor="middle" fontWeight="700">PAST</text>
        <text x="15" y="25" fontSize="7" fill="#c0392b" textAnchor="middle" fontWeight="700">DUE</text></svg>
    );
  const gold = kind === "secret";
  return (
    <svg width="32" height="32" viewBox="0 0 32 32">
      <rect x="3" y="8" width="26" height="22" rx="3" fill={gold ? "#f5c518" : "#ff8fb1"} stroke={gold ? "#b8860b" : "#d1567a"} strokeWidth="1.5" />
      <rect x="1" y="5" width="30" height="7" rx="2" fill={gold ? "#ffd84d" : "#ffb3c9"} stroke={gold ? "#b8860b" : "#d1567a"} strokeWidth="1.5" />
      <text x="16" y="25" fontSize="12" fontWeight="800" textAnchor="middle" fill="#fff">{gold ? "★" : "?"}</text>
    </svg>
  );
}

export default function LabubuGame({ onClose, agentsBusy }: { onClose: () => void; agentsBusy: boolean }) {
  const [view, setView] = useState<View>(FRESH);  // what's drawn; the loop updates it each frame
  const [state, setState] = useState<"ready" | "playing" | "over">("ready");
  const s = useRef({ x: W / 2, drops: [] as Drop[], score: 0, lives: 3, t: 0, next: 0, id: 0, ouch: 0, keys: new Set<string>() });
  const [best, setBest] = useState(() => Number(localStorage.getItem("labubu-best") ?? 0));
  const area = useRef<HTMLDivElement>(null);

  const start = useCallback(() => {
    Object.assign(s.current, { ...FRESH, drops: [], t: 0, next: 0 });
    setView(FRESH);
    setState("playing");
  }, []);

  useEffect(() => {
    const down = (e: KeyboardEvent) => { s.current.keys.add(e.key); if (e.key === " " && state !== "playing") start(); };
    const up = (e: KeyboardEvent) => s.current.keys.delete(e.key);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [state, start]);

  useEffect(() => {
    if (state !== "playing") return;
    let raf = 0, last = performance.now();
    const loop = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      const g = s.current;
      g.t += dt;
      const speed = 330;
      if (g.keys.has("ArrowLeft") || g.keys.has("a")) g.x -= speed * dt;
      if (g.keys.has("ArrowRight") || g.keys.has("d")) g.x += speed * dt;
      g.x = Math.max(CATCHER / 2, Math.min(W - CATCHER / 2, g.x));

      g.next -= dt;
      if (g.next <= 0) {
        const r = Math.random();
        const kind: Kind = r < 0.06 ? "secret" : r < 0.3 + Math.min(0.2, g.t / 200) ? "invoice" : "box";
        g.drops.push({ id: g.id++, x: 20 + Math.random() * (W - 40), y: -36, vy: 110 + Math.random() * 60 + g.t * 3, kind });
        g.next = Math.max(0.35, 0.9 - g.t / 90);
      }
      const keep: Drop[] = [];
      for (const d of g.drops) {
        d.y += d.vy * dt;
        const caught = d.y > H - 70 && d.y < H - 30 && Math.abs(d.x - g.x) < CATCHER / 2 + 10;
        if (caught) {
          if (d.kind === "invoice") { g.lives -= 1; g.ouch = 0.4; }
          else g.score += d.kind === "secret" ? 5 : 1;
        } else if (d.y < H + 40) keep.push(d);
      }
      g.drops = keep;
      g.ouch = Math.max(0, g.ouch - dt);
      setView({ x: g.x, drops: g.drops.map(d => ({ ...d })), score: g.score, lives: g.lives, ouch: g.ouch });
      if (g.lives <= 0) {
        const score = g.score;
        setBest(b => { if (score <= b) return b; localStorage.setItem("labubu-best", String(score)); return score; });
        setState("over");
        return;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [state]);

  const onMove = (e: React.PointerEvent) => {
    const rect = area.current?.getBoundingClientRect();
    if (rect) s.current.x = ((e.clientX - rect.left) / rect.width) * W;
  };

  const g = view;
  return (
    <div className="modal" onClick={onClose}>
      <div className="game" onClick={e => e.stopPropagation()}>
        <header className="game__head">
          <div>
            <h3>Blind Box Dash</h3>
            <span className="muted">{agentsBusy ? "The agents are still on it. Play while you wait!" : "The agents are done; one more round?"}</span>
          </div>
          <button className="ghost" onClick={onClose}>✕</button>
        </header>
        <div className="game__hud">
          <span>Score <b>{g.score}</b></span>
          <span>{"❤️".repeat(Math.max(0, g.lives))}{"🖤".repeat(3 - Math.max(0, g.lives))}</span>
          <span>Best <b>{best}</b></span>
        </div>
        <div className="game__area" ref={area} onPointerMove={onMove} style={{ aspectRatio: `${W}/${H}` }}>
          {g.drops.map(d => (
            <div key={d.id} className="drop" style={{ left: `${(d.x / W) * 100}%`, top: `${(d.y / H) * 100}%` }}><DropSprite kind={d.kind} /></div>
          ))}
          <div className="catcher" style={{ left: `${(g.x / W) * 100}%` }}><Labubu mood={g.ouch > 0 ? "ouch" : "happy"} /></div>
          {state !== "playing" && (
            <div className="game__overlay">
              <Labubu size={90} />
              <h4>{state === "over" ? `Game over: ${g.score} boxes!` : "Catch the blind boxes"}</h4>
              <p>🎁 +1 · ⭐ secret +5 · 🧾 past-due invoice costs a life</p>
              <button className="primary" onClick={start}>{state === "over" ? "Play again" : "Start"}</button>
              <span className="muted">Move with the mouse or ← → · Space to start</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
