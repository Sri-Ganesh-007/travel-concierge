from typing import TypedDict, List, Optional


class TravelState(TypedDict):
    origin: str
    destination: str
    max_budget: float
    travel_month: str
    departure_date: str
    nights: int
    adults: int
    trip_style: str
    comfort_level: str
    max_stops: int
    raw_flight_options: Optional[str]
    raw_hotel_options: Optional[str]
    compiled_itinerary: Optional[str]
    eval_feedback: Optional[str]
    attempts: int
    user_decision: str
    blacklisted_packages: List[str]
