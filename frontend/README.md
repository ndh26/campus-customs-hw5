# Campus Customs Agent Desk (frontend)

React + Vite + TypeScript dashboard for the Campus Customs agent team. It talks to the back-office API in `../backend` at `http://localhost:8000` (override with `VITE_API_URL`).

```bash
# 1. backend (from HW 5/backend)
uvicorn main:app --reload --port 8000

# 2. dashboard (from HW 5/frontend)
npm install
npm run dev        # http://localhost:5173
```

| File | What it is |
|---|---|
| `src/App.tsx` | Layout: tickets, stage, live feed, agent summaries, approvals, cash |
| `src/api.ts` | Typed client for the backend routes |
| `src/components/AgentStage.tsx` | The cinematic stage: title card, huddle, split to stations, live work |
| `src/components/AgentFigure.tsx` | The illustrated human figure for each agent |
| `src/components/LabubuGame.tsx` | Blind Box Dash, the game to play while agents work |
| `src/styles.css` | Yale-blue theme and all animations |

Design choices are written up in `../output/design.md`.
