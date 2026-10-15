# AI Prompt Log

## Problem 2 — Study the Campus Customs database

Prompt I typed: save a copy of it and call it campus_customs_new.db. Also let's start a harness.md. Lastly, take a look at the tables in the database and provide a brief summary of each and the purpose

What was lacking after the first prompt: Save this to the harness file

## Problem 3 — Build the MCP server

Prompt I typed:Create a folder called mcp_server and write an MCP server using FastMCP. Create the following three tools. 1. stock tracker - when a customer clicks on a product with a particular size he/she has in mind, make sure the customer is aware if it is in or out of stock. If it's out of stock, give him the estimated delivery time, which should include the time needed to restock. 2. Invoice Reminder and Payer - when invoices are due, notify employee user of due date and amount owed. Also allow for option to toggle automatic payment. 3. Bulk order discount - when customer requests a bulk order, determine pricing. Provide two sources, one that looks for comparable discounts from competitors on bulk orders and another based on a set margin % threshold at the discretion of the employee 

What was lacking after the first prompt: Add to the harness file my three tools, which ticket each tool addresses, and why the tool is relevant. Also add a README.md file in mcp_server that explains the server, the database file it uses, and the three tools it has

## Problem 4 — Add the MCP server to vibe coder and test each tool

Prompt I typed: Connect the MCP server to this project and save the connection as .mcp.json. After let's run the 3 MCP tools separately - I'll give you my go of when to run each one. Also set up an evidence file in output folder called mcp_smoke.json.

What was lacking after the first prompt: N/A

## Problem 5 — Build agent team and grow MCP tools

Prompt I typed: Let's build out the agentic suite: boss, inventory, accounting, facilities, and customer service. First create a backend folder. Next save prompts files there, with one file per agent - i'll give you the prompts here after. put the data types in models.py. add whatever tools the agents need to the MCP server so they can work on the open tickets. All shop info should come from data/campus_customs_new.db through the MCP server. Dont create another layer of shop tools that bypasses MCP. Make sure the agents log what they do to output/audit_trail.json as they go. For each step in the agent loop, record enough detail so someone can review it later. Keep adding to the file each run, dont overwrite whats already there. In output/harness.md, list all the agents and MCP tools, including any new ones you add, and mention which database tables each tool uses. Also add a safety section about protecting real customers and handling real money, along with ways to keep token usage under control. Update mcp_server/README.md so the tool list matches what is actually implemented.

What was lacking after the first prompt: Boss - coordinate the tickets and assign which let the user know what's still outstanding for them to complete, whether that be confirming an order or approving an invoice, etc. Inventory - coordinate customer orders vs inventory on hand. When we're out of stock, report it as necessary. Accounting - compile all finances and make sure bills are getting approved by human users (if toggle is turned off) and paid. Set up reminders if they aren't. Facilities - keep up the relationship with the landlord. make sure we're on time with bills and any communication with landlord is promptly made known to human user. Customer Service - you're the external communications of the website. Make sure you satisfy needs of customers and keep everything upbeat. Be sure to let customers know of any discounts in the store. Take these prompts and jazz them up with a bit mroe detail

## Problem 6 — Plan the three tickets

Prompt I typed: Save up a desk_tickets.html file with one page per ticket (101, 102, 103). Make an expected and actual section for each (I'll give you what to write in the expected and you'll fill in the actual at a later time).

What was lacking after the first prompt: N/A 

## Problem 7 — Backend routes

Prompt I typed: in main.py, add routes that show whether the tickets are resolved, take a ticket id and run the agent team, list what the agents did, approve a cash outflow after human approval, return balance from cash_accounts, and reset the database for a new run. start server with uvicorn main:app --reload --port 8000 and add to the harness each route in one line (URL and description)

What was lacking after the first prompt: N/A

## Problem 8 — Agent dashboard

Prompt I typed: Let's build the frontend with React + Vite + TypeScript. This should list all tickets, let the user click on a ticket so the agents can get started, show the agents at work when you start it and what they're doing, market a ticket resolved accordingly, show summary of what each agent did, let user approve cash outflows, show cash balance. Make this dashboard yale themed and sleek. Also when you click the ticket, add some cinematic affects with how the agents come into the picture and split off and do their own thing. Also make the agents human figures when they appear. Also, add a game the user can play while they wait on the dashboard - make it something labubu themed. Talk to the backend at http://localhost:8000 and start board with npm run dev. Lastly, in output/design.md, summarize the create ideas I suggested to you

What was lacking after the first prompt: N/A

## Problem 9 — Resolve the tickets

Prompt I typed: Reset the database (new copied version). Run the three tickets and fill in the actual section from desk_tickets. on the cash tab of the same file, itemize the money. Note the initial cash balance and for each ticket, how the cash changed when the ticket was resolved and why. Make sure the ending cash_accounts balance matches the working database. Let me know if it doesn't. Also for output/, add resolved_tickets.json for each ticket: id, final status, short outcome, what each agent contributed, and any human approvals and resolved_board.html so you can click into each resolved ticket. Add to the audit_trail.json and finish up harness so it covers tables, tools, 5 agents, API routes, dashboard, and safety. Take inspiration of safety from HW 4

What was lacking after the first prompt: 

## Problem 10 — Reflection

Prompt I typed: Include this in reflection tab on summary: The agents performed reasonably, though the boss sometimes under-delegated. On 101, the agent order matched exactly; only stock_tracker was used, since it already returns vendor and lead time, so list_vendors and get_inventory weren't needed. On 102, it took two runs: the first stopped at facilities and queued nothing, and the second sent the ticket to accounting. Customer service was never called, though the design partly prevents that, because landlord contact is human-only and the draft tool blocks rent wording. On 103, inventory and customer service were skipped, so no reply or restock was created.



What was lacking after the first prompt: N/A

