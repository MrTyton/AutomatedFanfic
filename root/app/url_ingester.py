import multiprocessing as mp
import socket
from contextlib import contextmanager
import time
import logging

from fanficfare import geturls
import ff_logging
import regex_parsing
import tomllib

@contextmanager
def set_timeout(time):
    """Set a timeout for socket operations."""
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(time)
    try:
        yield
    finally:
        socket.setdefaulttimeout(old_timeout)

class EmailInfo:
    """
    A class used to ingest URLs from an email account.

    Attributes:
    email (str): The email address.
    password (str): The password for the email account.
    smtp_server (str): The SMTP server for the email account.
    mailbox (str): The mailbox from which to ingest URLs.

    Methods:
    get_urls(): Get URLs from the email account.
    """

    def __init__(self, toml_path: str):
        """
        Initialize the UrlIngester with the email account information from a TOML file.

        Parameters:
        toml_path (str): The path of the TOML file.
        """
        with open(toml_path, "rb") as file:
            config = tomllib.load(file)
        email_config = config.get("email", {})
        self.email = email_config.get("email")
        self.password = email_config.get("password")
        self.server = email_config.get("server")
        self.mailbox = email_config.get("mailbox")
        self.sleep_time = email_config.get("sleep_time")

    def get_urls(self) -> set[str]:
        """
        Get URLs from the email account.

        Returns:
        set[str]: A set of URLs.
        """
        urls = set()
                # Save the current logging level
        old_level = logging.root.manager.disable

        # Set the logging level to CRITICAL
        logging.disable(logging.CRITICAL)
        with set_timeout(55):
            try:
                # Get URLs from the email account
                urls = geturls.get_urls_from_imap(self.server, self.email, self.password, self.mailbox)
            except Exception as e:
                logging.disable(old_level)
                ff_logging.log_failure(f"Failed to get URLs: {e}")
            finally:
                # Restore the old logging level
                logging.disable(old_level)
        return urls
    


def email_watcher(email_info: EmailInfo, processor_queues: dict[str, mp.Queue]):
    """
    Continuously watch an email account for new URLs and add them to the appropriate processor queues.

    Parameters:
    email_info (EmailInfo): The email information object.
    processor_queues (dict[str, mp.Queue]): A dictionary mapping site names to processor queues.

    Returns:
    None
    """
    while True:
        # Get URLs from the email account
        urls = email_info.get_urls()
        # For each URL, generate a FanficInfo object and add it to the appropriate processor queue
        for url in urls:
            fanfic = regex_parsing.generate_FanficInfo_from_url(url)
            ff_logging.log(f"Adding {fanfic.url} to the {fanfic.site} processor queue", "OKBLUE")
            processor_queues[fanfic.site].put(fanfic)
        # Sleep for the specified amount of time before checking the email account again
        time.sleep(email_info.sleep_time)
