import asyncio
import json
import math
import re
import time
from datetime import date, timedelta

import requests
from crewai.tools import tool
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

KIWI_URL = "https://mcp.kiwi.com/"
TRIVAGO_URL = "https://mcp.trivago.com/mcp"
FLIGHT_TIMEOUT = 45
HOTEL_TIMEOUT = 60
REQUEST_TIMEOUT = 15
CURRENCY = "INR"
MAX_RESULTS = 5

# Records which data source each tool used in the current run, so the final
# itinerary can tell the user whether prices are live or simulated.
LAST_SOURCES: dict = {}


def _note_source(kind: str, source: str) -> None:
    LAST_SOURCES[kind] = source


def _call_mcp_tool(url: str, tool_name: str, arguments: dict, timeout: float) -> str:
    async def _run() -> str:
        async with streamablehttp_client(url, timeout=30) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                text = "".join(c.text for c in result.content if getattr(c, "type", "") == "text")
                if result.isError:
                    raise RuntimeError(text[:200])
                return text

    return asyncio.run(asyncio.wait_for(_run(), timeout))


def _month_number(month: str) -> int:
    months = ["january", "february", "march", "april", "may", "june", "july",
              "august", "september", "october", "november", "december"]
    key = month.strip().lower()
    numeric = re.fullmatch(r"(?:\d{4}-)?(\d{1,2})(?:-\d{1,2})?", key)
    if numeric and 1 <= int(numeric.group(1)) <= 12:
        return int(numeric.group(1))
    index = next((i for i, name in enumerate(months) if name.startswith(key[:3])), None)
    if index is None:
        raise ValueError(f"Unrecognised month: {month}")
    return index + 1


def _parse_price(text: str) -> float:
    return float(re.sub(r"[^\d.]", "", text))


def _mock_flights(origin: str, destination: str, adults: int, max_stops: int) -> list:
    per_adult_offers = [
        {"offer_id": "MOCK-1", "carrier_code": "AF", "duration": "PT7H45M",
         "stops": 0, "price_per_adult": 52400.00},
        {"offer_id": "MOCK-2", "carrier_code": "LH", "duration": "PT10H20M",
         "stops": 1, "price_per_adult": 38900.00},
        {"offer_id": "MOCK-3", "carrier_code": "BA", "duration": "PT9H05M",
         "stops": 1, "price_per_adult": 44750.00},
    ]
    return [
        {**offer, "adults": adults, "price": offer["price_per_adult"] * adults, "currency": CURRENCY}
        for offer in per_adult_offers
        if max_stops < 0 or offer["stops"] <= max_stops
    ]


def _mock_hotels(nights: int, min_stars: int) -> list:
    catalogue = [
        {"hotel_id": "MOCK-H1", "name": "Hotel Lumiere", "stars": 4,
         "guest_rating_out_of_10": 9.0, "price_per_night": 18000.00},
        {"hotel_id": "MOCK-H2", "name": "Maison Verte", "stars": 4,
         "guest_rating_out_of_10": 8.0, "price_per_night": 11500.00},
        {"hotel_id": "MOCK-H3", "name": "Budget Inn Centre", "stars": 3,
         "guest_rating_out_of_10": 7.0, "price_per_night": 7300.00},
    ]
    return [
        {**hotel, "nights": nights, "price": hotel["price_per_night"] * nights, "currency": CURRENCY}
        for hotel in catalogue
        if hotel["stars"] >= min_stars
    ]


@tool("fetch_flight_offers")
def fetch_flight_offers(
    origin: str, destination: str, departure_date: str, adults: int = 1, max_stops: int = -1
) -> str:
    """Search one-way flights between two cities on a given date (YYYY-MM-DD).
    Use 3-letter IATA airport or city codes for origin and destination (e.g. DEL, TYO).
    adults is the number of travelers; each offer's price is the total for all of them.
    max_stops limits the number of stops (-1 means any).
    Returns a JSON string with the cheapest flight offers including price, carrier and duration."""
    try:
        day = date.fromisoformat(departure_date.strip())
        arguments = {
            "flyFrom": origin.strip(),
            "flyTo": destination.strip(),
            "departureDate": day.strftime("%d/%m/%Y"),
            "currency": CURRENCY,
            "adults": adults,
            "sort": "price",
        }
        if max_stops >= 0:
            arguments["max_sector_stopovers"] = max_stops
        response = json.loads(_call_mcp_tool(KIWI_URL, "search-flight", arguments, FLIGHT_TIMEOUT))
        if response.get("error"):
            raise RuntimeError(str(response["error"])[:200])

        offers = []
        for itinerary in response["itineraries"]:
            outbound = itinerary["outbound"]
            first_segment = outbound["segments"][0]
            minutes = outbound["durationSeconds"] // 60
            offers.append({
                "offer_id": itinerary["id"],
                "carrier_code": first_segment["carrier"],
                "carrier_name": first_segment["carrierName"],
                "route": "-".join(outbound["route"]),
                "duration": f"PT{minutes // 60}H{minutes % 60}M",
                "stops": outbound["stops"],
                "price": float(itinerary["price"]),
                "currency": response.get("currency", CURRENCY),
            })
        offers.sort(key=lambda offer: offer["price"])
        if not offers:
            raise ValueError("no flight offers returned")
        _note_source("flights", "kiwi_live")
        return json.dumps({
            "source": "kiwi_live",
            "origin": origin.strip().upper(),
            "destination": destination.strip().upper(),
            "departure_date": day.isoformat(),
            "adults": adults,
            "offers": offers[:MAX_RESULTS],
        })
    except Exception as error:
        fallback_reason = f"{type(error).__name__}: {error or 'no details'}"[:200]

    _note_source("flights", "fallback_mock")
    time.sleep(1)  # simulate network latency
    return json.dumps({
        "source": "fallback_mock",
        "fallback_reason": fallback_reason,
        "origin": origin.strip().upper()[:3],
        "destination": destination.strip().upper()[:3],
        "departure_date": departure_date,
        "offers": _mock_flights(origin, destination, adults, max_stops),
    })


@tool("fetch_hotel_properties")
def fetch_hotel_properties(
    destination: str,
    checkin_date: str,
    nights: int,
    price_ceiling: float,
    adults: int = 1,
    min_stars: int = 0,
) -> str:
    """Search hotels in a destination city for a stay starting on checkin_date (YYYY-MM-DD).
    Use the full city name for destination (e.g. 'Tokyo'), not an airport code.
    nights is the length of the stay, price_ceiling is the maximum total price for all nights,
    adults is the number of travelers, and min_stars is the minimum star rating (0 means any).
    Returns a JSON string with the cheapest hotels including name, star rating and total stay price."""
    try:
        checkin = date.fromisoformat(checkin_date.strip())
        checkout = checkin + timedelta(days=nights)
        text = _call_mcp_tool(TRIVAGO_URL, "trivago-accommodation-search", {
            "query": destination.strip(),
            "arrival": checkin.isoformat(),
            "departure": checkout.isoformat(),
            "currency": CURRENCY,
            "adults": adults,
            "rooms": math.ceil(adults / 2),
        }, HOTEL_TIMEOUT)

        # The server wraps its JSON in extra text, including a "system_message" field with
        # instructions aimed at the reader. It is untrusted data: only the hotel list is used.
        payload, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
        listings = json.loads(payload["output"])

        hotels = []
        for listing in listings:
            price = _parse_price(listing["price_per_stay"])
            stars = int(listing.get("hotel_rating") or 0)
            if price > price_ceiling or stars < min_stars:
                continue
            hotels.append({
                "hotel_id": listing["accommodation_id"],
                "name": listing["accommodation_name"],
                "stars": stars,
                "guest_rating_out_of_10": float(listing["review_rating"]) if listing.get("review_rating") else None,
                "price": price,
                "price_per_night": _parse_price(listing["price_per_night"]),
                "currency": CURRENCY,
                "nights": nights,
                "booked_via": listing.get("advertisers"),
                "distance": listing.get("distance"),
            })
        hotels.sort(key=lambda hotel: hotel["price"])
        _note_source("hotels", "trivago_live")
        return json.dumps({
            "source": "trivago_live",
            "destination": destination.strip(),
            "price_ceiling": price_ceiling,
            "checkin": checkin.isoformat(),
            "checkout": checkout.isoformat(),
            "hotels": hotels[:MAX_RESULTS],
        })
    except Exception as error:
        fallback_reason = f"{type(error).__name__}: {error or 'no details'}"[:200]

    _note_source("hotels", "fallback_mock")
    time.sleep(1)  # simulate network latency
    return json.dumps({
        "source": "fallback_mock",
        "fallback_reason": fallback_reason,
        "destination": destination.strip(),
        "price_ceiling": price_ceiling,
        "hotels": [h for h in _mock_hotels(nights, min_stars) if h["price"] <= price_ceiling],
    })


@tool("fetch_destination_climate")
def fetch_destination_climate(destination: str, travel_month: str) -> str:
    """Fetch typical weather for a destination city in a given month, averaged over the last
    3 years of historical data. Use the full city name (e.g. 'Paris'), not an airport code.
    Returns a JSON string with average high/low temperature (Celsius) and rainfall."""
    try:
        month_number = _month_number(travel_month)
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": destination, "count": 1},
            timeout=REQUEST_TIMEOUT,
        )
        geo.raise_for_status()
        place = geo.json()["results"][0]

        last_year = date.today().year - 1
        archive = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "start_date": f"{last_year - 2}-01-01",
                "end_date": f"{last_year}-12-31",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "timezone": "auto",
            },
            timeout=REQUEST_TIMEOUT,
        )
        archive.raise_for_status()
        daily = archive.json()["daily"]

        rows = [
            (hi, lo, rain)
            for day, hi, lo, rain in zip(
                daily["time"], daily["temperature_2m_max"],
                daily["temperature_2m_min"], daily["precipitation_sum"],
            )
            if int(day[5:7]) == month_number and None not in (hi, lo, rain)
        ]
        years_covered = 3
        _note_source("weather", "open_meteo_archive")
        return json.dumps({
            "source": "open_meteo_archive",
            "attribution": "Weather data by Open-Meteo.com",
            "destination": f"{place['name']}, {place.get('country', '')}".strip(", "),
            "travel_month": travel_month,
            "years_averaged": years_covered,
            "avg_high_c": round(sum(r[0] for r in rows) / len(rows), 1),
            "avg_low_c": round(sum(r[1] for r in rows) / len(rows), 1),
            "avg_rainy_days": round(sum(1 for r in rows if r[2] >= 1.0) / years_covered, 1),
            "avg_total_rain_mm": round(sum(r[2] for r in rows) / years_covered, 1),
        })
    except Exception as error:
        _note_source("weather", "unavailable")
        return json.dumps({
            "source": "unavailable",
            "destination": destination,
            "travel_month": travel_month,
            "error": f"Climate data could not be retrieved: {error}",
        })
