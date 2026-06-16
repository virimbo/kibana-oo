"""Custom time-range support: resolve_window (absolute from/to with validation,
falling back to the rolling period) and interval_for_span (auto bucket sizing)."""
from datetime import datetime, timedelta, timezone

from monitoring import interval_for_span, period_bounds, resolve_window

NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)


def test_no_from_to_falls_back_to_period():
    start, end, custom = resolve_window(60, None, None, now=NOW)
    assert custom is False
    assert (start, end) == period_bounds(60, NOW)


def test_absolute_range_used_verbatim():
    start, end, custom = resolve_window(
        60, "2026-01-01T00:00:00+00:00", "2026-03-31T23:59:59+00:00", now=NOW)
    assert custom is True
    assert start.year == 2026 and start.month == 1
    assert end.month == 3


def test_future_end_is_clamped_to_now():
    _, end, custom = resolve_window(60, "2026-06-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00", now=NOW)
    assert custom is True and end == NOW


def test_inverted_range_keeps_a_sane_span():
    start, end, custom = resolve_window(60, "2026-06-16T11:00:00+00:00", "2026-06-16T09:00:00+00:00", now=NOW)
    assert custom is True and start < end


def test_epoch_millis_parsed():
    ms_from = int(datetime(2026, 6, 10, tzinfo=timezone.utc).timestamp() * 1000)
    ms_to = int(datetime(2026, 6, 12, tzinfo=timezone.utc).timestamp() * 1000)
    start, end, custom = resolve_window(60, str(ms_from), str(ms_to), now=NOW)
    assert custom is True and start.day == 10 and end.day == 12


def test_only_from_uses_now_as_end():
    start, end, custom = resolve_window(60, "2026-06-15T00:00:00+00:00", None, now=NOW)
    assert custom is True and end == NOW and start.day == 15


def test_interval_scales_with_span():
    assert interval_for_span(NOW - timedelta(hours=1), NOW).endswith("m")
    assert interval_for_span(NOW - timedelta(days=365), NOW).endswith("d")
    # a 6-hour window buckets into minutes, not seconds
    iv = interval_for_span(NOW - timedelta(hours=6), NOW)
    assert iv.endswith("m") or iv.endswith("h")
