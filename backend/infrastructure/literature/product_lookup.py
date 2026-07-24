"""Production citation existence lookup: offline provenance first, then live HTTP.

Offline dual-clean roots seed integrity-checked literature snapshots. Those
snapshots are first-class evidence that a DOI/title was recorded under a hashed
provider envelope. Live DOI/arXiv checks run only when offline layers miss and
the network is available; network failures surface as OSError so CitationVerifier
returns UNAVAILABLE instead of a silent PASS.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProductCitationLookup:
    """Layered lookup used by CitationVerifier during evidence-card review."""

    USER_AGENT = "VibeResearch/1.0 citation-existence-client"
    DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)

    def __init__(
        self,
        *,
        offline_dois: Iterable[str] = (),
        offline_arxiv: Iterable[str] = (),
        offline_titles: Iterable[str] = (),
        enable_network: bool = True,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.offline_dois = {self._norm_doi(item) for item in offline_dois if item}
        self.offline_arxiv = {self._norm_arxiv(item) for item in offline_arxiv if item}
        self.offline_titles = {self._norm_title(item) for item in offline_titles if item}
        self.enable_network = enable_network
        self.timeout_seconds = timeout_seconds
        self.last_layer = "input"

    @staticmethod
    def _norm_doi(value: str) -> str:
        text = value.strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")
        return text

    @staticmethod
    def _norm_arxiv(value: str) -> str:
        text = value.strip().lower()
        text = text.removeprefix("https://arxiv.org/abs/").removeprefix("arxiv:")
        return text

    @staticmethod
    def _norm_title(value: str) -> str:
        return " ".join(value.strip().casefold().split())

    def doi_exists(self, doi: str) -> bool:
        normalized = self._norm_doi(doi)
        if not normalized or not self.DOI_RE.fullmatch(normalized):
            self.last_layer = "doi_format"
            return False
        if normalized in self.offline_dois:
            self.last_layer = "offline_snapshot"
            return True
        if not self.enable_network:
            self.last_layer = "network_disabled"
            raise OSError("network citation lookup disabled")
        self.last_layer = "live_doi"
        return self._live_doi_exists(normalized)

    def arxiv_exists(self, identifier: str) -> bool:
        normalized = self._norm_arxiv(identifier)
        if not normalized:
            self.last_layer = "arxiv_format"
            return False
        if normalized in self.offline_arxiv:
            self.last_layer = "offline_snapshot"
            return True
        if not self.enable_network:
            self.last_layer = "network_disabled"
            raise OSError("network citation lookup disabled")
        self.last_layer = "live_arxiv"
        return self._live_arxiv_exists(normalized)

    def metadata_matches(self, title: str, authors: tuple[str, ...], year: int | None) -> bool:
        del authors, year
        normalized = self._norm_title(title)
        if not normalized:
            self.last_layer = "metadata_format"
            return False
        if normalized in self.offline_titles:
            self.last_layer = "offline_snapshot"
            return True
        if not self.enable_network:
            self.last_layer = "network_disabled"
            raise OSError("network citation lookup disabled")
        self.last_layer = "live_metadata"
        # Live metadata search is intentionally conservative: without a DOI/arXiv
        # identifier we only accept offline-proven titles, never invent a PASS.
        return False

    def _live_doi_exists(self, doi: str) -> bool:
        url = f"https://doi.org/api/handles/{doi}"
        req = Request(url, headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"})
        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", None) or response.getcode()
                if status >= 400:
                    return False
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code in {404, 400}:
                return False
            raise OSError(f"doi lookup HTTP {error.code}") from error
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise OSError(f"doi lookup unavailable: {error}") from error
        response_code = payload.get("responseCode")
        return response_code == 1 or str(payload.get("handle") or "").lower() == doi.lower()

    def _live_arxiv_exists(self, identifier: str) -> bool:
        url = f"https://export.arxiv.org/api/query?id_list={identifier}"
        req = Request(url, headers={"User-Agent": self.USER_AGENT, "Accept": "application/atom+xml"})
        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", None) or response.getcode()
                if status >= 400:
                    return False
                body = response.read().decode("utf-8")
        except HTTPError as error:
            if error.code in {404, 400}:
                return False
            raise OSError(f"arxiv lookup HTTP {error.code}") from error
        except (URLError, TimeoutError, UnicodeDecodeError) as error:
            raise OSError(f"arxiv lookup unavailable: {error}") from error
        return "<entry>" in body and identifier.split("v")[0] in body


def offline_sets_from_cache(cache_dir: Path) -> tuple[set[str], set[str], set[str]]:
    """Collect DOI/arXiv/title identities from integrity-checked literature envelopes."""
    dois: set[str] = set()
    arxiv_ids: set[str] = set()
    titles: set[str] = set()
    if not cache_dir.is_dir():
        return dois, arxiv_ids, titles
    for path in cache_dir.glob("*.json"):
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        records = envelope.get("records")
        if not isinstance(records, list):
            continue
        content_sha = envelope.get("content_sha256")
        if isinstance(content_sha, str) and content_sha:
            canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            import hashlib

            if hashlib.sha256(canonical).hexdigest() != content_sha:
                continue
        for item in records:
            if not isinstance(item, dict):
                continue
            doi = item.get("doi")
            if isinstance(doi, str) and doi.strip():
                dois.add(ProductCitationLookup._norm_doi(doi))
            url = str(item.get("url") or "")
            if "arxiv.org" in url:
                arxiv_ids.add(ProductCitationLookup._norm_arxiv(url))
            title = item.get("title")
            if isinstance(title, str) and title.strip():
                titles.add(ProductCitationLookup._norm_title(title))
    return dois, arxiv_ids, titles
