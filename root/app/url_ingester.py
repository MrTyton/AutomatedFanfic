import multiprocessing as mp
import socket
import time
import logging
import tomllib
from contextlib import contextmanager
from fanficfare import geturls
import ff_logging
import regex_parsing
import notification_base


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
        # Open the TOML configuration file in binary mode
        with open(toml_path, "rb") as file:
            # Load the configuration from the TOML file
            config = tomllib.load(file)
        # Retrieve the 'email' section from the loaded configuration
        email_config = config.get("email", {})
        # Set the email address from the configuration
        self.email = email_config.get("email")
        # Set the password for the email account from the configuration
        self.password = email_config.get("password")
        # Set the email server from the configuration
        self.server = email_config.get("server")
        # Set the mailbox to be used from the configuration
        self.mailbox = email_config.get("mailbox")
        # Set the default sleep time, defaulting to 60 seconds if not specified
        self.sleep_time = email_config.get("sleep_time", 60)

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
    notification_info: notification_base.NotificationBase,
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
            if fanfic.site == "ffnet":
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
