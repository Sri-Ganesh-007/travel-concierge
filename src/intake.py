"""Conversational intake: an LLM turns free-form chat into a validated trip request.

The model only proposes field updates and a friendly reply. Code validates every value,
decides what is still missing, and controls the stages (collecting, optional preferences,
confirmation), so the conversation cannot skip required information.
"""
import json
from datetime import date, datetime, timedelta

from openai import OpenAI

from src.config import GROQ_API_KEY, GROQ_MODEL_NAME
from src.guards.guardrails import InputGuardrail

client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY, timeout=40)

COMFORT_LEVELS = ("any", "budget", "mid-range", "luxury")
SERVICES = ("flight_only", "hotel_only", "both")
VALID_STOPS = (-1, 0, 1, 2)
HISTORY_TURNS = 8

SCOPE_TEXT = {
    "flight_only": "your flight",
    "hotel_only": "your hotel stay",
    "both": "flights and hotel together",
}


def wants_flights(request: dict) -> bool:
    return request.get("services") in ("flight_only", "both")


def wants_hotel(request: dict) -> bool:
    return request.get("services") in ("hotel_only", "both")


def question_for(key: str, request: dict) -> str:
    services = request.get("services")
    questions = {
        "destination": "Where would you like to go?",
        "services": "Would you like me to look for flights, a hotel, or both?",
        "origin": "Where will you be flying from?",
        "trip_type": "Is this a round trip or a one-way flight?",
        "departure_date": (
            "What date will you check in?" if services == "hotel_only"
            else "What date do you want to leave?"
        ),
        "stay": (
            "How many nights will you stay?" if services == "hotel_only"
            else "How many nights will you stay (or what is your return date)?"
        ),
        "return_flight": "When would you like to fly back?",
        "stay_one_way": "How many nights will you stay at the destination?",
        "travelers": "Who is travelling: how many adults, and any children (with their ages) or infants?",
        "budget_amount": (
            f"Do you have a budget in mind for {SCOPE_TEXT.get(services, 'your trip')}? "
            "Say 'no limit' if you don't want to set one."
        ),
        "budget_basis": "Is that budget for the whole group, or per person?",
    }
    return questions[key]


def optional_question(request: dict) -> str:
    parts = []
    if wants_hotel(request):
        parts.append("hotel comfort (budget, mid-range or luxury)")
    parts.append("your trip style or interests (for example food, culture, relaxed)")
    if wants_flights(request):
        parts.append("the most flight stops you'd accept")
    return (
        "Almost there. A few optional preferences, say 'skip' to use defaults: "
        + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + "."
    )


SYSTEM_PROMPT = """You are the intake step of a friendly travel concierge. Today's date is {today}.
Read the conversation and the current known request, then reply with JSON only:
{{"updates": {{...}}, "reply": "...", "language": "..."}}

LANGUAGE: users may write in any language, including Indian languages typed in English letters
(romanized Telugu, Hindi, Tamil and so on). First work out what they mean in English, then fill
"updates" using English values only. Examples: Telugu "repe" = tomorrow, "nenokkadine" = only me
(1 adult, no children), "memu iddaram" = the two of us, "X nunchi Y vellali" = going from X to Y;
Hindi "kal" = tomorrow, "akela" = alone, "hum teen log" = the three of us. Write "reply" in the
same language and script the user is using (for example romanized Telugu if they typed romanized
Telugu), in simple words. Set "language" to a short description of it, for example "English" or
"Telugu (romanized)".

"updates" may contain ONLY these keys, and only values the user stated or clearly implied in
their latest message (never invent anything):
- services: "flight_only", "hotel_only" or "both". Set it when the user says what they want
  ("just a flight", "only flights", "only a hotel", "flights and hotel", "a full trip"). If it is
  unclear, leave it unset. Never assume the user wants a hotel.
- origin, destination: city names (strings). Origin is only needed when flights are wanted.
- trip_type: "round_trip" or "one_way" (flights only)
- departure_date, return_date: "YYYY-MM-DD" (resolve phrases like "next Friday" using today's
  date). For a hotel-only stay, departure_date is the check-in date.
- nights: integer number of nights away ("a week" = 7, "a weekend" = 2)
- adults: integer 1-9
- children_ages: list of integers (ages 2-11). Use [] if the user says there are no children.
- infants: integer (children under 2). Use 0 if the user says there are none.
- budget_amount: a number in Indian rupees (1 lakh = 100000, 1k = 1000). If the user gives another
  currency, do not set it; ask them for a rupee amount in the reply.
- budget_basis: "total" (whole group) or "per_person". Set it ONLY if the user said which.
- no_budget: true if the user says they have no budget limit or do not want to give one
- comfort_level: "budget", "mid-range", "luxury" or "any"
- trip_style: a short phrase for style or interests, for example "food and culture"
- max_stops: -1 (any), 0 (non-stop), 1 or 2
- skip_optional: true if the user declines to give optional preferences
- confirmed: true ONLY if the user clearly agrees to start planning after seeing a summary

"reply" is 1-3 short, warm sentences. Ask about at most two missing things at a time, most
important first, and never ask about something already known or something the user said they
don't want (for example hotel details when they only want a flight). The budget is optional and
covers only what the user asked for. Do not give prices, recommendations or plans, and do not ask
about hotel comfort, trip style, flight stops or whether to start planning: the system asks those
later. If nothing is missing, just acknowledge what the user said in one short sentence.

Current known request: {request}
Still missing (ask about these, in this order): {missing}
"""


def _parse_date(value) -> date:
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def missing_fields(request: dict) -> list:
    missing = []
    services = request.get("services")
    if not request.get("destination"):
        missing.append("destination")
    if not services:
        missing.append("services")
        return missing  # the rest depends on what the user wants
    if wants_flights(request):
        if not request.get("origin"):
            missing.append("origin")
        if not request.get("trip_type"):
            missing.append("trip_type")
    if not request.get("departure_date"):
        missing.append("departure_date")

    has_stay = bool(request.get("return_date") or request.get("nights"))
    if services == "hotel_only":
        if not request.get("nights"):
            missing.append("stay")
    elif services == "flight_only":
        if request.get("trip_type") == "round_trip" and not has_stay:
            missing.append("return_flight")
    else:
        if request.get("trip_type") == "round_trip" and not has_stay:
            missing.append("stay")
        elif request.get("trip_type") == "one_way" and not request.get("nights"):
            missing.append("stay_one_way")

    if not request.get("adults") or request.get("children_ages") is None:
        missing.append("travelers")

    if not request.get("budget_amount") and not request.get("no_budget"):
        missing.append("budget_amount")
    elif request.get("budget_amount"):
        group = (request.get("adults") or 1) + len(request.get("children_ages") or [])
        if group > 1 and not request.get("budget_basis"):
            missing.append("budget_basis")
    return missing


def apply_updates(request: dict, updates: dict, today: date) -> list:
    """Validate and merge model-proposed updates into request. Returns problem notes."""
    problems = []

    def text(key, limit=60):
        value = updates.get(key)
        if isinstance(value, str) and value.strip():
            clean = value.strip()[:limit]
            if InputGuardrail.validate_input(clean):
                request[key] = clean
            else:
                problems.append(f"I couldn't use that {key.replace('_', ' ')}.")

    text("origin")
    text("destination")
    text("trip_style", 80)

    if updates.get("services") in SERVICES:
        request["services"] = updates["services"]
    if updates.get("trip_type") in ("round_trip", "one_way"):
        request["trip_type"] = updates["trip_type"]
    if updates.get("comfort_level") in COMFORT_LEVELS:
        request["comfort_level"] = updates["comfort_level"]
    if updates.get("max_stops") in VALID_STOPS:
        request["max_stops"] = updates["max_stops"]
    if updates.get("budget_basis") in ("total", "per_person"):
        request["budget_basis"] = updates["budget_basis"]

    dates_changed = False
    if "departure_date" in updates:
        try:
            departure = _parse_date(updates["departure_date"])
            if departure <= today:
                problems.append("The date needs to be in the future.")
            else:
                request["departure_date"] = departure.isoformat()
                dates_changed = True
        except ValueError:
            problems.append("I didn't understand the date.")

    return_given = False
    if "return_date" in updates:
        try:
            return_day = _parse_date(updates["return_date"])
            departure_text = request.get("departure_date")
            if departure_text and return_day <= _parse_date(departure_text):
                problems.append("The return date needs to be after the departure date.")
            else:
                request["return_date"] = return_day.isoformat()
                return_given = True
        except ValueError:
            problems.append("I didn't understand the return date.")

    nights_given = False
    if isinstance(updates.get("nights"), int) and not isinstance(updates["nights"], bool):
        if 1 <= updates["nights"] <= 30:
            request["nights"] = updates["nights"]
            nights_given = True
        else:
            problems.append("I can plan stays of 1 to 30 nights.")

    if isinstance(updates.get("adults"), int) and not isinstance(updates["adults"], bool):
        if 1 <= updates["adults"] <= 9:
            request["adults"] = updates["adults"]
        else:
            problems.append("I can plan for 1 to 9 adults.")

    ages = updates.get("children_ages")
    if isinstance(ages, list) and all(isinstance(a, int) and 2 <= a <= 11 for a in ages) and len(ages) <= 8:
        request["children_ages"] = ages
    elif ages is not None:
        problems.append("Children's ages should be between 2 and 11 (younger ones count as infants).")

    infants = updates.get("infants")
    if isinstance(infants, int) and not isinstance(infants, bool) and 0 <= infants <= 4:
        request["infants"] = infants
    if request.get("children_ages") is not None and request.get("infants") is None:
        request["infants"] = 0  # not mentioned alongside the children, so assume none

    budget = updates.get("budget_amount")
    if isinstance(budget, (int, float)) and not isinstance(budget, bool):
        if 1000 <= budget <= 100_000_000:
            request["budget_amount"] = float(budget)
            request.pop("no_budget", None)
        else:
            problems.append("That budget looks off. Please give an amount in rupees.")
    elif updates.get("no_budget") is True:
        request["no_budget"] = True
        request.pop("budget_amount", None)
        request.pop("budget_basis", None)

    # Keep dates, nights and trip type consistent (dates win when both are given).
    if request.get("trip_type") == "one_way" and request.get("services") != "hotel_only":
        request.pop("return_date", None)
    elif request.get("departure_date"):
        departure = _parse_date(request["departure_date"])
        if return_given and request.get("return_date"):
            request["nights"] = (_parse_date(request["return_date"]) - departure).days
        elif request.get("nights") and (nights_given or dates_changed or not request.get("return_date")):
            request["return_date"] = (departure + timedelta(days=request["nights"])).isoformat()
    return problems


def travelers_count(request: dict) -> int:
    return (request.get("adults") or 1) + len(request.get("children_ages") or [])


def trip_inputs(request: dict) -> dict:
    """Normalize a complete request into the arguments the planner needs."""
    services = request["services"]
    max_budget = None
    if request.get("budget_amount"):
        max_budget = request["budget_amount"]
        if request.get("budget_basis") == "per_person":
            max_budget *= travelers_count(request)
    flights = services in ("flight_only", "both")
    return {
        "services": services,
        "origin": request.get("origin", "") if flights else "",
        "destination": request["destination"],
        "departure": _parse_date(request["departure_date"]),
        "nights": 0 if services == "flight_only" else request["nights"],
        "adults": request["adults"],
        "max_budget": max_budget,
        "trip_style": request.get("trip_style", "any"),
        "comfort_level": request.get("comfort_level", "any"),
        "max_stops": request.get("max_stops", -1),
        "trip_type": request["trip_type"] if flights else "one_way",
        "return_date": request.get("return_date", "") if flights else "",
        "children_ages": request.get("children_ages") or [],
        "infants": request.get("infants") or 0,
    }


def summarize(request: dict) -> str:
    inputs = trip_inputs(request)
    services = request["services"]
    travelers = f"{request['adults']} adult(s)"
    ages = request.get("children_ages") or []
    if ages:
        travelers += f", {len(ages)} child(ren) aged {', '.join(str(a) for a in ages)}"
    if request.get("infants"):
        travelers += f", {request['infants']} infant(s)"

    lines = ["Here's what I have:"]
    if services == "hotel_only":
        lines.append(f"- Hotel only, in {request['destination']}")
        lines.append(f"- Check-in {request['departure_date']}, {request['nights']} nights")
    else:
        kind = "Flight only" if services == "flight_only" else "Flights and hotel"
        lines.append(f"- {kind}: from {request['origin']} to {request['destination']}")
        if request["trip_type"] == "round_trip":
            trip = f"Round trip, leaving {request['departure_date']}, back {request['return_date']}"
            if services == "both":
                trip += f" ({request['nights']} nights)"
        else:
            trip = f"One-way, leaving {request['departure_date']}"
            if services == "both":
                trip += f", hotel for {request['nights']} nights"
        lines.append(f"- {trip}")
    lines.append(f"- Travellers: {travelers}")

    max_budget = inputs["max_budget"]
    scope = SCOPE_TEXT[services]
    if max_budget is None:
        lines.append("- Budget: no limit")
    elif request.get("budget_basis") == "per_person" and travelers_count(request) > 1:
        lines.append(f"- Budget: INR {request['budget_amount']:,.0f} per person = INR {max_budget:,.0f} total ({scope})")
    else:
        lines.append(f"- Budget: INR {max_budget:,.0f} total ({scope})")

    preferences = [f"Style: {request.get('trip_style', 'any')}"]
    if wants_hotel(request):
        preferences.insert(0, f"Hotel comfort: {request.get('comfort_level', 'any')}")
    if wants_flights(request):
        stops = request.get("max_stops", -1)
        preferences.append(
            "Flight stops: " + ("any" if stops == -1 else "non-stop only" if stops == 0 else f"up to {stops}")
        )
    lines.append("- " + " | ".join(preferences))
    return "\n".join(lines) + "\n\nShall I start planning? You can also tell me anything to change."


def new_session() -> dict:
    return {"request": {}, "optional_asked": False, "confirming": False, "language": "English"}


def localize(text: str, language: str) -> str:
    """Translate a code-written message into the user's language (no-op for English)."""
    if not language or language.strip().lower().startswith("english"):
        return text
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL_NAME,
            temperature=0,
            messages=[
                {"role": "system", "content": (
                    f"Translate the user's message into {language}, using the same script the "
                    "language description implies. If the description says romanized, use plain "
                    "English letters only, with no accents or diacritics, the way people type on "
                    "a phone. Keep numbers, dates, currency amounts, names and the bullet-list "
                    "layout unchanged. Output only the translation."
                )},
                {"role": "user", "content": text},
            ],
        )
        return response.choices[0].message.content.strip() or text
    except Exception:
        return text


def _ask_model(history: list, session: dict, today: date) -> dict:
    system = SYSTEM_PROMPT.format(
        today=today.isoformat(),
        request=json.dumps(session["request"]),
        missing=", ".join(missing_fields(session["request"])) or "nothing",
    )
    messages = [{"role": "system", "content": system}] + history[-HISTORY_TURNS:]
    for _ in range(2):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL_NAME,
                temperature=0,
                response_format={"type": "json_object"},
                messages=messages,
            )
            data = json.loads(response.choices[0].message.content)
            if isinstance(data.get("updates"), dict) and isinstance(data.get("reply"), str):
                return data
        except Exception:
            continue
    return {"updates": {}, "reply": ""}


def intake_turn(history: list, session: dict, today: date = None) -> tuple:
    """Process the latest user message (last item of history).

    Returns (reply_text, ready). When ready is True, trip_inputs(session["request"])
    holds the confirmed, validated trip.
    """
    today = today or date.today()
    request = session["request"]
    data = _ask_model(history, session, today)
    updates = data["updates"]
    reply = data["reply"].strip()
    changed = {k for k in updates if k not in ("confirmed", "skip_optional")}
    if isinstance(data.get("language"), str) and data["language"].strip():
        session["language"] = data["language"].strip()[:40]
    language = session.get("language", "English")

    problems = apply_updates(request, updates, today)
    missing = missing_fields(request)
    note = (localize(" ".join(problems), language) + " ") if problems else ""

    if missing:
        session["confirming"] = False
        if not reply or "?" not in reply:
            lead = reply + " " if reply else localize("Sorry, I didn't catch that.", language) + " "
            reply = lead + localize(question_for(missing[0], request), language)
        return note + reply, False

    if not session["optional_asked"]:
        session["optional_asked"] = True
        return note + localize(optional_question(request), language), False

    if session["confirming"] and updates.get("confirmed") is True and not changed:
        return localize("Great, planning your trip now.", language), True

    session["confirming"] = True
    return note + localize(summarize(request), language), False
