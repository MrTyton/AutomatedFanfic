import requests
from requests.exceptions import ConnectionError
import ff_logging
import notification_base


class DiscordNotification(notification_base.NotificationBase):
    def __init__(self, toml_path: str):
        super().__init__(toml_path)
        discord_config = self.config.get("discord", None)
        if discord_config is None:
            return

        self.enabled = discord_config["enabled"]
        if not self.enabled:
            return

        self.webhook_url = discord_config["webhook_url"]
        if not self.webhook_url:
            message = "Discord webhook URL is missing in the config file. Cannot send notifications."
            ff_logging.log_failure(message)
            self.enabled = False

    @notification_base.retry_decorator
    def send_notification(self, title: str, body: str, site: str) -> bool:
        if not self.enabled:
            return False

        try:
            ff_logging.log(
                f"\t({site}) Sending Discord notification: {title} - {body}",
                "OKGREEN",
            )
            data = {
                "content": f"**{title}**\n{body}"
            }
            response = requests.post(self.webhook_url, json=data)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            message = f"\tFailed to send Discord notification: {e}"
            ff_logging.log_failure(message)
            return False
        except ConnectionError as e:
            message = f"\tDiscord notification failed with connection error, retrying: {e}"
            ff_logging.log_failure(message)
            return False