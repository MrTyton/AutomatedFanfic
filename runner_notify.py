from StringIO import StringIO
import re
from subprocess import check_output, STDOUT

from sys import platform
from os import utime

if platform == "linux" or platform == "linux2":
    from giNotify import Notification
elif platform == "win32":
    from ballonNotify import Notification

from optparse import OptionParser
from ConfigParser import ConfigParser

def enable_notifications(options):
    notary_options = []
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
        
        notary_options.append(temp_note)
        
    if options.notify:
        notary = Notification()
        notary_options.append(notary)
        
    return notary_options
    
def touch(fname, times=None):
    with open(fname, 'a'):
        utime(fname, times)
    
    
def main(options):

    res = check_output("python fanficdownload.py -c config.ini", shell=True,stderr=STDOUT)
    buf = StringIO(res)
    regex = re.compile("Added (?:.*/)?(.*)-.* to library with id \d*")
    for line in buf.readlines():
        r = regex.search(line)
        if r:
            story = r.group(1).strip()
            for notify in enable_notifications(options):
                notify.send_notification("New Fanfiction Download", story)
    if res != "": print res
    return

if __name__ == "__main__":
    option_parser = OptionParser(usage="usage: %prog [flags]")
    option_parser.add_option('-p', '--pushbullet', action='store', dest='pushbullet', help='If you want to use pushbullet, pass in your key here.')
    option_parser.add_option('-d', '--device', action='store', dest='pbdevice', help='If you wish to only send to a certian pushbullet device, put the device name here. If the device name is invalid, will just send to all pushbullets associated with the acc')
    option_parser.add_option('-n', '--notify', action='store_true', dest='notify', help='Enable if you want to use system notifications. Only for Win/Linux.')
    option_parser.add_option('-c', '--config', action='store', dest='config', help='Config file for inputs. Blank config file is provided. No default. If an option is present in whatever config file is passed it, the option will overwrite whatever is passed in through command line arguments unless the option is blank. Do not put any quotation marks in the options.')
    
    (options, args) = option_parser.parse_args()
    
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
    
    if options.pbdevice and not options.pushbullet:
        raise ValueError("Can't use a pushbullet device without key")
    if options.pushbullet:
        from pushbullet import Pushbullet
        
    main(options)
