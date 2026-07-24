from __future__ import annotations
import json
import socket
from pathlib import Path
from urllib.error import HTTPError
import pytest
from domain.evidence import normalize_records
from infrastructure.literature import FixtureTransport, HttpTransport, LiteratureClient, ProviderUnavailable

RAW={'title':'  A Study  ','authors':['Doe, J.'],'year':'2024','doi':'https://doi.org/10.1000/ABC','url':'https://example.test/a'}
def test_offline_fixture_normalizes_and_replays_cache(tmp_path:Path)->None:
 transport=FixtureTransport({'openalex':[RAW]}); client=LiteratureClient(transport,tmp_path)
 first=client.search('openalex','study'); second=client.search('openalex','study')
 assert first[0].doi=='10.1000/abc' and first[0].title=='A Study' and transport.calls==1 and second[0].query_snapshot=='study'
def test_network_failure_does_not_fabricate_a_source(tmp_path:Path)->None:
 with pytest.raises(ProviderUnavailable): LiteratureClient(FixtureTransport({}),tmp_path).search('crossref','missing')
def test_doi_and_title_author_year_deduplication(tmp_path:Path)->None:
 transport=FixtureTransport({'openalex':[RAW],'crossref':[dict(RAW,doi='10.1000/abc')],'datacite':[],'arxiv':[],'semantic_scholar':[]})
 records=LiteratureClient(transport,tmp_path).search_all('study')
 assert len(records)==1 and records[0].provider=='openalex'
def test_unknown_provider_is_rejected(tmp_path:Path)->None:
 with pytest.raises(ValueError): LiteratureClient(FixtureTransport({}),tmp_path).search('invented','q')

@pytest.mark.parametrize('failure',[HTTPError('https://example.test',429,'rate limited',{},None),HTTPError('https://example.test',503,'unavailable',{},None),socket.timeout('timed out')])
def test_http_failures_retry_then_report_unavailable(failure)->None:
 calls=[]
 def opener(request,timeout):
  calls.append((request.full_url,timeout));raise failure
 transport=HttpTransport(retries=2,backoff_seconds=0,opener=opener)
 with pytest.raises(ProviderUnavailable,match='after 3 attempts'):
  transport.get_json('openalex','fault injection',.01)
 assert len(calls)==3

def test_exact_query_offline_replay_after_timeout(tmp_path:Path)->None:
 query='verified replay query';records=[RAW]
 digest=__import__('hashlib').sha256(json.dumps(records,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
 tmp_path.mkdir(parents=True,exist_ok=True)
 (tmp_path/f'openalex-{digest}.json').write_text(json.dumps({'provider':'openalex','query':query,'content_sha256':digest,'records':records}),encoding='utf-8')
 class TimeoutTransport:
  def get_json(self,provider,requested,timeout_seconds):raise TimeoutError('offline')
 replayed=LiteratureClient(TimeoutTransport(),tmp_path).search('openalex',query)
 assert replayed[0].doi=='10.1000/abc' and replayed[0].query_snapshot==query

def test_tampered_replay_is_quarantined_and_never_returns_success(tmp_path:Path)->None:
 query='tampered replay';cache=LiteratureClient(FixtureTransport({}),tmp_path)._cache_file('openalex',query)
 cache.parent.mkdir(parents=True,exist_ok=True)
 cache.write_text(json.dumps({'provider':'openalex','query':query,'content_sha256':'0'*64,'records':[RAW]}),encoding='utf-8')
 with pytest.raises(ProviderUnavailable,match='no verified offline replay'):
  LiteratureClient(FixtureTransport({}),tmp_path).search('openalex',query)
 assert cache.with_suffix(cache.suffix+'.invalid').exists()
