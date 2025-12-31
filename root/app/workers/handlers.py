"""
Failure and success handling logic for worker processes.
"""

import multiprocessing as mp

import config_models
import retry_types
import calibre_info
import fanfic_info
import notification_wrapper
import calibredb_utils
import ff_logging
import update_strategies


def handle_failure(
    fanfic: fanfic_info.FanficInfo,
    notification_info: notification_wrapper.NotificationWrapper,
    waiting_queue: mp.Queue,
    retry_config: config_models.RetryConfig,
    cdb: calibre_info.CalibreInfo | None = None,
) -> None:
    """
    Handle failure of a fanfiction download/update task.

    Determines whether to retry, activate Hail-Mary protocol, or abandon the task
    based on the number of failures and configuration.

    Args:
        fanfic (fanfic_info.FanficInfo): The fanfiction story object.
        notification_info (notification_wrapper.NotificationWrapper): Notification wrapper.
        waiting_queue (mp.Queue): Queue to put the task back into for retry.
        retry_config (config_models.RetryConfig): Retry configuration.
        cdb (calibre_info.CalibreInfo, optional): Calibre configuration info.
    """
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
        f"Sending {fanfic.title} to waiting queue for {decision.action.value}. "
        f"Attempt {fanfic.repeats}"
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
    calibre_client: calibredb_utils.CalibreDBClient,
    temp_dir: str,
    site: str,
    path_or_url: str,
    waiting_queue: mp.Queue,
    notification_info: notification_wrapper.NotificationWrapper,
    retry_config: config_models.RetryConfig,
) -> None:
    """
    Integrate downloaded fanfic with Calibre library.

    Args:
        fanfic: Fanfiction info
        calibre_client: CalibreDB client
        temp_dir: Temporary directory path
        site: Site identifier
        path_or_url: Path or URL being processed
        waiting_queue: Queue for retries
        notification_info: Notification wrapper
        retry_config: Retry configuration
    """
    try:
        # Determine strategy
        story_id = calibre_client.get_story_id(fanfic.url)

        if story_id:
            # Existing story
            strategy = update_strategies.RemoveAddStrategy(calibre_client, ff_logging)
            success = strategy.execute(story_id, path_or_url, fanfic, temp_dir)
        else:
            # New story
            strategy = update_strategies.AddNewStoryStrategy(calibre_client, ff_logging)
            success = strategy.execute(path_or_url, fanfic, temp_dir)

        if success:
            ff_logging.log(f"({site}) Successfully processed {fanfic.title}")
        else:
            # Strategy failed
            handle_failure(
                fanfic,
                notification_info,
                waiting_queue,
                retry_config,
                calibre_client.cdb_info,
            )

    except Exception as e:
        ff_logging.log_failure(f"Error processing additions to Calibre: {e}")
        handle_failure(
            fanfic,
            notification_info,
            waiting_queue,
            retry_config,
            calibre_client.cdb_info,
        )
