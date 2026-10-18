import re


class InputGuardrail:
    _INJECTION_PATTERNS = [
        re.compile(p, re.IGNORECASE)
        for p in (
            r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instructions|prompts?|rules)",
            r"disregard\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instructions|prompts?|rules)",
            r"system\s+override",
            r"(act|behave)\s+as\s+(a\s+|an\s+)?(developer|dev|admin|root)\s+mode",
            r"developer\s+mode",
            r"you\s+are\s+now\s+(dan|jailbroken|unrestricted)",
            r"reveal\s+(your\s+)?(system\s+)?prompt",
            r"\b(eval|exec|compile)\s*\(",
            r"__import__",
            r"\bimport\s+(os|sys|subprocess|shutil)\b",
            r"\bsubprocess\b",
            r"\bos\.system\b",
            r"\brm\s+-rf\b",
            r"<\s*script\b",
            r"\$\(.*\)",
            r"`[^`]*`",
        )
    ]

    @staticmethod
    def validate_input(user_input: str) -> bool:
        for pattern in InputGuardrail._INJECTION_PATTERNS:
            if pattern.search(user_input):
                return False
        return True


class OutputGuardrail:
    _MASK = "XXXX-XXXX"
    _SENSITIVE_PATTERNS = [
        re.compile(p)
        for p in (
            r"\b(?:\d[ -]?){13,19}\b",                      # credit card numbers
            r"\b\d{3}-\d{2}-\d{4}\b",                       # US SSN layout
            r"\b(?:sk|gsk|pk|rk)[-_][A-Za-z0-9_-]{16,}\b",  # API key layouts
            r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}",      # bearer tokens
            r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b",  # JWT layout
        )
    ]

    @staticmethod
    def mask_private_telemetry(payload: str) -> str:
        for pattern in OutputGuardrail._SENSITIVE_PATTERNS:
            payload = pattern.sub(OutputGuardrail._MASK, payload)
        return payload
