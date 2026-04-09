# AutomatedFanfic
Automated Fanfiction Download using FanficFare CLI

This is a docker image to run the Automated FFF CLI, with Apprise integration.

[FanFicFare](https://github.com/JimmXinu/FanFicFare)

[Dockerhub Link](https://hub.docker.com/r/mrtyton/automated-ffdl)

- [AutomatedFanfic](#automatedfanfic)
  - [Platform Support](#platform-support)
  - [Site Support](#site-support)
  - [Repeats](#repeats)
  - [Calibre Setup](#calibre-setup)
  - [Execution](#execution)
    - [How to Install - Docker](#how-to-install---docker)
    - [How to Run - Non-Docker](#how-to-run---non-docker)
  - [Configuration](#configuration)
    - [Email](#email)
    - [Calibre](#calibre)
    - [Retry and Hail-Mary Protocol](#retry-and-hail-mary-protocol)
    - [Pushbullet](#pushbullet)
    - [Apprise](#apprise)
    - [Web Dashboard](#web-dashboard)

## Platform Support

This Docker image supports multi-platform deployment:

- **linux/amd64** (x86_64): Uses official Calibre binaries for optimal performance
- **linux/arm64** (ARM64): Uses system package manager Calibre installation

The image automatically detects the target architecture during build and configures Calibre appropriately. Both platforms provide full functionality, though x86_64 may have slightly newer Calibre versions due to using official releases.

## Site Support

This program will support any website that FanFicFare will support. However, it does make use of multi-processing, spawning a different "watcher" for each website. This list is automatically generated, based on the adaptors that FanFicFare has.

## Repeats

The script will try to download every story maximum of 11 times, waiting an additional minute for each time - so on the first failure, it will wait for 1 minute, then on the second failure, it will wait for 2. The 11th time is special, as it activates a Hail-Mary protocol, which will wait for an additional 12 hours before continuing. This is to try and get around server instability, which can happen on sites like AO3.

If you have notifications enabled, it will send a notification of the failure for the penultimate failure, before the Hail-Mary - but it will not send a notification if the Hail-Mary fails, only if it succeeds.

**Special Case - Force Requests with `update_no_force`:**
If the `update_method` is set to `"update_no_force"` and a force update is requested (either through email commands or manual triggers), the force request will be ignored and the story will be processed as a normal update. If the final Hail-Mary attempt fails under these conditions, a special notification will be sent explaining that the force request was ignored due to the `update_no_force` setting.

## Calibre Setup

1. Setup the Calibre Content Server. Instructions can be found on the [calibre website](https://manual.calibre-ebook.com/server.html)
2. Make note of the IP address, Port and Library for the server. If needed, also make note of the Username and Password.

## Execution

### How to Install - Docker

1. Install the docker image with `docker pull mrtyton/automated-ffdl`
   - The image supports both x86_64 and ARM64 architectures
   - Docker will automatically pull the correct version for your platform
2. Map the `/config` volume to someplace on your drive.
3. Map the `/data` volume for persistent history database storage (required if using the web dashboard).
4. If you want to use the web dashboard, map port `8080` (or your configured port) and set `enabled = true` in the `[web]` section of `config.toml`.
5. After running the image once, it will have copied over default configs. Fill them out and everything should start working.
   1. This default config is currently broken, so when you map the `/config` volume just copy over the default ones found in this repo.

**Docker Run Example:**
```bash
docker run -d \
  --name automated-ffdl \
  -v /path/to/config:/config \
  -v /path/to/data:/data \
  -p 8080:8080 \
  mrtyton/automated-ffdl
```

**Docker Compose Example:**
```yaml
services:
  automated-ffdl:
    image: mrtyton/automated-ffdl
    container_name: automated-ffdl
    volumes:
      - /path/to/config:/config
      - /path/to/data:/data
    ports:
      - "8080:8080"
    restart: unless-stopped
```

**Volumes:**
| Volume | Purpose |
|---|---|
| `/config` | Configuration files (`config.toml`, `defaults.ini`, `personal.ini`) |
| `/data` | Persistent data (history database for the web dashboard) |

**Ports:**
| Port | Purpose |
|---|---|
| `8080` | Web dashboard (only needed if `[web] enabled = true`) |

### How to Run - Non-Docker

1. Make sure that you have calibre, and more importantly [calibredb](https://manual.calibre-ebook.com/generated/en/calibredb.html) installed on the system that you're running the script on. `calibredb` should be installed standard when you install calibre.
2. Install [Python3](https://www.python.org/downloads/)
3. Clone the Repo
4. For production use: `python -m pip install -r requirements.txt`
   For development (includes testing tools): `python -m pip install -r requirements-dev.txt`
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
disabled_sites = []
```


- `email`: The email authentication field. Different email providers have different requirements:
  - **Username only** (e.g., `username`): Required by some providers like Gmail
  - **Full email address** (e.g., `username@domain.com`): Required by some providers like mailbox.org
  - Use whichever format your email provider requires for IMAP authentication
- `password`: The password to the email address. It is recommened that you use an app password (Google's page on [App Password](https://support.google.com/accounts/answer/185833?hl=en)), rather than your email's actual password.
- `server`: Address for the email server. For Gmail, this is going to be `imap.gmail.com`. For other web services, you'll have to search for them.
- `mailbox`: Which mailbox to check, such as `INBOX`, for the unread update emails.
- `sleep_time`: How often to check the email account for new updates, in seconds. Default is 60 seconds, but you can make this as often as you want. Recommended that you don't go too fast though, since some email providers will not be happy.
- `disabled_sites`: A list of site identifiers for which URLs should only trigger notifications without being processed by FanFicFare. Defaults to an empty list `[]` (all sites enabled). When a site is disabled, URLs from that site found in emails will only send a notification and will not be downloaded or processed further.

**Site Identifier Parsing:**
Site identifiers are automatically generated from FanFicFare's supported adapters and use a standardized format. The system extracts the base domain from a fanfiction site URL and converts it to an identifier by:

1. **Domain Extraction**: Takes the main domain from the site (e.g., `www.fanfiction.net` → `fanfiction.net`)
2. **Subdomain Removal**: Removes common subdomains like `www.`, `m.`, `forums.`
3. **Identifier Generation**: Converts the remaining domain to a simple identifier (e.g., `fanfiction.net` → `fanfiction`)

**Common Site Identifiers:**
- `fanfiction` (FanFiction.Net)
- `archiveofourown` (Archive of Our Own)
- `spacebattles` (SpaceBattles Forums)
- `sufficientvelocity` (Sufficient Velocity Forums)
- `questionablequesting` (Questionable Questing Forums)
- `royalroad` (Royal Road)
- `fictionpress` (FictionPress)
- `webnovel` (WebNovel)
- `scribblehub` (ScribbleHub)

**Examples:**
```toml
# Disable FanFiction.Net only (due to access issues)
disabled_sites = ["fanfiction"]

# Disable multiple forum sites
disabled_sites = ["spacebattles", "sufficientvelocity", "questionablequesting"]

# Enable all sites (default)
disabled_sites = []
```

**Backward Compatibility:**
The old `ffnet_disable = true` configuration is automatically converted to `disabled_sites = ["fanfiction"]` when the application starts, so existing configurations will continue to work without changes.

### Calibre

The Calibre information for access and updating.

```toml
[calibre]
path=""
username=""
password=""
default_ini=""
personal_ini=""
update_method="update"
metadata_preservation_mode="remove_add"
```

- `path`: This is the path to your Calibre database. It's the location where your Calibre library is stored on your system. This can be either a directory that contains the `calibre.db` file, or the URL/Port/Library marked down above, such as `https://192.168.1.1:9001/#Fanfiction` This is the only argument that is **required** in this section.
- `username`: If your Calibre database is password protected, this is the username you use to access it.
- `password`: If your Calibre database is password protected, this is the password you use to access it.
- `default_ini`: This is the path to the [default INI configuration file](https://github.com/JimmXinu/FanFicFare/blob/main/fanficfare/defaults.ini) for FanFicFare.
- `personal_ini`: This is the path to your [personal INI configuration file](https://github.com/JimmXinu/FanFicFare/wiki/INI-File) for FanFicFare.
- `update_method`: Controls how FanFicFare handles story updates. Valid options are described below.
- `metadata_preservation_mode`: Controls how Calibre metadata is preserved during story updates. Valid options are described below.

**Update Method Use Cases:**
- Use `"update"` for normal operation with good performance and minimal server load
- Use `"update_always"` if you want to ensure all stories are always refreshed regardless of apparent changes
- Use `"force"` if you frequently encounter stories that need forced updates to work properly
- Use `"update_no_force"` if you want to prevent any forced updates (useful for being gentler on target websites or avoiding potential issues with forced downloads)

**Metadata Preservation Modes:**

This setting controls how custom metadata (tags, reading progress, custom columns, etc.) is handled when updating existing stories in your Calibre library:

- `"remove_add"` (default): Traditional behavior - removes the old entry and adds the updated story as new. **WARNING**: This will lose ALL custom metadata you've added manually in Calibre (custom columns, tags you added, reading progress, etc.). Only metadata embedded in the EPUB file by FanFicFare is preserved.

- `"preserve_metadata"`: Exports all custom columns before updating, then restores them after adding the updated story. This preserves your custom fields but requires two database operations (remove/add). **Recommended if you use custom columns or manually add metadata.**

- `"add_format"`: Replaces only the EPUB file without touching the database entry. This preserves **ALL** metadata perfectly because it updates the file in-place. This is the fastest and safest option for metadata preservation.

**Which mode should you use?**
- If you **don't** manually add tags, ratings, or use custom columns → Use `"remove_add"` (faster, simpler)
- If you **do** add custom metadata and want maximum safety → Use `"add_format"` (preserves everything)
- If `"add_format"` has issues with your setup → Use `"preserve_metadata"` (fallback option)

**Note:** The `metadata_preservation_mode` only affects **updates to existing stories**. New stories being added for the first time are unaffected by this setting.

**Dynamic Force Behavior:**
The system can automatically trigger force updates in certain circumstances, regardless of your configured `update_method`:

1. **Automatic Force Detection**: When FanFicFare encounters specific error conditions that indicate a force update would resolve the issue, the system automatically sets the story's behavior to "force" and re-queues it for processing. This happens when:
   - There's a chapter count mismatch between the source and your local copy
   - Your local file has been updated more recently than the story (indicating a metadata bug)

2. **Force Request Precedence**: The precedence order for determining whether to use force is:
   - If `update_method` is `"update_no_force"`: Force requests are **always ignored**, even automatic ones
   - If a force is requested (either automatically detected or manually triggered): Uses `--force` flag
   - If `update_method` is `"force"`: Uses `--force` flag
   - If `update_method` is `"update_always"`: Uses `-U` flag
   - Default: Uses `-u` flag for normal updates

3. **Special Cases**:
   - When `update_method` is `"update_no_force"` and a force is requested, the force is ignored and a normal update (`-u`) is performed instead
   - If the final Hail-Mary attempt fails under these conditions, a special notification explains that the force request was ignored

For both the default and personal INI, any changes made to them will take effect during the next update check, it does not require a restart of the script.

### Retry and Hail-Mary Protocol

Configure the retry behavior and Hail-Mary protocol settings:

```toml
[retry]
hail_mary_enabled = true
hail_mary_wait_hours = 12.0
max_normal_retries = 11
```

- `hail_mary_enabled`: Whether to enable the Hail-Mary protocol (defaults to `true` for backward compatibility). When `false`, stories that reach maximum retry attempts will be permanently failed without the final extended wait attempt.
- `hail_mary_wait_hours`: Hours to wait before attempting the final Hail-Mary retry (defaults to `12.0`). Can be set to any value between 0.1 and 168 hours (1 week). This allows customization for different use cases - you might want 24 or 36 hours for sites with longer outages.
- `max_normal_retries`: Maximum number of normal retry attempts before activating Hail-Mary protocol (defaults to `11`). Normal retries use exponential backoff (1min, 2min, 3min, etc.). Can be set between 1 and 50 attempts.

**Backward Compatibility:** If this section is omitted from your configuration, the application will use the original behavior: 11 normal retries followed by a 12-hour Hail-Mary attempt.

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

### Web Dashboard

AutomatedFanfic includes an optional built-in web dashboard for monitoring downloads, retries, and activity in real time. It is **disabled by default** and must be explicitly enabled.

```toml
[web]
enabled = false
host = "0.0.0.0"
port = 8080
history_db_path = "/data/history.db"
```

- `enabled`: Set to `true` to start the web dashboard server. Defaults to `false`.
- `host`: The address the web server binds to. Use `"0.0.0.0"` to listen on all interfaces (required for Docker), or `"127.0.0.1"` for local-only access.
- `port`: The port the web server listens on (1–65535). Defaults to `8080`.
- `history_db_path`: Path to the SQLite database file used for storing download history, retry events, email checks, and notifications. Defaults to `"/data/history.db"` (the `/data` Docker volume).

**Dashboard Features:**
- **Live Dashboard**: Real-time view of active downloads, waiting retries, queue depths, and process status
- **Activity Feed**: Recent downloads, retries, and notifications in a unified timeline
- **Add URLs**: Manually inject fanfiction URLs into the processing queue
- **History**: Searchable, paginated history of all downloads, retries, email checks, and notifications
- **Expandable Errors**: Click truncated error messages to see full details

**Docker Setup:**

To use the web dashboard in Docker, you need to:
1. Set `enabled = true` in the `[web]` section of your `config.toml`
2. Map the `/data` volume for persistent history storage
3. Map the dashboard port

```bash
docker run -d \
  -v /path/to/config:/config \
  -v /path/to/data:/data \
  -p 8080:8080 \
  mrtyton/automated-ffdl
```

If you change the `port` in `config.toml`, update the Docker port mapping accordingly (e.g., `-p 9999:9999` for `port = 9999`).

**Non-Docker Setup:**

For non-Docker usage, set `host = "127.0.0.1"` to restrict access to localhost, and set `history_db_path` to a writable path on your filesystem (e.g., `"./data/history.db"`).

**Homepage (gethomepage.dev) Widget:**

The web dashboard exposes a widget-friendly endpoint at `/api/widget` for use with [Homepage](https://gethomepage.dev/)'s [Custom API widget](https://gethomepage.dev/widgets/services/customapi/). Use two widget entries under the same service group for a Sonarr-style layout with stat counters and an active downloads list:

```yaml
- AutomatedFanfic:
    icon: mdi-book-open-variant
    href: http://your-host:8080
    widget:
      type: customapi
      url: http://your-host:8080/api/widget
      mappings:
        - field: active_downloads
          label: Active
          format: number
        - field: queued
          label: Queued
          format: number
        - field: waiting_retry
          label: Retrying
          format: number
        - field: total_completed
          label: Completed
          format: number
- AutomatedFanfic Queue:
    widget:
      type: customapi
      url: http://your-host:8080/api/widget
      display: dynamic-list
      mappings:
        items: active
        name: title
        label: site
        limit: 5
```

Replace `your-host:8080` with the address and port of your AutomatedFanfic instance.
