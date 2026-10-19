import os
import sqlite3

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.sqlite import SqliteSaver

from src.state import TravelState
from src.crews.agent_crew import run_travel_crew
from src.guards.guardrails import InputGuardrail, OutputGuardrail
from src.evals.evaluator import ItineraryEvaluator
from src.tools.travel_mcp import LAST_SOURCES

MAX_ATTEMPTS = 3

# Kept outside Desktop: iCloud-synced folders can cause SQLite "disk I/O error".
CHECKPOINT_DIR = os.path.expanduser("~/.travel-agent")
os.makedirs(CHECKPOINT_DIR, exist_ok=True)
CHECKPOINT_DB_PATH = os.path.join(CHECKPOINT_DIR, "checkpoints.sqlite")


def guardrail_input_node(state: TravelState) -> dict:
    prompt_fields = [
        state["origin"],
        state["destination"],
        state["travel_month"],
        state["trip_style"],
        state["comfort_level"],
    ]
    if all(InputGuardrail.validate_input(field) for field in prompt_fields):
        return {}
    return {"user_decision": "rejected"}


def _sources_line() -> str:
    labels = {
        "kiwi_live": "Kiwi.com (live)",
        "trivago_live": "Trivago (live)",
        "open_meteo_archive": "Open-Meteo (historical averages)",
        "fallback_mock": "simulated sample data",
        "unavailable": "unavailable",
    }
    parts = [
        f"{kind}: {labels.get(LAST_SOURCES.get(kind), 'not used')}"
        for kind in ("flights", "hotels", "weather")
    ]
    return "\n\n_Data sources - " + "; ".join(parts) + "._"


def call_agents_crew_node(state: TravelState) -> dict:
    LAST_SOURCES.clear()
    itinerary = run_travel_crew(
        origin=state["origin"],
        destination=state["destination"],
        budget=state["max_budget"],
        month=state["travel_month"],
        departure_date=state["departure_date"],
        nights=state["nights"],
        adults=state["adults"],
        style=state["trip_style"],
        comfort=state["comfort_level"],
        max_stops=state["max_stops"],
        services=state["services"],
        trip_type=state["trip_type"],
        return_date=state["return_date"],
        children_ages=state["children_ages"],
        infants=state["infants"],
        feedback=state.get("eval_feedback") or "",
    )
    return {
        "compiled_itinerary": itinerary + _sources_line(),
        "attempts": state.get("attempts", 0) + 1,
    }


def evaluate_output_node(state: TravelState) -> dict:
    if state["max_budget"] is None:
        result = {"success": True, "feedback": None}  # the traveler set no budget limit
    else:
        result = ItineraryEvaluator.evaluate_budget(
            state["compiled_itinerary"], state["max_budget"]
        )
    if not result["success"]:
        if state.get("attempts", 0) >= MAX_ATTEMPTS:
            notice = (
                f"\n\n> Warning: after {MAX_ATTEMPTS} attempts no plan met the budget. "
                f"{result['feedback']}"
            )
            return {
                "compiled_itinerary": OutputGuardrail.mask_private_telemetry(
                    state["compiled_itinerary"]
                ) + notice,
                "eval_feedback": None,
            }
        return {"eval_feedback": result["feedback"]}
    return {
        "compiled_itinerary": OutputGuardrail.mask_private_telemetry(
            state["compiled_itinerary"]
        ),
        "eval_feedback": None,
    }


def route_after_guardrail(state: TravelState) -> str:
    if state.get("user_decision") == "rejected":
        return END
    return "call_agents_crew_node"


def determine_next_step(state: TravelState) -> str:
    if state.get("eval_feedback"):
        return "call_agents_crew_node"
    return END


builder = StateGraph(TravelState)
builder.add_node("guardrail_input_node", guardrail_input_node)
builder.add_node("call_agents_crew_node", call_agents_crew_node)
builder.add_node("evaluate_output_node", evaluate_output_node)

builder.add_edge(START, "guardrail_input_node")
builder.add_conditional_edges(
    "guardrail_input_node",
    route_after_guardrail,
    {"call_agents_crew_node": "call_agents_crew_node", END: END},
)
builder.add_edge("call_agents_crew_node", "evaluate_output_node")
builder.add_conditional_edges(
    "evaluate_output_node",
    determine_next_step,
    {"call_agents_crew_node": "call_agents_crew_node", END: END},
)

checkpointer = SqliteSaver(sqlite3.connect(CHECKPOINT_DB_PATH, check_same_thread=False))

workflow = builder.compile(
    checkpointer=checkpointer,
    interrupt_after=["evaluate_output_node"],
)
