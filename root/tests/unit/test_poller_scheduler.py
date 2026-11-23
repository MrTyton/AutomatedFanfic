"""Unit tests for adaptive library update poller scheduling and scoring."""

from datetime import date, datetime, timedelta, timezone
import random

import pytest

from config.schemas.poller import SitePollerConfig
from history.poller_store import TrackedStory
from services.poller_scheduler import (
    CadenceEstimate,
    PollTier,
    classify_tier,
    compute_effective_interval_days,
    compute_error_backoff,
    compute_initial_staggered_check,
    compute_next_check,
    compute_predictive_next_check,
    estimate_update_cadence,
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


def test_estimate_update_cadence_regular_irregular_and_dedup() -> None:
    base = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)  # Thursday

    # Fewer than 3 distinct updates -> None
    assert estimate_update_cadence([]) is None
    assert estimate_update_cadence([base, base + timedelta(days=7)]) is None
    # 3 timestamps within 12h collapse to 1 -> None
    assert (
        estimate_update_cadence(
            [base, base + timedelta(hours=2), base + timedelta(hours=5)]
        )
        is None
    )

    # Regular weekly Thursday cadence (7d) with a retry 3h after one download -> deduplicated
    weekly = [
        base,
        base + timedelta(days=7),
        base + timedelta(days=7, hours=3),  # duplicate retry within 12h
        base + timedelta(days=14),
        base + timedelta(days=21),
    ]
    est_weekly = estimate_update_cadence(weekly)
    assert isinstance(est_weekly, CadenceEstimate)
    assert est_weekly.kind == "weekday"
    assert est_weekly.weekdays == (3,)
    assert est_weekly.label == "Thu"
    assert est_weekly.typical_hour_utc == pytest.approx(12.0, abs=0.1)
    assert est_weekly.median_gap_days == pytest.approx(7.0)
    assert est_weekly.is_regular is True
    assert est_weekly.sample_count == 4

    # Regular bi-weekly cadence (14d exact on same weekday -> interval, not weekly weekday)
    biweekly_exact = [
        base,
        base + timedelta(days=14),
        base + timedelta(days=28),
        base + timedelta(days=42),
    ]
    est_biweekly_exact = estimate_update_cadence(biweekly_exact)
    assert est_biweekly_exact is not None
    assert est_biweekly_exact.kind == "interval"
    assert est_biweekly_exact.weekdays == ()
    assert est_biweekly_exact.is_regular is True
    assert est_biweekly_exact.median_gap_days == pytest.approx(14.0)
    assert est_biweekly_exact.label == "Every ~14d"

    # Regular bi-weekly cadence with slight variance (13d, 14d, 15d -> MAD=1, 1/14=0.071 <= 0.25)
    biweekly = [
        base,
        base + timedelta(days=13),
        base + timedelta(days=27),
        base + timedelta(days=42),
    ]
    est_biweekly = estimate_update_cadence(biweekly)
    assert est_biweekly is not None
    assert est_biweekly.kind == "interval"
    assert est_biweekly.is_regular is True
    assert est_biweekly.median_gap_days == pytest.approx(14.0)
    assert est_biweekly.label == "Every ~14d"
    assert est_biweekly.sample_count == 4

    # Monthly cadence (~30d) -> Monthly (~30d)
    monthly = [
        base,
        base + timedelta(days=30),
        base + timedelta(days=61),
        base + timedelta(days=90),
    ]
    est_monthly = estimate_update_cadence(monthly)
    assert est_monthly is not None
    assert est_monthly.kind == "interval"
    assert est_monthly.is_regular is True
    assert est_monthly.label == "Monthly (~30d)"

    # Irregular cadence (2d, 25d, 3d, 30d) -> is_regular is False
    irregular = [
        base,
        base + timedelta(days=2),
        base + timedelta(days=27),
        base + timedelta(days=30),
        base + timedelta(days=60),
    ]
    est_irregular = estimate_update_cadence(irregular)
    assert est_irregular is not None
    assert est_irregular.is_regular is False

    # Fast daily cadence (span < 10d and median_gap < 10d) -> is_regular is False
    daily = [base, base + timedelta(days=1), base + timedelta(days=2)]
    est_daily = estimate_update_cadence(daily)
    assert est_daily is not None
    assert est_daily.is_regular is False


def test_weekday_set_schedules_mon_wed_fri_and_tue_thu() -> None:
    cfg = SitePollerConfig()
    rng = random.Random(42)

    # Mon/Wed/Fri at 18:00 UTC (Nov 2, 2026 is Monday)
    mwf_downloads = [
        datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc),  # Mon
        datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc),  # Wed
        datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc),  # Fri
        datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc),  # Mon
        datetime(2026, 11, 11, 18, 0, tzinfo=timezone.utc),  # Wed
        datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc),  # Fri
        datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc),  # Mon
        datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc),  # Wed
        datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc),  # Fri
    ]
    est_mwf = estimate_update_cadence(mwf_downloads)
    assert est_mwf is not None
    assert est_mwf.kind == "weekday"
    assert est_mwf.weekdays == (0, 2, 4)
    assert est_mwf.label == "Mon/Wed/Fri"
    assert est_mwf.is_regular is True
    assert est_mwf.typical_hour_utc == pytest.approx(18.0, abs=0.05)

    # Checked Sun Nov 22 18:00 UTC -> next slot is Mon Nov 23 18:00 + 6h = Tue Nov 24 00:00 ± 1h
    now_sun = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)
    next_check = compute_predictive_next_check(
        now_sun, date(2026, 11, 20), mwf_downloads, cfg, rng
    )
    expected_mwf_target = datetime(2026, 11, 24, 0, 0, tzinfo=timezone.utc)
    assert (
        expected_mwf_target - timedelta(hours=1)
        <= next_check
        <= expected_mwf_target + timedelta(hours=1)
    )

    # Tue/Thu at 15:30 UTC (Nov 3, 2026 is Tuesday)
    tt_downloads = [
        datetime(2026, 11, 3, 15, 30, tzinfo=timezone.utc),  # Tue
        datetime(2026, 11, 5, 15, 30, tzinfo=timezone.utc),  # Thu
        datetime(2026, 11, 10, 15, 30, tzinfo=timezone.utc),  # Tue
        datetime(2026, 11, 12, 15, 30, tzinfo=timezone.utc),  # Thu
        datetime(2026, 11, 17, 15, 30, tzinfo=timezone.utc),  # Tue
        datetime(2026, 11, 19, 15, 30, tzinfo=timezone.utc),  # Thu
    ]
    est_tt = estimate_update_cadence(tt_downloads)
    assert est_tt is not None
    assert est_tt.kind == "weekday"
    assert est_tt.weekdays == (1, 3)
    assert est_tt.label == "Tue/Thu"
    assert est_tt.is_regular is True
    assert est_tt.typical_hour_utc == pytest.approx(15.5, abs=0.05)


def test_weekly_saturday_schedule_uses_after_buffer_and_handles_late_author() -> None:
    cfg = SitePollerConfig()
    rng = random.Random(42)

    # Weekly Saturday author at noon UTC: Oct 31, Nov 7, Nov 14, Nov 21
    sat_downloads = [
        datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc),
    ]
    est_sat = estimate_update_cadence(sat_downloads)
    assert est_sat is not None
    assert est_sat.kind == "weekday"
    assert est_sat.weekdays == (5,)
    assert est_sat.label == "Sat"
    assert est_sat.typical_hour_utc == pytest.approx(12.0, abs=0.05)

    # Expected target is Sat Nov 28 12:00 + 6h = Sat Nov 28 18:00 UTC (~6pm Sat)
    expected_target = datetime(2026, 11, 28, 18, 0, tzinfo=timezone.utc)

    # Checked on Fri Nov 27 12:00 UTC (30h away, within 1.5d hot ceiling) -> ~6pm Sat ± 1h
    now_friday = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
    next_check = compute_predictive_next_check(
        now_friday, date(2026, 11, 21), sat_downloads, cfg, rng
    )
    assert (
        expected_target - timedelta(hours=1)
        <= next_check
        <= expected_target + timedelta(hours=1)
    )

    # Target very close to now (30m away) -> clamped to >= now + 1h
    near_target_now = expected_target - timedelta(minutes=30)
    clamped = compute_predictive_next_check(
        near_target_now, date(2026, 11, 21), sat_downloads, cfg, random.Random(1)
    )
    assert clamped >= near_target_now + timedelta(hours=1)

    # Missed-slot fallback: now is Sun Nov 29 12:00 (past Sat Nov 28 18:00 target)
    # -> checks promptly within min(1.0, hot_interval_days) ± jitter
    now_late = datetime(2026, 11, 29, 12, 0, tzinfo=timezone.utc)
    late_check = compute_predictive_next_check(
        now_late, date(2026, 11, 21), sat_downloads, cfg, random.Random(7)
    )
    late_delta_days = (late_check - now_late).total_seconds() / 86400.0
    assert (
        min(1.0, cfg.hot_interval_days) * (1.0 - cfg.jitter_ratio)
        <= late_delta_days
        <= min(1.0, cfg.hot_interval_days) * (1.0 + cfg.jitter_ratio)
    )

    # Irregular / insufficient downloads -> falls back to tier interval
    fallback_check = compute_predictive_next_check(
        now_friday, date(2026, 11, 21), [], cfg, random.Random(7)
    )
    fallback_delta_days = (fallback_check - now_friday).total_seconds() / 86400.0
    assert (
        cfg.hot_interval_days * (1.0 - cfg.jitter_ratio)
        <= fallback_delta_days
        <= cfg.hot_interval_days * (1.0 + cfg.jitter_ratio)
    )


def test_dormant_ceiling_clamps_extreme_predictive_interval_while_honoring_weekly_and_monthly() -> (
    None
):
    cfg = SitePollerConfig()  # dormant_interval_days=60.0
    rng = random.Random(99)

    # Monthly author (~30d interval): trusted directly without being clamped to hot 1.5d
    monthly_downloads = [
        datetime(2026, 8, 22, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc),
    ]
    est = estimate_update_cadence(monthly_downloads)
    assert est is not None
    assert est.label == "Monthly (~30d)"

    now_hot = datetime(2026, 11, 22, 14, 0, tzinfo=timezone.utc)
    expected_monthly = datetime(2026, 12, 20, 20, 0, tzinfo=timezone.utc)
    monthly_check = compute_predictive_next_check(
        now_hot, date(2026, 11, 20), monthly_downloads, cfg, rng
    )
    assert (
        expected_monthly - timedelta(hours=1)
        <= monthly_check
        <= expected_monthly + timedelta(hours=1)
    )

    # Extreme 90-day regular interval -> capped at dormant_interval_days (60d)
    quarterly_downloads = [
        datetime(2026, 2, 22, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 23, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 19, 14, 0, tzinfo=timezone.utc),
    ]
    dormant_ceiling = now_hot + timedelta(days=cfg.dormant_interval_days)
    quarterly_check = compute_predictive_next_check(
        now_hot, date(2026, 11, 19), quarterly_downloads, cfg, rng
    )
    assert quarterly_check == dormant_ceiling
