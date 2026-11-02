"""Routing and readable text for self-contained arithmetic questions."""
from __future__ import annotations

import re


def is_self_contained_math_request(text: str) -> bool:
    value = " ".join(str(text or "").lower().split())
    # Requests for current facts or explicit browsing still need real sources.
    if re.search(
        r"\b(?:search (?:the )?(?:web|internet)|look up|lookup|current|latest|"
        r"today|tonight|yesterday|right now|live|news|market prices?)\b"
        r"|\bfind\b.{0,60}\b(?:vendors?|suppliers?|prices?)\b"
        r"|\b(?:grants?|funding|eligib\w*|regulations?|licenses?|permits?|"
        r"legal\w*|laws?|admissions?|tax (?:laws?|rules?|rates?))\b",
        value,
    ):
        return False
    numbers = re.findall(r"(?<!\w)\$?\d[\d,]*(?:\.\d+)?%?", value)
    intent = re.search(
        r"\b(?:calculat\w*|comput\w*|solve|arithmetic|algebra|equations?|"
        r"word problem|how many|maximum|minimum|greatest|smallest|"
        r"total (?:cost|price)|how much)\b",
        value,
    )
    operations = re.search(
        r"\b(?:each|costs?|percent|discount|tax|budget|sum|average|speed|distance|"
        r"hours?|profit|loss|ratio|fraction|remainder)\b|[%=+*/]",
        value,
    )
    return len(numbers) >= 2 and bool(intent and operations)


def readable_calculation(text: str) -> str:
    """Plain text, not HTML; preserves values and leaves unknown notation intact."""
    value = str(text or "")
    value = re.sub(r"\\(?:\(|\)|\[|\])", "", value)
    commands = {
        "times": "×", "cdot": "·", "div": "÷", "leq": "≤", "le": "≤",
        "geq": "≥", "ge": "≥", "approx": "≈", "neq": "≠",
        "implies": "⇒", "therefore": "∴", "to": "→",
    }
    value = re.sub(
        r"\\(" + "|".join(sorted(commands, key=len, reverse=True)) + r")\b",
        lambda match: commands[match.group(1)],
        value,
    )
    # Convert innermost fractions first, retaining parentheses for precedence.
    for _ in range(8):
        converted = re.sub(
            r"\\(?:dfrac|tfrac|frac)\{([^{}]+)\}\{([^{}]+)\}",
            lambda m: f"({m.group(1)})/({m.group(2)})",
            value,
        )
        if converted == value:
            break
        value = converted
    value = re.sub(r"\\(?:text|mathrm|mathbf)\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\\(?:left|right)\b", "", value)
    value = value.replace(r"\%", "%").replace(r"\$", "$").replace(r"\,", " ")
    value = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", value)
    value = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", value)
    return value
