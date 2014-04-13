# Portions (c) 2014, Alexander Klimenko <alex@erix.ru>
# All rights reserved.
#
# Copyright (c) 2011, SmartFile <btimby@smartfile.com>
# All rights reserved.
#
# This file is part of DjangoDav.
#
# DjangoDav is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# DjangoDav is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with DjangoDav.  If not, see <http://www.gnu.org/licenses/>.

import mimetypes, urllib, urlparse, re
from xml.etree import ElementTree
from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound, HttpResponseNotAllowed, \
    HttpResponseBadRequest

from django.utils.http import http_date, parse_etags
from django.shortcuts import render_to_response

from djangodav.acls import DavAcl
from djangodav.responses import HttpPreconditionFailed, HttpNotModified, HttpNotAllowed, HttpError, HttpResponseCreated, \
    HttpResponseNoContent, HttpResponseConflict, HttpResponseMediatypeNotSupported, HttpResponseBadGateway, \
    HttpResponsePreconditionFailed, HttpResponseMultiStatus, HttpResponseNotImplemented
from djangodav.locks import DavLock
from djangodav.properties import DavProperty
from djangodav.requests import DavRequest
from djangodav.resources import DavResource
from djangodav.utils import parse_time, url_join


PATTERN_IF_DELIMITER = re.compile(r'(<([^>]+)>)|(\(([^\)]+)\))')


class DavServer(object):
    def __init__(self, request, path, property_class=DavProperty, resource_class=DavResource, lock_class=DavLock,
                 acl_class=DavAcl):
        self.request = DavRequest(self, request, path)
        self.resource_class = resource_class
        self.acl_class = acl_class
        self.props = property_class(self)
        self.locks = lock_class(self)

    def get_root(self):
        """Return the root of the file system we wish to export. By default the root
        is read from the DAV_ROOT setting in django's settings.py. You can override
        this method to export a different directory (maybe even different per user)."""
        return getattr(settings, 'DAV_ROOT', None)

    def get_access(self, path):
        """Return permission as DavAcl object. A DavACL should have the following attributes:
        read, write, delete, create, relocate, list. By default we implement a read-only
        system."""
        return self.acl_class(listing=True, read=True, full=False)

    def get_resource(self, path):
        """Return a DavResource object to represent the given path."""
        return self.resource_class(self, path)

    def get_depth(self, default='infinity'):
        depth = str(self.request.META.get('HTTP_DEPTH', default)).lower()
        if not depth in ('0', '1', 'infinity'):
            raise HttpResponseBadRequest('Invalid depth header value %s' % depth)
        if depth == 'infinity':
            depth = -1
        else:
            depth = int(depth)
        return depth

    def evaluate_conditions(self, res):
        if not res.exists():
            return
        etag = res.get_etag()
        mtime = res.get_mtime_stamp()
        cond_if_match = self.request.META.get('HTTP_IF_MATCH', None)
        if cond_if_match:
            etags = parse_etags(cond_if_match)
            if '*' in etags or etag in etags:
                raise HttpPreconditionFailed()
        cond_if_modified_since = self.request.META.get('HTTP_IF_MODIFIED_SINCE', False)
        if cond_if_modified_since:
            # Parse and evaluate, but don't raise anything just yet...
            # This might be ignored based on If-None-Match evaluation.
            cond_if_modified_since = parse_time(cond_if_modified_since)
            if cond_if_modified_since and cond_if_modified_since > mtime:
                cond_if_modified_since = True
            else:
                cond_if_modified_since = False
        cond_if_none_match = self.request.META.get('HTTP_IF_NONE_MATCH', None)
        if cond_if_none_match:
            etags = parse_etags(cond_if_none_match)
            if '*' in etags or etag in etags:
                if self.request.method in ('GET', 'HEAD'):
                    raise HttpNotModified()
                raise HttpPreconditionFailed()
            # Ignore If-Modified-Since header...
            cond_if_modified_since = False
        cond_if_unmodified_since = self.request.META.get('HTTP_IF_UNMODIFIED_SINCE', None)
        if cond_if_unmodified_since:
            cond_if_unmodified_since = parse_time(cond_if_unmodified_since)
            if cond_if_unmodified_since and cond_if_unmodified_since <= mtime:
                raise HttpPreconditionFailed()
        if cond_if_modified_since:
            # This previously evaluated True and is not being ignored...
            raise HttpNotModified()
        # TODO: complete If header handling...
        cond_if = self.request.META.get('HTTP_IF', None)
        if cond_if:
            if not cond_if.startswith('<'):
                cond_if = '<*>' + cond_if
            #for (tmpurl, url, tmpcontent, content) in PATTERN_IF_DELIMITER.findall(cond_if):

    def get_response(self):
        handler = getattr(self, 'do' + self.request.method, None)
        try:
            if not callable(handler):
                raise HttpNotAllowed()
            return handler()
        except HttpError, e:
            return e.get_response()

    def doGET(self, head=False):
        res = self.get_resource(self.request.path)
        acl = self.get_access(res.get_abs_path())
        if not res.exists():
            return HttpResponseNotFound()
        if not head and res.isdir():
            if not acl.listing:
                return HttpResponseForbidden()
            return render_to_response('djangodav/index.html', {'res': res})
        else:
            if not acl.read:
                return HttpResponseForbidden()
            if head and res.exists():
                response = HttpResponse()
            elif head:
                response = HttpResponseNotFound()
            else:
                use_sendfile = getattr(settings, 'DAV_USE_SENDFILE', '').split()
                if len(use_sendfile) > 0 and use_sendfile[0].lower() == 'x-sendfile':
                    full_path = res.get_abs_path().encode('utf-8')
                    if len(use_sendfile) == 2 and use_sendfile[1] == 'escape':
                        full_path = urllib.quote(full_path)
                    response = HttpResponse()
                    response['X-SendFile'] = full_path
                elif len(use_sendfile) == 2 and use_sendfile[0].lower() == 'x-accel-redir':
                    full_path = res.get_abs_path().encode('utf-8')
                    full_path = url_join(use_sendfile[1], full_path)
                    response = HttpResponse()
                    response['X-Accel-Redirect'] = full_path
                    response['X-Accel-Charset'] = 'utf-8'
                else:
                    # Do things the slow way:
                    response = HttpResponse(res.read())
            if res.exists():
                response['Content-Type'] = mimetypes.guess_type(res.get_name())
                response['Content-Length'] = res.get_size()
                response['Last-Modified'] = http_date(res.get_mtime_stamp())
                response['ETag'] = res.get_etag()
            response['Date'] = http_date()
        return response

    def doHEAD(self):
        return self.doGET(head=True)

    def doPOST(self):
        return HttpResponseNotAllowed('POST method not allowed')

    def doPUT(self):
        res = self.get_resource(self.request.path)
        if res.isdir():
            return HttpResponseNotAllowed()
        if not res.get_parent().exists():
            return HttpResponseNotFound()
        acl = self.get_access(res.get_abs_path())
        if not acl.write:
            return HttpResponseForbidden()
        created = not res.exists()
        res.write(self.request)
        if created:
            return HttpResponseCreated()
        else:
            return HttpResponseNoContent()

    def doDELETE(self):
        res = self.get_resource(self.request.path)
        if not res.exists():
            return HttpResponseNotFound()
        acl = self.get_access(res.get_abs_path())
        if not acl.delete:
            return HttpResponseForbidden()
        self.locks.del_locks(res)
        self.props.del_props(res)
        res.delete()
        response = HttpResponseNoContent()
        response['Date'] = http_date()
        return response

    def doMKCOL(self):
        res = self.get_resource(self.request.path)
        if res.exists():
            return HttpResponseNotAllowed()
        if not res.get_parent().exists():
            return HttpResponseConflict()
        length = self.request.META.get('CONTENT_LENGTH', 0)
        if length and int(length) != 0:
            return HttpResponseMediatypeNotSupported()
        acl = self.get_access(res.get_abs_path())
        if not acl.create:
            return HttpResponseForbidden()
        res.mkdir()
        return HttpResponseCreated()

    def doCOPY(self, move=False):
        res = self.get_resource(self.request.path)
        if not res.exists():
            return HttpResponseNotFound()
        acl = self.get_access(res.get_abs_path())
        if not acl.relocate:
            return HttpResponseForbidden()
        dst = urllib.unquote(self.request.META.get('HTTP_DESTINATION', ''))
        if not dst:
            return HttpResponseBadRequest('Destination header missing.')
        dparts = urlparse.urlparse(dst)
        # TODO: ensure host and scheme portion matches ours...
        sparts = urlparse.urlparse(self.request.build_absolute_uri())
        if sparts.scheme != dparts.scheme or sparts.netloc != dparts.netloc:
            return HttpResponseBadGateway('Source and destination must have the same scheme and host.')
        # adjust path for our base url:
        dst = self.get_resource(dparts.path[len(self.request.get_base()):])
        if not dst.get_parent().exists():
            return HttpResponseConflict()
        overwrite = self.request.META.get('HTTP_OVERWRITE', 'T')
        if overwrite not in ('T', 'F'):
            return HttpResponseBadRequest('Overwrite header must be T or F.')
        overwrite = (overwrite == 'T')
        if not overwrite and dst.exists():
            return HttpResponsePreconditionFailed('Destination exists and overwrite False.')
        depth = self.get_depth()
        if move and depth != -1:
            return HttpResponseBadRequest()
        if depth not in (0, -1):
            return HttpResponseBadRequest()
        dst_exists = dst.exists()
        if move:
            if dst_exists:
                self.locks.del_locks(dst)
                self.props.del_props(dst)
                dst.delete()
            errors = res.move(dst)
        else:
            errors = res.copy(dst, depth=depth)
        self.props.copy_props(res, dst, move=move)
        if move:
            self.locks.del_locks(res)
        if errors:
            response = HttpResponseMultiStatus()
        elif dst_exists:
            response = HttpResponseNoContent()
        else:
            response = HttpResponseCreated()
        return response

    def doMOVE(self):
        return self.doCOPY(move=True)

    def doLOCK(self):
        return HttpResponseNotImplemented()

    def doUNLOCK(self):
        return HttpResponseNotImplemented()

    def doOPTIONS(self):
        response = HttpResponse(mimetype='text/html')
        response['DAV'] = '1,2'
        response['Date'] = http_date()
        if self.request.path in ('/', '*'):
            return response
        res = self.get_resource(self.request.path)
        if not res.exists():
            res = res.get_parent()
            if not res.isdir():
                return HttpResponseNotFound()
            response['Allow'] = 'OPTIONS PUT MKCOL'
        elif res.isdir():
            response['Allow'] = 'OPTIONS HEAD GET DELETE PROPFIND PROPPATCH COPY MOVE LOCK UNLOCK'
        else:
            response['Allow'] = 'OPTIONS HEAD GET PUT DELETE PROPFIND PROPPATCH COPY MOVE LOCK UNLOCK'
            response['Allow-Ranges'] = 'bytes'
        return response

    def doPROPFIND(self):
        res = self.get_resource(self.request.path)
        if not res.exists():
            return HttpResponseNotFound()
        acl = self.get_access(res.get_abs_path())
        if not acl.listing:
            return HttpResponseForbidden()
        depth = self.get_depth()
        names_only, props = False, []
        length = self.request.META.get('CONTENT_LENGTH', 0)
        if not length or int(length) != 0:
            #Otherwise, empty prop list is treated as request for ALL props.
            for ev, el in ElementTree.iterparse(self.request):
                if el.tag == '{DAV:}allprop':
                    if props:
                        return HttpResponseBadRequest()
                elif el.tag == '{DAV:}propname':
                    names_only = True
                elif el.tag == '{DAV:}prop':
                    if names_only:
                        return HttpResponseBadRequest()
                    for pr in el:
                        props.append(pr.tag)
        msr = ElementTree.Element('{DAV:}multistatus')
        for child in res.get_descendants(depth=depth, include_self=True):
            response = ElementTree.SubElement(msr, '{DAV:}response')
            ElementTree.SubElement(response, '{DAV:}href').text = child.get_url()
            self.props.get_propstat(child, response, *props)
        response = HttpResponseMultiStatus(ElementTree.tostring(msr, 'UTF-8'), mimetype='application/xml')
        response['Date'] = http_date()
        return response

    def doPROPPATCH(self):
        res = self.get_resource(self.request.path)
        if not res.exists():
            return HttpResponseNotFound()
        depth = self.get_depth(default="0")
        if depth != 0:
            return HttpResponseBadRequest('Invalid depth header value %s' % depth)
