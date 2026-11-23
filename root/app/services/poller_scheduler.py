"""Pure, deterministic adaptive scheduling and candidate scoring for library polling."""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import math
import random
import statistics
from typing import Literal

from config.schemas.poller import SitePollerConfig
from history.poller_store import TrackedStory

PollTier = Literal["hot", "warm", "cool", "dormant"]
CadenceKind = Literal["weekday", "interval"]

_SECONDS_PER_DAY = 86400.0
_MIN_CADENCE_INTERVAL_DAYS = 0.5
_CADENCE_SAFETY_FACTOR = 0.8
_HOT_STAGGER_MAX_DAYS = 1.0
_DEDUP_WINDOW_SECONDS = 12 * 3600.0
_WEEKDAY_COVERAGE_THRESHOLD = 0.80
_WEEKDAY_SINGLE_MIN_SPAN_DAYS = 12
_WEEKDAY_MULTI_MIN_SPAN_DAYS = 10
_MIN_INTERVAL_MEDIAN_GAP_DAYS = 10.0
_MAX_INTERVAL_MAD_RATIO = 0.25
_MONTHLY_MIN_GAP_DAYS = 26.0
_MONTHLY_MAX_GAP_DAYS = 35.0
_PREDICTIVE_AFTER_BUFFER_HOURS = 6.0
_PREDICTIVE_JITTER_HOURS = 1.0
_PREDICTIVE_MIN_DELAY_HOURS = 1.0
_WEEKDAY_NAMES: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class CadenceEstimate:
    """Estimated update cadence derived from recent download timestamps."""

    kind: CadenceKind
    weekdays: tuple[int, ...]
    typical_hour_utc: float
    median_gap_days: float
    is_regular: bool
    sample_count: int
    label: str


def _to_utc(dt: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def classify_tier(
    last_update_date: date | None,
    today: date,
    cfg: SitePollerConfig,
) -> tuple[PollTier, float]:
    """Classify a story into a polling tier and return its base interval in days."""
    if last_update_date is None:
        return ("dormant", cfg.dormant_interval_days)
    age_days = max(0, (today - last_update_date).days)
    if age_days <= cfg.hot_max_age_days:
        return ("hot", cfg.hot_interval_days)
    if age_days <= cfg.warm_max_age_days:
        return ("warm", cfg.warm_interval_days)
    if age_days <= cfg.cool_max_age_days:
        return ("cool", cfg.cool_interval_days)
    return ("dormant", cfg.dormant_interval_days)


def compute_effective_interval_days(
    last_update_date: date | None,
    recent_downloads: list[datetime],
    today: date,
    cfg: SitePollerConfig,
) -> float:
    """Compute polling interval in days, tightening when recent downloads show faster cadence."""
    _tier, base_interval = classify_tier(last_update_date, today, cfg)
    if len(recent_downloads) < 2:
        return base_interval

    sorted_timestamps = sorted(_to_utc(ts) for ts in recent_downloads)
    positive_gaps_days = [
        gap_seconds / _SECONDS_PER_DAY
        for prev_ts, curr_ts in zip(sorted_timestamps, sorted_timestamps[1:])
        if (gap_seconds := (curr_ts - prev_ts).total_seconds()) > 0.0
    ]
    if not positive_gaps_days:
        return base_interval

    median_gap_days = statistics.median(positive_gaps_days)
    cadence_interval = max(
        _MIN_CADENCE_INTERVAL_DAYS,
        median_gap_days * _CADENCE_SAFETY_FACTOR,
    )
    return min(base_interval, cadence_interval)


def compute_next_check(
    now: datetime,
    interval_days: float,
    jitter_ratio: float,
    rng: random.Random,
) -> datetime:
    """Compute next check timestamp by applying uniform random jitter to interval_days."""
    multiplier = rng.uniform(1.0 - jitter_ratio, 1.0 + jitter_ratio)
    return now + timedelta(days=interval_days * multiplier)


def _circular_mean_hour_utc(timestamps: list[datetime]) -> float:
    """Compute circular mean hour-of-day in [0.0, 24.0) from UTC timestamps."""
    if not timestamps:
        return 12.0
    sin_sum = 0.0
    cos_sum = 0.0
    for dt in timestamps:
        hour_val = dt.hour + dt.minute / 60.0
        angle = hour_val * 2.0 * math.pi / 24.0
        sin_sum += math.sin(angle)
        cos_sum += math.cos(angle)
    if math.isclose(sin_sum, 0.0, abs_tol=1e-12) and math.isclose(
        cos_sum, 0.0, abs_tol=1e-12
    ):
        return 12.0
    mean_angle = math.atan2(sin_sum, cos_sum)
    if mean_angle < 0.0:
        mean_angle += 2.0 * math.pi
    return (mean_angle * 24.0 / (2.0 * math.pi)) % 24.0


def _next_weekday_dt(
    base_date: date,
    weekdays: tuple[int, ...],
    typical_hour_utc: float,
) -> datetime:
    """Return the strictly next calendar date matching `weekdays` at `typical_hour_utc`."""
    for day_offset in range(1, 8):
        candidate_date = base_date + timedelta(days=day_offset)
        if candidate_date.weekday() in weekdays:
            return datetime(
                candidate_date.year,
                candidate_date.month,
                candidate_date.day,
                tzinfo=timezone.utc,
            ) + timedelta(hours=typical_hour_utc)
    # Unreachable when weekdays is non-empty with values in 0..6
    return datetime(
        base_date.year,
        base_date.month,
        base_date.day,
        tzinfo=timezone.utc,
    ) + timedelta(days=7, hours=typical_hour_utc)


def estimate_update_cadence(
    recent_downloads: list[datetime],
) -> CadenceEstimate | None:
    """Estimate a story's update cadence from recent successful download timestamps.

    Deduplicates timestamps within 12 hours of each other so retries or repeated
    downloads do not skew patterns. Detects:
    1. Weekday-set schedules (1 to 3 recurring weekdays, e.g. Sat, Tue/Thu, Mon/Wed/Fri)
    2. Multi-week fixed-interval cadences (e.g. bi-weekly ~14d, monthly ~30d)
    """
    if len(recent_downloads) < 3:
        return None

    sorted_timestamps = sorted(_to_utc(ts) for ts in recent_downloads)
    deduped: list[datetime] = []
    for ts in sorted_timestamps:
        if not deduped or (ts - deduped[-1]).total_seconds() >= _DEDUP_WINDOW_SECONDS:
            deduped.append(ts)

    n = len(deduped)
    if n < 3:
        return None

    gaps = [
        gap_seconds / _SECONDS_PER_DAY
        for prev_ts, curr_ts in zip(deduped, deduped[1:])
        if (gap_seconds := (curr_ts - prev_ts).total_seconds()) > 0.0
    ]
    if len(gaps) < 2:
        return None

    median_gap = statistics.median(gaps)
    typical_hour_utc = _circular_mean_hour_utc(deduped)
    span_days = (deduped[-1] - deduped[0]).days

    # Primary detector: Weekday-set schedule (1 to 3 recurring weekdays per week)
    if median_gap < _MIN_INTERVAL_MEDIAN_GAP_DAYS:
        counts = Counter(dt.weekday() for dt in deduped)
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        for size in (1, 2, 3):
            if len(ranked) < size:
                continue
            candidate = tuple(sorted(day for day, _cnt in ranked[:size]))
            hits = sum(counts[d] for d in candidate)
            coverage = hits / n
            if size == 1:
                valid = (
                    n >= 3
                    and coverage >= _WEEKDAY_COVERAGE_THRESHOLD
                    and hits >= 3
                    and span_days >= _WEEKDAY_SINGLE_MIN_SPAN_DAYS
                )
            else:
                valid = (
                    n >= 4
                    and coverage >= _WEEKDAY_COVERAGE_THRESHOLD
                    and all(counts[d] >= 2 for d in candidate)
                    and span_days >= _WEEKDAY_MULTI_MIN_SPAN_DAYS
                )
            if valid:
                label = "/".join(_WEEKDAY_NAMES[d] for d in candidate)
                return CadenceEstimate(
                    kind="weekday",
                    weekdays=candidate,
                    typical_hour_utc=typical_hour_utc,
                    median_gap_days=median_gap,
                    is_regular=True,
                    sample_count=n,
                    label=label,
                )

    # Secondary detector: Multi-week fixed-interval cadence (e.g. bi-weekly, monthly)
    mad = statistics.median([abs(g - median_gap) for g in gaps])
    if (
        median_gap >= _MIN_INTERVAL_MEDIAN_GAP_DAYS
        and (mad / median_gap) <= _MAX_INTERVAL_MAD_RATIO
    ):
        label = (
            "Monthly (~30d)"
            if _MONTHLY_MIN_GAP_DAYS <= median_gap <= _MONTHLY_MAX_GAP_DAYS
            else f"Every ~{round(median_gap)}d"
        )
        return CadenceEstimate(
            kind="interval",
            weekdays=(),
            typical_hour_utc=typical_hour_utc,
            median_gap_days=median_gap,
            is_regular=True,
            sample_count=n,
            label=label,
        )

    return CadenceEstimate(
        kind="interval",
        weekdays=(),
        typical_hour_utc=typical_hour_utc,
        median_gap_days=median_gap,
        is_regular=False,
        sample_count=n,
        label="",
    )


def compute_predictive_next_check(
    now: datetime,
    last_update_date: date | None,
    recent_downloads: list[datetime],
    cfg: SitePollerConfig,
    rng: random.Random,
) -> datetime:
    """Compute next check time using predictive schedule when regular, bounded by tier ceiling."""
    now_utc = _to_utc(now)
    _, tier_interval_days = classify_tier(last_update_date, now_utc.date(), cfg)
    ceiling_dt = now_utc + timedelta(days=tier_interval_days)

    if last_update_date is not None:
        estimate = estimate_update_cadence(recent_downloads)
        if estimate is not None and estimate.is_regular:
            latest_download_utc = max(_to_utc(ts) for ts in recent_downloads)
            if latest_download_utc.date() >= last_update_date:
                base_dt = latest_download_utc
            else:
                base_dt = datetime(
                    last_update_date.year,
                    last_update_date.month,
                    last_update_date.day,
                    tzinfo=timezone.utc,
                ) + timedelta(hours=estimate.typical_hour_utc)

            if estimate.kind == "weekday":
                predicted_dt = _next_weekday_dt(
                    base_dt.date(),
                    estimate.weekdays,
                    estimate.typical_hour_utc,
                )
            else:
                predicted_dt = base_dt + timedelta(days=estimate.median_gap_days)

            target = predicted_dt + timedelta(hours=_PREDICTIVE_AFTER_BUFFER_HOURS)
            if target > now_utc:
                jitter_hours = rng.uniform(
                    -_PREDICTIVE_JITTER_HOURS, _PREDICTIVE_JITTER_HOURS
                )
                min_next = now_utc + timedelta(hours=_PREDICTIVE_MIN_DELAY_HOURS)
                if ceiling_dt < min_next:
                    return ceiling_dt
                return min(
                    max(target + timedelta(hours=jitter_hours), min_next), ceiling_dt
                )

            return compute_next_check(
                now_utc,
                min(1.0, cfg.hot_interval_days),
                cfg.jitter_ratio,
                rng,
            )

    interval_days = compute_effective_interval_days(
        last_update_date,
        recent_downloads,
        now_utc.date(),
        cfg,
    )
    return compute_next_check(now_utc, interval_days, cfg.jitter_ratio, rng)


def compute_initial_staggered_check(
    now: datetime,
    last_update_date: date | None,
    cfg: SitePollerConfig,
    rng: random.Random,
) -> datetime:
    """Spread newly discovered stories across their tier window to avoid startup bursts."""
    today = _to_utc(now).date()
    tier, interval_days = classify_tier(last_update_date, today, cfg)
    window_days = (
        min(interval_days, _HOT_STAGGER_MAX_DAYS) if tier == "hot" else interval_days
    )
    offset_days = rng.uniform(0.0, window_days)
    return now + timedelta(days=offset_days)


def compute_error_backoff(
    now: datetime,
    consecutive_errors: int,
    max_backoff_days: float,
) -> datetime:
    """Compute exponential error backoff timestamp capped at max_backoff_days."""
    delay_days = min(
        1.0 * (2 ** max(0, consecutive_errors - 1)),
        max_backoff_days,
    )
    return now + timedelta(days=delay_days)


def select_next_candidate(
    due_stories: list[TrackedStory],
    now: datetime,
    cfg: SitePollerConfig,
) -> TrackedStory | None:
    """Select the most overdue story normalized by its tier base interval."""
    if not due_stories:
        return None

    now_utc = _to_utc(now)
    today = now_utc.date()

    def _priority_key(story: TrackedStory) -> tuple[float, datetime, str]:
        _tier, base_interval_days = classify_tier(story.last_update_date, today, cfg)
        next_check_utc = _to_utc(story.next_check_at)
        overdue_seconds = (now_utc - next_check_utc).total_seconds()
        normalized_ratio = overdue_seconds / (base_interval_days * _SECONDS_PER_DAY)
        return (-normalized_ratio, next_check_utc, story.url)

    return min(due_stories, key=_priority_key)
