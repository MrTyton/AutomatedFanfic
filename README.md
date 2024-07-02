# AutomatedFanfic
Automated Fanfiction Download using FanficFare CLI

This is a docker image to run the Automated FFF CLI, with pushbullet integration.

[FanFicFare](https://github.com/JimmXinu/FanFicFare)

[Dockerhub Link](https://hub.docker.com/r/mrtyton/automated-ffdl)

- [AutomatedFanfic](#automatedfanfic)
  - [Site Support](#site-support)
  - [Calibre Setup](#calibre-setup)
  - [Execution](#execution)
    - [How to Install - Docker](#how-to-install---docker)
    - [How to Run - Non-Docker](#how-to-run---non-docker)
  - [Configuration](#configuration)
    - [Email](#email)
    - [Calibre](#calibre)
    - [Pushbullet](#pushbullet)

## Site Support

This program will support any website that FanFicFare will support. However, it does make use of multi-processing, spawning a different "watcher" for each website. This list is currently hard-coded, and anything not in the list is treated as part of a single queue "other".

If you wish to add more watchers for different websites, then open an issue or submit a request to modify [this](https://github.com/MrTyton/AutomatedFanfic/blob/master/root/app/regex_parsing.py#L7) dictionary.

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
4. Run `python -m pip install -r requirements.txt`
5. Install [FanficFare](https://github.com/JimmXinu/FanFicFare/wiki#command-line-interface-cli-version)
6. Fill out the config.toml file
7. Navigate to `root/app` and run `python fanficdownload.py`

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

This script has an _optional_ [Pushbullet](https://pushbullet.com) integration, in case you want to get phone notifications when an update has occurred. The system will also send a notification if it fails to update a story, for whatever reason.

```toml
[pushbullet]
enabled = false
api_key = ""
device = ""
```

- `enabled`: Whether or not to enable the pushbullet notifications
- `api_key`: Your [Pushbullet API Key](https://docs.pushbullet.com/#authentication)
- `device`: If you want to send the notification to a specific device rather than the entirety of the pushbullet subscriptions, you can specify which device here with the device name.