#!/usr/bin/env python

"""
Generate Maintainers file used by e.g. the Debian Bug Tracking System
@contact: Debian FTP Master <ftpmaster@debian.org>
@copyright: 2000, 2001, 2002, 2003, 2004, 2006  James Troup <james@nocrew.org>
@copyright: 2011 Torsten Werner <twerner@debian.org>
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

# ``As opposed to "Linux sucks. Respect my academic authoritah, damn
#   you!" or whatever all this hot air amounts to.''
#                             -- ajt@ in _that_ thread on debian-devel@

################################################################################

def usage (exit_code=0):
    print """Usage: dak make-maintainers [OPTION] EXTRA_FILE[...]
Generate an index of packages <=> Maintainers / Uploaders.

  -h, --help                 show this help and exit
"""
    sys.exit(exit_code)

################################################################################

def format(package, person):
    '''Return a string nicely formatted for writing to the output file.'''
    return '%-20s %s\n' % (package, person)

################################################################################

def uploader_list(source):
    '''Return a sorted list of uploader names for source package.'''
    return sorted([uploader.name for uploader in source.uploaders])

################################################################################

def main():
    cnf = Config()

    Arguments = [('h',"help","Make-Maintainers::Options::Help")]
    if not cnf.has_key("Make-Maintainers::Options::Help"):
        cnf["Make-Maintainers::Options::Help"] = ""

    extra_files = apt_pkg.ParseCommandLine(cnf.Cnf, Arguments, sys.argv)
    Options = cnf.SubTree("Make-Maintainers::Options")

    if Options["Help"]:
        usage()

    session = DBConn().session()

    # dictionary packages to maintainer names
    maintainers = dict()
    # dictionary packages to list of uploader names
    uploaders = dict()

    source_query = session.query(DBSource).from_statement('''
        select distinct on (source) * from source
            order by source, version desc''')

    binary_query = session.query(DBBinary).from_statement('''
        select distinct on (package) * from binaries
            order by package, version desc''')

    for source in source_query:
        maintainers[source.source] = source.maintainer.name
        uploaders[source.source] = uploader_list(source)

    for binary in binary_query:
        if binary.package not in maintainers:
            maintainers[binary.package] = binary.maintainer.name
            uploaders[binary.package] = uploader_list(binary.source)

    maintainer_file = open('Maintainers', 'w')
    uploader_file = open('Uploaders', 'w')
    for package in sorted(uploaders):
        maintainer_file.write(format(package, maintainers[package]))
        for uploader in uploaders[package]:
            uploader_file.write(format(package, uploader))
    uploader_file.close()
    maintainer_file.close()

################################################################################

if __name__ == '__main__':
    main()
