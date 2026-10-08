"""Bibliographic metadata from Crossref (primary) and DataCite (fallback).

Responses are cached in ``.cache/http/`` so re-running an ingestion does not
hit the network again.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

from .. import __version__
from ..textutil import strip_markup

CROSSREF = "https://api.crossref.org"
DATACITE = "https://api.datacite.org"

CROSSREF_TYPES = {
    "journal-article": "article-journal",
    "proceedings-article": "paper-conference",
    "book-chapter": "chapter",
    "book-part": "chapter",
    "book-section": "chapter",
    "book": "book",
    "edited-book": "book",
    "monograph": "book",
    "reference-book": "book",
    "dissertation": "thesis",
    "report": "report",
    "report-component": "report",
    "standard": "standard",
    "posted-content": "preprint",
    "dataset": "dataset",
}


class NetworkError(RuntimeError):
    """The metadata service could not be reached (offline, timeout, 5xx)."""


class MetadataClient:
    def __init__(
        self,
        cache_dir: Path,
        email: str | None = None,
        client: httpx.Client | None = None,
        retries: int = 2,
    ):
        self.cache_dir = cache_dir / "http"
        contact = f"; mailto:{email}" if email else ""
        self.client = client or httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers={
                "User-Agent": f"second-brain/{__version__} (https://github.com/AltamarMx/second-brain{contact})"
            },
        )
        self.retries = retries

    def _get(self, url: str, refresh: bool = False) -> dict[str, Any] | None:
        """JSON body for 200, ``None`` for 404; both are cached (``refresh`` asks again)."""
        key = hashlib.sha256(url.encode()).hexdigest()
        cached = self.cache_dir / f"{key}.json"
        if cached.is_file() and not refresh:
            return json.loads(cached.read_text(encoding="utf-8"))["body"]
        for attempt in range(self.retries + 1):
            try:
                response = self.client.get(url)
            except httpx.HTTPError as exc:
                if attempt == self.retries:
                    raise NetworkError(
                        f"sin conexión con {urllib.parse.urlsplit(url).netloc}: {exc}"
                    ) from exc
            else:
                if response.status_code in (200, 404):
                    body = response.json() if response.status_code == 200 else None
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    cached.write_text(json.dumps({"url": url, "body": body}), encoding="utf-8")
                    return body
                if response.status_code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise NetworkError(
                        f"{urllib.parse.urlsplit(url).netloc} respondió {response.status_code}"
                    )
            time.sleep(2**attempt)
        return None

    def crossref_work(self, doi: str, refresh: bool = False) -> dict[str, Any] | None:
        body = self._get(f"{CROSSREF}/works/{urllib.parse.quote(doi, safe='/')}", refresh=refresh)
        return body["message"] if body else None

    def crossref_search(self, query: str, rows: int = 5) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode({"query.bibliographic": query[:300], "rows": rows})
        body = self._get(f"{CROSSREF}/works?{params}")
        return body["message"]["items"] if body else []

    def datacite_work(self, doi: str) -> dict[str, Any] | None:
        body = self._get(f"{DATACITE}/dois/{urllib.parse.quote(doi, safe='')}")
        return body["data"]["attributes"] if body else None


def _first(values: list[str] | None) -> str | None:
    return strip_markup(values[0]) if values else None


def _year(message: dict[str, Any]) -> int | None:
    for key in ("issued", "published-print", "published-online", "created"):
        parts = message.get(key, {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def _abstract(raw: str | None) -> str | None:
    if not raw:
        return None
    text = re.sub(r"<(jats:)?title>.*?</(jats:)?title>", "", raw, flags=re.S)
    text = text.replace("</jats:p>", "\n\n").replace("</p>", "\n\n")
    paragraphs = [strip_markup(p) for p in text.split("\n\n")]
    paragraphs = [p for p in paragraphs if p and p.lower() not in {"abstract", "resumen"}]
    return "\n\n".join(paragraphs) or None


PARTICLES = {
    "de",
    "del",
    "la",
    "las",
    "los",
    "da",
    "das",
    "do",
    "dos",
    "di",
    "du",
    "van",
    "von",
    "der",
    "den",
    "ter",
    "y",
}


def name_case(name: str | None) -> str | None:
    """Capitalize a name that comes all in lowercase ("liu" → "Liu", "garcía-lópez" →
    "García-López", "de la cruz" → "de la Cruz"); any other casing is left as it is."""
    if not name or name != name.lower() or not any(c.isalpha() for c in name):
        return name
    words = name.split()

    def cap(word: str) -> str:
        return re.sub(r"(^|[-'’.])(\w)", lambda m: m.group(1) + m.group(2).upper(), word)

    return " ".join(
        word if word in PARTICLES and i < len(words) - 1 else cap(word)
        for i, word in enumerate(words)
    )


def crossref_fields(message: dict[str, Any]) -> dict[str, Any]:
    """Map a Crossref ``work`` to ``Paper`` fields (without citekey, dates or status)."""
    authors = []
    for author in message.get("author", []):
        orcid = author.get("ORCID")
        if author.get("family"):
            authors.append(
                {
                    "family": name_case(author["family"]),
                    "given": name_case(author.get("given")),
                    "orcid": orcid.rsplit("/", 1)[-1] if orcid else None,
                }
            )
        elif author.get("name"):
            authors.append({"family": author["name"]})
    licenses = message.get("license") or []
    return {
        "type": CROSSREF_TYPES.get(message.get("type", ""), "article"),
        "doi": message.get("DOI"),
        "ids": {"isbn": _first(message.get("ISBN"))},
        "title": _first(message.get("title")) or "(sin título)",
        "authors": authors,
        "year": _year(message),
        # a preprint has no journal: its server ("SSRN", "Research Square") is the group title
        "container_title": _first(message.get("container-title")) or message.get("group-title"),
        "volume": message.get("volume"),
        "issue": message.get("issue"),
        "pages": message.get("page") or message.get("article-number"),
        "publisher": message.get("publisher"),
        "language": message.get("language"),
        "license": licenses[0].get("URL") if licenses else None,
        "abstract": _abstract(message.get("abstract")),
        "updates": crossref_updates(message),
    }


EMPTY = (None, "", [], {}, "(sin título)")


def fill(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """``base`` with the values of ``extra`` that say something: an incomplete Crossref record
    (no authors, no pages…) never erases data that was already there."""
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = fill(merged[key], value)
        elif value not in EMPTY:
            merged[key] = value
    return merged


RETRACTING = {"retraction", "withdrawal", "removal", "partial_retraction"}


def crossref_updates(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Notices about this work (retraction, correction, expression of concern…), oldest first."""
    updates = []
    for item in message.get("updated-by") or []:
        parts = (item.get("updated") or {}).get("date-parts") or [[None]]
        date = None
        if parts[0] and parts[0][0]:
            year, month, day = (list(parts[0]) + [1, 1])[:3]
            date = f"{year:04d}-{month:02d}-{day:02d}"
        updates.append(
            {
                "type": item.get("type", "update"),
                "doi": item.get("DOI"),
                "date": date,
                "source": item.get("source"),
            }
        )
    return sorted(updates, key=lambda u: u["date"] or "")


def flags_from_updates(updates: list[Any]) -> list[str]:
    types = {
        (u["type"] if isinstance(u, dict) else u.type).lower().replace("-", "_") for u in updates
    }
    flags = []
    if types & RETRACTING:
        flags.append("retracted")
    if "expression_of_concern" in types:
        flags.append("expression_of_concern")
    return flags


def crossref_relations(message: dict[str, Any]) -> list[str]:
    """DOIs of preprints / published versions of this work."""
    relations = message.get("relation", {})
    dois = []
    for kind in ("has-preprint", "is-preprint-of"):
        for item in relations.get(kind, []):
            if item.get("id-type") == "doi":
                dois.append(item["id"])
    return dois


def datacite_fields(attributes: dict[str, Any]) -> dict[str, Any]:
    authors = []
    for creator in attributes.get("creators", []):
        if creator.get("familyName"):
            authors.append(
                {
                    "family": name_case(creator["familyName"]),
                    "given": name_case(creator.get("givenName")),
                }
            )
        elif creator.get("name"):
            authors.append({"family": creator["name"]})
    titles = attributes.get("titles") or [{}]
    publisher = attributes.get("publisher")
    if isinstance(publisher, dict):
        publisher = publisher.get("name")
    general = (attributes.get("types") or {}).get("resourceTypeGeneral", "")
    descriptions = [
        d.get("description")
        for d in attributes.get("descriptions", [])
        if d.get("descriptionType") == "Abstract"
    ]
    return {
        "type": {
            "Dissertation": "thesis",
            "Preprint": "preprint",
            "Report": "report",
            "Book": "book",
            "Dataset": "dataset",
        }.get(general, "article"),
        "doi": attributes.get("doi"),
        "title": strip_markup(titles[0].get("title", "")) or "(sin título)",
        "authors": authors,
        "year": attributes.get("publicationYear"),
        "publisher": publisher,
        "language": attributes.get("language"),
        "abstract": strip_markup(descriptions[0]) if descriptions and descriptions[0] else None,
    }
