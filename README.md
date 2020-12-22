# AutomatedFanfic

Python script to automate the use of FanFicFare CLI (https://github.com/JimmXinu/FanFicFare) with calibre.

Primary script is fanficdownload.py. Use -h or --help to see the options.

All of the options can be loaded into the config file, of which the template is provided in `config_template.ini`, and utilized with `python3 fanficdownload.py -c path_to_config.ini`.

There is additional support for notifications, including pushbullet integration, through runner_notify. Use -h to see options.

Works with Fanficfare 2.3.6+. Rewrite underway to take advantage of new features in Fanficfare 2.4.0

Requires Python 3.6.9. Unsure if it will work on higher versions of Python.

For basic cron usage, this is not needed, `fanficfare -dowload-imap -u` should work if you're not integrating into calibre. This script is best used if you want to update the calibre library, for the usage of calibre-server for instance.

If anything does not work, please open a ticket.