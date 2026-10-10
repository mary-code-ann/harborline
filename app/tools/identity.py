"""Compare a caller's stated identity with the account. The model does not do this."""

import re
from datetime import date

MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_NAME = re.compile(r"my name is\s+([A-Za-z]+(?:\s+[A-Za-z]+){1,3})", re.IGNORECASE)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MDY = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONTH_FIRST = re.compile(
    r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\,?\s+(\d{4})",
    re.IGNORECASE,
)
_DAY_FIRST = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")\,?\s+(\d{4})",
    re.IGNORECASE,
)


def normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def names_match(stated: str, on_file: str) -> bool:
    return normalize_name(stated) == normalize_name(on_file)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_dob(text: str) -> date | None:
    """Pull one calendar date out of free text. Returns None when nothing valid is there."""
    if not text:
        return None
    iso = _ISO.search(text)
    if iso:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    named = _MONTH_FIRST.search(text)
    if named:
        return _safe_date(int(named.group(3)), MONTHS[named.group(1).casefold()], int(named.group(2)))
    day_first = _DAY_FIRST.search(text)
    if day_first:
        return _safe_date(
            int(day_first.group(3)), MONTHS[day_first.group(2).casefold()], int(day_first.group(1))
        )
    numeric = _MDY.search(text)
    if numeric:
        return _safe_date(int(numeric.group(3)), int(numeric.group(1)), int(numeric.group(2)))
    return None


def extract_name(text: str) -> str | None:
    match = _NAME.search(text)
    if not match:
        return None
    raw = match.group(1)
    for stopper in (" and ", " dob", " date"):
        index = raw.casefold().find(stopper)
        if index != -1:
            raw = raw[:index]
    cleaned = " ".join(raw.split())
    parts = cleaned.split()
    if len(parts) < 2:
        return None
    return cleaned
