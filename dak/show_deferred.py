#!/usr/bin/env python

# based on queue-report
#    Copyright (C) 2001, 2002, 2003, 2005, 2006  James Troup <james@nocrew.org>
# Copyright (C) 2008 Thomas Viehmann <tv@beamnet.de>

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

import sys, os, re, time
import apt_pkg
import tempfile
from debian_bundle import deb822
from daklib import database
from daklib import queue
from daklib import utils

################################################################################
### work around bug #487902 in debian-python 0.1.10
deb822.Changes._multivalued_fields = {
            "files": [ "md5sum", "size", "section", "priority", "name" ],
            "checksums-sha1": ["sha1", "size", "name"],
            "checksums-sha256": ["sha256", "size", "name"],
          }

################################################################################

row_number = 1

html_escaping = {'"':'&quot;', '&':'&amp;', '<':'&lt;', '>':'&gt;'}
re_html_escaping = re.compile('|'.join(map(re.escape, html_escaping.keys())))
def html_escape(s):
    return re_html_escaping.sub(lambda x: html_escaping.get(x.group(0)), s)

################################################################################

def header():
  return  """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
        <html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8">
        <title>Deferred uploads to Debian</title>
        <link type="text/css" rel="stylesheet" href="style.css">
        <link rel="shortcut icon" href="http://www.debian.org/favicon.ico">
        </head>
        <body>
        <div align="center">
        <a href="http://www.debian.org/">
     <img src="http://www.debian.org/logos/openlogo-nd-50.png" border="0" hspace="0" vspace="0" alt=""></a>
        <a href="http://www.debian.org/">
     <img src="http://www.debian.org/Pics/debian.png" border="0" hspace="0" vspace="0" alt="Debian Project"></a>
        </div>
        <br />
        <table class="reddy" width="100%">
        <tr>
        <td class="reddy">
    <img src="http://www.debian.org/Pics/red-upperleft.png" align="left" border="0" hspace="0" vspace="0"
     alt="" width="15" height="16"></td>
        <td rowspan="2" class="reddy">Deferred uploads to Debian</td>
        <td class="reddy">
    <img src="http://www.debian.org/Pics/red-upperright.png" align="right" border="0" hspace="0" vspace="0"
     alt="" width="16" height="16"></td>
        </tr>
        <tr>
        <td class="reddy">
    <img src="http://www.debian.org/Pics/red-lowerleft.png" align="left" border="0" hspace="0" vspace="0"
     alt="" width="16" height="16"></td>
        <td class="reddy">
    <img src="http://www.debian.org/Pics/red-lowerright.png" align="right" border="0" hspace="0" vspace="0"
     alt="" width="15" height="16"></td>
        </tr>
        </table>
        """

def footer():
    res = "<p class=\"validate\">Timestamp: %s (UTC)</p>" % (time.strftime("%d.%m.%Y / %H:%M:%S", time.gmtime()))
    res += """<a href="http://validator.w3.org/check?uri=referer">
    <img border="0" src="http://www.w3.org/Icons/valid-html401" alt="Valid HTML 4.01!" height="31" width="88"></a>
        <a href="http://jigsaw.w3.org/css-validator/check/referer">
    <img border="0" src="http://jigsaw.w3.org/css-validator/images/vcss" alt="Valid CSS!"
     height="31" width="88"></a>
    """
    res += "</body></html>"
    return res

def table_header():
    return """<h1>Deferred uploads</h1>
      <center><table border="0">
        <tr>
          <th align="center">Change</th>
          <th align="center">Time remaining</th>
          <th align="center">Uploader</th>
          <th align="center">Closes</th>
        </tr>
        """
    return res

def table_footer():
    return '</table><br/><p>non-NEW uploads are <a href="/deferred/">available</a>, see the <a href="ftp://ftp-master.debian.org/pub/UploadQueue/README">UploadQueue-README</a> for more information.</p></center><br/>\n'

def table_row(changesname, delay, changed_by, closes):
    global row_number

    res = '<tr class="%s">'%((row_number%2) and 'odd' or 'even')
    res += (3*'<td valign="top">%s</td>')%tuple(map(html_escape,(changesname,delay,changed_by)))
    res += ('<td valign="top">%s</td>' %
             ''.join(map(lambda close:  '<a href="http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=%s">#%s</a><br>' % (close, close),closes)))
    res += '</tr>\n'
    row_number+=1
    return res

def get_upload_data(changesfn):
    achanges = deb822.Changes(file(changesfn))
    changesname = os.path.basename(changesfn)
    delay = os.path.basename(os.path.dirname(changesfn))
    m = re.match(r'([0-9]+)-day', delay)
    if m:
        delaydays = int(m.group(1))
        remainingtime = (delaydays>0)*max(0,24*60*60+os.stat(changesfn).st_mtime-time.time())
        delay = "%d days %02d:%02d" %(max(delaydays-1,0), int(remainingtime/3600),int(remainingtime/60)%60)
    else:
        remainingtime = 0

    uploader = achanges.get('changed-by')
    uploader = re.sub(r'^\s*(\S.*)\s+<.*>',r'\1',uploader)
    if Cnf.has_key("Show-Deferred::LinkPath"):
        isnew = 0
        suites = database.get_suites(achanges['source'],src=1)
        if 'unstable' not in suites and 'experimental' not in suites:
            isnew = 1
        for b in achanges['binary'].split():
            suites = database.get_suites(b)
            if 'unstable' not in suites and 'experimental' not in suites:
                isnew = 1
        if not isnew:
            # we don't link .changes because we don't want other people to
            # upload it with the existing signature.
            for afn in map(lambda x: x['name'],achanges['files']):
                lfn = os.path.join(Cnf["Show-Deferred::LinkPath"],afn)
                qfn = os.path.join(os.path.dirname(changesfn),afn)
                if os.path.islink(lfn):
                    os.unlink(lfn)
                if os.path.exists(qfn):
                    os.symlink(qfn,lfn)
                    os.chmod(qfn, 0644)
    return (max(delaydays-1,0)*24*60*60+remainingtime, changesname, delay, uploader, achanges.get('closes').split(),achanges)

def list_uploads(filelist):
    uploads = map(get_upload_data, filelist)
    uploads.sort()
    # print the summary page
    print header()
    if uploads:
        print table_header()
        print ''.join(map(lambda x: table_row(*x[1:5]), uploads))
        print table_footer()
    else:
        print '<h1>Currently no deferred uploads to Debian</h1>'
    print footer()
    # machine readable summary
    if Cnf.has_key("Show-Deferred::LinkPath"):
        fn = os.path.join(Cnf["Show-Deferred::LinkPath"],'.status.tmp')
        f = open(fn,"w")
        try:
            for u in uploads:
                print >> f, "Changes: %s"%u[1]
                fields = """Location: DEFERRED
Delayed-Until: %s
Delay-Remaining: %s"""%(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()+u[0])),u[2])
                print >> f, fields
                print >> f, str(u[5]).rstrip()
                open(os.path.join(Cnf["Show-Deferred::LinkPath"],u[1]),"w").write(str(u[5])+fields+'\n')
                print >> f
            f.close()
            os.rename(os.path.join(Cnf["Show-Deferred::LinkPath"],'.status.tmp'),
                      os.path.join(Cnf["Show-Deferred::LinkPath"],'status'))
        except:
            os.unlink(fn)
            raise

def usage (exit_code=0):
    if exit_code:
        f = sys.stderr
    else:
        f = sys.stdout
    print >> f, """Usage: dak show-deferred
  -h, --help                    show this help and exit.
  -p, --link-path [path]        override output directory.
  -d, --deferred-queue [path]   path to the deferred queue
  """
    sys.exit(exit_code)

def init():
    global Cnf, Options, Upload, projectB
    Cnf = utils.get_conf()
    Arguments = [('h',"help","Show-Deferred::Options::Help"),
                 ("p","link-path","Show-Deferred::LinkPath","HasArg"),
                 ("d","deferred-queue","Show-Deferred::DeferredQueue","HasArg")]
    args = apt_pkg.ParseCommandLine(Cnf,Arguments,sys.argv)
    for i in ["help"]:
        if not Cnf.has_key("Show-Deferred::Options::%s" % (i)):
            Cnf["Show-Deferred::Options::%s" % (i)] = ""
    for i,j in [("DeferredQueue","--deferred-queue")]:
        if not Cnf.has_key("Show-Deferred::%s" % (i)):
            print >> sys.stderr, """Show-Deferred::%s is mandatory.
  set via config file or command-line option %s"""%(i,j)

    Options = Cnf.SubTree("Show-Deferred::Options")
    if Options["help"]:
        usage()
    Upload = queue.Upload(Cnf)
    projectB = Upload.projectB
    return args

def main():
    args = init()
    if len(args)!=0:
        usage(1)

    filelist = []
    for r,d,f  in os.walk(Cnf["Show-Deferred::DeferredQueue"]):
        filelist += map (lambda x: os.path.join(r,x),
                         filter(lambda x: x.endswith('.changes'), f))
    list_uploads(filelist)

    available_changes = set(map(os.path.basename,filelist))
    if Cnf.has_key("Show-Deferred::LinkPath"):
        # remove dead links
        for r,d,f in os.walk(Cnf["Show-Deferred::LinkPath"]):
            for af in f:
                afp = os.path.join(r,af)
                if (not os.path.exists(afp) or
                    (af.endswith('.changes') and af not in available_changes)):
                    os.unlink(afp)
