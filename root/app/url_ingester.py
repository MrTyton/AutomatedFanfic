import multiprocessing as mp
import socket
import time
import logging
from contextlib import contextmanager
from fanficfare import geturls
import ff_logging
import regex_parsing
import notification_wrapper
from config_models import ConfigManager


@contextmanager
def set_timeout(timeout_duration):
    """
    Context manager to temporarily set a socket operation timeout.

    Args:
        timeout_duration (int): The timeout duration in seconds.
    """
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_duration)
    try:
        yield
    finally:
        socket.setdefaulttimeout(old_timeout)


@contextmanager
def suppress_logging():
    """
    A context manager that temporarily suppresses all logging output.

    This context manager disables all logging across the application by setting the
    logging level to CRITICAL, which is the highest level. Only messages with a
    level CRITICAL or higher would be processed. Since typically there are no
    messages at a level higher than CRITICAL, this effectively suppresses all
    logging while the context manager is active. Once the code block using this
    context manager exits, the original logging level is restored, allowing logging
    to proceed as before.

    Usage:
        with suppress_logging():
            # Code block where logging is suppressed
            pass

    Yields:
        None
    """
    # Save the current global logging level
    old_level = logging.root.manager.disable
    # Temporarily set global logging level to CRITICAL to suppress all logging
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(old_level)


class EmailInfo:
    """
    A class for ingesting URLs from an email account based on provided credentials
    and server information.

    Attributes:
        email (str): The email address.
        password (str): The password for the email account.
        server (str): The IMAP server for the email account.
        mailbox (str): The mailbox from which to ingest URLs.
        sleep_time (int): Time to wait between checks for new emails.

    Methods:
        get_urls(): Retrieves URLs from the specified mailbox.
    """

    def __init__(self, toml_path: str):
        """
        Initializes the EmailInfo object with configuration from a TOML file.

        This constructor reads the specified TOML configuration file to set up the
        EmailInfo object. It extracts email-related configuration such as the email
        address, password, server, and mailbox to be used for email operations.
        Additionally, it sets a default sleep time for operations that require waiting.

        Args:
            toml_path (str): The path to the TOML configuration file.
        """
        # Load configuration using the new ConfigManager
        config = ConfigManager.load_config(toml_path)

        # Extract email configuration with proper type safety
        email_config = config.email

        # Set attributes from the validated configuration
        self.email = email_config.email
        self.password = email_config.password
        self.server = email_config.server
        self.mailbox = email_config.mailbox
        self.sleep_time = email_config.sleep_time
        self.ffnet_disable = email_config.ffnet_disable

    def get_urls(self) -> set[str]:
        """
        Retrieves URLs from the email account's specified mailbox.

        Returns:
            set[str]: A set of URLs found in the emails.
        """
        urls = set()

        with set_timeout(55), suppress_logging():
            try:
                urls = geturls.get_urls_from_imap(
                    self.server, self.email, self.password, self.mailbox
                )
            except Exception as e:
                ff_logging.log_failure(f"Failed to get URLs: {e}")

        return urls


def email_watcher(
    email_info: EmailInfo,
    notification_info: notification_wrapper.NotificationWrapper,
    processor_queues: dict[str, mp.Queue],
):
    """
    Watches an email account for new URLs and adds them to the appropriate processor queues.

    Parameters:
        email_info (EmailInfo): The email information object.
        notification_info (notification_wrapper.NotificationWrapper): The notification information object.
        processor_queues (dict[str, mp.Queue]): A dictionary mapping site names to processor queues.
    """
    while True:
        # Get URLs from the email account
        urls = email_info.get_urls()
        fics_to_add = set()
        for url in urls:
            fanfic = regex_parsing.generate_FanficInfo_from_url(url)

            # Workaround for ffnet issues
            if email_info.ffnet_disable and fanfic.site == "ffnet":
                notification_info.send_notification(
                    "New Fanfiction Download", fanfic.url, fanfic.site
                )
                continue
            fics_to_add.add(fanfic)
        for fic in fics_to_add:
            ff_logging.log(
                f"Adding {fic.url} to the {fic.site} processor queue",
                "HEADER",
            )
            processor_queues[fic.site].put(fic)
        # Wait before checking the email account again
        time.sleep(email_info.sleep_time)
