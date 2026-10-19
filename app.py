import hmac
import os
import uuid

import streamlit as st

from src.graph.workflow import workflow
from src.guards.guardrails import InputGuardrail
from src.intake import intake_turn, new_session, trip_inputs
from src.session import build_initial_state, search_more_update

GREETING = (
    "Hi, I'm your travel concierge. Tell me about the trip you have in mind: "
    "where you'd like to go, and roughly when."
)
NODE_LABELS = {
    "guardrail_input_node": "Checked your request",
    "call_agents_crew_node": "Agents searched flights, hotels and weather",
    "evaluate_output_node": "Checked the total against your budget",
}

MAX_PLANS_PER_SESSION = 3
LIMIT_MESSAGE = (
    f"You've reached the limit of {MAX_PLANS_PER_SESSION} plans for this session. "
    "Please come back later."
)

st.set_page_config(page_title="Travel Concierge", page_icon="✈️", layout="centered")

# Optional access code: set APP_ACCESS_CODE in the environment to keep a public deployment
# from spending the model quota on strangers. Unset it for local use.
ACCESS_CODE = os.getenv("APP_ACCESS_CODE")
if ACCESS_CODE and not st.session_state.get("authorized"):
    st.title("✈️ Travel Concierge")
    with st.form("access"):
        code = st.text_input("Access code", type="password")
        entered = st.form_submit_button("Enter")
    if entered:
        if hmac.compare_digest(code.encode(), ACCESS_CODE.encode()):
            st.session_state.authorized = True
            st.rerun()
        st.error("That access code isn't right.")
    st.stop()


def start_over():
    st.session_state.phase = "chat"
    st.session_state.messages = [{"role": "assistant", "content": GREETING}]
    st.session_state.intake = new_session()
    st.session_state.pop("config", None)
    # plans_used is deliberately kept across "start over" so the limit can't be reset by it


def run_graph(graph_input, config, status):
    for update in workflow.stream(graph_input, config, stream_mode="updates"):
        for node in update:
            if node in NODE_LABELS:
                status.write(f"✓ {NODE_LABELS[node]}")


def run_until_review(graph_input, config, status) -> str:
    """Run the graph until it needs the user; retry automatically while over budget."""
    while True:
        run_graph(graph_input, config, status)
        values = workflow.get_state(config).values
        if values.get("user_decision") == "rejected":
            return "rejected"
        if values.get("eval_feedback"):
            status.write("↻ Over budget, asking the agents to try again...")
            graph_input = None
            continue
        return "review"


if "phase" not in st.session_state:
    start_over()

with st.sidebar:
    st.header("How it works")
    st.markdown(
        "1. Chat with the concierge about your trip.\n"
        "2. It asks for anything missing, then confirms a summary.\n"
        "3. Four agents find a flight (Kiwi.com), a hotel (Trivago) and check the "
        "weather (Open-Meteo).\n"
        "4. The total is checked against your budget, and the agents retry if it is over.\n"
        "5. You approve the plan or ask for another one.\n\n"
        "Nothing is booked or paid for. If a data source is unavailable, sample data is "
        "used and the plan says so."
    )
    st.button("Start over", on_click=start_over)

st.title("✈️ Travel Concierge")
phase = st.session_state.phase

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if phase == "chat":
    prompt = st.chat_input("Type your message...")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        if not InputGuardrail.validate_input(prompt):
            reply, ready = "I can't process that message. Could you rephrase it?", False
        else:
            with st.spinner("Thinking..."):
                reply, ready = intake_turn(st.session_state.messages, st.session_state.intake)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        if ready:
            st.session_state.phase = "planning"
        st.rerun()

elif phase == "planning" and st.session_state.get("plans_used", 0) >= MAX_PLANS_PER_SESSION:
    st.session_state.messages.append({"role": "assistant", "content": LIMIT_MESSAGE})
    st.session_state.phase = "limit"
    st.rerun()

elif phase == "planning":
    st.session_state.plans_used = st.session_state.get("plans_used", 0) + 1
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    st.session_state.config = config
    state = build_initial_state(**trip_inputs(st.session_state.intake["request"]))
    with st.chat_message("assistant"):
        with st.status("Planning your trip. This can take a couple of minutes...", expanded=True) as status:
            st.session_state.phase = run_until_review(state, config, status)
            status.update(label="Done", state="complete")
    st.rerun()

elif phase == "rejected":
    st.error("That request was blocked by the safety check. Please start over and rephrase it.")

elif phase == "review":
    config = st.session_state.config
    values = workflow.get_state(config).values
    with st.chat_message("assistant"):
        st.markdown(values["compiled_itinerary"])
    approve_col, more_col = st.columns(2)
    if approve_col.button("Approve this plan", type="primary", use_container_width=True):
        workflow.update_state(config, {"user_decision": "approved"})
        for _ in workflow.stream(None, config, stream_mode="updates"):
            pass
        st.session_state.phase = "approved"
        st.rerun()
    if more_col.button("Search for another option", use_container_width=True):
        if st.session_state.get("plans_used", 0) >= MAX_PLANS_PER_SESSION:
            st.warning(LIMIT_MESSAGE)
            st.stop()
        st.session_state.plans_used = st.session_state.get("plans_used", 0) + 1
        workflow.update_state(config, search_more_update(values), as_node="evaluate_output_node")
        with st.status("Looking for an alternative...", expanded=True) as status:
            st.session_state.phase = run_until_review(None, config, status)
            status.update(label="Done", state="complete")
        st.rerun()

elif phase == "approved":
    st.success("Plan approved. Have a great trip!")
    st.button("Plan another trip", on_click=start_over)
