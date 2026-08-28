"""Natural-language expiry date parsing (no AI needed — pure stdlib)."""
import re
from datetime import date, timedelta

_IN_N_UNITS = re.compile(
    r"^(?:in\s+)?(\d+)\s*(day|days|d|week|weeks|w|month|months|m|mo)$"
)

_TODAY = ("today", "tonight")
_TOMORROW = ("tomorrow", "tmr", "tmrw", "2moro", "2morrow")


def parse_expiry_input(raw: str) -> str:
    """Parse an expiry description into an ISO date string (YYYY-MM-DD).

    Accepted inputs:
      - natural phrases: ``today``, ``tomorrow``, ``in 3 days``, ``2 weeks``,
        ``next week``, ``next month``
      - ``DD/MM`` (year inferred as the next occurrence; also accepts ``-``,
        ``.`` or space as the separator)

    Raises:
        ValueError: if the input cannot be understood.
    """
    text = (raw or "").strip().lower()
    today = date.today()

    if text in _TODAY:
        return today.isoformat()
    if text in _TOMORROW:
        return (today + timedelta(days=1)).isoformat()
    if text in ("next week", "in a week", "1 week"):
        return (today + timedelta(days=7)).isoformat()
    if text in ("next month", "in a month", "1 month"):
        return (today + timedelta(days=30)).isoformat()

    match = _IN_N_UNITS.match(text)
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        if unit in ("day", "days", "d"):
            delta = timedelta(days=n)
        elif unit in ("week", "weeks", "w"):
            delta = timedelta(weeks=n)
        else:  # month(s), m, mo
            delta = timedelta(days=30 * n)
        return (today + delta).isoformat()

    # DD/MM style — also accepts "-", "." or space separators.
    parts = text.replace("/", " ").replace("-", " ").replace(".", " ").split()
    if len(parts) >= 2:
        try:
            day, month = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError(f"Unrecognised expiry date: {raw!r}") from None
        try:
            expiry = date(today.year, month, day)
        except ValueError:
            # Impossible calendar date (e.g. Feb 30)
            raise ValueError(f"Invalid calendar date: {raw!r}") from None
        if expiry < today:
            try:
                expiry = date(today.year + 1, month, day)
            except ValueError:
                raise ValueError(f"Invalid calendar date: {raw!r}") from None
        return expiry.isoformat()

    raise ValueError(f"Unrecognised expiry date: {raw!r}")
