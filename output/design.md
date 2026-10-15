# Campus Customs Agent Desk: Design

The dashboard (`frontend/`, React + Vite + TypeScript) is the desk where a person sits to dispatch the agent team, watch it work, and release cash. It talks to the back-office API at `http://localhost:8000` and starts with `npm run dev`.

## The creative ideas I asked for

| Idea | How it shows up |
|---|---|
| **Yale-themed and sleek** | A deep Yale-blue (#00356b) dark theme with glassy panels, serif headings like Yale's, and a shield-shaped "Y" crest as the logo, favicon and empty-stage emblem. |
| **Cinematic entrance when you click a ticket** | Black letterbox bars slide in and a title card fades up ("Now dispatching · Ticket #103") as if a film is starting. |
| **Agents come into the picture, then split off to do their own thing** | Under a spotlight, the five agents walk in one after another and huddle around the ticket. Then they break formation and walk to their own stations across a stage with a perspective floor. Agents who aren't needed on that ticket still take their posts, dimmed, with a "Standing by" bubble. |
| **Agents as human figures** | Each agent is an illustrated person with its own shirt colour and a prop that says what it does: the **Boss** wears a Yale-blue tie with a "Y" pin, **Inventory** carries a Campus Customs box, **Accounting** has glasses and a calculator, **Facilities** wears a hard hat and carries keys, and **Customer Service** wears a headset. Their arms and legs swing as they walk, they type while working, and they wave when the run ends. |
| **A Labubu-themed game while you wait** | **Blind Box Dash**, opened from the pink "Play" button in the top bar. It pulses while agents are working, and a toast suggests a round when you dispatch. You steer a fuzzy, bunny-eared Labubu-style monster (with its toothy grin) to catch falling Pop Mart-style blind boxes for +1. A rare golden secret box is worth +5. "Past due" invoices cost a life, a nod to the shop's real cash problem. The best score is saved in the browser. |

## Layout

Three columns, so everything a person needs stays on screen:

- **Left: Tickets.** One card per ticket with its number, subject, requester and a status pill. Clicking a card dispatches the team. While a ticket runs, its card shows "agents at work" and the other cards are disabled.
- **Centre: the stage.** The cinematic and the live agents, then the **Live feed** (a running log of every step) and, when the run ends, **What each agent did**.
- **Right: Approvals.** A field for the approver's name and one card per item the agents have queued.
- **Top bar:** the Yale crest, the checking balance, the game button, and a Reset button for a fresh run.

## How the agents read differently

- **Colour:** each agent keeps one colour everywhere (shirt, name in the feed, top border of its summary card): Boss gold, Inventory blue, Accounting green, Facilities orange, Customer Service pink.
- **Props:** the props above, so you can tell who's who without reading a label.
- **Live state:**
  - Whoever is acting right now glows in their colour.
  - A dashed beam runs from the Boss to the specialist it has handed work to.
  - The tool being used lights up as a chip under the agent's name.
  - Speech bubbles show the latest thing each agent said or the tool it's calling.
  - A call stopped by the safety guard shows as ⛔ in the bubble and in the feed.
- **Live feed:** delegations appear in italics, tool calls in monospace, and blocked calls with a red tint, so the conversation reads like a script.

## How resolved tickets show up

- **Status pills** on each card: blue "Open", gold "Needs approval", green "✓ Resolved". The card's left edge changes colour to match, and resolved subjects get a soft strike-through.
- When a run ends, a **"That's a wrap"** banner drops onto the stage with the outcome, and the agents wave.
- Cards say "**N awaiting your approval**" while anything is queued. When you approve a ticket's last pending payment or purchase, the backend marks the ticket resolved and the pill turns green.
- A **"Your move"** line under the Boss's report says exactly what you still need to do on each ticket.

## How cash shows up

- **Checking balance** sits in the top bar at all times, with the "as of" date from the shop's books. It flashes green when it changes.
- Each approval card shows the amount large, the agent's reason, and **"Checking after: $X"**, which turns amber if it would drop below $500. The money impact is clear before you click.
- **"Approve & pay"** is the only button in the app that moves money. A toast confirms the payment ("Paid $264.00. Checking is now $3,136.00.") and the top-bar balance drops.
- Price sign-offs get a **"Sign off"** button instead, with a note that no cash leaves the account.

## Why

- **Watching builds trust.** Watching the team work (who has the ticket, what they're saying, which tool they're using) makes the agents' reasoning visible. A person can see why something landed in their approval queue instead of trusting a black box.
- **The cinematic opening covers the wait.** Agent runs take a while, and the opening turns that wait into something worth watching.
- **The game makes waiting fun.** It's a lighthearted reason to stay at the desk while the team finishes.
- **Human figures make it feel like a team,** like a real back office rather than a log viewer.
- **Money stays obvious and deliberate.** Cash is always visible, every approval shows the balance after paying, and a person has to type their name and click to release money. That matches the harness rule that agents can prepare payments but only people approve them.
