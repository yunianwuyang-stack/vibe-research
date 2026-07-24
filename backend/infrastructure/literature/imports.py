"""Deterministic imports for common scholarly citation exports."""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from typing import Any


def _record(title: str, authors: list[str], year: int | None, doi: str | None, url: str = "") -> dict[str, Any]:
    if not title.strip():
        raise ValueError("citation title is required")
    normalized = doi.lower().removeprefix("https://doi.org/").removeprefix("doi:") if doi else None
    return {"title": title.strip(), "authors": tuple(a.strip() for a in authors if a.strip()), "year": year, "doi": normalized, "url": url.strip()}


def parse_bibtex(text: str) -> list[dict[str, Any]]:
    records = []
    for match in re.finditer(r"@\w+\s*\{[^,]+,(.*?)\}\s*(?=@|$)", text, re.S | re.I):
        fields = {k.lower(): v.strip().strip('{}"') for k, v in re.findall(r"(\w+)\s*=\s*[\{\"](.*?)[\}\"]\s*,?\s*(?=\w+\s*=|$)", match.group(1), re.S)}
        authors = [a.strip() for a in fields.get("author", "").replace(" and ", "\n").splitlines()]
        year = int(fields["year"]) if fields.get("year", "").isdigit() else None
        records.append(_record(fields.get("title", ""), authors, year, fields.get("doi"), fields.get("url", "")))
    return records


def parse_ris(text: str) -> list[dict[str, Any]]:
    records = []
    for block in re.split(r"\n\s*ER\s*\-", text, flags=re.I):
        fields: dict[str, list[str]] = {}
        for line in block.splitlines():
            match = re.match(r"\s*([A-Z0-9]{2})\s*\-\s?(.*)", line)
            if match:
                fields.setdefault(match.group(1), []).append(match.group(2).strip())
        if not fields:
            continue
        year = next((int(v[:4]) for v in fields.get("PY", []) if v[:4].isdigit()), None)
        records.append(_record((fields.get("TI") or [""])[0], fields.get("AU", []), year, (fields.get("DO") or [None])[0], (fields.get("UR") or [""])[0]))
    return records


def parse_pubmed_xml(text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(text)
    records = []
    for article in root.findall(".//PubmedArticle"):
        title = "".join(article.findtext(".//ArticleTitle", default="").split())
        authors = []
        for author in article.findall(".//Author"):
            name = " ".join(filter(None, [author.findtext("ForeName"), author.findtext("LastName")]))
            if name: authors.append(name)
        year_text = article.findtext(".//PubDate/Year") or article.findtext(".//PubDate/MedlineDate", default="")[:4]
        doi = next((x.text for x in article.findall(".//ArticleId") if x.attrib.get("IdType") == "doi"), None)
        pmid = article.findtext(".//PMID", default="")
        records.append(_record(title, authors, int(year_text) if year_text.isdigit() else None, doi, f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""))
    return records
