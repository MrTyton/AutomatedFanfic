import apprise
import ff_logging
import notification_base
from notification_base import JobConfigLoadError

class AppriseNotification(notification_base.NotificationBase):
    def __init__(self, toml_path: str):
        super().__init__(toml_path)
        self.apprise_urls = []
        self.enabled = False

        try:
            apprise_config = self.config.get("apprise")
            if apprise_config:
                self.apprise_urls = apprise_config.get("urls", [])
        except Exception as e:
            ff_logging.log_error(f"Error loading apprise config: {e}")
            raise JobConfigLoadError("Error loading apprise config") from e

        if self.apprise_urls or self.can_handle_pushbullet():
            self.enabled = True

    @notification_base.retry_decorator
    def send_notification(self, title: str, body: str, site: str) -> bool:
        if not self.enabled:
            return False

        apobj = apprise.Apprise()
        for url in self.apprise_urls:
            apobj.add(url)

        success = False
        if apobj.notify(body=body, title=title):
            ff_logging.log_success(f"Apprise notification sent successfully to {len(self.apprise_urls)} URLs.")
            success = True
        else:
            ff_logging.log_failure(f"Failed to send Apprise notification to {len(self.apprise_urls)} URLs.")
        return success

    def can_handle_pushbullet(self) -> bool:
        try:
            pushbullet_config = self.config.get("pushbullet")
            if pushbullet_config and pushbullet_config.get("enabled"):
                api_key = pushbullet_config.get("api_key")
                device_iden = pushbullet_config.get("device_iden")
                if api_key:
                    # Construct the Apprise Pushbullet URL format
                    # pbul://{apikey}
                    # pbul://{apikey}/{device_id}
                    # pbul://{apikey}/{device_name}
                    # pbul://{apikey}/#{channel_tag}
                    # pbul://{apikey}/{email_addr}
                    # pbul://{apikey}/*  (broadcast to all devices)
                    # pbul://{apikey]/{device_id_1}/{device_id_2} (to multiple devices)

                    # We will check for the simplest pbul://{apikey} and pbul://{apikey}/{device_iden}
                    # as these are the most common use cases from the existing pushbullet config
                    pb_url_base = f"pbul://{api_key}"
                    
                    # Check for broadcast URL
                    if f"{pb_url_base}/*" in self.apprise_urls:
                        return True
                    if pb_url_base in self.apprise_urls: # Handles case where apprise has just the key and will broadcast
                        return True

                    if device_iden:
                        pb_url_with_device = f"{pb_url_base}/{device_iden}"
                        if pb_url_with_device in self.apprise_urls:
                            return True
        except Exception as e:
            ff_logging.log_error(f"Error checking if Apprise can handle Pushbullet: {e}")
        return False

    def is_enabled(self) -> bool:
        return self.enabled

    def get_service_name(self) -> str:
        return "Apprise"
