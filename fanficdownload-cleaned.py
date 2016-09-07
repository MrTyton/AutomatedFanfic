from fanficfare import geturls
import os
from os import listdir, remove, rename
from os.path import isfile, join
import subprocess
import time
import logging
from optparse import OptionParser

logging.getLogger("fanficfare").setLevel(logging.ERROR)


def main(user, password, server="imap.gmail.com", label="INBOX", path=""):

    if path != "":
        path = '--with-library "{}"'.format(path)

    with open("thesebroke", "rb") as fp:
        urls = set([x.replace("\n", "") for x in fp.readlines()])
    with open("todo", "wb") as fp:
        fp.write("")
    urls |= geturls.get_urls_from_imap(server, user, password, label)
    
    def parse_url(url):
        url = url.replace("https://", "")
        url = url.replace("http://", "")
        url = url[:url.find("/", url.find("/s/") + 3)+1]
        return url
    
    
    urls = set(parse_url(x) for x in urls)
    
    if len(urls) != 0: print "URLs to parse: {}".format(", ".join(urls))

    files = lambda x: [f for f in listdir(x) if isfile(join(x, f))]

#    if len(urls) != 0:
#        print time.strftime("%d/%m/%Y, %H:%M:%S\n\n")


    for url in urls:
        print "Working with url {}".format(url)
        try:
            res = subprocess.check_output('calibredb search "Identifiers:{}" {}'.format(url, path), shell=True,stderr=subprocess.STDOUT) 
            id = res
            print "\tStory is in calibre with id {}".format(id)
            try:
                print "\tExporting file"
                res = subprocess.check_output('calibredb export {} --dont-save-cover --dont-write-opf --single-dir {}'.format(id, path), shell=True)
                onlyfiles = files(".")
                for cur in onlyfiles:
                    if not cur.endswith(".epub"): continue
                    print '\tDownloading with fanficfare, updating file "{}"'.format(cur)
                    res = subprocess.check_output('fanficfare -u "{}" --update-cover'.format(cur), shell=True,stderr=subprocess.STDOUT)
                    #print res
                    if "already contains" in res:
                        print "\tIssue with story, FF.net site is broken."
                        with open("todo", "ab") as fp:
                            fp.write("{}\n".format(url))
                        remove(cur)
                        continue
                    elif "Story does not exist" in res:
                        print "\tInvalid URL"
                        continue
                    elif "more recently than Story" in res:
                        print "\tForcing download update\n"
                        res = subprocess.check_output('fanficfare -u "{}" --force --update-cover'.format(cur), shell=True,stderr=subprocess.STDOUT)
                
                    print "\tRemoving {} from library".format(id)
                    res = subprocess.check_output('calibredb remove {} {}'.format(id, path), shell=True,stderr=subprocess.STDOUT)
                    #print res
                    print "\tAdding {} to library".format(cur)
                    res = subprocess.check_output('calibredb add "{}" {}'.format(cur, path), shell=True,stderr=subprocess.STDOUT)
                    res = subprocess.check_output('calibredb search "Identifiers:{}" {}'.format(url, path), shell=True, stderr=subprocess.STDOUT)
                    print "\tAdded {} to library with id {}".format(cur, res)
                    #print res
                    remove(cur)
            except Exception as e:
                print "\tSomething fucked up: {}".format(e)
                remove(cur)
                with open("todo", "ab") as fp:
                    fp.write("{}\n".format(url))
        except:
            print "\tStory is not in calibre"
            try:
                res = subprocess.check_output('fanficfare -u "{}" --update-cover'.format(url), shell=True)
                #print res
                onlyfiles = files(".")
                for cur in onlyfiles:
                    if not cur.endswith(".epub"): continue
                    try:
                        print "\tAdding {} to library".format(cur)
                        res = subprocess.check_output('calibredb add "{}" {}'.format(cur, path), shell=True, stderr=subprocess.STDOUT)
                        #print res
                        remove(cur)
                    except Exception:
                        remove(cur)
                        raise
            except Exception as e:
                print "\tSomething fucked up: {}".format(e)
                with open("todo", "ab") as fp:
                    fp.write("{}\n".format(url))

    remove("thesebroke")
    rename("todo", "thesebroke")

if __name__ == "__main__":
    option_parser = OptionParser(usage="usage: %prog [flags]")
    
    option_parser.add_option('-u', '--user', action='store', dest='user', help='Email Account Username. Required.')
    
    option_parser.add_option('-p', '--password', action='store', dest='password', help='Email Account Password. Required.')
    
    option_parser.add_option('-s', '--server', action='store', dest='server', default="imap.gmail.com", help='Email IMAP Server. Default is "imap.gmail.com".')
    
    option_parser.add_option('-m', '--mailbox', action='store', dest='label', default='INBOX', help='Email Label. Default is "INBOX".')
    
    option_parser.add_option('-l', '--library', action='store', dest='library', default="", help="calibre library db location. If none is passed, the default is the calibre system library location. Make sure to enclose the path in quotes.")
    
    (options, args) = option_parser.parse_args()
    if options.user is None or options.password is None:
        raise ValueError("User or Password not given")
    
    main(options.user, options.password, options.server, options.label, options.library)
            
            
    

        
