"""Timestamp parsing for OCPP 2.0.1 messages.

Chargers send RFC 3339 strings ("2026-11-21T12:29:39Z", with or without
fractional seconds or an offset). asyncpg needs real datetime objects for
timestamptz columns; passing the string raised
"expected a datetime.date or datetime.datetime instance, got 'str'" for every
handler that stores a time (StatusNotification, TransactionEvent, MeterValues,
SecurityEventNotification).
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def parse_timestamp(value, default: datetime | None = None) -> datetime:
    """Return a timezone-aware datetime; falls back to `default` (or now) when missing or invalid."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value:
        text = str(value).strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning("Unparseable OCPP timestamp %r, using server time", value)
    return default or datetime.now(timezone.utc)
