"""Normalized literature metadata shared by all provider adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRecord:
    provider: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    doi: str | None
    url: str
    retrieved_at: str
    query_snapshot: str

    def __post_init__(self) -> None:
        if not all((self.provider.strip(), self.title.strip(), self.url.strip(), self.retrieved_at.strip(), self.query_snapshot.strip())):
            raise ValueError("source record requires provider, title, URL, retrieval time, and query snapshot")
        if self.doi is not None and not self.doi.startswith("10."):
            raise ValueError("DOI must be normalized")

    @property
    def identity(self) -> str:
        return f"doi:{self.doi}" if self.doi else f"title:{self.title.casefold()}|year:{self.year}|authors:{'|'.join(a.casefold() for a in self.authors)}"


def normalize_records(records: list[SourceRecord]) -> list[SourceRecord]:
    """Deduplicate provider results without inventing a missing source."""
    unique: dict[str, SourceRecord] = {}
    for record in records:
        unique.setdefault(record.identity, record)
    return list(unique.values())
