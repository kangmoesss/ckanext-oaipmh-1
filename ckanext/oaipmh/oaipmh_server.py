'''OAI-PMH implementation for CKAN datasets and groups.
'''
# pylint: disable=E1101,E1103
import json
import logging

from oaipmh import common
from oaipmh.common import ResumptionOAIPMH
from oaipmh.error import IdDoesNotExistError
import ckan.plugins.toolkit as toolkit
from sqlalchemy import between

from ckan.lib.helpers import url_for
from ckan.logic import get_action
from ckan.model import Package, Session, Group, PackageRevision
from ckanext.dcat.processors import RDFSerializer
from ckanext.kata import helpers
from ckanext.oaipmh.utils import get_earliest_datestamp

log = logging.getLogger(__name__)

rdfserializer = RDFSerializer()


class CKANServer(ResumptionOAIPMH):
    '''A OAI-PMH implementation class for CKAN.
    '''
    def identify(self):
        '''Return identification information for this server.
        '''
        return common.Identify(
            repositoryName=config.get('ckan.site_title', 'repository'),
            baseURL=config.get('ckan.site_url', None) + url_for(controller='ckanext.oaipmh.controller:OAIPMHController', action='index'),
            protocolVersion="2.0",
            adminEmails=['etsin@csc.fi'],
            earliestDatestamp=get_earliest_datestamp(),
            deletedRecord='no',
            granularity='YYYY-MM-DDThh:mm:ssZ',
            compression=['identity'])

    def _get_json_content(self, js):
        '''
        Gets all items from JSON

        :param js: json string
        :return: list of items
        '''

        try:
            json_data = json.loads(js)
            json_titles = list()
            for key, value in json_data.iteritems():
                json_titles.append(value)
            return json_titles
        except:
            return [js]

    def _record_for_dataset_dcat(self, dataset, spec):
        '''Show a tuple of a header and metadata for this dataset.
        Note that dataset_xml (metadata) returned is just a string containing
        ready rdf xml. This is contrary to the common practice of pyoia's
        getRecord method.
        '''
        package = get_action('package_show')({}, {'id': dataset.id})
        dataset_xml = rdfserializer.serialize_dataset(package, _format='xml')
        return (common.Header('', dataset.id, dataset.metadata_created, [spec], False),
                dataset_xml, None)

    def _record_for_dataset(self, dataset, spec):
        '''Show a tuple of a header and metadata for this dataset.
        '''
        package = get_action('package_show')({}, {'id': dataset.id})

        coverage = []
        temporal_begin = package.get('temporal_coverage_begin', '')
        temporal_end = package.get('temporal_coverage_end', '')

        geographic = package.get('geographic_coverage', '')
        if geographic:
            coverage.extend(geographic.split(','))
        if temporal_begin or temporal_end:
            coverage.append("%s/%s" % (temporal_begin, temporal_end))

        pids = [pid.get('id') for pid in package.get('pids', {}) if pid.get('id', False)]
        pids.append(package.get('id'))
        pids.append(config.get('ckan.site_url') + url_for(controller="package", action='read', id=package['name']))

        meta = {'title': self._get_json_content(package.get('title', None) or package.get('name')),
                'creator': [author['name'] for author in helpers.get_authors(package) if 'name' in author],
                'publisher': [agent['name'] for agent in helpers.get_distributors(package) + helpers.get_contacts(package) if 'name' in agent],
                'contributor': [author['name'] for author in helpers.get_contributors(package) if 'name' in author],
                'identifier': pids,
                'type': ['dataset'],
                'language': [l.strip() for l in package.get('language').split(",")] if package.get('language', None) else None,
                'description': self._get_json_content(package.get('notes')) if package.get('notes', None) else None,
                'subject': [tag.get('display_name') for tag in package['tags']] if package.get('tags', None) else None,
                'date': [dataset.metadata_created.strftime('%Y-%m-%d')] if dataset.metadata_created else None,
                'rights': [package['license_title']] if package.get('license_title', None) else None,
                'coverage': coverage if coverage else None, }

        iters = dataset.extras.items()
        meta = dict(iters + meta.items())
        metadata = {}
        # Fixes the bug on having a large dataset being scrambled to individual
        # letters
        for key, value in meta.items():
            if not isinstance(value, list):
                metadata[str(key)] = [value]
            else:
                metadata[str(key)] = value
        return (common.Header('', dataset.id, dataset.metadata_created, [spec], False),
                common.Metadata('', metadata), None)

    @staticmethod
    def _filter_packages(set, cursor, from_, until, batch_size):
        '''Get a part of datasets for "listNN" verbs.
        '''
        packages = []
        group = None
        if not set:
            packages = Session.query(Package).filter(Package.type=='dataset'). \
                filter(Package.state == 'active').filter(Package.private!=True)
            if from_ and not until:
                packages = packages.filter(PackageRevision.revision_timestamp > from_).\
                    filter(Package.name==PackageRevision.name)
            if until and not from_:
                packages = packages.filter(PackageRevision.revision_timestamp < until).\
                    filter(Package.name==PackageRevision.name)
            if from_ and until:
                packages = packages.filter(between(PackageRevision.revision_timestamp, from_, until)).\
                    filter(Package.name==PackageRevision.name)
            packages = packages.all()
        else:
            group = Group.get(set)
            if group:
                # Note that group.packages never returns private datasets regardless of 'with_private' parameter.
                packages = group.packages(return_query=True, with_private=False).filter(Package.type=='dataset'). \
                    filter(Package.state == 'active')
                if from_ and not until:
                    packages = packages.filter(PackageRevision.revision_timestamp > from_).\
                        filter(Package.name==PackageRevision.name)
                if until and not from_:
                    packages = packages.filter(PackageRevision.revision_timestamp < until).\
                        filter(Package.name==PackageRevision.name)
                if from_ and until:
                    packages = packages.filter(between(PackageRevision.revision_timestamp, from_, until)).\
                        filter(Package.name==PackageRevision.name)
                packages = packages.all()
        if cursor is not None:
            cursor_end = cursor + batch_size if cursor + batch_size < len(packages) else len(packages)
            packages = packages[cursor:cursor_end]
        return packages, group

    def getRecord(self, metadataPrefix, identifier):
        '''Simple getRecord for a dataset.
        '''
        package = Package.get(identifier)
        if not package:
            raise IdDoesNotExistError("No dataset with id %s" % identifier)
        spec = package.name
        if package.owner_org:
            group = Group.get(package.owner_org)
            if group and group.name:
                spec = group.name
        if metadataPrefix == 'rdf':
            return self._record_for_dataset_dcat(package, spec)
        return self._record_for_dataset(package, spec)

    def listIdentifiers(self, metadataPrefix=None, set=None, cursor=None,
                        from_=None, until=None, batch_size=None):
        '''List all identifiers for this repository.
        '''
        data = []
        packages, group = self._filter_packages(set, cursor, from_, until, batch_size)
        for package in packages:
            spec = package.name
            if group:
                spec = group.name
            else:
                if package.owner_org:
                    group = Group.get(package.owner_org)
                    if group and group.name:
                        spec = group.name
            data.append(common.Header('', package.id, package.metadata_created, [spec], False))
        return data

    def listMetadataFormats(self, identifier=None):
        '''List available metadata formats.
        '''
        return [('oai_dc',
                'http://www.openarchives.org/OAI/2.0/oai_dc.xsd',
                'http://www.openarchives.org/OAI/2.0/oai_dc/'),
                ('rdf',
                 'http://www.openarchives.org/OAI/2.0/rdf.xsd',
                 'http://www.openarchives.org/OAI/2.0/rdf/')]

    def listRecords(self, metadataPrefix=None, set=None, cursor=None, from_=None,
                    until=None, batch_size=None):
        '''Show a selection of records, basically lists all datasets.
        '''
        data = []
        packages, group = self._filter_packages(set, cursor, from_, until, batch_size)
        for package in packages:
            spec = package.name
            if group:
                spec = group.name
            else:
                if package.owner_org:
                    group = Group.get(package.owner_org)
                    if group and group.name:
                        spec = group.name
            if metadataPrefix == 'rdf':
                data.append(self._record_for_dataset_dcat(package, spec))
            else:
                data.append(self._record_for_dataset(package, spec))
        return data

    def listSets(self, cursor=None, batch_size=None):
        '''List all sets in this repository, where sets are groups.
        '''
        data = []
        groups = Session.query(Group).filter(Group.state == 'active')
        if cursor is not None:
            cursor_end = cursor+batch_size if cursor+batch_size < groups.count() else groups.count()
            groups = groups[cursor:cursor_end]
        for dataset in groups:
            data.append((dataset.name, dataset.title, dataset.description))
        return data
