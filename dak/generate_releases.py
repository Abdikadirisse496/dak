#!/usr/bin/env python

"""
Create all the Release files

@contact: Debian FTPMaster <ftpmaster@debian.org>
@copyright: 2011  Joerg Jaspert <joerg@debian.org>
@copyright: 2011  Mark Hymers <mhy@debian.org>
@license: GNU General Public License version 2 or later

"""

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

################################################################################

# <mhy> I wish they wouldnt leave biscuits out, thats just tempting. Damnit.

################################################################################

import sys
import os
import os.path
import stat
import time
import gzip
import bz2
import apt_pkg
from tempfile import mkstemp, mkdtemp
import commands
from multiprocessing import Pool, TimeoutError
from sqlalchemy.orm import object_session

from daklib import utils, daklog
from daklib.regexes import re_gensubrelease, re_includeinrelease
from daklib.dak_exceptions import *
from daklib.dbconn import *
from daklib.config import Config

################################################################################
Logger = None                  #: Our logging object
results = []                   #: Results of the subprocesses

################################################################################

def usage (exit_code=0):
    """ Usage information"""

    print """Usage: dak generate-releases [OPTIONS]
Generate the Release files

  -s, --suite=SUITE(s)       process this suite
                             Default: All suites not marked 'untouchable'
  -f, --force                Allow processing of untouchable suites
                             CAREFUL: Only to be used at (point) release time!
  -h, --help                 show this help and exit

SUITE can be a space seperated list, e.g.
   --suite=unstable testing
  """
    sys.exit(exit_code)

########################################################################

def get_result(arg):
    global results
    if arg:
        results.append(arg)

def sign_release_dir(suite, dirname):
    cnf = Config()

    if cnf.has_key("Dinstall::SigningKeyring"):
        keyring = "--secret-keyring \"%s\"" % cnf["Dinstall::SigningKeyring"]
        if cnf.has_key("Dinstall::SigningPubKeyring"):
            keyring += " --keyring \"%s\"" % cnf["Dinstall::SigningPubKeyring"]

        arguments = "--no-options --batch --no-tty --armour"

        relname = os.path.join(dirname, 'Release')

        dest = os.path.join(dirname, 'Release.gpg')
        if os.path.exists(dest):
            os.unlink(dest)

        inlinedest = os.path.join(dirname, 'InRelease')
        if os.path.exists(inlinedest):
            os.unlink(inlinedest)

        # We can only use one key for inline signing so use the first one in
        # the array for consistency
        firstkey = True

        for keyid in suite.signingkeys:
            defkeyid = "--default-key %s" % keyid

            os.system("gpg %s %s %s --detach-sign <%s >>%s" %
                    (keyring, defkeyid, arguments, relname, dest))

            if firstkey:
                os.system("gpg %s %s %s --clearsign <%s >>%s" %
                        (keyring, defkeyid, arguments, relname, inlinedest))
                firstkey = False

class ReleaseWriter(object):
    def __init__(self, suite):
        self.suite = suite

    def generate_release_files(self):
        """
        Generate Release files for the given suite

        @type suite: string
        @param suite: Suite name
        """

        suite = self.suite
        session = object_session(suite)

        architectures = get_suite_architectures(suite.suite_name, skipall=True, skipsrc=True, session=session)

        # Attribs contains a tuple of field names and the database names to use to
        # fill them in
        attribs = ( ('Origin',      'origin'),
                    ('Label',       'label'),
                    ('Suite',       'suite_name'),
                    ('Version',     'version'),
                    ('Codename',    'codename') )

        # A "Sub" Release file has slightly different fields
        subattribs = ( ('Archive',  'suite_name'),
                       ('Origin',   'origin'),
                       ('Label',    'label'),
                       ('Version',  'version') )

        # Boolean stuff. If we find it true in database, write out "yes" into the release file
        boolattrs = ( ('NotAutomatic',         'notautomatic'),
                      ('ButAutomaticUpgrades', 'butautomaticupgrades') )

        cnf = Config()

        suite_suffix = "%s" % (cnf.Find("Dinstall::SuiteSuffix"))

        outfile = os.path.join(cnf["Dir::Root"], 'dists', "%s/%s" % (suite.suite_name, suite_suffix), "Release")
        out = open(outfile + ".new", "w")

        for key, dbfield in attribs:
            if getattr(suite, dbfield) is not None:
                out.write("%s: %s\n" % (key, getattr(suite, dbfield)))

        out.write("Date: %s\n" % (time.strftime("%a, %d %b %Y %H:%M:%S UTC", time.gmtime(time.time()))))

        if suite.validtime:
            validtime=float(suite.validtime)
            out.write("Valid-Until: %s\n" % (time.strftime("%a, %d %b %Y %H:%M:%S UTC", time.gmtime(time.time()+validtime))))

        for key, dbfield in boolattrs:
            if getattr(suite, dbfield, False):
                out.write("%s: yes\n" % (key))

        out.write("Architectures: %s\n" % (" ".join([a.arch_string for a in architectures])))

        ## FIXME: Components need to be adjusted to whatever will be in the db
        ## Needs putting in the DB
        components = ['main', 'contrib', 'non-free']

        out.write("Components: %s\n" % ( " ".join(map(lambda x: "%s%s" % (suite_suffix, x), components ))))

        # For exact compatibility with old g-r, write out Description here instead
        # of with the rest of the DB fields above
        if getattr(suite, 'description') is not None:
            out.write("Description: %s\n" % suite.description)

        for comp in components:
            for dirpath, dirnames, filenames in os.walk("%sdists/%s/%s%s" % (cnf["Dir::Root"], suite.suite_name, suite_suffix, comp), topdown=True):
                if not re_gensubrelease.match(dirpath):
                    continue

                subfile = os.path.join(dirpath, "Release")
                subrel = open(subfile + '.new', "w")

                for key, dbfield in subattribs:
                    if getattr(suite, dbfield) is not None:
                        subrel.write("%s: %s\n" % (key, getattr(suite, dbfield)))

                for key, dbfield in boolattrs:
                    if getattr(suite, dbfield, False):
                        subrel.write("%s: yes\n" % (key))

                subrel.write("Component: %s%s\n" % (suite_suffix, comp))

                # Urgh, but until we have all the suite/component/arch stuff in the DB,
                # this'll have to do
                arch = os.path.split(dirpath)[-1]
                if arch.startswith('binary-'):
                    arch = arch[7:]

                subrel.write("Architecture: %s\n" % (arch))
                subrel.close()

                os.rename(subfile + '.new', subfile)

        # Now that we have done the groundwork, we want to get off and add the files with
        # their checksums to the main Release file
        oldcwd = os.getcwd()

        os.chdir("%sdists/%s/%s" % (cnf["Dir::Root"], suite.suite_name, suite_suffix))

        hashfuncs = { 'MD5Sum' : apt_pkg.md5sum,
                      'SHA1' : apt_pkg.sha1sum,
                      'SHA256' : apt_pkg.sha256sum }

        fileinfo = {}

        uncompnotseen = {}

        for dirpath, dirnames, filenames in os.walk(".", followlinks=True, topdown=True):
            for entry in filenames:
                # Skip things we don't want to include
                if not re_includeinrelease.match(entry):
                    continue

                if dirpath == '.' and entry in ["Release", "Release.gpg", "InRelease"]:
                    continue

                filename = os.path.join(dirpath.lstrip('./'), entry)
                fileinfo[filename] = {}
                contents = open(filename, 'r').read()

                # If we find a file for which we have a compressed version and
                # haven't yet seen the uncompressed one, store the possibility
                # for future use
                if entry.endswith(".gz") and entry[:-3] not in uncompnotseen.keys():
                    uncompnotseen[filename[:-3]] = (gzip.GzipFile, filename)
                elif entry.endswith(".bz2") and entry[:-4] not in uncompnotseen.keys():
                    uncompnotseen[filename[:-4]] = (bz2.BZ2File, filename)

                fileinfo[filename]['len'] = len(contents)

                for hf, func in hashfuncs.items():
                    fileinfo[filename][hf] = func(contents)

        for filename, comp in uncompnotseen.items():
            # If we've already seen the uncompressed file, we don't
            # need to do anything again
            if filename in fileinfo.keys():
                continue

            # Skip uncompressed Contents files as they're huge, take ages to
            # checksum and we checksum the compressed ones anyways
            if os.path.basename(filename).startswith("Contents"):
                continue

            fileinfo[filename] = {}

            # File handler is comp[0], filename of compressed file is comp[1]
            contents = comp[0](comp[1], 'r').read()

            fileinfo[filename]['len'] = len(contents)

            for hf, func in hashfuncs.items():
                fileinfo[filename][hf] = func(contents)


        for h in sorted(hashfuncs.keys()):
            out.write('%s:\n' % h)
            for filename in sorted(fileinfo.keys()):
                out.write(" %s %8d %s\n" % (fileinfo[filename][h], fileinfo[filename]['len'], filename))

        out.close()
        os.rename(outfile + '.new', outfile)

        sign_release_dir(suite, os.path.dirname(outfile))

        os.chdir(oldcwd)

        return


def main ():
    global Logger, results

    cnf = Config()

    for i in ["Help", "Suite", "Force"]:
        if not cnf.has_key("Generate-Releases::Options::%s" % (i)):
            cnf["Generate-Releases::Options::%s" % (i)] = ""

    Arguments = [('h',"help","Generate-Releases::Options::Help"),
                 ('s',"suite","Generate-Releases::Options::Suite"),
                 ('f',"force","Generate-Releases::Options::Force")]

    suite_names = apt_pkg.ParseCommandLine(cnf.Cnf, Arguments, sys.argv)
    Options = cnf.SubTree("Generate-Releases::Options")

    if Options["Help"]:
        usage()

    Logger = daklog.Logger(cnf, 'generate-releases')

    session = DBConn().session()

    if Options["Suite"]:
        suites = []
        for s in suite_names:
            suite = get_suite(s.lower(), session)
            if suite:
                suites.append(suite)
            else:
                print "cannot find suite %s" % s
                Logger.log(['cannot find suite %s' % s])
    else:
        suites = session.query(Suite).filter(Suite.untouchable == False).all()

    broken=[]
    # For each given suite, run one process
    results = []

    pool = Pool()

    for s in suites:
        # Setup a multiprocessing Pool. As many workers as we have CPU cores.
        if s.untouchable and not Options["Force"]:
            print "Skipping %s (untouchable)" % s.suite_name
            continue

        print "Processing %s" % s.suite_name
        Logger.log(['Processing release file for Suite: %s' % (s.suite_name)])
        pool.apply_async(generate_helper, (s.suite_id, ), callback=get_result)

    # No more work will be added to our pool, close it and then wait for all to finish
    pool.close()
    pool.join()

    retcode = 0

    if len(results) > 0:
        Logger.log(['Release file generation broken: %s' % (results)])
        print "Release file generation broken:\n", '\n'.join(results)
        retcode = 1

    Logger.close()

    sys.exit(retcode)

def generate_helper(suite_id):
    '''
    This function is called in a new subprocess.
    '''
    session = DBConn().session()
    suite = Suite.get(suite_id, session)
    try:
        rw = ReleaseWriter(suite)
        rw.generate_release_files()
    except Exception, e:
        return str(e)

    return

#######################################################################################

if __name__ == '__main__':
    main()
