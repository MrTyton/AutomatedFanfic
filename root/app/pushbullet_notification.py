from pushbullet import InvalidKeyError, Pushbullet, PushbulletError
from requests.exceptions import ConnectionError

import ff_logging
import notification_base


class PushbulletNotification(notification_base.NotificationBase):
    # Initialization Function
    def __init__(self, toml_path: str):
        super().__init__(toml_path)
        # Extract the Pushbullet configuration
        pushbullet_config = self.config.get("pushbullet", None)
        if pushbullet_config is None:
            return

        # Check if Pushbullet is enabled
        self.enabled = pushbullet_config["enabled"]
        if not self.enabled:
            return

        try:
            # Initialize the Pushbullet client
            self.pb = Pushbullet(pushbullet_config["api_key"])
            # If a device is specified, get the device
            device = pushbullet_config["device"]
            if device:
                self.pb = self.pb.get_device(device)
        except InvalidKeyError:
            message = "Invalid Pushbullet API key in the config file. Cannot send notifications."
            ff_logging.log_failure(message)
            self.enabled = False
        except PushbulletError as e:
            message = f"Pushbullet error: {e}. Cannot send notifications."
            ff_logging.log_failure(message)
            self.enabled = False

    # Function to send a notification
    @notification_base.retry_decorator
    def send_notification(self, title: str, body: str, site: str) -> bool:
        # If Pushbullet is enabled, send the notification
        try:
            ff_logging.log(
                f"\t({site}) Sending Pushbullet notification: {title} - {body}",
                "OKGREEN",
            )
            self.pb.push_note(title, body)
            return True
        except PushbulletError as e:
            message = f"\tFailed to send Pushbullet notification: {e}"
            ff_logging.log_failure(message)
            return False
        except ConnectionError as e:
            message = f"\tPushbullet notification failed with connection error, retrying: {e}"
            ff_logging.log_failure(message)
            return False
