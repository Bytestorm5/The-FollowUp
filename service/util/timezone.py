import datetime as _dt
import os as _os


def fixed_offset_tz() -> _dt.timezone:
    """Return a fixed UTC-5 timezone (no DST), explicitly -05:00.

    This is intentionally a fixed offset and does not observe daylight saving time.
    """
    return _dt.timezone(_dt.timedelta(hours=-5), name="UTC-05:00")


def now_utc_minus_5() -> _dt.datetime:
    """Current time in fixed UTC-5 timezone as an aware datetime."""
    return _dt.datetime.now(_dt.timezone.utc).astimezone(fixed_offset_tz())


def today_utc_minus_5() -> _dt.date:
    """Today as a date in fixed UTC-5 timezone."""
    return now_utc_minus_5().date()


def pipeline_today() -> _dt.date:
    """Resolve pipeline 'today':

    - If `PIPELINE_RUN_DATE` env var is set (YYYY-MM-DD), use that date.
    - Otherwise, return fixed UTC-5 'today'.
    """
    v = _os.environ.get("PIPELINE_RUN_DATE")
    if v:
        try:
            return _dt.date.fromisoformat(v)
        except Exception:
            pass
    return today_utc_minus_5()


def pipeline_yesterday() -> _dt.date:
    """Return pipeline 'yesterday' relative to fixed UTC-5."""
    return today_utc_minus_5() - _dt.timedelta(days=1)
