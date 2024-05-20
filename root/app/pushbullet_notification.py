from pushbullet import InvalidKeyError, Pushbullet, PushbulletError

import ff_logging
import tomllib

class PushbulletNotification:
    # Initialization Function
    def __init__(self, toml_path: str):
        # Load the configuration from the TOML file
        with open(toml_path, "rb") as file:
            config = tomllib.load(file)

        # Extract the Pushbullet configuration
        pushbullet_config = config["pushbullet"]

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
    def send_notification(self, title: str, body: str) -> None:
        # If Pushbullet is enabled, send the notification
        if self.enabled:
            try:
                ff_logging.log(f"\tSending Pushbullet notification: {title} - {body}", "OKBLUE")
                self.pb.push_note(title, body)
            except PushbulletError as e:
                message = f"\tFailed to send Pushbullet notification: {e}"
                ff_logging.log_failure(message)