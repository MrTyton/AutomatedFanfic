# AutomatedFanfic

Python script to automate the use of FanFicFare CLI (https://github.com/JimmXinu/FanFicFare) with calibre.

Primary script is fanficdownload.py. Use -h or --help to see the options.

There is additional support for notifications, including pushbullet integration, through runner_notify. Use -h to see options.

Works with Fanficfare 2.3.6+. Rewrite underway to take advantage of new features in Fanficfare 2.4.0

For basic cron usage, this is not needed, `fanficfare -dowload-imap -u` should work if you're not integrating into calibre. This script is best used if you want to update the calibre library, for the usage of calibre-server for instance.
