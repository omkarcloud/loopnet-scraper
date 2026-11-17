"""Date helpers for parsers: whatever a site prints -> ISO text, or None."""
import re
from datetime import datetime

from scraper_utils.text import clean as text

_LONG_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y")


def iso_date(value):
    """'21 Sep 2026' / '2026-09-22T…' / 'September 22, 2026' -> 'YYYY-MM-DD'.
    A slash date is read month first ('03/04/2026' is 4 March)."""
    value = text(value)
    if not value:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if match:
        return "-".join(match.groups())
    for fmt in _LONG_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def iso_datetime(value):
    """'2026-09-18T04:30:49.433Z' / {dateTimeUtc} -> '2026-09-18T04:30:49Z' (the
    clock time as written, to the second); a bare date -> 'YYYY-MM-DD'."""
    if isinstance(value, dict):
        value = value.get("dateTimeUtc") or value.get("dateTime") or value.get("shortAbsoluteLabel")
    value = text(value)
    if not value:
        return None
    match = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})", value)
    if match:
        return f"{match.group(1)}T{match.group(2)}Z"
    return iso_date(value)
