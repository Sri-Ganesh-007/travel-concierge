import uuid
from datetime import date, datetime

from src.graph.workflow import workflow as app
from src.session import build_initial_state


def run_graph(graph_input, config):
    for update in app.stream(graph_input, config, stream_mode="updates"):
        for node_name in update:
            print(f"  [graph] {node_name} finished")


TRIP_STYLES = ["any", "relaxed", "adventure", "food", "culture", "nightlife", "family"]
COMFORT_LEVELS = ["budget", "mid-range", "luxury"]
STOP_CHOICES = {"any": -1, "0": 0, "1": 1, "2": 2}


def ask_text(prompt: str) -> str:
    while True:
        answer = input(prompt).strip()
        if answer:
            return answer
        print("Please enter a value.")


def ask_number(prompt: str, cast, low, high, default=None):
    while True:
        answer = input(prompt).strip().replace(",", "")
        if not answer and default is not None:
            return default
        try:
            value = cast(answer)
            if low <= value <= high:
                return value
        except ValueError:
            pass
        print(f"Please enter a number between {low} and {high}.")


def ask_choice(prompt: str, options: list, default: str) -> str:
    while True:
        answer = input(prompt).strip().lower()
        if not answer:
            return default
        if answer in options:
            return answer
        print(f"Please choose one of: {', '.join(options)}.")


def ask_departure_date() -> date:
    while True:
        answer = input("Departure date (YYYY-MM-DD): ").strip()
        try:
            departure = datetime.strptime(answer, "%Y-%m-%d").date()
            if departure > date.today():
                return departure
            print("Please enter a date in the future.")
        except ValueError:
            print("Please use the format YYYY-MM-DD.")


def ask_trip_constraints() -> dict:
    print("Let's plan your trip. Press Enter to accept a default shown in [brackets].\n")
    while True:
        origin = ask_text("Where are you flying from? (e.g., Delhi or DEL): ")
        destination = ask_text("Where do you want to go? (e.g., Tokyo or TYO): ")
        departure = ask_departure_date()
        nights = ask_number("How many nights will you stay? [3]: ", int, 1, 30, default=3)
        adults = ask_number("How many adults are travelling? [1]: ", int, 1, 9, default=1)
        max_budget = ask_number(
            "Total budget for flights and hotel, in INR (e.g., 150000): ", float, 1, 10**9
        )
        print("\nA few optional preferences:")
        trip_style = ask_choice(
            f"Trip style ({'/'.join(TRIP_STYLES)}) [any]: ", TRIP_STYLES, "any"
        )
        comfort = ask_choice(
            f"Hotel comfort ({'/'.join(COMFORT_LEVELS)}) [budget]: ", COMFORT_LEVELS, "budget"
        )
        stops = ask_choice(
            f"Max flight stops ({'/'.join(STOP_CHOICES)}) [any]: ", list(STOP_CHOICES), "any"
        )

        print(
            f"\nSo that's {origin} to {destination}, departing {departure}, {nights} nights, "
            f"{adults} adult(s), budget INR {max_budget:,.0f}, style: {trip_style}, "
            f"comfort: {comfort}, max stops: {stops}."
        )
        if input("Look right? [Y/n]: ").strip().lower() != "n":
            break
        print()

    return build_initial_state(
        origin=origin,
        destination=destination,
        departure=departure,
        nights=nights,
        adults=adults,
        max_budget=max_budget,
        trip_style=trip_style,
        comfort_level=comfort,
        max_stops=STOP_CHOICES[stops],
    )


if __name__ == "__main__":
    initial_state = ask_trip_constraints()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    print("\nPlanning your trip...")
    run_graph(initial_state, config)

    while True:
        state = app.get_state(config)
        values = state.values

        if values.get("user_decision") == "rejected":
            print("\nRequest rejected: the input failed the safety check.")
            break

        if values.get("eval_feedback"):
            print(
                "\nSystem Notice: Iteration crossed target constraints. "
                "Initiating autonomous self-correction loop..."
            )
            run_graph(None, config)
            continue

        itinerary = values.get("compiled_itinerary")
        print("\n" + "=" * 60)
        print(itinerary)
        print("=" * 60)

        choice = ""
        while choice not in ("A", "S"):
            choice = input(
                "\nType 'A' to Approve this package, or "
                "'S' to Search More and blacklist this option: "
            ).strip().upper()

        if choice == "A":
            app.update_state(config, {"user_decision": "approved"})
            run_graph(None, config)
            print("\nItinerary approved. Have a great trip!")
            break

        # 'S': blacklist this deal and route back into the crew with feedback.
        blacklist = list(values.get("blacklisted_packages") or []) + [itinerary]
        app.update_state(
            config,
            {
                "user_decision": "search_more",
                "attempts": 0,
                "blacklisted_packages": blacklist,
                "eval_feedback": (
                    "User rejected the previous package. Choose a different flight and "
                    "hotel than this one: " + itinerary[:300]
                ),
            },
            as_node="evaluate_output_node",
        )
        print("\nSearching for an alternative...")
        run_graph(None, config)
