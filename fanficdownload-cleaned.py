from fanficfare import geturls
import os
from os import listdir, remove, rename, utime
from os.path import isfile, join
from subprocess import check_output, STDOUT
import logging
from optparse import OptionParser
import re
from ConfigParser import ConfigParser

logging.getLogger("fanficfare").setLevel(logging.ERROR)

def touch(fname, times=None):
    with open(fname, 'a'):
        utime(fname, times)


ffnet = re.compile('(fanfiction.net/s/\d*)/?.*')
neutral = re.compile('https?://(.*)')

def parse_url(url):
    if ffnet.search(url):
        url = "www." + ffnet.search(url).group(1)
    elif neutral.search(url):
        url = neutral.search(url).group(1)
    return url

def main(user, password, server, label, inout_file, path="", ):

    if path != "":
        path = '--with-library "{}"'.format(path)
        
    touch(inout_file)

    with open(inout_file, "r") as fp:
        urls = set([x.replace("\n", "") for x in fp.readlines()])
        
    with open(inout_file, "w") as fp:
        fp.write("")
        urls |= geturls.get_urls_from_imap(server, user, password, label)
                
        urls = set(parse_url(x) for x in urls)
        
        if len(urls) != 0: print "URLs to parse: {}".format(", ".join(urls))

        files = lambda x: [f for f in listdir(x) if isfile(join(x, f))]


        for url in urls:
            print "Working with url {}".format(url)
            try:
                res = check_output('calibredb search "Identifiers:{}" {}'.format(url, path), shell=True,stderr=STDOUT) 
                storyId = res
                print "\tStory is in calibre with id {}".format(storyId)
                try:
                    print "\tExporting file"
                    res = check_output('calibredb export {} --dont-save-cover --dont-write-opf --single-dir {}'.format(storyId, path), shell=True)
                    onlyfiles = files(".")
                    for cur in onlyfiles:
                        if not cur.endswith(".epub"): continue
                        print '\tDownloading with fanficfare, updating file "{}"'.format(cur)
                        res = check_output('fanficfare -u "{}" --update-cover'.format(cur), shell=True,stderr=STDOUT)
                        #print res
                        if "already contains" in res:
                            print "\tIssue with story, FF.net site is broken."
                            fp.write("{}\n".format(url))
                            remove(cur)
                            continue
                        elif "Story does not exist" in res:
                            print "\tInvalid URL"
                            continue
                        elif "more recently than Story" in res:
                            print "\tForcing download update\n"
                            res = check_output('fanficfare -u "{}" --force --update-cover'.format(cur), shell=True,stderr=STDOUT)
                    
                        print "\tRemoving {} from library".format(storyId)
                        res = check_output('calibredb remove {} {}'.format(storyId, path), shell=True,stderr=STDOUT)
                        #print res
                        print "\tAdding {} to library".format(cur)
                        res = check_output('calibredb add "{}" {}'.format(cur, path), shell=True,stderr=STDOUT)
                        res = check_output('calibredb search "Identifiers:{}" {}'.format(url, path), shell=True, stderr=STDOUT)
                        print "\tAdded {} to library with id {}".format(cur, res)
                        #print res
                        remove(cur)
                except Exception as e:
                    print "\tSomething fucked up: {}".format(e)
                    remove(cur)
                    fp.write("{}\n".format(url))
            except:
                print "\tStory is not in calibre"
                try:
                    res = check_output('fanficfare -u "{}" --update-cover'.format(url), shell=True)
                    #print res
                    onlyfiles = files(".")
                    for cur in onlyfiles:
                        if not cur.endswith(".epub"): continue
                        try:
                            print "\tAdding {} to library".format(cur)
                            res = check_output('calibredb add "{}" {}'.format(cur, path), shell=True, stderr=STDOUT)
                            #print res
                            remove(cur)
                        except Exception:
                            remove(cur)
                            raise
                except Exception as e:
                    print "\tSomething fucked up: {}".format(e)
                    fp.write("{}\n".format(url))


if __name__ == "__main__":
    option_parser = OptionParser(usage="usage: %prog [flags]")
    
    option_parser.add_option('-u', '--user', action='store', dest='user', help='Email Account Username. Required.')
    
    option_parser.add_option('-p', '--password', action='store', dest='password', help='Email Account Password. Required.')
    
    option_parser.add_option('-s', '--server', action='store', dest='server', default="imap.gmail.com", help='Email IMAP Server. Default is "imap.gmail.com".')
    
    option_parser.add_option('-m', '--mailbox', action='store', dest='mailbox', default='INBOX', help='Email Label. Default is "INBOX".')
    
    option_parser.add_option('-l', '--library', action='store', dest='library', default="", help="calibre library db location. If none is passed, the default is the calibre system library location. Make sure to enclose the path in quotes.")
    
    option_parser.add_option('-i', '--input', action='store', dest='input', default="./fanfiction.txt", help="Error file. Any urls that fail will be output here, and file will be read to find any urls that failed previously. If file does not exist will create. File is overwitten every time the program is run.")
    
    option_parser.add_option('-c', '--config', action='store', dest='config', help='Config file for inputs. Example config file is provided. No default. If an option is present in whatever config file is passed it, the option will overwrite whatever is passed in through command line arguments unless the option is blank.')
    
    (options, args) = option_parser.parse_args()
    
    if options.config:
        config = ConfigParser(allow_no_value=True)
        config.read(options.config)
        
        updater = lambda option, newval : newval if newval != "" else option
        
        options.user = updater(options.user, config.get('login', 'user').strip())
        
        options.password = updater(options.password, config.get('login', 'password').strip())
        
        options.server = updater(options.server, config.get('login', 'server').strip())
        
        options.mailbox = updater(options.mailbox, config.get('login', 'mailbox').strip())
        
        options.library = updater(options.library, config.get('locations', 'library').strip())
        
        options.input = updater(options.input, config.get('locations', 'input').strip())
        
    if not (options.user or options.password):
        raise ValueError("User or Password not given")
    
    main(options.user, options.password, options.server, options.mailbox, options.input, options.library)
            
            
    

        
