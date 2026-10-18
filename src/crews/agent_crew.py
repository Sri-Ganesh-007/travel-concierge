from crewai import Agent, Task, Crew, Process, LLM

from src.tools.travel_mcp import (
    fetch_flight_offers,
    fetch_hotel_properties,
    fetch_destination_climate,
)
from src.config import GROQ_API_KEY, GROQ_MODEL_NAME

# Groq via its OpenAI-compatible endpoint (CrewAI's native OpenAI adapter strips
# the cache_breakpoint marker that Groq's API rejects on the LiteLLM path).
groq_llm = LLM(
    model=f"openai/{GROQ_MODEL_NAME}",
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY,
)

IATA_RULE = (
    "You MUST convert full city names into official 3-letter IATA airport codes "
    "(e.g., 'Paris' to 'CDG', 'Bengaluru' to 'BLR') before executing tool calls."
)

HOTEL_CITY_RULE = (
    "For the hotel tool, pass the full city name (e.g., 'Tokyo') as destination, "
    "not an airport code."
)

flight_scout_agent = Agent(
    role="Airfare Optimization Expert",
    goal=(
        "Find the best-value flights from {origin} to {destination} for {month} "
        "within the traveler's budget. " + IATA_RULE
    ),
    backstory=(
        "A veteran fare analyst who knows how pricing shifts by season and route, "
        "and who balances cost, duration, and layovers. " + IATA_RULE
    ),
    tools=[fetch_flight_offers],
    llm=groq_llm,
    verbose=True,
)

hotel_scout_agent = Agent(
    role="Lodging Curator",
    goal=(
        "Select a hotel in {destination} that fits what remains of the budget "
        "after flights. " + HOTEL_CITY_RULE
    ),
    backstory=(
        "A hospitality specialist who matches properties to budget, location, "
        "and travel season. " + HOTEL_CITY_RULE
    ),
    tools=[fetch_hotel_properties],
    llm=groq_llm,
    verbose=True,
)

compliance_officer_agent = Agent(
    role="Travel Risk Analyst",
    goal=(
        "Verify the compiled itinerary: confirm the total stays within the budget "
        "and flag any logistical failures or errors reported by the other agents."
    ),
    backstory=(
        "A careful reviewer who checks that every itinerary is complete, "
        "within budget, and honest about missing or failed data."
    ),
    llm=groq_llm,
    verbose=True,
)

destination_advisor_agent = Agent(
    role="Destination Suitability Advisor",
    goal=(
        "Judge how good {destination} is for travel in {month}, using real climate data."
    ),
    backstory=(
        "A seasoned travel advisor who turns climate numbers into practical advice "
        "about comfort, packing, and whether the timing suits the destination. "
        "For the climate tool, pass the full city name (e.g. 'Paris'), not an airport code."
    ),
    tools=[fetch_destination_climate],
    llm=groq_llm,
    verbose=True,
)

flight_search_task = Task(
    description=(
        "Discover flight paths from {origin} to {destination} departing {departure_date} "
        "(month: {month}) for {adults} adult(s). The total trip budget is {budget}. "
        "Maximum stops the traveler accepts: {max_stops} (-1 means any). Call the flight "
        "tool with departure_date {departure_date}, adults and max_stops, and report the "
        "most promising options with prices. " + IATA_RULE
    ),
    expected_output="A concise list of flight options with route, price, and duration.",
    agent=flight_scout_agent,
)

hotel_search_task = Task(
    description=(
        "Using the flight options from the previous task, find hotels in {destination} "
        "for a stay of {nights} nights so that flight plus hotel cost can stay under the "
        "budget of {budget}. The traveler's comfort level is '{comfort}' (budget = any star "
        "rating, mid-range = at least 3 stars, luxury = at least 4 stars) and the trip style "
        "is '{style}'. Call the hotel tool with checkin_date {departure_date}, nights, "
        "price_ceiling (the budget remaining after the flight), adults ({adults}) and "
        "min_stars, and report the best options with total stay prices. " + HOTEL_CITY_RULE +
        " Feedback from a previous failed attempt, if any: {feedback}"
    ),
    expected_output="A concise list of hotel options with name, rating, price, and city code.",
    agent=hotel_scout_agent,
    context=[flight_search_task],
)

destination_advice_task = Task(
    description=(
        "Use the climate tool for {destination} in {month} (pass the full city name). "
        "Then write a short suitability assessment: typical temperatures, rainfall, "
        "whether {month} is a good time to visit for a '{style}' trip, and what to pack. "
        "Base every number "
        "on the tool output. If the tool reports an error, say the climate data was "
        "unavailable instead of guessing."
    ),
    expected_output=(
        "A short 'Destination Suitability' assessment with a verdict (great, good, "
        "fair, or poor), key weather figures, packing tips, and the source attribution."
    ),
    agent=destination_advisor_agent,
)

compliance_verification_task = Task(
    description=(
        "Review the flight array from task 1 and hotel options from task 2. "
        "Verify that the total cost does not cross max_budget ({budget}) and that "
        "the hotel is in the destination city ({destination}). The trip is "
        "{nights} nights for {adults} adult(s) departing {departure_date}; mention these "
        "details in the itinerary. "
        "Output a beautifully formatted final markdown itinerary that also includes "
        "the destination suitability assessment from task 3 as its own section, "
        "keeping its weather-data attribution. "
        "The final output markdown must contain a separate, clean line at the absolute "
        "bottom formatted exactly like this: 'Total Cost: <calculated_number>' using a "
        "basic float with no commas. This line is mandatory for system calculations."
    ),
    expected_output=(
        "A beautifully formatted final markdown itinerary with the chosen flight, "
        "the chosen hotel, the total cost versus budget, and a short compliance note."
    ),
    agent=compliance_officer_agent,
    context=[flight_search_task, hotel_search_task, destination_advice_task],
)


def run_travel_crew(
    origin: str,
    destination: str,
    budget: float,
    month: str,
    departure_date: str,
    nights: int,
    adults: int,
    style: str,
    comfort: str,
    max_stops: int,
    feedback: str = "",
) -> str:
    crew = Crew(
        agents=[
            flight_scout_agent,
            hotel_scout_agent,
            destination_advisor_agent,
            compliance_officer_agent,
        ],
        tasks=[
            flight_search_task,
            hotel_search_task,
            destination_advice_task,
            compliance_verification_task,
        ],
        process=Process.sequential,
        verbose=True,
    )
    result = crew.kickoff(
        inputs={
            "origin": origin,
            "destination": destination,
            "budget": budget,
            "month": month,
            "departure_date": departure_date,
            "nights": nights,
            "adults": adults,
            "style": style,
            "comfort": comfort,
            "max_stops": max_stops,
            "feedback": feedback or "none",
        }
    )
    return result.raw
