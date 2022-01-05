import http.client 
import json
import logging
import urllib.request,urllib.parse,urllib.error
from lxml import etree
import oaipmh

from ckanext.oaipmh import importformats
from ckanext.oaipmh.cmdi_reader import CmdiReader
from ckanext.oaipmh.harvester import OAIPMHHarvester
import ckan.plugins.toolkit as toolkit

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

class CMDIHarvester(OAIPMHHarvester):
    md_format = 'cmdi0571'
    client = None  # used for testing

    def info(self):
        ''' See ;meth:`ckanext.harvest.harvesters.base.HarvesterBase.info`. '''

        return {
            'name': 'cmdi',
            'title': 'OAI-PMH CMDI',
            'description': 'Harvests CMDI dataset'
        }

    #def get_schema(self, config, pkg):
        #from ckanext.kata.plugin import KataPlugin
        #return KataPlugin.create_package_schema_oai_cmdi()

    def on_deleted(self, harvest_object, header):
        """ See :meth:`OAIPMHHarvester.on_deleted`
            Mark package for deletion.
        """
        package_id = get_package_id_by_pid(header.identifier(), 'primary')
        if package_id:
            harvest_object.package_id = package_id
        harvest_object.content = None
        harvest_object.report_status = "deleted"
        harvest_object.save()
        return True

    def gather_stage(self, harvest_job):
        """ See :meth:`OAIPMHHarvester.gather_stage`  """
        config = self._get_configuration(harvest_job)
        if not config.get('type'):
            config['type'] = 'cmdi'
            harvest_job.source.config = json.dumps(config)
            harvest_job.source.save()
        registry = self.metadata_registry(config, harvest_job)
        client = self.client or oaipmh.client.Client(harvest_job.source.url, registry)
        return self.populate_harvest_job(harvest_job, None, config, client)

    def parse_xml(self, f, context, orig_url=None, strict=True):
        return CmdiReader().read_data(etree.fromstring(f))
