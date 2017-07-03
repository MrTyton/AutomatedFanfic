from StringIO import StringIO
import re
from subprocess import check_output, STDOUT

from sys import platform
from os import utime
from os.path import join

'''if platform == "linux" or platform == "linux2":
    from giNotify import Notification
elif platform == "win32":
    from ballonNotify import Notification'''
from notifications import Notification

from optparse import OptionParser
from ConfigParser import ConfigParser


def enable_notifications(options):
    if options.pushbullet:
        pb = Pushbullet(options.pushbullet)
        if options.pbdevice:
            try:
                pb = pb.get_device(options.pbdevice)
            except:
                print "Cannot get this device."
                pass
        temp_note = Notification()
        temp_note.send_notification = pb.push_note
        yield temp_note
        
    if options.notify:
        notary = Notification()
        yield notary
        
    
    
def touch(fname, times=None):
    with open(fname, 'a'):
        utime(fname, times)
    
    
def main(options):
    try:
        res = check_output("python fanficdownload.py -c config.ini", shell=True,stderr=STDOUT)
    except Exception as e:
        print e
        res = None
    if not res:
        return
    else:
        print res
    buf = StringIO(res)
    regex = re.compile("Added (?:.*/)?(.*)-.* to library with id \d*")
    searcher = regex.search
    stripper = False
    if options.pushbullet:
        from pushbullet import Pushbullet
    for line in buf.readlines():
        r = searcher(line)
        if r:
            story = r.group(1).strip()
            stripper = True
            for notify in enable_notifications(options):
                notify.send_notification("New Fanfiction Download", story)
    if stripper and options.tag:
        import sqlite3
        with sqlite3.connect(join(options.library_path, "metadata.db")) as conn:
            c = conn.cursor()
            c.execute("delete from books_tags_link where id in (select id from books_tags_link where tag in (select id from tags where name like '%Last Update%'));")
    return

if __name__ == "__main__":
    option_parser = OptionParser(usage="usage: %prog [flags]")
    option_parser.add_option('-p', '--pushbullet', action='store', dest='pushbullet', help='If you want to use pushbullet, pass in your key here.')
    option_parser.add_option('-d', '--device', action='store', dest='pbdevice', help='If you wish to only send to a certian pushbullet device, put the device name here. If the device name is invalid, will just send to all pushbullets associated with the acc')
    option_parser.add_option('-n', '--notify', action='store_true', dest='notify', help='Enable if you want to use system notifications. Only for Win/Linux.')
    option_parser.add_option('-c', '--config', action='store', dest='config', help='Config file for inputs. Blank config file is provided. No default. If an option is present in whatever config file is passed it, the option will overwrite whatever is passed in through command line arguments unless the option is blank. Do not put any quotation marks in the options.')
    option_parser.add_option('-t', '--tag', action='store_true', dest='tag', help='Strip Last Updated tags from calibredb. Requires library to be passed in.')
    option_parser.add_option('-l', '--library', action='store', dest='library', help='Path to calibre library. If you are connecting to a calibre webserver then this should be the url.')
    option_parser.add_option('-a', '--library-path', action='store', dest='library_path', help='Path location of library. Will be equal to library if nothing is passed in.')
    
    (options, args) = option_parser.parse_args()
    
    if options.library and not options.library_path: options.library_path = options.library
    
    if options.config:
        touch(options.config)
        config = ConfigParser(allow_no_value=True)
        config.read(options.config)
        updater = lambda option, newval : newval if newval != "" else option
        
        try: options.notify = updater(options.notify, config.getboolean('runner', 'notification'))
        except: pass
        
        try: options.pushbullet = updater(options.pushbullet, config.get('runner', 'pushbullet'))
        except: pass
        
        try: options.pbdevice = updater(options.pbdevice, config.get('runner', 'pbdevice'))
        except: pass

        try: options.tag = updater(options.tag, config.getboolean('runner', 'tag'))
        except: pass

        try: options.library = updater(options.library, config.get('locations', 'library'))
        except: pass
        
        try: options.library_path = updater(options.library, config.get('locations', 'library_path'))
        except: pass
    
    if options.pbdevice and not options.pushbullet:
        raise ValueError("Can't use a pushbullet device without key")
    if options.tag and not options.library:
	raise ValueError("Can't strip tags from calibre library without a library location.")
        
    main(options)
