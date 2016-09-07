# AutomatedFanfic

Python script to automate the use of FanFicFare CLI (https://github.com/JimmXinu/FanFicFare) with calibre.

Use -h or --help to see the options.

Usage: fanficdownload-cleaned.py [flags]

Options:
  -h, --help            show this help message and exit
  -u USER, --user=USER  Email Account Username. Required.
  -p PASSWORD, --password=PASSWORD
                        Email Account Password. Required.
  -s SERVER, --server=SERVER
                        Email IMAP Server. Default is "imap.gmail.com".
  -m MAILBOX, --mailbox=MAILBOX
                        Email Label. Default is "INBOX".
  -l LIBRARY, --library=LIBRARY
                        calibre library db location. If none is passed, then
                        this merely scrapes the email and error file for new
                        stories and downloads them into the current directory.
  -i INPUT, --input=INPUT
                        Error file. Any urls that fail will be output here,
                        and file will be read to find any urls that failed
                        previously. If file does not exist will create. File
                        is overwitten every time the program is run.
  -c CONFIG, --config=CONFIG
                        Config file for inputs. Blank config file is provided.
                        No default. If an option is present in whatever config
                        file is passed it, the option will overwrite whatever
                        is passed in through command line arguments unless the
                        option is blank. Do not put any quotation marks in the
                        options.
                        
