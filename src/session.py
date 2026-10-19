from datetime import date, timedelta


def build_initial_state(
    origin: str,
    destination: str,
    departure: date,
    nights: int,
    adults: int,
    max_budget,
    trip_style: str,
    comfort_level: str,
    max_stops: int,
    trip_type: str = "round_trip",
    return_date: str = "",
    children_ages: list = None,
    infants: int = 0,
    services: str = "both",
) -> dict:
    if trip_type == "round_trip" and not return_date and nights > 0:
        return_date = (departure + timedelta(days=nights)).isoformat()
    if trip_type == "one_way":
        return_date = ""
    return {
        "services": services,
        "origin": origin,
        "destination": destination,
        "travel_month": departure.strftime("%B"),
        "trip_type": trip_type,
        "departure_date": departure.isoformat(),
        "return_date": return_date,
        "nights": nights,
        "adults": adults,
        "children_ages": list(children_ages or []),
        "infants": infants,
        "trip_style": trip_style,
        "comfort_level": comfort_level,
        "max_stops": max_stops,
        "max_budget": max_budget,
        "raw_flight_options": None,
        "raw_hotel_options": None,
        "compiled_itinerary": None,
        "eval_feedback": None,
        "attempts": 0,
        "user_decision": "",
        "blacklisted_packages": [],
    }


def search_more_update(values: dict) -> dict:
    """State update for 'search more': blacklist the shown plan and ask for another."""
    itinerary = values.get("compiled_itinerary") or ""
    return {
        "user_decision": "search_more",
        "attempts": 0,
        "blacklisted_packages": list(values.get("blacklisted_packages") or []) + [itinerary],
        "eval_feedback": (
            "User rejected the previous package. Choose a different flight and "
            "hotel than this one: " + itinerary[:300]
        ),
    }
