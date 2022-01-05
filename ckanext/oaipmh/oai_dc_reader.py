# coding=utf-8
import logging
from re import unicode
import re 
from itertools import tee, chain

import bs4
import lxml.etree
import pointfree as pf
from fn.uniform import zip, filter, filterfalse
from first import first
import json

from iso639 import languages

from oaipmh import common as oc
from ckanext.oaipmh import importcore

from urllib.parse import urlparse

xml_reader = importcore.generic_xml_metadata_reader
log = logging.getLogger(__name__)

NS = {
    'dct': 'http://purl.org/dc/terms/',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'cscida': "http://etsin.avointiede.fi/cscida/",
}

# TODO: Change this file to class structure to allow harvester to set values also with OAI-PMH verb 'Identify'.

def convert_language(lang):
    '''
    Convert alpha2 language (eg. 'en') to terminology language (eg. 'eng')
    '''

    if not lang:
        return "und"

    try:
        lang_object = languages.get(part1=lang)
        return lang_object.terminology
    except KeyError as ke:
        try:
            lang_object = languages.get(part2b=lang)
            return lang_object.terminology
        except KeyError as ke:
            return ''

def label_list_yso(tag_url):
    """
    Takes tag keyword URL and fetches the labels that link to it.
    :returns: the labels
    """

    _tagspaces = {
        'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
        'yso-meta': 'http://www.yso.fi/onto/yso-meta/2007-03-02/',
        'rdfs': "http://www.w3.org/2000/01/rdf-schema#",
        'ysa': "http://www.yso.fi/onto/ysa/",
        'skos': "http://www.w3.org/2004/02/skos/core#",
        'om': "http://www.yso.fi/onto/yso-peilaus/2007-03-02/",
        'dc': "http://purl.org/dc/elements/1.1/",
        'allars': "http://www.yso.fi/onto/allars/",
        'daml': "http://www.daml.org/2001/03/daml+oil#",
        'yso-kehitys': "http://www.yso.fi/onto/yso-kehitys/",
        'owl': "http://www.w3.org/2002/07/owl#",
        'xsd': "http://www.w3.org/2001/XMLSchema#",
        'yso': "http://www.yso.fi/onto/yso/",
    }

    labels = []
    if not tag_url.endswith("?rdf=xml"):
        tag_url += "?rdf=xml" # Small necessary bit.
    request = urllib2.Request(tag_url, headers={"Accept": "application/rdf+xml"})
    try:
        contents = urllib2.urlopen(request).read()
    except (socket.error, urllib2.HTTPError, urllib2.URLError,):
        log.debug("Failed to read tag XML.")
        return []
    try:
        xml = etree.XML(contents)
    except etree.XMLSyntaxError:
        log.debug("Tag XMl syntax error.")
        return []
    for descr in xml.xpath('/rdf:RDF/rdf:Description', namespaces=_tagspaces):
        for tag in ('yso-meta:prefLabel', 'rdfs:label', 'yso-meta:altLabel',):
            nodes = descr.xpath('./%s' % tag, namespaces=_tagspaces)
            for node in nodes:
                text = node.text.strip() if node.text else ''
                if text:
                    labels.append(text)

    for node in xml.xpath('/rdf:RDF/skos:Concept/skos:prefLabel', namespaces=_tagspaces):
        text = node.text.strip() if node.text else None
        if text:
            labels.append(text)

    return labels

def generate_pid():
    """
    Generate a permanent Kata identifier
    """
    import datetime
    return "urn:nbn:fi:csc-kata%s" % datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")


def dc_metadata_reader(harvest_type):
    """ Get correct reader for given harvest_type. Currently supports 'ida' or 'default'. """
    def method(xml):
        reader_class = {u'ida': IdaDcMetadataReader}.get(unicode(harvest_type).lower(), DefaultDcMetadataReader)
        reader = reader_class(xml)
        return reader.read()
    return method

def pid_to_name(string):
    '''
    Wrap re.sub to convert a PID to package.name.
    '''
    if string:
        return re.sub(*settings.PID_TO_NAME_REGEXES, string=string)

class DcMetadataReader():
    def __init__(self, xml):
        """ Create new instanse from given XML element. """
        self.xml = xml
        self.bs = bs4.BeautifulSoup(lxml.etree.tostring(self.xml), 'xml')
        self.dc = self.bs.metadata.dc

    def read(self):
        """ Parse metadata and return metadata (oaipmh.common.Metadata) with unified dictionty. """
        unified = self._read()
        result = xml_reader(self.xml).getMap()
        result['unified'] = unified
        return oc.Metadata(self.xml, result)

    def _skip_note(self, note):
        return False

    def _read_notes(self):

        desc = '\r\n\r\n'.join(sorted([a.string for a in self.dc(_filter_tag_name_namespace('description', NS['dc']),
                                                                 recursive=False) if not self._skip_note(a.string)])) or ''

        return json.dumps({ "und" : desc })

    def _get_maintainer_stuff(self):
        for a in self.dc(_filter_tag_name_namespace(name='publisher', namespace=NS['dct']), recursive=False):
            for b in a(recursive=False):
                n = b.find('name').string if b.find('name') else ''
                m = b.mbox.get('resource', '') if b.mbox else ''
                p = b.phone.get('resource', '') if b.phone else ''
                h = b.get('about', '')
                yield n, m, p, h

    def _get_availability(self):
        """ Get fallback availability. """
        return ['contact_owner']

    def _get_uploader(self):
        return ''

    def _get_version_pids(self):
        """ Get version pid. By default does not return any data. """
        return []

    def _resolve_tags(self, tag):
        try:
            if urlparse(tag).scheme in ('http', 'https'):
                resolved = label_list_yso(tag)
                if resolved:
                    return resolved
        except:
            pass
        return [tag]

    def _get_mime_type(self):
        return first([a.string for a in self.dc('format', text=re.compile('/'), recursive=False)]) or ''

    def _read(self):
        project_funder, project_funding, project_name, project_homepage = _get_project_stuff(self.dc) or ('', '', '', '')

        # Todo! This needs to be improved to use also simple-dc
        # dc(filter_tag_name_namespace('publisher', ns['dc']), recursive=False)
        availability, license_id, license_url, access_application_url = _get_rights(self.dc) or ('', '', '', '')
        if not availability:
            availability = first(self._get_availability())

        uploader = self._get_uploader()

        data_pids = list(_get_data_pids(self.dc))

        tags = []
        #for tag in sorted([a.string for a in self.dc('subject', recursive=False)]):
        #    tags.extend(self._resolve_tags(tag))
        tags = [a.string for a in self.dc('subject', recursive=False)]

        transl_json = {}
        for title in self.dc('title', recursive=False):
            lang = utils.convert_language(title.get('xml:lang', '').strip())
            transl_json[lang] = title.string.strip()

        title = json.dumps(transl_json)

        def _get_primary_pid(data_pids):
            for dpid in data_pids:
                if dpid.startswith('urn:nbn:fi:csc-ida'):
                    data_pids.remove(dpid)
                    return [dpid]
            return []

        # Create a unified internal harvester format dict
        unified = dict(
            # ?=dc('source', recursive=False),
            # ?=dc('relation', recursive=False),
            # ?=dc('type', recursive=False),

            access_application_URL=access_application_url or '',

            # Todo! Implement
            access_request_URL='',

            algorithm=first(_get_algorithm(self.dc)) or '',

            # TODO: Handle availabilities better
            availability=availability,

            checksum=_get_checksum(self.dc) or '',

            direct_download_URL=first(_get_download(self.dc)) or '',

            # Todo! Implement
            discipline='',

            # Todo! Should be possible to implement with QDC, but not with OAI_DC
            # evdescr=[],
            # evtype=[],
            # evwhen=[],
            # evwho=[],

            # Todo! Implement
            geographic_coverage='',

            #langtitle=[dict(lang=a.get('xml:lang', ''), value=a.string) for a in self.dc('title', recursive=False)],

            title=title,

            language=','.join(sorted([a.string for a in self.dc('language', recursive=False)])),

            license_URL=license_url or '',
            license_id=license_id or 'notspecified',

            # Todo! Using only the first entry, for now
            contact=[dict(name=name or "", email=email or "", URL=url or "", phone=phone or "")
                     for name, email, phone, url in self._get_maintainer_stuff()],

            # Todo! IDA currently doesn't produce this, maybe in future
            # dc('hasFormat', recursive=False)
            mimetype=self._get_mime_type(),

            notes=self._read_notes(),

            # Todo! Using only the first entry, for now
            # owner=first([a.get('resource') for a in dc('rightsHolder', recursive=False)]) or '',

            pids=[dict(id=pid, provider=_get_provider(self.bs), type=u'primary') for pid in _get_primary_pid(data_pids)] +
                 [dict(id=pid, provider=_get_provider(self.bs), type=u'relation', relation=u'generalRelation') for pid in data_pids] +
                 [dict(id=pid, provider=_get_provider(self.bs), type=u'relation', relation=u'generalRelation') for pid in self._get_version_pids()] +
                 [dict(id=pid, provider=_get_provider(self.bs), type=u'relation', relation=u'generalRelation') for pid in _get_metadata_pid(self.dc)],

            agent=[dict(role='author', name=orgauth.get('value', ''), id='', organisation=orgauth.get('org', ''), URL='', fundingid='') for orgauth in _get_org_auth(self.dc)] +
                  [dict(role='contributor', name=contributor.get('value', ''), id='', organisation=contributor.get('org', ''), URL='', fundingid='') for contributor in _get_contributor(self.dc)] +
                  [dict(role='funder', name=first(project_name) or '', id=first(project_name) or '', organisation=first(project_funder) or "", URL=first(project_homepage) or '', fundingid=first(project_funding) or '',)] +
                  [dict(role='owner', name=first([a.get('resource') for a in self.dc('rightsHolder', recursive=False)]) or first(_get_rightsholder(self.dc)) or '', id='', organisation='', URL='', fundingid='')],

            tag_string=','.join(tags) or '',

            # Todo! Implement if possible
            temporal_coverage_begin='',
            temporal_coverage_end='',

            type='dataset',
            uploader=uploader,

            # Used in smear harvest code to extract variable, station and year values, but is not used when
            # creating the dataset via API.
            smear_url=first(_get_download(self.dc, False)) or '',

            # Todo! This should be more exactly picked
            version=(self.dc.modified or self.dc.date).string if (self.dc.modified or self.dc.date) else '',
            # version=dc(
            #     partial(filter_tag_name_namespace, 'modified', ns['dct']), recursive=False)[0].string or dc(
            #         partial(filter_tag_name_namespace, 'date', ns['dc']), recursive=False)[0].string,

        )
        if not unified['language']:
            unified['langdis'] = 'True'

        # Create id and name
        unified['id'] = generate_pid()
        unified['name'] = pid_to_name(unified['id'])

        # If primary pid is missing, set package id as primary pid
        if not any(pid.get('type', None) == u'primary' for pid in unified['pids']):
            unified['pids'].append(dict(id=unified['id'], type=u'primary', provider=None))

        # if not unified['project_name']:
        #    unified['projdis'] = 'True'
        return unified


class IdaDcMetadataReader(DcMetadataReader):
    def _skip_note(self, note):
        """ Skip directo_download descriptions """
        return not note or u'direct_download' in unicode(note)

    def _get_maintainer_stuff(self):
        """ IDA does not provide valid url for maintainer. Instead it might gives something like 'person'. This omits the URL data. """
        for name, email, phone, _url in DcMetadataReader._get_maintainer_stuff(self):
            yield name, email, phone, ''

    def _get_description_parameters(self):
        """ Get parameters from description tags. Format is 'key: value'.
            If key parameter is given then filter results by that key.
        """
        for description in self.dc(_filter_tag_name_namespace('description', NS['dc']), recursive=False):
            description = description.string.strip()
            split = re.split(r'\s*:\s*', description, 1)
            if len(split) == 2:
                yield split

    def _get_description_values(self, key):
        for description_key, value in self._get_description_parameters():
            if key == description_key:
                yield value

    def _get_description_value(self, key):
        return first(self._get_description_values(key))

    def _get_availability(self):
        """ Get availibility from description tags """
        availability = first(self.dc(_filter_tag_name_namespace(name='availability', namespace=NS['cscida']), recursive=False))
        if availability:
            return [availability.string.strip()]

        return self._get_description_values('availability')

    def _get_uploader(self):
        '''
        Get uploader from cscida tags
        :return
        '''
        uploader = first(self.dc(_filter_tag_name_namespace(name='uploader', namespace=NS['cscida']), recursive=False))
        if uploader:
            return uploader.string.strip()

        return ''

    def _get_version_pids(self):
        '''
        Get version PID (Indetifier.version) from data.

        '''
        versions = self.dc(_filter_tag_name_namespace(name='Identifier.version', namespace=NS['cscida']), recursive=False)
        if versions:
            result = []
            for version in versions:
                result.append(version.string.strip())
            return result

        return self._get_description_values('Identifier.version')

    def _get_mime_type(self):
        '''
        Get general.mime_type from data

        '''
        mime_type = first(self.dc(_filter_tag_name_namespace(name='general.mime_type', namespace=NS['cscida']), recursive=False))
        if mime_type:
            return mime_type.string.strip()

        return self._get_description_value('general.mime_type')


class DefaultDcMetadataReader(DcMetadataReader):
    pass


@pf.partial
def _filter_tag_name_namespace(name, namespace, tag):
    '''
    Boolean filter function, for BeautifulSoup find functions, that checks tag's name and namespace
    '''
    return tag.name == name and tag.namespace == namespace


def _get_project_stuff(tag_tree):
    '''
    Get project_funder, project_funding, project_name, project_homepage

    :param tag_tree: metadata (dc) element in BeautifulSoup tree
    '''
    def ida():
        for a in tag_tree(_filter_tag_name_namespace(name='contributor', namespace=NS['dct']), recursive=False):
            if a.Project:
                funder_funding = a.Project.comment.string.split(u' rahoituspäätös ') if a.Project.comment else ('', '')
                name = a.Project.find('name').string if a.Project.find('name') else ''
                about = a.Project.get('about', '')
                yield tuple(funder_funding) + (name,) + (about,)

    return zip(*ida()) if first(ida()) else None


def _get_data_pids(tag_tree):
    '''
    Returns an iterator over data PIDs from metadata
    '''
    def pids(t):
        '''
        Get data 'PIDs' from OAI-DC and IDA
        '''
        for p in t('identifier', recursive=False):
            yield p.string

    pids1, pids2 = tee(pids(tag_tree), 2)
    pred = lambda x: re.search('urn', x, flags=re.I)
    return chain(filter(pred, pids1), filterfalse(pred, pids2))


def _get_metadata_pid(tag_tree):
    '''
    Returns a metadata PID from response header
    '''
    try:
        return tag_tree.header.identifier.contents
    except AttributeError:
        return []


def _get_checksum(tag_tree):
    '''
    Get checksum of data file
    '''
    try:
        return tag_tree.hasFormat.File.checksum.Checksum.checksumValue.string
    except Exception:
        log.info('Checksum missing from dataset!')


def _get_download(tag_tree, avaa=True):
    # @ExceptReturn(exception=Exception, returns=None)
    def ida():
        try:
            if not avaa:
                yield tag_tree.hasFormat.File.get('about')
            ida_id = tag_tree.identifier
            if ida_id.string and ida_id.string.startswith('urn:nbn:fi:csc-ida'):
                yield 'https://avaa.tdata.fi/openida/dl.jsp?pid=' + ida_id.string
        except Exception:
            pass

    # @ExceptReturn(Exception, None)
    def helda():
        for pid in _get_data_pids(tag_tree):
            if pid.startswith('http'):
                yield pid

    return chain(ida(), helda())


def _get_org_auth(tag_tree):
    '''
    Returns an iterator over organization-author dicts from metadata
    '''
    def oai_dc():
        '''
        Get 'author' and 'organization' information from OAI-DC
        '''
        for c in tag_tree(_filter_tag_name_namespace(name='creator', namespace=NS['dc']), recursive=False):
            yield {'org': '', 'value': c.string}


    def ida():
        '''
        Get 'author' and 'organization' information from IDA
        '''
        for c in tag_tree(_filter_tag_name_namespace(name='contributor', namespace=NS['dct']), recursive=False):
            # Todo! Simplify this!
            if c.Person and c.Organization:
                yield {'org': c.Organization.find('name').string, 'value': c.Person.find('name').string}
            elif c.Person:
                yield {'org': '', 'value': c.Person.find('name').string}
            elif c.Organization:
                yield {'org': c.Organization.find('name').string, 'value': ''}

    return ida() if first(ida()) else oai_dc()


def _get_contributor(tag_tree):
    def oai_dc():
        for c in tag_tree(_filter_tag_name_namespace(name='contributor', namespace=NS['dc']), recursive=False):
            yield {'org': '', 'value': c.string}

    return oai_dc()


def _get_rightsholder(tag_tree):
    def ida():
        for c in tag_tree(_filter_tag_name_namespace(name='rightsHolder', namespace=NS['dct']), recursive=False):
            yield c.get('resource')

    return ida()


def _get_algorithm(tag_tree):
    # @ExceptReturn(exception=Exception, passes=True)
    def ida():
        try:
            yield tag_tree.hasFormat.File.checksum.Checksum.generator.Algorithm.get('about').split('/')[-1]
        except Exception:
            pass

    return ida()


def _get_rights(tag_tree):
    '''
    Returns a bunch of rights information (availability, license-id, license-url, access-application-url)
    '''
    def ida():
        '''
        Get rights information from IDA
        '''
        try:
            decl = tag_tree.find(_filter_tag_name_namespace(name='rights', namespace=NS['dct'])).RightsDeclaration.string
            cat = tag_tree.find(_filter_tag_name_namespace(name='rights', namespace=NS['dct'])).RightsDeclaration.get('RIGHTSCATEGORY')
            avail = lid = lurl = aaurl = None
            if cat == 'COPYRIGHTED':
                avail = 'contact_owner'
                lid = 'notspecified'
            elif cat == 'LICENSED':
                avail = 'direct_download'
                lid = 'notspecified'
                lurl = decl
            elif cat == 'CONTRACTUAL':
                avail = 'access_application_other'
                lid = 'notspecified'
                aaurl = decl
            elif cat == 'PUBLIC DOMAIN':
                avail = 'direct_download'
                lid = 'other-pd'
            elif cat == 'OTHER':
                avail = 'direct_download'
                lid = 'other-open'
                lurl = decl
            else:
                return None
            return avail, lid, lurl, aaurl
        except AttributeError as e:
            log.info('IDA rights not detected. Probably not harvesting IDA. {e}'.format(e=e))

    def oai_dc():
        '''
        Get rights information from OAI-DC
        '''
        try:
            return '', '', tag_tree.find(_filter_tag_name_namespace(name='rights', namespace=NS['dc'])).string, ''
        except AttributeError as e:
            log.info('OAI_DC rights not detected. Probably just missing. {e}'.format(e=e))

    return ida() or oai_dc()


def _get_provider(tag_tree):
    '''
    Get metadata provider

    TODO: Take these from request identifier directly in fetch_stage.
    '''
    provider = None
    try:
        for ident in tag_tree('identifier', recursive=True):
            if u'helda.helsinki.fi' in unicode(ident.contents[0]):
                provider = u'http://helda.helsinki.fi/oai/request'
                break
    except AttributeError:
        pass

    if not provider:
        try:
            for ident in tag_tree('identifier', recursive=True):
                if unicode(ident.contents[0]).startswith(u'urn:nbn:fi:csc-ida'):
                    provider = 'ida'
                    break

        except AttributeError:
            pass

    return provider if provider else 'unknown'
