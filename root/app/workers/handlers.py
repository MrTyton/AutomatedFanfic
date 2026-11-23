"""
Failure and success handling logic for worker processes.
"""

from datetime import date, datetime, timedelta, timezone
import random
import traceback

from calibre_integration import update_strategies
import config
from config.schemas.poller import LibraryPollerConfig, SitePollerConfig
from config.store import ConfigStore
import ff_logging
from models import fanfic_info
from models import retry_types
from models.context import WorkerContext
from parsers import regex_parsing
from services import poller_scheduler
from workers import fff_runner


def resolve_site_poller_config(
    config_store: ConfigStore | None,
    site: str,
) -> SitePollerConfig:
    """Resolve the SitePollerConfig for a site from ConfigStore, falling back to defaults."""
    if config_store is None:
        return SitePollerConfig()

    site_key = site.strip().lower()
    raw_sites = config_store.get("library_poller.sites")
    if isinstance(raw_sites, dict):
        raw_cfg = raw_sites.get(site_key) or raw_sites.get(site)
        if isinstance(raw_cfg, SitePollerConfig):
            return raw_cfg
        if isinstance(raw_cfg, dict):
            try:
                return SitePollerConfig.model_validate(raw_cfg)
            except Exception:
                return SitePollerConfig()

    raw_poller = config_store.get("library_poller")
    if isinstance(raw_poller, LibraryPollerConfig):
        return raw_poller.sites.get(site_key, SitePollerConfig())
    if isinstance(raw_poller, dict):
        nested_sites = raw_poller.get("sites")
        if isinstance(nested_sites, dict):
            raw_cfg = nested_sites.get(site_key) or nested_sites.get(site)
            if isinstance(raw_cfg, SitePollerConfig):
                return raw_cfg
            if isinstance(raw_cfg, dict):
                try:
                    return SitePollerConfig.model_validate(raw_cfg)
                except Exception:
                    return SitePollerConfig()

    return SitePollerConfig()


def is_poller_equal_chapters_noop(
    fanfic: fanfic_info.FanficInfo,
    fff_result: fff_runner.FanFicFareResult,
) -> bool:
    """Return True when a poller-triggered download failed solely due to equal_chapters."""
    if fanfic.source != "poller":
        return False
    if fff_result.exception is not None or not fff_result.failure_messages:
        return False
    return all(
        regex_parsing.equal_chapters.search(msg) is not None
        for msg in fff_result.failure_messages
    )


def handle_poller_equal_chapters(
    fanfic: fanfic_info.FanficInfo,
    ctx: WorkerContext,
    fff_result: fff_runner.FanFicFareResult,
    *,
    remote_updated_at: date | None = None,
) -> bool:
    """Treat a poller download that hit equal_chapters as a silent no-op."""
    chapter_count: int | None = None
    for msg in fff_result.failure_messages:
        match = regex_parsing.equal_chapters.search(msg)
        if match is not None:
            chapter_count = int(match.group(1))
            break

    ff_logging.log(
        f"\t({fanfic.site}) Poller download for {fanfic.url} is already up to date "
        f"(equal chapters: {chapter_count if chapter_count is not None else 'unknown'}) — "
        f"treating as silent no-op"
    )

    if ctx.poller_store is not None:
        try:
            now = datetime.now(timezone.utc)
            site_cfg = resolve_site_poller_config(ctx.config_store, fanfic.site)
            tracked = ctx.poller_store.get_tracked_story(fanfic.url)
            recent_downloads = ctx.poller_store.get_recent_download_timestamps(
                fanfic.url,
                now - timedelta(days=site_cfg.cool_max_age_days),
            )
            effective_update_date = remote_updated_at or (
                tracked.last_update_date if tracked is not None else None
            )
            interval_days = poller_scheduler.compute_effective_interval_days(
                effective_update_date,
                recent_downloads,
                now.date(),
                site_cfg,
            )
            next_check_at = poller_scheduler.compute_next_check(
                now,
                interval_days,
                site_cfg.jitter_ratio,
                random.Random(),
            )
            ctx.poller_store.record_probe_outcome(
                url=fanfic.url,
                site=fanfic.site,
                outcome="unchanged",
                checked_at=now,
                next_check_at=next_check_at,
                remote_chapters=chapter_count,
                remote_updated_at=remote_updated_at,
                remote_status=None,
                error_message=None,
                advance_baseline=True,
            )
        except Exception as e:
            ff_logging.log(
                f"\t({fanfic.site}) Failed to update poller store on equal_chapters no-op for {fanfic.url}: {e}",
                "WARNING",
            )

    fanfic.retry_decision = None
    ctx.history_recorder.record_download_success(
        url=fanfic.url,
        title=fanfic.title,
        calibre_id=fanfic.calibre_id,
        site=fanfic.site,
    )
    return True


def _refresh_poller_after_download(
    fanfic: fanfic_info.FanficInfo,
    ctx: WorkerContext,
    known_chapters: int | None,
) -> None:
    """Refresh poller tracking state after any successful Calibre download."""
    poller_store = ctx.poller_store
    if poller_store is None:
        return
    try:
        now = datetime.now(timezone.utc)
        site_cfg = resolve_site_poller_config(ctx.config_store, fanfic.site)
        recent_downloads = poller_store.get_recent_download_timestamps(
            fanfic.url,
            now - timedelta(days=site_cfg.cool_max_age_days),
        )
        interval_days = poller_scheduler.compute_effective_interval_days(
            now.date(),
            recent_downloads,
            now.date(),
            site_cfg,
        )
        new_next_check_at = poller_scheduler.compute_next_check(
            now,
            interval_days,
            site_cfg.jitter_ratio,
            random.Random(),
        )
        poller_store.mark_story_downloaded(
            url=fanfic.url,
            downloaded_at=now,
            new_next_check_at=new_next_check_at,
            known_chapters=known_chapters,
        )
    except Exception as e:
        ff_logging.log(
            f"\t({fanfic.site}) Failed to refresh poller schedule after download of {fanfic.url}: {e}",
            "WARNING",
        )


def handle_failure(
    fanfic: fanfic_info.FanficInfo,
    ctx: WorkerContext,
    error_message: str | None = None,
) -> None:
    """
    Handle failure of a fanfiction download/update task.

    Determines whether to retry, activate Hail-Mary protocol, or abandon the task
    based on the number of failures and configuration.

    Args:
        fanfic: The fanfiction story object.
        ctx: WorkerContext containing notification_info, waiting_queue, retry_config,
             calibre_client, and optional history_recorder.
        error_message: Optional detailed failure message.
    """
    retry_config = ctx.retry_config
    notification_info = ctx.notification_info
    waiting_queue = ctx.waiting_queue
    cdb = ctx.cdb_info
    history_recorder = ctx.history_recorder

    # Sync hot-reloaded retry settings if ConfigStore is attached
    if hasattr(retry_config, "update_from_config_store"):
        retry_config.update_from_config_store()

    fanfic.increment_repeat()

    # Check for special case: force requested but update_no_force configured
    is_force_with_update_no_force = bool(
        cdb and fanfic.behavior == "force" and cdb.update_method == "update_no_force"
    )

    # Get comprehensive retry decision including timing and notifications
    retry_count = fanfic.repeats or 0
    decision = retry_types.determine_retry_decision(
        retry_count, retry_config, is_force_with_update_no_force
    )

    # Store the decision in the fanfic object for later use by ff_waiter
    fanfic.retry_decision = decision

    # Handle decision based on action
    if decision.action == retry_types.FailureAction.ABANDON:
        if decision.should_notify:
            notification_info.send_notification(
                "Fanfiction Update Permanently Skipped",
                f"Update for {fanfic.url} was permanently skipped because a force was requested but the update method is set to 'update_no_force'. The force request was ignored and a normal update was attempted instead.",
                fanfic.site,
            )

        ff_logging.log_failure(
            f"Maximum retries reached for {fanfic.title}. "
            f"Abandoning after {fanfic.repeats} attempts."
        )
        history_recorder.record_download_abandoned(
            fanfic.url,
            (
                error_message
                if error_message is not None
                else f"Maximum retries reached after {fanfic.repeats} attempts"
            ),
            site=fanfic.site,
        )
        return

    # Handle RETRY and HAIL_MARY cases
    if decision.action == retry_types.FailureAction.HAIL_MARY:
        ff_logging.log_failure(
            f"Maximum attempts reached for {fanfic.url}. Activating Hail-Mary Protocol."
        )

        if decision.should_notify:
            notification_info.send_notification(
                f"Fanfiction Download Failed, trying Hail-Mary in {decision.delay_minutes / 60:.2f} hours.",
                fanfic.url,
                fanfic.site,
            )

    ff_logging.log_failure(
        f"Sending {fanfic.title or fanfic.url} to waiting queue for {decision.action.value}. "
        f"Attempt {fanfic.repeats}, delay {decision.delay_minutes:.1f} min"
    )

    # Record retry event in history and update download status to waiting
    history_recorder.record_retry(
        url=fanfic.url,
        site=fanfic.site,
        attempt_number=fanfic.repeats or 0,
        action=decision.action.value,
        delay_minutes=decision.delay_minutes,
        error_message=error_message,
    )
    history_recorder.record_download_waiting(
        url=fanfic.url,
        site=fanfic.site,
        title=fanfic.title,
        error_message=error_message,
    )

    # Send to waiting queue with decision information attached
    waiting_queue.put(fanfic)


def check_active_removal(fanfic: fanfic_info.FanficInfo) -> bool:
    """Determine if a fanfic should be removed from `active_urls`.

    Args:
        fanfic (FanficInfo): Fanfiction task object with optional `retry_decision`.

    Returns:
        bool: True if the URL should be removed from `active_urls` (abandoned or
            finished), False if it is waiting for retry (`RETRY` or `HAIL_MARY`).
    """
    if hasattr(fanfic, "retry_decision") and fanfic.retry_decision:
        action = fanfic.retry_decision.action
        if (
            action == retry_types.FailureAction.RETRY
            or action == retry_types.FailureAction.HAIL_MARY
        ):
            return False
    return True


def process_fanfic_addition(
    fanfic: fanfic_info.FanficInfo,
    ctx: WorkerContext,
    temp_dir: str,
    path_or_url: str,
    *,
    known_chapters: int | None = None,
) -> bool:
    """
    Integrate downloaded fanfic with Calibre library.

    Args:
        fanfic: Fanfiction info
        ctx: WorkerContext bundling calibre_client, notification_info, waiting_queue, retry_config, etc.
        temp_dir: Temporary directory path
        path_or_url: Path or URL being processed

    Returns:
        bool: True if the URL should be removed from active_urls (succeeded or abandoned),
              False if it is waiting for retry.
    """
    site = fanfic.site
    calibre_client = ctx.calibre_client
    notification_info = ctx.notification_info
    history_recorder = ctx.history_recorder

    try:
        # Determine if the story exists in Calibre
        # We already checked in pipeline.py (common.get_path_or_url), so fanfic.calibre_id should be set if it exists.
        story_id = fanfic.calibre_id

        if story_id:
            ff_logging.log(f"\t({site}) Story is in Calibre with Story ID: {story_id}")
            # Existing story - use metadata preservation mode from config
            mode = calibre_client.cdb_info.metadata_preservation_mode

            if mode == config.MetadataPreservationMode.ADD_FORMAT:
                strategy: update_strategies.UpdateStrategy = (
                    update_strategies.AddFormatStrategy()
                )
            elif mode == config.MetadataPreservationMode.PRESERVE_METADATA:
                strategy = update_strategies.PreserveMetadataStrategy()
            else:
                strategy = update_strategies.RemoveAddStrategy()
        else:
            # New story
            strategy = update_strategies.AddNewStoryStrategy()

        # Execute the chosen strategy
        outcome = strategy.execute(
            fanfic=fanfic,
            calibre_client=calibre_client,
            temp_dir=temp_dir,
            path_or_url=path_or_url,
        )
        if isinstance(outcome, tuple):
            success, error_msg = outcome
        else:
            success, error_msg = bool(outcome), None

        if success:
            fanfic.retry_decision = None
            if fanfic.title:
                ff_logging.set_thread_story_title(fanfic.title)
            if fanfic.calibre_id:
                ff_logging.log(f"\t({site}) Story ID: {fanfic.calibre_id}")

            ff_logging.log(f"\t({site}) Successfully processed {fanfic.title}")

            history_recorder.record_download_success(
                url=fanfic.url,
                title=fanfic.title,
                calibre_id=fanfic.calibre_id,
                site=fanfic.site,
            )

            if ctx.poller_store is not None:
                _refresh_poller_after_download(fanfic, ctx, known_chapters)

            ff_logging.log_debug(
                f"\t({site}) Sending success notification for {fanfic.title}"
            )
            notification_info.send_notification(
                "New Fanfiction Download", fanfic.title or "Unknown Title", site
            )
            return True

        handle_failure(
            fanfic,
            ctx,
            error_message=error_msg,
        )
        return check_active_removal(fanfic)

    except Exception as e:
        tb = traceback.format_exc()
        ff_logging.log_failure(f"Error processing additions to Calibre: {e}\n{tb}")
        full_err = f"{e}\n{tb}".strip()
        history_recorder.record_download_failed(fanfic.url, full_err, site=fanfic.site)
        handle_failure(
            fanfic,
            ctx,
            error_message=full_err,
        )
        return check_active_removal(fanfic)
