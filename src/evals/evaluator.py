import re


class ItineraryEvaluator:
    _TOTAL_COST = re.compile(r"Total Cost:\s*\**\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)

    @staticmethod
    def evaluate_budget(compiled_itinerary: str, max_budget: float) -> dict:
        matches = ItineraryEvaluator._TOTAL_COST.findall(compiled_itinerary or "")

        if not matches:
            return {"success": True, "feedback": None}

        total_cost = float(matches[-1].replace(",", ""))

        if total_cost <= 0:
            return {
                "success": False,
                "feedback": (
                    "FAILED EVALUATION: No complete plan was produced (total cost is 0). "
                    "Choose the cheapest available flight and hotel, even if close to the budget."
                ),
            }

        if total_cost > max_budget:
            return {
                "success": False,
                "feedback": (
                    f"FAILED EVALUATION: Total itinerary price of {total_cost:,.2f} "
                    f"crosses the budget cap of {max_budget:,.2f}. "
                    "Please optimize and choose a different hotel option."
                ),
            }

        return {"success": True, "feedback": None}
