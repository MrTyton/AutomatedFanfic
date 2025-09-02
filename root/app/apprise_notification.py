import apprise
import ff_logging
import notification_base
import requests


class AppriseNotification(notification_base.NotificationBase):
    def __init__(self, toml_path: str):
        super().__init__(toml_path)
        self.apprise_urls = set()  # Use a set to avoid duplicates initially
        self.apobj = apprise.Apprise()
        self.enabled = False

        # Skip initialization if config loading failed
        if self.config is None:
            return

        try:
            # Load URLs from apprise configuration
            if self.config.apprise.urls:
                for url in self.config.apprise.urls:
                    self.apprise_urls.add(url)

            # Automatically add Pushbullet config if enabled
            if self.config.pushbullet.enabled and self.config.pushbullet.api_key:
                pb_api_key = self.config.pushbullet.api_key
                pb_url = f"pbul://{pb_api_key}"
                pb_device = self.config.pushbullet.device
                if pb_device:
                    ff_logging.log_debug(
                        f"Pushbullet device specified: {pb_device}. Finding device ID..."
                    )
                    r = requests.get(
                        "https://api.pushbullet.com/v2/devices",
                        headers={"Access-Token": pb_api_key},
                    )
                    devices = r.json().get("devices", [])
                    matched_device = next(
                        (
                            device
                            for device in devices
                            if device.get("active")
                            and device.get("pushable")
                            and device.get("nickname") == pb_device
                        ),
                        None,
                    )
                    if matched_device:
                        pb_device = matched_device.get("iden")
                        ff_logging.log_debug(f"Found device ID: {pb_device}")
                        pb_url += f"/{pb_device}"
                    else:
                        ff_logging.log_failure(
                            f"Pushbullet device '{pb_device}' not found or not pushable. Using default Pushbullet URL."
                        )

                if pb_url not in self.apprise_urls:
                    self.apprise_urls.add(pb_url)
                    ff_logging.log_debug(
                        f"Automatically added Pushbullet URL to Apprise: {pb_url}"
                    )
                else:
                    ff_logging.log_debug(
                        f"Pushbullet URL {pb_url} was already present in Apprise config."
                    )

        except Exception as e:
            ff_logging.log_failure(
                f"Error processing Apprise/Pushbullet configuration: {e}"
            )

        if not self.apprise_urls:
            ff_logging.log(
                "No Apprise URLs configured (including auto-added Pushbullet). Apprise disabled."
            )
            self.enabled = False
            return

        # Add all unique URLs to the Apprise object
        for url in self.apprise_urls:
            if not self.apobj.add(url):
                ff_logging.log_failure(
                    f"Failed to add Apprise URL: {url}. It might be invalid or unsupported."
                )

        # Check if any URLs were successfully added to the Apprise object
        urls_list = list(self.apobj.urls())
        if urls_list:
            self.enabled = True
            ff_logging.log(
                f"Apprise enabled with {len(urls_list)} notification target(s)."
            )
        else:
            ff_logging.log_failure(
                "Apprise configured with URLs, but none could be successfully added to Apprise. Apprise disabled."
            )
            self.enabled = False
        self.apprise_urls = list(self.apprise_urls)

    @notification_base.retry_decorator
    def send_notification(self, title: str, body: str, site: str) -> bool:
        if not self.enabled or not self.apobj:  # Check self.apobj too
            return False

        # URLs are already added to self.apobj in __init__
        success = False
        urls_list = list(self.apobj.urls())
        if self.apobj.notify(body=body, title=title):
            ff_logging.log(
                f"({site}) Apprise notification for '{title}':'{body}' sent successfully to {len(urls_list)} {'target' if len(urls_list) == 1 else 'targets'}"
            )
            success = True
        else:
            ff_logging.log_failure(
                f"({site}) Failed to send Apprise notification to {len(urls_list)} target(s)."
            )
        return success

    def is_enabled(self) -> bool:
        return self.enabled

    def get_service_name(self) -> str:
        return "Apprise"
