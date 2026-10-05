"""Download the PDF of a DOI.

Order: open access (Unpaywall, arXiv) → institutional access (PDF links that
Crossref reports and the ``citation_pdf_url`` tag of the publisher's page).
Every download is checked to really be a PDF. Requests to publishers are
spaced out and capped per run so the institution is never flagged for bulk
downloading; blocks are reported, never circumvented.
"""

from __future__ import annotations

import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

import httpx

from .. import __version__
from ..config import AccessSection
from .network import in_ranges, public_ip

Reason = Literal["needs_vpn", "access_denied", "blocked", "no_pdf_link", "limit", "offline"]
Source = Literal["openaccess", "institutional"]

USER_AGENT = f"Mozilla/5.0 (compatible; second-brain/{__version__}; +https://github.com/AltamarMx/second-brain)"
MAX_PDF_BYTES = 150 * 1024 * 1024
# Text-mining endpoints that need an API key we do not have (phase 8).
KEYED_HOSTS = {"api.elsevier.com", "api.wiley.com"}
BLOCK_MARKERS = (
    "captcha", "just a moment", "are you a robot", "cf-challenge", "client challenge",
    "access denied", "content blocked", "enable javascript and cookies",
)  # fmt: skip
PAYWALL_MARKERS = (
    "purchase", "subscribe", "buy article", "rent this article", "get access",
    "access through your institution", "institutional access",
)  # fmt: skip


class FetchFailure(RuntimeError):
    def __init__(self, reason: Reason, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class FetchedPdf:
    path: Path
    source: Source
    via: str


@dataclass
class _Attempt:
    url: str
    via: str
    outcome: str  # "denied", "blocked", "not_pdf", "not_found", "error"
    detail: str = ""


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.pdf_urls: list[str] = []
        self.refresh: str | None = None
        self.redirect_input: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            if values.get("name", "").lower() == "citation_pdf_url" and values.get("content"):
                self.pdf_urls.append(values["content"])
            if (
                values.get("http-equiv", "").lower() == "refresh"
                and "url=" in values.get("content", "").lower()
            ):
                self.refresh = values["content"].split("=", 1)[1].strip("'\" ")
        elif tag == "input" and values.get("name") == "redirectURL" and values.get("value"):
            self.redirect_input = urllib.parse.unquote(values["value"])  # Elsevier's linkinghub


def parse_landing(html: str) -> _MetaParser:
    parser = _MetaParser()
    parser.feed(html)
    return parser


def crossref_pdf_links(message: dict[str, Any] | None) -> list[str]:
    links = []
    for link in (message or {}).get("link", []):
        url = link.get("URL", "")
        if (
            link.get("content-type") == "application/pdf"
            and urllib.parse.urlsplit(url).netloc not in KEYED_HOSTS
        ):
            links.append(url)
    return links


class Fetcher:
    def __init__(
        self,
        access: AccessSection,
        email: str | None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        confirm_vpn: Callable[[str], bool] | None = None,
    ):
        self.access = access
        self.email = email
        self.client = client or httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8",
            },
        )
        self.sleep = sleep
        self.confirm_vpn = confirm_vpn
        self.downloads = 0
        self._last_publisher_request: float | None = None
        self._inside: bool | None = None
        self.notes: list[str] = []

    # --- network --------------------------------------------------------------

    def inside_institution(self, refresh: bool = False) -> bool | None:
        """``True``/``False`` if it could be determined; ``None`` without configured ranges or IP."""
        if not self.access.ip_ranges:
            return None
        if self._inside is None or refresh:
            ip = public_ip(self.client)
            self._inside = None if ip is None else in_ranges(ip, self.access.ip_ranges)
        return self._inside

    def _require_institution(self) -> bool:
        inside = self.inside_institution()
        if inside is not False:
            return bool(inside)
        hint = self.access.vpn_hint or "Conéctate a la red de tu institución"
        while self.confirm_vpn is not None and self.confirm_vpn(hint):
            if self.inside_institution(refresh=True):
                return True
        institution = self.access.institution or "la institución"
        raise FetchFailure("needs_vpn", f"no estás en la red de {institution}. {hint}")

    # --- requests -------------------------------------------------------------

    def _pace(self) -> None:
        if self._last_publisher_request is not None:
            wait = self.access.seconds_between_downloads - (
                time.monotonic() - self._last_publisher_request
            )
            if wait > 0:
                self.sleep(wait)
        self._last_publisher_request = time.monotonic()

    def _get_page(self, url: str) -> httpx.Response:
        self._pace()
        try:
            return self.client.get(url)
        except httpx.HTTPError as exc:
            raise FetchFailure(
                "offline", f"sin conexión con {urllib.parse.urlsplit(url).netloc}: {exc}"
            ) from exc

    def _download(self, url: str, via: str, dest: Path, publisher: bool) -> _Attempt | None:
        """Save ``url`` to ``dest`` if it is a PDF; return the failed attempt otherwise."""
        if self.downloads >= self.access.max_downloads_per_run:
            raise FetchFailure(
                "limit",
                f"se alcanzó el máximo de {self.access.max_downloads_per_run} descargas por corrida",
            )
        if publisher:
            self._pace()
        self.downloads += 1
        try:
            with self.client.stream("GET", url) as response:
                if response.status_code == 404:
                    return _Attempt(url, via, "not_found")
                head = b""
                chunks = response.iter_bytes()
                for chunk in chunks:
                    head += chunk
                    if len(head) >= 1024:
                        break
                if response.status_code == 200 and head.lstrip().startswith(b"%PDF"):
                    tmp = dest.with_name(f".{dest.name}.part")
                    size = len(head)
                    with tmp.open("wb") as handle:
                        handle.write(head)
                        for chunk in chunks:
                            size += len(chunk)
                            if size > MAX_PDF_BYTES:
                                handle.close()
                                tmp.unlink()
                                return _Attempt(url, via, "error", "el PDF pasa de 150 MB")
                            handle.write(chunk)
                    tmp.replace(dest)
                    return None
                body = head
                for chunk in chunks:
                    body += chunk
                    if len(body) > 65536:
                        break
                text = body.decode("utf-8", "ignore").lower()
        except httpx.HTTPError as exc:
            return _Attempt(url, via, "error", str(exc))
        if any(marker in text for marker in BLOCK_MARKERS):
            return _Attempt(url, via, "blocked", f"HTTP {response.status_code}")
        if response.status_code in (401, 402, 403) or any(
            marker in text for marker in PAYWALL_MARKERS
        ):
            return _Attempt(url, via, "denied", f"HTTP {response.status_code}")
        return _Attempt(url, via, "not_pdf", f"HTTP {response.status_code}, no es un PDF")

    # --- sources --------------------------------------------------------------

    def _open_access(self, doi: str, arxiv: str | None) -> list[tuple[str, str]]:
        candidates = []
        if arxiv:
            candidates.append((f"https://arxiv.org/pdf/{arxiv}", "arxiv"))
        if not self.email:
            self.notes.append("sin [user].email no se consulta Unpaywall")
            return candidates
        try:
            response = self.client.get(
                f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi, safe='/')}",
                params={"email": self.email},
            )
        except httpx.HTTPError:
            return candidates
        if response.status_code != 200:
            return candidates
        data = response.json()
        locations = [data.get("best_oa_location")] + list(data.get("oa_locations") or [])
        for location in locations:
            url = (location or {}).get("url_for_pdf")
            if url and url not in (c[0] for c in candidates):
                candidates.append((url, "unpaywall"))
        return candidates

    def _landing_links(self, doi: str, attempts: list[_Attempt]) -> list[tuple[str, str]]:
        url = f"https://doi.org/{urllib.parse.quote(doi, safe='/')}"
        for _ in range(3):  # follow HTML/JS redirections such as Elsevier's linkinghub
            response = self._get_page(url)
            if response.status_code in (401, 402, 403, 429):
                text = response.text[:65536].lower()
                blocked = response.status_code == 429 or any(m in text for m in BLOCK_MARKERS)
                paywall = any(m in text for m in PAYWALL_MARKERS)
                outcome = "denied" if paywall and not blocked else "blocked"
                attempts.append(
                    _Attempt(str(response.url), "landing", outcome, f"HTTP {response.status_code}")
                )
                return []
            if "html" not in response.headers.get("content-type", ""):
                return [(str(response.url), "doi")] if response.status_code == 200 else []
            meta = parse_landing(response.text)
            base = str(response.url)
            if not meta.pdf_urls and any(m in response.text[:65536].lower() for m in BLOCK_MARKERS):
                attempts.append(_Attempt(base, "landing", "blocked", "prueba anti-robots"))
                return []
            if meta.pdf_urls:
                return [(urllib.parse.urljoin(base, u), "citation_pdf_url") for u in meta.pdf_urls]
            nxt = meta.redirect_input or meta.refresh
            if not nxt:
                return []
            url = urllib.parse.urljoin(base, nxt)
        return []

    def fetch(
        self, doi: str, dest: Path, crossref: dict[str, Any] | None = None, arxiv: str | None = None
    ) -> FetchedPdf:
        attempts: list[_Attempt] = []
        for url, via in self._open_access(doi, arxiv):
            failed = self._download(url, via, dest, publisher=False)
            if failed is None:
                return FetchedPdf(dest, "openaccess", via)
            attempts.append(failed)

        inside = self._require_institution()
        candidates = [(u, "crossref") for u in crossref_pdf_links(crossref)]
        candidates += [
            c for c in self._landing_links(doi, attempts) if c[0] not in (u for u, _ in candidates)
        ]
        for url, via in candidates:
            failed = self._download(url, via, dest, publisher=True)
            if failed is None:
                return FetchedPdf(dest, "institutional", via)
            attempts.append(failed)
        raise self._failure(attempts, inside)

    def _failure(self, attempts: list[_Attempt], inside: bool) -> FetchFailure:
        outcomes = {a.outcome for a in attempts}
        if "blocked" in outcomes:
            return FetchFailure(
                "blocked",
                "la editorial bloquea las descargas automáticas; ábrelo con sb pdf open y guarda el PDF en inbox/",
            )
        if "denied" in outcomes or "not_pdf" in outcomes:
            if inside:
                return FetchFailure(
                    "access_denied",
                    "la editorial negó el acceso: la suscripción probablemente no cubre esta revista",
                )
            return FetchFailure("access_denied", "la editorial pidió autenticación")
        if not attempts:
            return FetchFailure(
                "no_pdf_link", "no encontré un enlace al PDF en la página de la editorial"
            )
        return FetchFailure(
            "no_pdf_link",
            "los enlaces al PDF no funcionaron: "
            + "; ".join(f"{a.via}: {a.outcome}" for a in attempts),
        )
