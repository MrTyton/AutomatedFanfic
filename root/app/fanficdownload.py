from fanficfare import geturls
from os import listdir, remove, rename, utime, devnull
from os.path import isfile, join
from subprocess import check_output, STDOUT, call, PIPE
import logging
from optparse import OptionParser
import re
from configparser import ConfigParser
from tempfile import mkdtemp
from shutil import rmtree, copyfile
import socket
from time import strftime, localtime
import os
import errno

from multiprocessing import Pool

logging.getLogger("fanficfare").setLevel(logging.ERROR)


class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def log(msg, color=None, output=True):
    if color:
        col = bcolors.HEADER
        if color == 'BLUE':
            col = bcolors.OKBLUE
        elif color == 'GREEN':
            col = bcolors.OKGREEN
        elif color == 'WARNING':
            col = bcolors.WARNING
        elif color == 'FAIL':
            col = bcolors.FAIL
        elif color == 'BOLD':
            col = bcolors.BOLD
        elif color == 'UNDERLINE':
            col = bcolors.UNDERLINE
        line = '{}{}{}: \t {}{}{}'.format(
            bcolors.BOLD,
            strftime(
                '%m/%d/%Y %H:%M:%S',
                localtime()),
            bcolors.ENDC,
            col,
            msg,
            bcolors.ENDC)
    else:
        line = '{}{}{}: \t {}'.format(
            bcolors.BOLD,
            strftime(
                '%m/%d/%Y %H:%M:%S',
                localtime()),
            bcolors.ENDC,
            msg)
    if output:
        print(line)
        return ""
    else:
        return line + "\n"


def touch(fname, times=None):
    with open(fname, 'a'):
        utime(fname, times)


url_parsers = [(re.compile('(fanfiction.net/s/\d*/?).*'), "www."), #ffnet
               (re.compile('(archiveofourown.org/works/\d*)/?.*'), ""), #ao3
               (re.compile('(fictionpress.com/s/\d*)/?.*'), ""), #fictionpress
			   (re.compile('(royalroad.com/fiction/\d*)/?.*'), ""), #royalroad
               (re.compile('https?://(.*)'), "")] #other sites
story_name = re.compile('(.*)-.*')

equal_chapters = re.compile('.* already contains \d* chapters.')
chapter_difference = re.compile(
    '.* contains \d* chapters, more than source: \d*.')
bad_chapters = re.compile(
    ".* doesn't contain any recognizable chapters, probably from a different source.  Not updating.")
no_url = re.compile('No story URL found in epub to update.')
more_chapters = re.compile(
    ".*File\(.*\.epub\) Updated\(.*\) more recently than Story\(.*\) - Skipping")


def parse_url(url):
    for cur_parser, cur_prefix in url_parsers:
        if cur_parser.search(url):
            url = cur_prefix + cur_parser.search(url).group(1)
            return url
    return url


def get_files(mypath, filetype=None, fullpath=False):
    ans = []
    if filetype:
        ans = [f for f in listdir(mypath) if isfile(
            join(mypath, f)) and f.endswith(filetype)]
    else:
        ans = [f for f in listdir(mypath) if isfile(join(mypath, f))]
    if fullpath:
        return [join(mypath, f) for f in ans]
    else:
        return ans


def check_regexes(output):
    if equal_chapters.search(output):
        raise ValueError(
            "Issue with story, site is broken. Story likely hasn't updated on site yet.")
    if bad_chapters.search(output):
        raise ValueError(
            "Something is messed up with the site or the epub. No chapters found.")
    if no_url.search(output):
        raise ValueError("No URL in epub to update from. Fix the metadata.")


def downloader(args):
    url, inout_file, path, live = args
    loc = mkdtemp()
    output = ""
    output += log("Working with url {}".format(url), 'HEADER', live)
    storyId = None
    try:
        if path:
            try:
                storyId = check_output(
                    'calibredb search "Identifiers:{}" {}'.format(
                        url, path), shell=True, stderr=STDOUT, stdin=PIPE, ).decode('utf-8')
                output += log("\tStory is in calibre with id {}".format(storyId), 'BLUE', live)
                output += log("\tExporting file", 'BLUE', live)
                res = check_output(
                    'calibredb export {} --dont-save-cover --dont-write-opf --single-dir --to-dir "{}" {}'.format(
                        storyId, loc, path), shell=True, stdin=PIPE, stderr=STDOUT).decode('utf-8')
                cur = get_files(loc, ".epub", True)[0]
                output += log(
                    '\tDownloading with fanficfare, updating file "{}"'.format(cur),
                    'GREEN',
                    live)
                moving = ""
            except BaseException:
                # story is not in calibre
                output += log("\tStory is not in Calibre", 'WARNING', live)
                cur = url
                moving = 'cd "{}" && '.format(loc)
            copyfile("/config/personal.ini", "{}/personal.ini".format(loc))
            copyfile("/config/defaults.ini", "{}/defaults.ini".format(loc))
            output += log('\tRunning: {}python3.9 -m fanficfare.cli -u "{}" --update-cover --non-interactive'.format(
                moving, cur), 'BLUE', live)
            res = check_output('{}python3.9 -m fanficfare.cli -u "{}" --update-cover --non-interactive --config={}/personal.ini'.format(
                moving, cur, loc), shell=True, stderr=STDOUT, stdin=PIPE).decode('utf-8')
            check_regexes(res)
            if chapter_difference.search(res) or more_chapters.search(res):
                output += log("\tForcing download update due to:",
                              'WARNING', live)
                for line in res.split("\n"):
                    if line:
                        output += log("\t\t{}".format(line), 'WARNING', live)
                res = check_output(
                    '{}python3.9 -m fanficfare.cli -u "{}" --force --update-cover --non-interactive --config={}/personal.ini'.format(
                        moving, cur, loc), shell=True, stderr=STDOUT, stdin=PIPE).decode('utf-8')
                check_regexes(res)
            cur = get_files(loc, '.epub', True)[0]

            if storyId:
                output += log("\tRemoving {} from library".format(storyId),
                              'BLUE', live)
                try:
                    res = check_output(
                        'calibredb remove {} {}'.format(
                            path,
                            storyId),
                        shell=True,
                        stderr=STDOUT,
                        stdin=PIPE,
                    ).decode('utf-8')
                except BaseException:
                    if not live:
                        print(output.strip())
                    raise

            output += log("\tAdding {} to library".format(cur), 'BLUE', live)
            try:
                res = check_output(
                    'calibredb add -d {} "{}"'.format(path, cur), shell=True, stderr=STDOUT, stdin=PIPE, ).decode('utf-8')
            except Exception as e:
                output += log(e)
                if not live:
                    print(output.strip())
                raise
            try:
                res = check_output(
                    'calibredb search "Identifiers:{}" {}'.format(
                        url, path), shell=True, stderr=STDOUT, stdin=PIPE).decode('utf-8')
                output += log("\tAdded {} to library with id {}".format(cur,
                                                                        res), 'GREEN', live)
            except BaseException:
                output += log(
                    "It's been added to library, but not sure what the ID is.",
                    'WARNING',
                    live)
                output += log("Added /Story-file to library with id 0", 'GREEN', live)
            remove(cur)
        else:
            res = check_output(
                'cd "{}" && fanficfare -u "{}" --update-cover'.format(
                    loc, url), shell=True, stderr=STDOUT, stdin=PIPE).decode('utf-8')
            check_regexes(res)
            cur = get_files(loc, '.epub', True)[0]
            name = get_files(loc, '.epub', False)[0]
            rename(cur, name)
            output += log(
                "Downloaded story {} to {}".format(
                    story_name.search(name).group(1),
                    name),
                'GREEN',
                live)
        if not live:
            print(output.strip())
        rmtree(loc)
    except Exception as e:
        output += log("Exception: {}".format(e), 'FAIL', live)
        if not live:
            print(output.strip())
        try:
            rmtree(loc)
        except BaseException:
            pass
        with open(inout_file, "a") as fp:
            fp.write("{}\n".format(url))


def main(user, password, server, label, inout_file, path, lib_user, lib_password, live):

    if path:
        path = '--with-library "{}" --username {} --password {}'.format(
            path, lib_user, lib_password)
        try:
            with open(devnull, 'w') as nullout:
                call(['calibredb'], stdout=nullout, stderr=nullout)
        except OSError as e:
            if e.errno == errno.ENOENT:
                log("Calibredb is not installed on this system. Cannot search the calibre library or update it.", 'FAIL')
                return

    touch(inout_file)

    with open(inout_file, "r") as fp:
        urls = set([x.replace("\n", "") for x in fp.readlines()])

    with open(inout_file, "w") as fp:
        fp.write("")

    try:
        socket.setdefaulttimeout(55)
        urls |= geturls.get_urls_from_imap(server, user, password, label)
        socket.setdefaulttimeout(None)
    except BaseException:
        with open(inout_file, "w") as fp:
            for cur in urls:
                fp.write("{}\n".format(cur))
        return

    if not urls:
        return
    urls = set(parse_url(x) for x in urls)
    log("URLs to parse ({}):".format(len(urls)), 'HEADER')
    for url in urls:
        log("\t{}".format(url), 'BLUE')
    if len(urls) == 1:
        downloader([list(urls)[0], inout_file, path, True])
    else:
        for url in urls:
            downloader([url, inout_file, path, True])
    with open(inout_file, "r") as fp:
        urls = set([x.replace("\n", "") for x in fp.readlines()])
    with open(inout_file, "w") as fp:
        fp.writelines(["{}\n".format(x) for x in urls])
    return


if __name__ == "__main__":
    option_parser = OptionParser(usage="usage: %prog [flags]")

    option_parser.add_option(
        '-u',
        '--user',
        action='store',
        dest='user',
        help='Email Account Username. Required.')

    option_parser.add_option(
        '-p',
        '--password',
        action='store',
        dest='password',
        help='Email Account Password. Required.')

    option_parser.add_option(
        '-s',
        '--server',
        action='store',
        dest='server',
        default="imap.gmail.com",
        help='Email IMAP Server. Default is "imap.gmail.com".')

    option_parser.add_option(
        '-m',
        '--mailbox',
        action='store',
        dest='mailbox',
        default='INBOX',
        help='Email Label. Default is "INBOX".')

    option_parser.add_option(
        '-l',
        '--library',
        action='store',
        dest='library',
        help="calibre library db location. If none is passed, then this merely scrapes the email and error file for new stories and downloads them into the current directory.")

    option_parser.add_option(
        '-i',
        '--input',
        action='store',
        dest='input',
        default="./fanfiction.txt",
        help="Error file. Any urls that fail will be output here, and file will be read to find any urls that failed previously. If file does not exist will create. File is overwitten every time the program is run.")

    option_parser.add_option(
        '-c',
        '--config',
        action='store',
        dest='config',
        help='Config file for inputs. Blank config file is provided. No default. If an option is present in whatever config file is passed it, the option will overwrite whatever is passed in through command line arguments unless the option is blank. Do not put any quotation marks in the options.')

    option_parser.add_option(
        '-o',
        '--output',
        action='store_true',
        dest='live',
        help='Include this if you want all the output to be saved and posted live. Useful when multithreading.')
        
    option_parser.add_option(
        '-q',
        '--libuser',
        action='store',
        dest='libuser',
        help='Calibre User. Required.')

    option_parser.add_option(
        '-w',
        '--libpassword',
        action='store',
        dest='libpassword',
        help='Calibre Password. Required.')
        
    (options, args) = option_parser.parse_args()

    if options.config:
        touch(options.config)
        config = ConfigParser(allow_no_value=True)
        config.read(options.config)

        def updater(option, newval): return newval if newval != "" else option
        try:
            options.user = updater(
                options.user, config.get(
                    'login', 'user').strip())
        except BaseException:
            pass

        try:
            options.password = updater(
                options.password, config.get(
                    'login', 'password').strip())
        except BaseException:
            pass
            
        try:
            options.libuser = updater(
                options.libuser, config.get(
                    'login', 'libuser').strip())
        except BaseException:
            pass

        try:
            options.libpassword = updater(
                options.libpassword, config.get(
                    'login', 'libpassword').strip())
        except BaseException:
            pass

        try:
            options.server = updater(
                options.server, config.get(
                    'login', 'server').strip())
        except BaseException:
            pass

        try:
            options.mailbox = updater(
                options.mailbox, config.get(
                    'login', 'mailbox').strip())
        except BaseException:
            pass

        try:
            options.library = updater(
                options.library, config.get(
                    'locations', 'library').strip())
        except BaseException:
            pass

        try:
            options.input = updater(
                options.input, config.get(
                    'locations', 'input').strip())
        except BaseException:
            pass

        try:
            options.live = updater(
                options.live, config.getboolean(
                    'output', 'live').strip())
        except BaseException:
            pass

    if not (options.user or options.password):
        raise ValueError("User or Password not given")
    main(
        options.user,
        options.password,
        options.server,
        options.mailbox,
        options.input,
        options.library,
        options.libuser,
        options.libpassword,
        options.live)
