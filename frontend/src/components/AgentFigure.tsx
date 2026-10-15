// A small illustrated person for each agent, with a role-specific prop.
import type { AgentName } from "../api";
import { AGENT_INFO } from "../api";

const LOOKS: Record<AgentName, { skin: string; hair: string; pants: string }> = {
  boss: { skin: "#f1c27d", hair: "#2b2b2b", pants: "#1d2a3a" },
  inventory: { skin: "#c68642", hair: "#1a1a1a", pants: "#2f3e52" },
  accounting: { skin: "#ffdbac", hair: "#7a4b2a", pants: "#26323f" },
  facilities: { skin: "#8d5524", hair: "#111111", pants: "#3a3226" },
  customer_service: { skin: "#e0ac69", hair: "#b5651d", pants: "#2d2340" },
};

function Prop({ agent }: { agent: AgentName }) {
  switch (agent) {
    case "boss": // tie + Yale Y pin
      return (
        <g>
          <path d="M50 44 l-4 6 l4 18 l4 -18 z" fill="#00356b" stroke="#fff" strokeWidth="0.8" />
          <circle cx="40" cy="52" r="3.6" fill="#00356b" stroke="#fff" strokeWidth="0.8" />
          <text x="40" y="54.2" fontSize="5" fontWeight="700" fill="#fff" textAnchor="middle">Y</text>
        </g>
      );
    case "inventory": // carrying a box
      return (
        <g>
          <rect x="34" y="58" width="32" height="20" rx="2" fill="#c49a6c" stroke="#7a5a35" strokeWidth="1.2" />
          <line x1="34" y1="64" x2="66" y2="64" stroke="#7a5a35" strokeWidth="1" />
          <text x="50" y="74" fontSize="6" fill="#5a3e1e" textAnchor="middle" fontWeight="700">CC</text>
        </g>
      );
    case "accounting": // glasses + calculator
      return (
        <g>
          <circle cx="45" cy="25" r="3.4" fill="none" stroke="#222" strokeWidth="1.2" />
          <circle cx="55" cy="25" r="3.4" fill="none" stroke="#222" strokeWidth="1.2" />
          <line x1="48.4" y1="25" x2="51.6" y2="25" stroke="#222" strokeWidth="1.2" />
          <rect x="56" y="60" width="13" height="17" rx="2" fill="#2d3436" />
          <rect x="58" y="62" width="9" height="4" fill="#9be7a5" />
          <g fill="#dfe6e9">
            {[0, 1, 2].map(r => [0, 1].map(c => <rect key={`${r}${c}`} x={58.5 + c * 4.5} y={68 + r * 3} width="3" height="2" />))}
          </g>
        </g>
      );
    case "facilities": // hard hat + keys
      return (
        <g>
          <path d="M37 19 a13 11 0 0 1 26 0 z" fill="#f2c94c" stroke="#b8860b" strokeWidth="1" />
          <rect x="35" y="18" width="30" height="3" rx="1.5" fill="#e0b13a" />
          <circle cx="68" cy="70" r="3" fill="none" stroke="#d4d4d4" strokeWidth="1.4" />
          <path d="M68 73 v6 h2 M68 76 h2" stroke="#d4d4d4" strokeWidth="1.4" fill="none" />
        </g>
      );
    case "customer_service": // headset
      return (
        <g>
          <path d="M38 26 a12 12 0 0 1 24 0" fill="none" stroke="#222" strokeWidth="2" />
          <rect x="35.5" y="24" width="4" height="7" rx="2" fill="#222" />
          <rect x="60.5" y="24" width="4" height="7" rx="2" fill="#222" />
          <path d="M37.5 31 q2 7 9 6" fill="none" stroke="#222" strokeWidth="1.4" />
          <circle cx="47" cy="37" r="1.6" fill="#ef7fbf" />
        </g>
      );
  }
}

export default function AgentFigure({ agent, mood }: { agent: AgentName; mood: "idle" | "walking" | "working" | "done" }) {
  const look = LOOKS[agent];
  const shirt = AGENT_INFO[agent].color;
  return (
    <svg className={`figure figure--${mood}`} viewBox="0 0 100 130" aria-label={AGENT_INFO[agent].title}>
      <ellipse cx="50" cy="125" rx="20" ry="4" fill="rgba(0,0,0,.35)" />
      {/* legs */}
      <g className="leg leg--left"><rect x="41" y="84" width="8" height="34" rx="4" fill={look.pants} /><ellipse cx="44" cy="119" rx="6" ry="3" fill="#111" /></g>
      <g className="leg leg--right"><rect x="51" y="84" width="8" height="34" rx="4" fill={look.pants} /><ellipse cx="56" cy="119" rx="6" ry="3" fill="#111" /></g>
      {/* torso */}
      <path d="M33 48 q17 -8 34 0 l-3 40 h-28 z" fill={shirt} />
      {/* arms */}
      <g className="arm arm--left"><rect x="26" y="48" width="8" height="30" rx="4" fill={shirt} /><circle cx="30" cy="80" r="4" fill={look.skin} /></g>
      <g className="arm arm--right"><rect x="66" y="48" width="8" height="30" rx="4" fill={shirt} /><circle cx="70" cy="80" r="4" fill={look.skin} /></g>
      {/* neck + head */}
      <rect x="46" y="36" width="8" height="10" fill={look.skin} />
      <circle cx="50" cy="26" r="13" fill={look.skin} />
      <path d="M37 24 q2 -14 13 -14 q12 0 14 13 q-6 -6 -14 -6 q-8 0 -13 7z" fill={look.hair} />
      <circle cx="45" cy="26" r="1.5" fill="#222" />
      <circle cx="55" cy="26" r="1.5" fill="#222" />
      <path d={mood === "done" ? "M44 31 q6 6 12 0" : "M45 32 q5 3 10 0"} stroke="#6b3a2a" strokeWidth="1.4" fill="none" strokeLinecap="round" />
      <Prop agent={agent} />
    </svg>
  );
}
