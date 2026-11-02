"""Email monitoring loop for AutomatedFanfic."""

import time

from config.store import ConfigStore
import ff_logging
from history.recorder import HistoryRecorder
from models import active_urls as active_urls_utils
from models.active_urls import ActiveUrlsDict
from models.queue_types import CheckEmailsEvent, IngressQueue, ShutdownEvent
from notifications import notification_wrapper
from parsers import regex_parsing
from services.email_client import EmailInfo


def email_watcher(
    email_info: EmailInfo,
    notification_info: notification_wrapper.NotificationWrapper,
    ingress_queue: IngressQueue,
    url_parsers: dict,
    active_urls: ActiveUrlsDict,
    verbose: bool,
    shutdown_event: ShutdownEvent,
    history_recorder: HistoryRecorder,
    config_store: ConfigStore,
    check_emails_event: CheckEmailsEvent | None,
) -> None:
    """Continuously monitor email for fanfiction URLs and route to the ingress queue."""
    ff_logging.set_verbose(verbose)
    ff_logging.set_thread_color("\033[93m")  # Yellow
    is_manual = False

    while True:
        if shutdown_event.is_set():
            ff_logging.log_debug("EmailWatcher received shutdown signal")
            break

        if check_emails_event is not None and check_emails_event.is_set():
            check_emails_event.clear()
            is_manual = True
            ff_logging.log("EmailWatcher: manual email check triggered")

        if email_info.update_from_config_store(config_store):
            ff_logging.log_debug(
                "EmailWatcher: credentials updated from ConfigStore, rebuilding URL extractor"
            )
            email_info._build_geturls()

        urls = email_info.get_urls()
        fics_to_add = set()
        processed_in_batch = set()

        urls_found = len(urls)
        urls_new = 0
        urls_duplicate = 0
        urls_disabled_site = 0

        for url in urls:
            fanfic = regex_parsing.generate_FanficInfo_from_url(url, url_parsers)
            fanfic.from_email = True

            if fanfic.url in processed_in_batch:
                continue
            processed_in_batch.add(fanfic.url)

            if fanfic.site in email_info.disabled_sites:
                urls_disabled_site += 1
                notification_info.send_notification(
                    "New Fanfiction Download", fanfic.url, fanfic.site
                )
                continue

            if active_urls_utils.is_url_active(active_urls, fanfic.url):
                urls_duplicate += 1
                ff_logging.log(
                    f"Skipping {fanfic.url} - already in queue or processing",
                    "WARNING",
                )
                continue

            urls_new += 1
            fics_to_add.add(fanfic)
            active_urls_utils.mark_url_queued(active_urls, fanfic.url, site=fanfic.site)

        for fic in fics_to_add:
            ff_logging.log(
                f"Adding {fic.url} to the ingestion queue (Site: {fic.site})"
            )
            ingress_queue.put(fic)
            history_recorder.record_download_created(fic.url, fic.site, fic.behavior)

        trigger = (
            "manual" if is_manual else ("idle" if email_info.imap_idle else "poll")
        )
        is_manual = False
        history_recorder.record_email_check(
            urls_found=urls_found,
            urls_new=urls_new,
            urls_duplicate=urls_duplicate,
            urls_disabled_site=urls_disabled_site,
            trigger=trigger,
        )

        if email_info.imap_idle:
            idle_notified = email_info._idle_wait_for_notification(
                shutdown_event, check_emails_event
            )
            if not idle_notified:
                break
        elif check_emails_event is None:
            if shutdown_event.wait(timeout=email_info.sleep_time):
                break
        else:
            start_wait = time.monotonic()
            while not shutdown_event.is_set():
                if check_emails_event.is_set():
                    break
                elapsed = time.monotonic() - start_wait
                remaining = email_info.sleep_time - elapsed
                if remaining <= 0:
                    break
                if shutdown_event.wait(timeout=min(1.0, remaining)):
                    break
            if shutdown_event.is_set():
                break
