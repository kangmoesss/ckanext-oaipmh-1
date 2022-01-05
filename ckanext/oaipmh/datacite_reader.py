# coding: utf-8

import datetime
import oaipmh.common

from ckanext.oaipmh.importcore import generic_xml_metadata_reader
from lxml import etree

from ckan.plugins.toolkit import config
import ckan.plugins.toolkit as toolkit

# for debug
import logging
log = logging.getLogger(__name__)


def get_package_id_by_pid(pid, pid_type):
    """ Find pid by id and type.
    :param pid: id of the pid
    :param pid_type: type of the pid (primary, relation)
    :return: id of the package
    """
    query = select(['key', 'package_id']).where(and_(model.PackageExtra.value == pid, model.PackageExtra.key.like('pids_%_id'),
                                                     model.PackageExtra.state == 'active'))

    for key, package_id in [('pids_%s_type' % key.split('_')[1], package_id) for key, package_id in Session.execute(query)]:
        query = select(['package_id']).where(and_(model.PackageExtra.value == pid_type, model.PackageExtra.key == key,
                                                  model.PackageExtra.state == 'active', model.PackageExtra.package_id == package_id))
        for package_id, in Session.execute(query):
            return package_id

    return None

def get_unique_package_id():
    '''
    Create new package id by generating a new one. Check that the generated id does not exist already.
    This method should always return a previously unexisting package id. If this method returns None,
    then something is wrong.
    '''

    new_id_exists = True
    i=0
    while new_id_exists and i < 10:
        new_id = unicode(generate_pid())
        existing_id_query = model.Session.query(model.Package)\
                        .filter(model.Package.id == new_id)
        if existing_id_query.first():
            i += 1
            continue
        return new_id
    return None

class DataCiteReader(object):
    """ Reader for DataCite XML data """


    def __init__(self, provider=None):
        """ Generate new reader instance.
        :param provider: URL used for pids.
        """
        super(DataCiteReader, self).__init__()
        self.provider = provider or config.get('ckan.site_url')

    def __call__(self, xml):
        """ Call :meth:`DataCiteReader.read`. """
        return self.read(xml)


    def read(self, xml):
        """ Extract package data from given XML.
        :param xml: xml element (lxml)
        :return: oaipmh.common.Metadata object generated from xml
        """
        result = generic_xml_metadata_reader(xml).getMap()
        result['unified'] = self.read_data(xml)
        return oaipmh.common.Metadata(xml, result)


    def read_data(self, xml):
        """ Extract package data from given XML.
        :param xml: xml element (lxml)
        :return: dictionary
        """

        # MAP DATACITE MANDATORY FIELD

        # Identifier to primary pid
        identifier = xml.find('.//{http://datacite.org/schema/kernel-3}identifier')
        pids = [{
            'id': identifier.text, 
            'type': 'primary', 
            'provider': identifier.get('identifierType')}]

        # Creator name to agent
        # TODO: map nameIdentifier to agent.id and nameIdentifierScheme and schemeURI 
        # to extras
        agents = []
        for creator in xml.findall('.//{http://datacite.org/schema/kernel-3}creator'):
            creatorName = creator.find('.//{http://datacite.org/schema/kernel-3}creatorName').text
            creatorAffiliation = creator.find('.//{http://datacite.org/schema/kernel-3}affiliation').text
            agents.append({
                'role': u'author', 
                'name': creatorName, 
                'organisation': creatorAffiliation
                })

        # Primary title to title
        # TODO: if titleType is present, check to find out if title is actually primary
        # TODO: map non-primary titles to extras
        title = xml.find('.//{http://datacite.org/schema/kernel-3}title').text
        langtitle = [{'lang': 'en', 'value': title}] # Assuming we always harvest English

        # Publisher to contact
        publisher = xml.find('.//{http://datacite.org/schema/kernel-3}publisher').text
        contacts = [{'name': publisher}]

        # Publication year to event
        publication_year = xml.find('.//{http://datacite.org/schema/kernel-3}publicationYear').text
        events = [{'type': u'published', 'when': publication_year, 'who': publisher, 'descr': u'Dataset was published'}]


        # MAP DATACITE RECOMMENDED FIELDS

        # Subject to tags
        # TODO: map subjectsScheme and schemeURI to extras

        # Contributor to agent
        # TODO: map nameIdentifier to agent.id, nameIdentifierScheme, schemeURI and 
        # contributorType to extras
        for contributor in xml.findall('.//{http://datacite.org/schema/kernel-3}contributor'):
            contributorName = contributor.find('.//{http://datacite.org/schema/kernel-3}contributorName').text
            contributorAffiliation = contributor.find('.//{http://datacite.org/schema/kernel-3}affiliation').text
            agents.append({
                'role': u'contributor', 
                'name': contributorName, 
                'organisation': contributorAffiliation
                })

        # Date to event
        for date in xml.findall('.//{http://datacite.org/schema/kernel-3}date'):
            events.append({
              'type': date.get('dateType'),
              'when': date.text,
              'who': u'unknown',
              'descr': date.get('dateType'),
              })

        # ResourceType to extra
        # TODO: map resourceType and resourceTypeGeneral to extras

        # RelatedIdentifier to showcase
        # TODO: map RelatedIdentifier to showcase title, relatedIdentifierType, relationType, 
        # relatedMetadataScheme, schemeURI and schemeType to showcase description

        # Description to langnotes
        description = ''
        for element in xml.findall('.//{http://datacite.org/schema/kernel-3}description'):
            description += element.get('descriptionType') + ': ' + element.text + ' '
        langnotes = [{
          'lang': 'en', # Assuming we always harvest English
          'value': description,
          }]

        # GeoLocation to geograhic_coverage
        # TODO: map geoLocationPoint and geoLocationBox to extras, geoLocationPlace to 
        # geographic_coverage


        # MAP DATACITE OPTIONAL FIELDS

        # Language to language
        # TODO: map language to language

        # AlternateIdentifier to pids
        # TODO: map AlternateIdentifier to pids.id, alternateIdentifierType to pids.provider

        # Size to extra
        # TODO: map size to extra

        # Format to resources
        # TODO: map format to resources.format

        # Version to extra
        # DataCite version is a string such as 'v3.2.1' and can't be used as Etsin version
        # TODO: map version to extra

        # Rights to license
        license_URL = ''
        for right in xml.findall('.//{http://datacite.org/schema/kernel-3}rights'):
            license_URL += right.text + ' ' + right.get('rightsURI') + ' '


        # OTHER - REQUIRED BY CKANEXT-HARVEST

        # Get or create package id
        existing_package_id = get_package_id_by_pid(identifier.text, u'primary')
        package_id = existing_package_id if existing_package_id else get_unique_package_id()

        result = {
                  'agent': agents,
                  'contact': contacts,
                  'event': events,
                  'id': package_id,
                  'langnotes': langnotes,
                  'langtitle': langtitle,
                  'license_URL': license_URL,
                  'pids': pids,
                  'title': title,
                  'type': 'dataset',
                  'version': datetime.datetime.now().strftime("%Y-%m-%d")
                  }


        return result
