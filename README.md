OAI-PMH harvester and server for CKAN. 
This extends CKAN harvester to parse OAI-PMH metadata sources and import datasets. 
Supported metadata schemas are oai_dc (Dublin Core), RDF.

At NINA, we use it uniquely as an OAI-PMH server, for exposing metadata

The list of supported verbs consists of:


* Identify: Displays information about this OAI-PMH server.
    - /oai?verb=Identify
* ListMetadataFormats: List available metadata standards.
    - /oai?verb=ListMetadataFormats
* ListSets: fetches identifiers of sets (in CKAN case: organizations).
    - /oai?verb=ListSets
* ListIdentifiers: fetches individual datasets' identifiers.
    - /oai?verb=ListIdentifiers&metadataPrefix=oai_dc
* ListRecords: List all public datasets
    - /oai?verb=ListRecords&metadataPrefix=oai_dc
* GetRecord: Fetches a single dataset.
    - /oai?verb=GetRecord&identifier=<some-identifier>&metadataPrefix=oai_dc
