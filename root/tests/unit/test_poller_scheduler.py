"""Unit tests for adaptive library update poller scheduling and scoring."""

from datetime import date, datetime, timedelta, timezone
import random

import pytest

from config.schemas.poller import SitePollerConfig
from history.poller_store import TrackedStory
from services.poller_scheduler import (
    PollTier,
    classify_tier,
    compute_effective_interval_days,
    compute_error_backoff,
    compute_initial_staggered_check,
    compute_next_check,
    select_next_candidate,
)


def _make_tracked_story(
    url: str,
    last_update_date: date | None,
    next_check_at: datetime,
    site: str = "ao3",
) -> TrackedStory:
    return TrackedStory(
        url=url,
        site=site,
        calibre_id="1",
        title="Test Story",
        last_update_date=last_update_date,
        update_date_exact=last_update_date is not None,
        known_chapters=10,
        remote_status="In-Progress",
        last_checked_at=None,
        next_check_at=next_check_at,
        consecutive_no_change=0,
        consecutive_errors=0,
        last_error=None,
        active=True,
        deleted_remotely=False,
    )


def test_classify_tiers_across_age_boundaries() -> None:
    cfg = SitePollerConfig()
    today = date(2026, 11, 22)

    cases: list[tuple[date | None, PollTier, float]] = [
        (today, "hot", cfg.hot_interval_days),
        (today - timedelta(days=14), "hot", cfg.hot_interval_days),
        (today - timedelta(days=15), "warm", cfg.warm_interval_days),
        (today - timedelta(days=90), "warm", cfg.warm_interval_days),
        (today - timedelta(days=91), "cool", cfg.cool_interval_days),
        (today - timedelta(days=365), "cool", cfg.cool_interval_days),
        (today - timedelta(days=366), "dormant", cfg.dormant_interval_days),
        (None, "dormant", cfg.dormant_interval_days),
        (today + timedelta(days=2), "hot", cfg.hot_interval_days),
    ]

    for last_update_date, expected_tier, expected_interval in cases:
        tier, interval_days = classify_tier(last_update_date, today, cfg)
        assert tier == expected_tier
        assert interval_days == expected_interval


def test_cadence_boost_tightens_weekly_author() -> None:
    cfg = SitePollerConfig()
    today = date(2026, 11, 22)
    last_update = today - timedelta(days=15)  # warm tier (base = 7.0d)
    base_time = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

    # 3 downloads 7 days apart -> median gap G = 7.0 -> G * 0.8 = 5.6 (< 7.0)
    weekly_downloads = [
        base_time + timedelta(days=14),
        base_time,
        base_time + timedelta(days=7),
    ]
    weekly_interval = compute_effective_interval_days(
        last_update, weekly_downloads, today, cfg
    )
    assert weekly_interval == pytest.approx(5.6)
    assert weekly_interval < cfg.warm_interval_days

    # Rapid downloads (6 hours = 0.25d apart) hit floor of 0.5d
    rapid_downloads = [
        base_time,
        base_time + timedelta(hours=6),
        base_time + timedelta(hours=12),
    ]
    rapid_interval = compute_effective_interval_days(
        last_update, rapid_downloads, today, cfg
    )
    assert rapid_interval == pytest.approx(0.5)

    # Very slow downloads (30d apart) remain capped by base_interval_days
    slow_downloads = [
        base_time - timedelta(days=60),
        base_time - timedelta(days=30),
        base_time,
    ]
    slow_interval = compute_effective_interval_days(
        last_update, slow_downloads, today, cfg
    )
    assert slow_interval == pytest.approx(cfg.warm_interval_days)

    # Fewer than 2 downloads or zero positive gaps falls back to base_interval_days
    assert compute_effective_interval_days(
        last_update, [base_time], today, cfg
    ) == pytest.approx(cfg.warm_interval_days)
    assert compute_effective_interval_days(
        last_update, [base_time, base_time], today, cfg
    ) == pytest.approx(cfg.warm_interval_days)


def test_compute_next_check_applies_jitter() -> None:
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    rng = random.Random(12345)
    interval_days = 10.0
    jitter_ratio = 0.15

    deltas = [
        (
            compute_next_check(now, interval_days, jitter_ratio, rng) - now
        ).total_seconds()
        / 86400.0
        for _ in range(50)
    ]
    assert min(deltas) >= interval_days * (1.0 - jitter_ratio)
    assert max(deltas) <= interval_days * (1.0 + jitter_ratio)
    assert len(set(deltas)) > 1

    exact = compute_next_check(now, interval_days, 0.0, rng)
    assert exact == now + timedelta(days=interval_days)


def test_initial_stagger_avoids_burst() -> None:
    cfg = SitePollerConfig()
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    today = now.date()

    # Hot stories spread across [now, now + min(hot_interval_days, 1.0)]
    hot_rng = random.Random(42)
    hot_checks = [
        compute_initial_staggered_check(now, today - timedelta(days=3), cfg, hot_rng)
        for _ in range(100)
    ]
    hot_offsets = [(dt - now).total_seconds() / 86400.0 for dt in hot_checks]
    assert all(
        0.0 <= offset <= min(cfg.hot_interval_days, 1.0) for offset in hot_offsets
    )
    assert max(hot_offsets) > 0.5
    assert min(hot_offsets) < 0.2
    assert len(set(hot_checks)) == 100

    # Warm stories spread across [now, now + warm_interval_days]
    warm_rng = random.Random(99)
    warm_checks = [
        compute_initial_staggered_check(now, today - timedelta(days=30), cfg, warm_rng)
        for _ in range(100)
    ]
    warm_offsets = [(dt - now).total_seconds() / 86400.0 for dt in warm_checks]
    assert all(0.0 <= offset <= cfg.warm_interval_days for offset in warm_offsets)
    assert max(warm_offsets) > 1.0
    assert len(set(warm_checks)) == 100


def test_normalized_overdue_ratio_prevents_dormant_starvation() -> None:
    cfg = SitePollerConfig()
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    today = now.date()

    assert select_next_candidate([], now, cfg) is None

    # Scenario 1: dormant 90d overdue (90/60 = 1.5) beats hot 0.5d overdue (0.5/1.5 = 0.333)
    dormant_very_overdue = _make_tracked_story(
        url="https://archiveofourown.org/works/1",
        last_update_date=today - timedelta(days=400),
        next_check_at=now - timedelta(days=90),
    )
    hot_slightly_overdue = _make_tracked_story(
        url="https://archiveofourown.org/works/2",
        last_update_date=today - timedelta(days=2),
        next_check_at=now - timedelta(days=0.5),
    )
    winner_1 = select_next_candidate(
        [hot_slightly_overdue, dormant_very_overdue], now, cfg
    )
    assert winner_1 == dormant_very_overdue

    # Scenario 2: hot 2d overdue (2/1.5 = 1.333) beats dormant 10d overdue (10/60 = 0.167)
    hot_more_overdue = _make_tracked_story(
        url="https://archiveofourown.org/works/3",
        last_update_date=today - timedelta(days=2),
        next_check_at=now - timedelta(days=2),
    )
    dormant_less_overdue = _make_tracked_story(
        url="https://archiveofourown.org/works/4",
        last_update_date=today - timedelta(days=400),
        next_check_at=now - timedelta(days=10),
    )
    winner_2 = select_next_candidate([dormant_less_overdue, hot_more_overdue], now, cfg)
    assert winner_2 == hot_more_overdue

    # Tie-breaking: equal ratio -> earlier next_check_at wins; equal next_check_at -> url
    tie_later_b = _make_tracked_story(
        url="https://archiveofourown.org/works/b",
        last_update_date=today - timedelta(days=30),
        next_check_at=now - timedelta(days=7),
    )
    tie_later_a = _make_tracked_story(
        url="https://archiveofourown.org/works/a",
        last_update_date=today - timedelta(days=30),
        next_check_at=now - timedelta(days=7),
    )
    assert select_next_candidate([tie_later_b, tie_later_a], now, cfg) == tie_later_a

    # Equal ratio (1.0) between hot (1.5d overdue / 1.5d) and warm (7d overdue / 7d):
    # warm has earlier next_check_at so it wins the tie-break
    tie_hot = _make_tracked_story(
        url="https://archiveofourown.org/works/0",
        last_update_date=today - timedelta(days=1),
        next_check_at=now - timedelta(days=1.5),
    )
    assert select_next_candidate([tie_hot, tie_later_b], now, cfg) == tie_later_b


def test_error_backoff_exponential_and_capped() -> None:
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    max_backoff = 30.0

    assert compute_error_backoff(now, 0, max_backoff) == now + timedelta(days=1.0)
    assert compute_error_backoff(now, 1, max_backoff) == now + timedelta(days=1.0)
    assert compute_error_backoff(now, 2, max_backoff) == now + timedelta(days=2.0)
    assert compute_error_backoff(now, 3, max_backoff) == now + timedelta(days=4.0)
    assert compute_error_backoff(now, 10, max_backoff) == now + timedelta(days=30.0)
