import apprise
import ff_logging
import notification_base
from notification_base import JobConfigLoadError

class AppriseNotification(notification_base.NotificationBase):
    def __init__(self, toml_path: str):
        super().__init__(toml_path)
        self.apprise_urls = set() # Use a set to avoid duplicates initially
        self.apobj = apprise.Apprise()
        self.enabled = False

        try:
            # Load URLs from [apprise] section
            apprise_config = self.config.get("apprise")
            if apprise_config:
                user_apprise_urls = apprise_config.get("urls", [])
                for url in user_apprise_urls:
                    self.apprise_urls.add(url)
            
            # Automatically add Pushbullet config if enabled
            pushbullet_config = self.config.get("pushbullet", {})
            if pushbullet_config.get("enabled") and pushbullet_config.get("api_key"):
                pb_api_key = pushbullet_config["api_key"]
                pb_url = f"pbul://{pb_api_key}"
                pb_device = pushbullet_config.get("device")
                if pb_device:
                    pb_url += f"/{pb_device}"
                
                if pb_url not in self.apprise_urls:
                    self.apprise_urls.add(pb_url)
                    ff_logging.log_info(f"Automatically added Pushbullet URL to Apprise: {pb_url}")
                else:
                    ff_logging.log_info(f"Pushbullet URL {pb_url} was already present in Apprise config.")

        except Exception as e:
            ff_logging.log_error(f"Error processing Apprise/Pushbullet configuration: {e}")
            # Depending on desired behavior, we might raise JobConfigLoadError here
            # For now, we'll let it try to enable if any URLs were processed before error.

        if not self.apprise_urls:
            ff_logging.log_info("No Apprise URLs configured (including auto-added Pushbullet). Apprise disabled.")
            self.enabled = False
            return

        # Add all unique URLs to the Apprise object
        for url in self.apprise_urls:
            if not self.apobj.add(url):
                ff_logging.log_warning(f"Failed to add Apprise URL: {url}. It might be invalid or unsupported.")
        
        # Check if any URLs were successfully added to the Apprise object
        if self.apobj.urls():
            self.enabled = True
            ff_logging.log_info(f"Apprise enabled with {len(self.apobj.urls())} notification target(s).")
        else:
            ff_logging.log_warning("Apprise configured with URLs, but none could be successfully added to Apprise. Apprise disabled.")
            self.enabled = False
            # Convert set back to list for consistent attribute type, though it's not strictly used later
        self.apprise_urls = list(self.apprise_urls)


    @notification_base.retry_decorator
    def send_notification(self, title: str, body: str, site: str) -> bool:
        if not self.enabled or not self.apobj: # Check self.apobj too
            return False

        # URLs are already added to self.apobj in __init__
        success = False
        if self.apobj.notify(body=body, title=title):
            ff_logging.log_success(f"Apprise notification sent successfully to {len(self.apobj.urls())} target(s).")
            success = True
        else:
            ff_logging.log_failure(f"Failed to send Apprise notification to {len(self.apobj.urls())} target(s).")
        return success

    def is_enabled(self) -> bool:
        return self.enabled

    def get_service_name(self) -> str:
        return "Apprise"
