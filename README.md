# AutomatedFanfic
Automated Fanfiction Download using FanficFare CLI

This is a docker image to run the Automated FFF CLI, with pushbullet integration.

[FanFicFare](https://github.com/JimmXinu/FanFicFare)

[Dockerhub Link](https://hub.docker.com/r/mrtyton/automated-ffdl)

- [AutomatedFanfic](#automatedfanfic)
  - [Site Support](#site-support)
  - [Repeats](#repeats)
  - [Calibre Setup](#calibre-setup)
  - [Execution](#execution)
    - [How to Install - Docker](#how-to-install---docker)
    - [How to Run - Non-Docker](#how-to-run---non-docker)
  - [Configuration](#configuration)
    - [Email](#email)
    - [Calibre](#calibre)
    - [Pushbullet](#pushbullet)
    - [Apprise](#apprise)

## Site Support

This program will support any website that FanFicFare will support. However, it does make use of multi-processing, spawning a different "watcher" for each website. This list is currently hard-coded, and anything not in the list is treated as part of a single queue "other".

If you wish to add more watchers for different websites, then open an issue or submit a request to modify [this](https://github.com/MrTyton/AutomatedFanfic/blob/master/root/app/regex_parsing.py#L7) dictionary.

## Repeats

The script will try to download every story maximum of 11 times, waiting an additional minute for each time - so on the first failure, it will wait for 1 minute, then on the second failure, it will wait for 2. The 11th time is special, as it activates a Hail-Mary protocol, which will wait for an additional 12 hours before continuing. This is to try and get around server instability, which can happen on sites like AO3.

If you have notifications enabled, it will send a notification of the failure for the penultimate failure, before the Hail-Mary - but it will not send a notification if the Hail-Mary fails, only if it succeeds.

## Calibre Setup

1. Setup the Calibre Content Server. Instructions can be found on the [calibre website](https://manual.calibre-ebook.com/server.html)
2. Make note of the IP address, Port and Library for the server. If needed, also make note of the Username and Password.

## Execution

### How to Install - Docker

1. Install the docker image with `docker pull mrtyton/automated-ffdl`
2. Map the `/config` volume to someplace on your drive.
3. After running the image once, it will have copied over default configs. Fill them out and everything should start working.
   1. This default config is currently broken, so when you map the `/config` volume just copy over the default ones found in this repo.

### How to Run - Non-Docker

1. Make sure that you have calibre, and more importantly [calibredb](https://manual.calibre-ebook.com/generated/en/calibredb.html) installed on the system that you're running the script on. `calibredb` should be installed standard when you install calibre.
2. Install [Python3](https://www.python.org/downloads/)
3. Clone the Repo
4. Run `python3 -m venv [ repoLocation ].venv`
5. Run `source [ repoLocation ].venv/bin/activate`
6. Run `python -m pip install -r requirements.txt`
7. Install [FanficFare](https://github.com/JimmXinu/FanFicFare/wiki#command-line-interface-cli-version) Currently run `pip install FanFicFare`
8. Fill out the config.toml file
9. Navigate to `root/app` and run `python fanficdownload.py`
10. To exit virtual enviorment, run `deactivate`

Heres an example of a run.sh script that will run the app, taking the install location as first argument:
´´´exec > "$1/aff.log" 2>&1
set -x
echo "Activating virtual environment..."
source "$1/.venv/bin/activate"

echo "Changing directory..."
cd "$1/root/app"

echo "Running Python script..."
"$1/.venv/bin/python" -u fanficdownload.py --verbose
´´´
Run: `./run.sh path/to/install/location`

## Configuration

The config file is a [TOML](https://toml.io/en/) file that contains the script's specific options. Changes to this file will only take effect upon script startup.


### Email

In order for the script to work, you have to fill out the email login information.

```toml
[email]
email = ""
password = ""
server = ""
mailbox = ""
sleep_time = 60
```


- `email`: The email address, username only.
- `password`: The password to the email address. It is recommened that you use an app password (Google's page on [App Password](https://support.google.com/accounts/answer/185833?hl=en)), rather than your email's actual password.
- `server`: Address for the email server. For Gmail, this is going to be `imap.gmail.com`. For other web services, you'll have to search for them.
- `mailbox`: Which mailbox to check, such as `INBOX`, for the unread update emails.
- `sleep_time`: How often to check the email account for new updates, in seconds. Default is 60 seconds, but you can make this as often as you want. Recommended that you don't go too fast though, since some email providers will not be happy.

### Calibre

The Calibre information for access and updating.

```toml
[calibre]
path=""
username=""
password=""
default_ini=""
personal_ini=""
```

- `path`: This is the path to your Calibre database. It's the location where your Calibre library is stored on your system. This can be either a directory that contains the `calibre.db` file, or the URL/Port/Library marked down above, such as `https://192.168.1.1:9001/#Fanfiction` This is the only argument that is **required** in this section.
- `username`: If your Calibre database is password protected, this is the username you use to access it.
- `password`: If your Calibre database is password protected, this is the password you use to access it.
- `default_ini`: This is the path to the [default INI configuration file](https://github.com/JimmXinu/FanFicFare/blob/main/fanficfare/defaults.ini) for FanFicFare.
- `personal_ini`: This is the path to your [personal INI configuration file](https://github.com/JimmXinu/FanFicFare/wiki/INI-File) for FanFicFare.

For both the default and personal INI, any changes made to them will take effect during the next update check, it does not require a restart of the script.

### Pushbullet

To enable Pushbullet notifications, configure the following in your `config.toml`:

```toml
[pushbullet]
enabled = true
api_key = "YOUR_PUSHBULLET_API_KEY"
device = "OPTIONAL_DEVICE_NICKNAME" # Optional: specify a device
```

These settings will be automatically used by the Apprise notification system to send notifications via Pushbullet. If `enabled` is `true` and an `api_key` is provided, Apprise will use this information.

**Apprise Integration**
The device that is stated here is what you should see in the pushbullet devices name. This is _not_ what Apprise expects, which is the device identifier. Since there is no easy way of getting this without coding, we try to automatically derive it. If it doesn't work (and you've confirmed with --verbose), then leaving this option blank will just send it to the entire device.

### Apprise

This script uses [Apprise](https://github.com/caronc/apprise) to handle all notifications. Apprise is a versatile library supporting a wide variety of services.

**Automatic Pushbullet Integration:**
The Pushbullet configuration in the `[pushbullet]` section (if enabled and an `api_key` is provided) is automatically used by Apprise. You do **not** need to add a separate `pbul://` URL for this primary Pushbullet account in the `[apprise].urls` list below. See above for more information about how it should be configured.

**Additional Notification Services:**
You can configure Apprise to send notifications to other services, or even additional Pushbullet accounts not covered by the main `[pushbullet]` section, by adding their Apprise URLs to the `urls` list in this section.

```toml
[apprise]
# List of additional Apprise URLs for other notification services.
# See https://github.com/caronc/apprise#supported-notifications for a full list.
# Your primary Pushbullet configuration (from the [pushbullet] section) is automatically included if enabled there.
#
# Examples for other services or additional Pushbullet accounts:
# urls = [
#   "discord://WEBHOOK_ID/WEBHOOK_TOKEN",   # For Discord
#   "mailto://USER:PASSWORD@HOST:PORT",     # For Email
#   "pbul://ANOTHER_PUSHBULLET_API_KEY",    # For a secondary Pushbullet account
# ]
urls = []
```

- `urls`: A list of Apprise service URLs for any *additional* notification targets. You can find a comprehensive list of supported services and their URL formats on the [Apprise GitHub page](https://github.com/caronc/apprise#supported-notifications).
