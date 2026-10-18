# Travel Concierge

A terminal travel concierge built with a **LangGraph state machine** and a **CrewAI multi-agent crew**. It asks a few questions about a trip, finds a flight and a hotel from live MCP servers, checks whether the destination suits the travel dates, verifies the total against the budget, and waits for the user to approve or ask for another option.

Prices come live from third-party MCP servers when they are reachable, and from clearly labelled sample data when they are not. Nothing is ever booked or paid for.

## How it works

```
run.py  ->  intake questions (dates, nights, travelers, budget, preferences)
   |
   v
LangGraph (src/graph/workflow.py)
   1. guardrail_input_node      rejects prompt-injection style text
   2. call_agents_crew_node     runs the CrewAI crew (below)
   3. evaluate_output_node      parses "Total Cost:" and compares it with the budget
         over budget  -> back to step 2 with feedback (max 3 attempts)
         within budget -> mask sensitive text, then pause for the user
   |
   v
run.py shows the itinerary:  A = approve   S = search more (blacklist + retry)
```

The crew runs four agents in sequence, each passing its result to the next:

| Agent | Tool | Data source |
|---|---|---|
| Flight scout | `fetch_flight_offers` | Kiwi.com MCP server |
| Hotel scout | `fetch_hotel_properties` | Trivago MCP server |
| Destination advisor | `fetch_destination_climate` | Open-Meteo (3-year monthly averages) |
| Compliance officer | none | reviews budget and city match, writes the final markdown itinerary |

## Design notes

- **MCP for data access.** The flight and hotel tools connect to hosted MCP servers as an MCP client, so the agents are decoupled from the data provider and a provider can be swapped without touching agent code.
- **Graceful fallback.** If a server is slow or down, the tool returns sample data with `"source": "fallback_mock"` and a `fallback_reason`. The final itinerary ends with a line stating whether each data source was live or simulated.
- **Deterministic budget check.** The compliance agent must end its answer with `Total Cost: <number>`. Plain code parses that line, so the budget gate does not depend on an LLM judging itself.
- **Human in the loop.** The graph is compiled with `interrupt_after` on the evaluator and checkpointed to SQLite, so it pauses before the final decision and can resume.
- **Untrusted tool output.** The Trivago server returns a `system_message` field with instructions for the reader. The tool extracts only the hotel list and never forwards that field to the agents.
- **Guardrails.** Regex-based input screening and output masking. These are a first line of defense for a prototype, not complete protection.

## Setup

Requires Python 3.11 and a free [Groq](https://console.groq.com) API key.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "GROQ_API_KEY=your_key_here" > .env
.venv/bin/python run.py
```

The model is set in `src/config.py` (`GROQ_MODEL_NAME`). The Groq endpoint is used through its OpenAI-compatible API.

The graph's checkpoint database is stored at `~/.travel-agent/checkpoints.sqlite`, outside the project folder.

## Project layout

```
run.py                        terminal interface and approve / search-more loop
src/state.py                  TravelState, the shared state passed between nodes
src/config.py                 environment variables and model name
src/graph/workflow.py         LangGraph nodes, routing, checkpointing
src/crews/agent_crew.py       CrewAI agents, tasks, and run_travel_crew()
src/tools/travel_mcp.py       MCP client tools, Open-Meteo tool, sample-data fallback
src/guards/guardrails.py      input and output guardrails
src/evals/evaluator.py        budget evaluation gate
```

## Known limitations

- Flights are one-way only, and hotels assume one room per two adults.
- The Kiwi.com and Trivago servers are third-party services built for chat clients. Their availability, rate limits, and terms of use are not guaranteed.
- A full run makes several LLM calls and may hit Groq's per-minute token limits on the free tier.
- "Search more" tells the agents to avoid the rejected option, but does not filter results in code.
- There is no automated test suite. Behavior was checked by running the app end to end.
