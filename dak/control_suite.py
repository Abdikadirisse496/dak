#!/usr/bin/env python

""" Manipulate suite tags """
# Copyright (C) 2000, 2001, 2002, 2003, 2004, 2005, 2006  James Troup <james@nocrew.org>

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

#######################################################################################

# 8to6Guy: "Wow, Bob, You look rough!"
# BTAF: "Mbblpmn..."
# BTAF <.oO>: "You moron! This is what you get for staying up all night drinking vodka and salad dressing!"
# BTAF <.oO>: "This coffee I.V. drip is barely even keeping me awake! I need something with more kick! But what?"
# BTAF: "OMIGOD! I OVERDOSED ON HEROIN"
# CoWorker#n: "Give him air!!"
# CoWorker#n+1: "We need a syringe full of adrenaline!"
# CoWorker#n+2: "Stab him in the heart!"
# BTAF: "*YES!*"
# CoWorker#n+3: "Bob's been overdosing quite a bit lately..."
# CoWorker#n+4: "Third time this week."

# -- http://www.angryflower.com/8to6.gif

#######################################################################################

# Adds or removes packages from a suite.  Takes the list of files
# either from stdin or as a command line argument.  Special action
# "set", will reset the suite (!) and add all packages from scratch.

#######################################################################################

import sys
import apt_pkg
import os

from daklib.config import Config
from daklib.dbconn import *
from daklib import daklog
from daklib import utils
from daklib.queue import get_suite_version_by_package, get_suite_version_by_source

#######################################################################################

Logger = None

################################################################################

def usage (exit_code=0):
    print """Usage: dak control-suite [OPTIONS] [FILE]
Display or alter the contents of a suite using FILE(s), or stdin.

  -a, --add=SUITE            add to SUITE
  -h, --help                 show this help and exit
  -l, --list=SUITE           list the contents of SUITE
  -r, --remove=SUITE         remove from SUITE
  -s, --set=SUITE            set SUITE
  -b, --britney              generate changelog entry for britney runs"""

    sys.exit(exit_code)

#######################################################################################

def get_id(package, version, architecture, session):
    if architecture == "source":
        q = session.execute("SELECT id FROM source WHERE source = :package AND version = :version",
                            {'package': package, 'version': version})
    else:
        q = session.execute("""SELECT b.id FROM binaries b, architecture a
                                WHERE b.package = :package AND b.version = :version
                                  AND (a.arch_string = :arch OR a.arch_string = 'all')
                                  AND b.architecture = a.id""",
                               {'package': package, 'version': version, 'arch': architecture})

    ql = q.fetchall()
    if len(ql) < 1:
        utils.warn("Couldn't find '%s_%s_%s'." % (package, version, architecture))
        return None

    if len(ql) > 1:
        utils.warn("Found more than one match for '%s_%s_%s'." % (package, version, architecture))
        return None

    return ql[0][0]

#######################################################################################

def britney_changelog(packages, suite, session):

    old = {}
    current = {}
    Cnf = utils.get_conf()

    try:
        q = session.execute("SELECT changelog FROM suite WHERE id = :suiteid", \
                            {'suiteid': suite.suite_id})
        brit_file = q.fetchone()[0]
    except:
        brit_file = None

    if brit_file:
        brit_file = os.path.join(Cnf['Dir::Root'], brit_file)
    else:
        return

    q = session.execute("""SELECT s.source, s.version, sa.id
                             FROM source s, src_associations sa
                            WHERE sa.suite = :suiteid
                              AND sa.source = s.id""", {'suiteid': suite.suite_id})

    for p in q.fetchall():
        current[p[0]] = p[1]
    for p in packages.keys():
        p = p.split()
        if p[2] == "source":
            old[p[0]] = p[1]

    new = {}
    for p in current.keys():
        if p in old.keys():
            if apt_pkg.VersionCompare(current[p], old[p]) > 0:
                new[p] = [current[p], old[p]]
        else:
            new[p] = [current[p], 0]

    query =  "SELECT source, changelog FROM changelogs WHERE"
    for p in new.keys():
        query += " source = '%s' AND version > '%s' AND version <= '%s'" \
                 % (p, new[p][1], new[p][0])
        query += " AND architecture LIKE '%source%' AND distribution in \
                  ('unstable', 'experimental', 'testing-proposed-updates') OR"
    query += " False ORDER BY source, version DESC"
    q = session.execute(query)

    pu = None
    brit = utils.open_file(brit_file, 'w')

    for u in q:
        if pu and pu != u[0]:
            brit.write("\n")
        brit.write("%s\n" % u[1])
        pu = u[0]
    if q.rowcount: brit.write("\n\n\n")

    for p in list(set(old.keys()).difference(current.keys())):
        brit.write("REMOVED: %s %s\n" % (p, old[p]))

    brit.flush()
    brit.close()

#######################################################################################

def version_checks(package, architecture, target_suite, new_version, session, force = False):
    if architecture == "source":
        suite_version_list = get_suite_version_by_source(package, session)
    else:
        suite_version_list = get_suite_version_by_package(package, architecture, session)

    must_be_newer_than = [ vc.reference.suite_name for vc in get_version_checks(target_suite, "MustBeNewerThan") ]
    must_be_older_than = [ vc.reference.suite_name for vc in get_version_checks(target_suite, "MustBeOlderThan") ]

    # Must be newer than an existing version in target_suite
    if target_suite not in must_be_newer_than:
        must_be_newer_than.append(target_suite)

    violations = False

    for suite, version in suite_version_list:
        cmp = apt_pkg.VersionCompare(new_version, version)
        if suite in must_be_newer_than and cmp < 1:
            utils.warn("%s (%s): version check violated: %s targeted at %s is *not* newer than %s in %s" % (package, architecture, new_version, target_suite, version, suite))
            violations = True
        if suite in must_be_older_than and cmp > 1:
            utils.warn("%s (%s): version check violated: %s targeted at %s is *not* older than %s in %s" % (package, architecture, new_version, target_suite, version, suite))
            violations = True

    if violations:
        if force:
            utils.warn("Continuing anyway (forced)...")
        else:
            utils.fubar("Aborting. Version checks violated and not forced.")

#######################################################################################

def set_suite(file, suite, session, britney=False, force=False):
    suite_id = suite.suite_id
    lines = file.readlines()

    # Our session is already in a transaction

    # Build up a dictionary of what is currently in the suite
    current = {}
    q = session.execute("""SELECT b.package, b.version, a.arch_string, ba.id
                             FROM binaries b, bin_associations ba, architecture a
                            WHERE ba.suite = :suiteid
                              AND ba.bin = b.id AND b.architecture = a.id""", {'suiteid': suite_id})
    for i in q.fetchall():
        key = " ".join(i[:3])
        current[key] = i[3]

    q = session.execute("""SELECT s.source, s.version, sa.id
                             FROM source s, src_associations sa
                            WHERE sa.suite = :suiteid
                              AND sa.source = s.id""", {'suiteid': suite_id})
    for i in q.fetchall():
        key = " ".join(i[:2]) + " source"
        current[key] = i[2]

    # Build up a dictionary of what should be in the suite
    desired = {}
    for line in lines:
        split_line = line.strip().split()
        if len(split_line) != 3:
            utils.warn("'%s' does not break into 'package version architecture'." % (line[:-1]))
            continue
        key = " ".join(split_line)
        desired[key] = ""

    # Check to see which packages need removed and remove them
    for key in current.keys():
        if not desired.has_key(key):
            (package, version, architecture) = key.split()
            pkid = current[key]
            if architecture == "source":
                session.execute("""DELETE FROM src_associations WHERE id = :pkid""", {'pkid': pkid})
            else:
                session.execute("""DELETE FROM bin_associations WHERE id = :pkid""", {'pkid': pkid})
            Logger.log(["removed", key, pkid])

    # Check to see which packages need added and add them
    for key in desired.keys():
        if not current.has_key(key):
            (package, version, architecture) = key.split()
            version_checks(package, architecture, suite.suite_name, version, session, force)
            pkid = get_id (package, version, architecture, session)
            if not pkid:
                continue
            if architecture == "source":
                session.execute("""INSERT INTO src_associations (suite, source)
                                        VALUES (:suiteid, :pkid)""", {'suiteid': suite_id, 'pkid': pkid})
            else:
                session.execute("""INSERT INTO bin_associations (suite, bin)
                                        VALUES (:suiteid, :pkid)""", {'suiteid': suite_id, 'pkid': pkid})
            Logger.log(["added", key, pkid])

    session.commit()

    if britney:
        britney_changelog(current, suite, session)

#######################################################################################

def process_file(file, suite, action, session, britney=False, force=False):
    if action == "set":
        set_suite(file, suite, session, britney, force)
        return

    suite_id = suite.suite_id

    lines = file.readlines()

    # Our session is already in a transaction
    for line in lines:
        split_line = line.strip().split()
        if len(split_line) != 3:
            utils.warn("'%s' does not break into 'package version architecture'." % (line[:-1]))
            continue

        (package, version, architecture) = split_line

        pkid = get_id(package, version, architecture, session)
        if not pkid:
            continue

        # Do version checks when adding packages
        if action == "add":
            version_checks(package, architecture, suite.suite_name, version, session, force)

        if architecture == "source":
            # Find the existing association ID, if any
            q = session.execute("""SELECT id FROM src_associations
                                    WHERE suite = :suiteid and source = :pkid""",
                                    {'suiteid': suite_id, 'pkid': pkid})
            ql = q.fetchall()
            if len(ql) < 1:
                association_id = None
            else:
                association_id = ql[0][0]

            # Take action
            if action == "add":
                if association_id:
                    utils.warn("'%s_%s_%s' already exists in suite %s." % (package, version, architecture, suite))
                    continue
                else:
                    session.execute("""INSERT INTO src_associations (suite, source)
                                            VALUES (:suiteid, :pkid)""",
                                       {'suiteid': suite_id, 'pkid': pkid})
            elif action == "remove":
                if association_id == None:
                    utils.warn("'%s_%s_%s' doesn't exist in suite %s." % (package, version, architecture, suite))
                    continue
                else:
                    session.execute("""DELETE FROM src_associations WHERE id = :pkid""", {'pkid': association_id})
        else:
            # Find the existing associations ID, if any
            q = session.execute("""SELECT id FROM bin_associations
                                    WHERE suite = :suiteid and bin = :pkid""",
                                    {'suiteid': suite_id, 'pkid': pkid})
            ql = q.fetchall()
            if len(ql) < 1:
                association_id = None
            else:
                association_id = ql[0][0]

            # Take action
            if action == "add":
                if association_id:
                    utils.warn("'%s_%s_%s' already exists in suite %s." % (package, version, architecture, suite))
                    continue
                else:
                    session.execute("""INSERT INTO bin_associations (suite, bin)
                                            VALUES (:suiteid, :pkid)""",
                                       {'suiteid': suite_id, 'pkid': pkid})
            elif action == "remove":
                if association_id == None:
                    utils.warn("'%s_%s_%s' doesn't exist in suite %s." % (package, version, architecture, suite))
                    continue
                else:
                    session.execute("""DELETE FROM bin_associations WHERE id = :pkid""", {'pkid': association_id})

    session.commit()

#######################################################################################

def get_list(suite, session):
    suite_id = suite.suite_id
    # List binaries
    q = session.execute("""SELECT b.package, b.version, a.arch_string
                             FROM binaries b, bin_associations ba, architecture a
                            WHERE ba.suite = :suiteid
                              AND ba.bin = b.id AND b.architecture = a.id""", {'suiteid': suite_id})
    for i in q.fetchall():
        print " ".join(i)

    # List source
    q = session.execute("""SELECT s.source, s.version
                             FROM source s, src_associations sa
                            WHERE sa.suite = :suiteid
                              AND sa.source = s.id""", {'suiteid': suite_id})
    for i in q.fetchall():
        print " ".join(i) + " source"

#######################################################################################

def main ():
    global Logger

    cnf = Config()

    Arguments = [('a',"add","Control-Suite::Options::Add", "HasArg"),
                 ('b',"britney","Control-Suite::Options::Britney"),
                 ('f','force','Control-Suite::Options::Force'),
                 ('h',"help","Control-Suite::Options::Help"),
                 ('l',"list","Control-Suite::Options::List","HasArg"),
                 ('r',"remove", "Control-Suite::Options::Remove", "HasArg"),
                 ('s',"set", "Control-Suite::Options::Set", "HasArg")]

    for i in ["add", "britney", "help", "list", "remove", "set", "version" ]:
        if not cnf.has_key("Control-Suite::Options::%s" % (i)):
            cnf["Control-Suite::Options::%s" % (i)] = ""

    try:
        file_list = apt_pkg.ParseCommandLine(cnf.Cnf, Arguments, sys.argv);
    except SystemError, e:
        print "%s\n" % e
        usage(1)
    Options = cnf.SubTree("Control-Suite::Options")

    if Options["Help"]:
        usage()

    session = DBConn().session()

    force = Options.has_key("Force") and Options["Force"]

    action = None

    for i in ("add", "list", "remove", "set"):
        if cnf["Control-Suite::Options::%s" % (i)] != "":
            suite_name = cnf["Control-Suite::Options::%s" % (i)]
            suite = get_suite(suite_name, session=session)
            if suite is None:
                utils.fubar("Unknown suite '%s'." % (suite_name))
            else:
                if action:
                    utils.fubar("Can only perform one action at a time.")
                action = i

    # Need an action...
    if action == None:
        utils.fubar("No action specified.")

    # Safety/Sanity check
    # XXX: This should be stored in the database
    if action == "set" and suite_name not in ["testing", "squeeze-updates"]:
        utils.fubar("Will not reset suite %s" % (suite_name))

    britney = False
    if action == "set" and cnf["Control-Suite::Options::Britney"]:
        britney = True

    if action == "list":
        get_list(suite, session)
    else:
        Logger = daklog.Logger("control-suite")
        if file_list:
            for f in file_list:
                process_file(utils.open_file(f), suite, action, session, britney, force)
        else:
            process_file(sys.stdin, suite, action, session, britney, force)
        Logger.close()

#######################################################################################

if __name__ == '__main__':
    main()
