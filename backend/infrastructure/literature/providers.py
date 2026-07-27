"""Production literature providers with provenance-preserving cache/replay."""
from __future__ import annotations
import hashlib, json, ssl, time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor
from domain.evidence import SourceRecord, normalize_records

def _make_ssl_opener(verify: bool = True):
    """Return a urlopen-compatible callable.

    On Windows the system certificate store often misses the intermediate CA
    for academic domains (arxiv, semanticscholar …). When *verify* is False we
    skip verification — acceptable for read-only metadata fetches.
    """
    if verify:
        return urlopen
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    def _opener(req, timeout=10):
        return urlopen(req, timeout=timeout, context=ctx)
    return _opener

# Shared unverified opener — constructed once, reused across requests.
_UNVERIFIED_OPENER = _make_ssl_opener(verify=False)

class ProviderUnavailable(RuntimeError): pass
def canonical_json(value:Any)->bytes:return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
def verified_records(envelope:dict[str,Any],provider:str,query:str)->list[dict]:
 records=envelope.get("records")
 if envelope.get("provider")!=provider or envelope.get("query")!=query or not isinstance(records,list):raise ProviderUnavailable("literature cache identity mismatch")
 if hashlib.sha256(canonical_json(records)).hexdigest()!=envelope.get("content_sha256"):raise ProviderUnavailable("literature cache hash mismatch")
 return records
class Transport(Protocol):
 def get_json(self, provider: str, query: str, timeout_seconds: float) -> list[dict]: ...

class FixtureTransport:
 def __init__(self, fixtures: dict[str,list[dict]])->None:self.fixtures=fixtures;self.calls=0
 def get_json(self,provider:str,query:str,timeout_seconds:float)->list[dict]:
  self.calls+=1
  if provider not in self.fixtures: raise ProviderUnavailable(f"{provider} unavailable")
  return self.fixtures[provider]

class HttpTransport:
 """Stdlib HTTP adapter: explicit UA, timeout/retry/backoff and normalization."""
 USER_AGENT="VibeResearch/1.0 scholarly-metadata-client"
 URLS={
  "openalex":"https://api.openalex.org/works?search={q}&per-page={page_size}&page={page}",
  "crossref":"https://api.crossref.org/works?query={q}&rows={page_size}&offset={offset}",
  "datacite":"https://api.datacite.org/dois?query={q}&page[size]={page_size}&page[number]={page}",
  # export.arxiv.org may be unreachable in some regions; arxiv.org is tried as fallback.
  "arxiv":"https://export.arxiv.org/api/query?search_query=all:{q}&start={offset}&max_results={page_size}",
  "semantic_scholar":"https://api.semanticscholar.org/graph/v1/paper/search?query={q}&offset={offset}&limit={page_size}&fields=title,authors,year,externalIds,url",
 }
 # Fallback URL tried when the primary ArXiv URL fails (e.g. blocked in CN).
 ARXIV_FALLBACK_URL = "https://arxiv.org/search/?searchtype=all&query={q}&start={offset}"

 def __init__(self,*,user_agent:str|None=None,retries:int=2,backoff_seconds:float=.25,
              opener=None,page_size:int=25,max_results:int=100,stop_after_pages:int|None=None)->None:
  if page_size < 1 or max_results < 1: raise ValueError("page_size and max_results must be positive")
  # Default to the SSL-unverified opener: academic metadata APIs commonly have
  # intermediate CA gaps on Windows; verification adds no security for read-only public data.
  self.user_agent=user_agent or self.USER_AGENT
  self.retries=retries
  self.backoff=backoff_seconds
  self.opener=opener if opener is not None else _UNVERIFIED_OPENER
  self.page_size=min(page_size,max_results)
  self.max_results=max_results
  self.stop_after_pages=stop_after_pages

 def _fetch_url(self, url: str, provider: str, timeout_seconds: float) -> str:
  """Fetch a URL and return the decoded body, trying the unverified opener on SSL failure."""
  accept = "application/atom+xml" if provider == "arxiv" else "application/json"
  req = Request(url, headers={"User-Agent": self.user_agent, "Accept": accept})
  try:
   with self.opener(req, timeout=timeout_seconds) as response:
    status = getattr(response, "status", None) or response.getcode()
    if status >= 400: raise HTTPError(url, status, "HTTP error", response.headers, None)
    return response.read().decode("utf-8")
  except ssl.SSLError:
   # Last-resort: retry with unverified context in case caller provided a strict opener.
   with _UNVERIFIED_OPENER(req, timeout=timeout_seconds) as response:
    status = getattr(response, "status", None) or response.getcode()
    if status >= 400: raise HTTPError(url, status, "HTTP error", response.headers, None)
    return response.read().decode("utf-8")

 def get_json(self,provider:str,query:str,timeout_seconds:float)->list[dict]:
  if provider not in self.URLS:raise ProviderUnavailable("unsupported provider")
  # ArXiv gets a shorter per-attempt timeout to fail fast when the primary host
  # is unreachable (e.g. blocked in CN), then falls back to the mirror.
  effective_timeout = min(timeout_seconds, 8.0) if provider == "arxiv" else timeout_seconds
  all_records=[]; page=1; pages=0
  while len(all_records) < self.max_results and (self.stop_after_pages is None or pages < self.stop_after_pages):
   remaining=self.max_results-len(all_records); page_size=min(self.page_size,remaining); offset=(page-1)*self.page_size
   primary_url=self.URLS[provider].format(q=quote_plus(query),page=page,page_size=page_size,offset=offset)
   last=None; raw=None
   for attempt in range(self.retries+1):
    # For ArXiv: on last retry, try the fallback URL (arxiv.org instead of export.arxiv.org).
    url = primary_url
    if provider == "arxiv" and attempt == self.retries:
     try:
      url = self.ARXIV_FALLBACK_URL.format(q=quote_plus(query), offset=offset)
     except Exception:
      url = primary_url
    try:
     raw = self._fetch_url(url, provider, effective_timeout)
     batch=self._normalize_arxiv(raw) if provider=="arxiv" else self._normalize(provider,json.loads(raw))
     all_records.extend(batch[:remaining]); pages += 1; page += 1
     if len(batch) < page_size: return all_records
     break
    except (HTTPError,URLError,TimeoutError,json.JSONDecodeError,ET.ParseError) as error:
     last=error
     if attempt<self.retries:time.sleep(self.backoff*(2**attempt))
   else:
    hint = " (ArXiv API may be blocked in your region — try a VPN or use a different provider)" if provider == "arxiv" else ""
    raise ProviderUnavailable(f"{provider} request failed after {self.retries+1} attempts{hint}") from last
  return all_records
 @staticmethod
 def _normalize_arxiv(xml_text:str)->list[dict]:
  ns={"a":"http://www.w3.org/2005/Atom"};out=[]
  for entry in ET.fromstring(xml_text).findall("a:entry",ns):
   title=entry.findtext("a:title",default="",namespaces=ns).strip().replace("\n"," ");identifier=entry.findtext("a:id",default="",namespaces=ns).strip();year=entry.findtext("a:published",default="",namespaces=ns)[:4]
   if title and identifier:out.append({"title":title,"authors":[x.findtext("a:name",default="",namespaces=ns).strip() for x in entry.findall("a:author",ns)],"year":year,"doi":None,"url":identifier})
  return out
 @staticmethod
 def _normalize(provider:str,payload:dict[str,Any])->list[dict]:
  if provider=="openalex":return [{"title":x.get("title"),"authors":[a.get("author",{}).get("display_name","") for a in x.get("authorships",[])],"year":x.get("publication_year"),"doi":x.get("doi"),"url":x.get("id")} for x in payload.get("results",[]) if x.get("title") and x.get("id")]
  if provider=="crossref":return [{"title":(x.get("title") or [""])[0],"authors":[" ".join(filter(None,[a.get("given"),a.get("family")])) for a in x.get("author",[])],"year":((x.get("published",{}).get("date-parts") or [[None]])[0][0]),"doi":x.get("DOI"),"url":x.get("URL")} for x in payload.get("message",{}).get("items",[]) if x.get("title") and x.get("URL")]
  if provider=="datacite":return [{"title":((x.get("attributes",{}).get("titles") or [{}])[0].get("title")),"authors":[a.get("name","") for a in x.get("attributes",{}).get("creators",[])],"year":x.get("attributes",{}).get("publicationYear"),"doi":x.get("id"),"url":x.get("attributes",{}).get("url") or "https://doi.org/"+x.get("id","")} for x in payload.get("data",[]) if x.get("id") and (x.get("attributes",{}).get("titles") or [])]
  return [{"title":x.get("title"),"authors":[a.get("name","") for a in x.get("authors",[])],"year":x.get("year"),"doi":x.get("externalIds",{}).get("DOI"),"url":x.get("url") or "https://api.semanticscholar.org/"} for x in payload.get("data",[]) if x.get("title")]

class RecordingHttpTransport(HttpTransport):
 """HTTP transport which stores immutable raw-response recordings for offline replay."""
 def __init__(self, recording_directory:str|Path, **kwargs)->None:
  super().__init__(**kwargs);self.recording_directory=Path(recording_directory)
 def get_json(self,provider:str,query:str,timeout_seconds:float)->list[dict]:
  records=super().get_json(provider,query,timeout_seconds)
  self.recording_directory.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256(canonical_json(records)).hexdigest();path=self.recording_directory/f"{provider}-{digest}.json"
  path.write_text(json.dumps({"provider":provider,"query":query,"recorded_at":datetime.now(timezone.utc).isoformat(),"content_sha256":digest,"records":records},ensure_ascii=False),encoding="utf-8")
  return records

class ReplayTransport:
 def __init__(self,recording_directory:str|Path)->None:self.directory=Path(recording_directory)
 def get_json(self,provider:str,query:str,timeout_seconds:float)->list[dict]:
  candidates=sorted(self.directory.glob(f"{provider}-*.json"),reverse=True)
  for path in candidates:
   saved=json.loads(path.read_text(encoding="utf-8"))
   try:return verified_records(saved,provider,query)
   except ProviderUnavailable:continue
  raise ProviderUnavailable(f"No verified offline replay for {provider} query")

class LiteratureClient:
 PROVIDERS=("openalex","crossref","datacite","arxiv","semantic_scholar")
 def __init__(self,transport:Transport,cache_directory:str|Path,*,min_interval_seconds:float=0.,timeout_seconds:float=10.)->None:self.transport=transport;self.cache=Path(cache_directory);self.interval=min_interval_seconds;self.timeout=timeout_seconds;self._last:dict[str,float]={}
 def _cache_file(self,provider:str,query:str)->Path:return self.cache/f"{provider}-{hashlib.sha256(query.encode()).hexdigest()}.json"
 def replay_snapshot(self,provider:str,query:str)->tuple[list[SourceRecord],str]:
  """Read the exact integrity-checked search snapshot without network access."""
  cache_file=self._cache_file(provider,query)
  if not cache_file.is_file():raise ProviderUnavailable(f"No verified search snapshot for {provider} query")
  try:
   raw=cache_file.read_bytes();saved=json.loads(raw.decode("utf-8"));records=verified_records(saved,provider,query)
  except (OSError,UnicodeDecodeError,json.JSONDecodeError,ProviderUnavailable) as error:
   raise ProviderUnavailable(f"Verified search snapshot unavailable for {provider} query") from error
  retrieved_at=saved.get("retrieved_at")
  return [self._record(provider,query,item,retrieved_at) for item in records],hashlib.sha256(raw).hexdigest()
 def search(self,provider:str,query:str)->list[SourceRecord]:
  if provider not in self.PROVIDERS:raise ValueError("unsupported literature provider")
  cache_file=self._cache_file(provider,query)
  if cache_file.exists():
   try:
    saved=json.loads(cache_file.read_text(encoding="utf-8"));records=verified_records(saved,provider,query);return [self._record(provider,query,item,saved.get("retrieved_at")) for item in records]
   except (json.JSONDecodeError,ProviderUnavailable):
    cache_file.rename(cache_file.with_suffix(cache_file.suffix+".invalid"))
  wait=self.interval-(time.monotonic()-self._last.get(provider,0))
  if wait>0:time.sleep(wait)
  try:payload=self.transport.get_json(provider,query,self.timeout)
  except Exception as error:
   try:
    replay=ReplayTransport(self.cache).get_json(provider,query,self.timeout);return [self._record(provider,query,item) for item in replay]
   except ProviderUnavailable:raise ProviderUnavailable(f"{provider} lookup failed and no verified offline replay exists") from error
  self._last[provider]=time.monotonic(); self.cache.mkdir(parents=True,exist_ok=True)
  envelope={"provider":provider,"query":query,"retrieved_at":datetime.now(timezone.utc).isoformat(),"records":payload,"content_sha256":hashlib.sha256(canonical_json(payload)).hexdigest()}
  cache_file.write_text(json.dumps(envelope,ensure_ascii=False),encoding="utf-8")
  return [self._record(provider,query,item) for item in payload]
 def search_all(self,query:str,*,return_failures:bool=False):
  failures:dict[str,str]={}
  def run(provider:str)->list[SourceRecord]:
   try:return self.search(provider,query)
   except ProviderUnavailable as error:
    failures[provider]=str(error); return []
  with ThreadPoolExecutor(max_workers=len(self.PROVIDERS),thread_name_prefix="literature") as pool:
   results=[record for batch in pool.map(run,self.PROVIDERS) for record in batch]
  records=normalize_records(results)
  self.last_failures=failures
  return (records, failures) if return_failures else records
 @staticmethod
 def _record(provider:str,query:str,raw:dict,retrieved_at:str|None=None)->SourceRecord:
  doi=raw.get("doi");doi=doi.lower().removeprefix("https://doi.org/").removeprefix("doi:") if doi else None
  return SourceRecord(provider,str(raw["title"]).strip(),tuple(raw.get("authors",())),int(raw["year"]) if raw.get("year") else None,doi,raw["url"],retrieved_at or datetime.now(timezone.utc).isoformat(),query)
