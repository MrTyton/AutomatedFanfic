"""
Failure and success handling logic for worker processes.
"""

from models import config_models
from models import retry_types
from models import fanfic_info
from models.context import WorkerContext
from utils import ff_logging
from calibre_integration import update_strategies


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
        if history_recorder:
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
    if history_recorder:
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
    """
    Helper to determine if a failed fanfic should be removed from active_urls.
    Returns True if it should be removed (abandoned or finished),
    False if it's waiting for retry (Hail Mary/Retry).
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

            if mode == config_models.MetadataPreservationMode.ADD_FORMAT:
                strategy: update_strategies.UpdateStrategy = (
                    update_strategies.AddFormatStrategy()
                )
            elif mode == config_models.MetadataPreservationMode.PRESERVE_METADATA:
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
            if fanfic.calibre_id:
                ff_logging.log(f"\t({site}) Story ID: {fanfic.calibre_id}")

            ff_logging.log(f"\t({site}) Successfully processed {fanfic.title}")

            if history_recorder:
                history_recorder.record_download_success(
                    url=fanfic.url,
                    title=fanfic.title,
                    calibre_id=fanfic.calibre_id,
                    site=fanfic.site,
                )

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
        ff_logging.log_failure(f"Error processing additions to Calibre: {e}")
        if history_recorder:
            history_recorder.record_download_failed(
                fanfic.url, str(e), site=fanfic.site
            )
        handle_failure(
            fanfic,
            ctx,
            error_message=str(e),
        )
        return check_active_removal(fanfic)
