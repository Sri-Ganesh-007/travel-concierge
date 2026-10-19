from typing import TypedDict, List, Optional


class TravelState(TypedDict):
    origin: str
    destination: str
    services: str
    max_budget: Optional[float]
    travel_month: str
    trip_type: str
    departure_date: str
    return_date: str
    nights: int
    adults: int
    children_ages: List[int]
    infants: int
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
