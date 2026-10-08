import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
from test_ingest import DOI, TITLE, crossref_message, make_pdf

from second_brain.checks import run_checks
from second_brain.config import AccessSection, load_config
from second_brain.fetch.download import Fetcher, FetchFailure, crossref_pdf_links, parse_landing
from second_brain.fetch.network import in_ranges
from second_brain.ingest.metadata import MetadataClient
from second_brain.ingest.pipeline import IngestOptions, Ingestor

INSIDE, OUTSIDE = "192.0.2.10", "198.51.100.7"
ACCESS = AccessSection(
    institution="Ejemplo", ip_ranges=["192.0.2.0/24"], vpn_hint="Activa el VPN",
    seconds_between_downloads=10,
)  # fmt: skip
LANDING = f"https://publisher.example/article/{DOI}"
PDF_URL = "https://publisher.example/pdf/article.pdf"


class FakeWeb:
    """IP service, Unpaywall, Crossref, doi.org and a publisher, all simulated."""

    def __init__(self, tmp: Path, ip=INSIDE, pdf_response="pdf", unpaywall_url=None, works=None):
        self.ips = [ip] if isinstance(ip, str) else list(ip)
        self.pdf_response = pdf_response
        self.unpaywall_url = unpaywall_url
        self.works = works if works is not None else {DOI: crossref_message()}
        self.pdf_bytes = make_pdf(tmp / "source.pdf").read_bytes()
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        host, path = request.url.host, request.url.path
        if host == "api.ipify.org":
            return httpx.Response(200, text=self.ips.pop(0) if len(self.ips) > 1 else self.ips[0])
        if host == "api.crossref.org":
            doi = path.removeprefix("/works/").lower()
            if doi in self.works:
                return httpx.Response(200, json={"message": self.works[doi]})
            return httpx.Response(404)
        if host == "api.datacite.org":
            return httpx.Response(404)
        if host == "api.unpaywall.org":
            location = {"url_for_pdf": self.unpaywall_url} if self.unpaywall_url else None
            return httpx.Response(200, json={"best_oa_location": location, "oa_locations": []})
        if host == "oa.example":
            return httpx.Response(
                200, content=self.pdf_bytes, headers={"content-type": "application/pdf"}
            )
        if host == "doi.org":
            return httpx.Response(302, headers={"location": LANDING})
        if url == LANDING:
            html = f'<html><head><meta name="citation_pdf_url" content="{PDF_URL}"></head></html>'
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        if url == PDF_URL:
            if self.pdf_response == "pdf":
                return httpx.Response(200, content=self.pdf_bytes)
            if self.pdf_response == "denied":
                return httpx.Response(403, text="<html>Purchase this article</html>")
            if self.pdf_response == "blocked":
                return httpx.Response(403, text="<html><title>Just a moment...</title></html>")
        return httpx.Response(404)


def fetcher_for(web: FakeWeb, email=None, confirm=None, access=ACCESS, sleeps=None):
    client = httpx.Client(transport=httpx.MockTransport(web), follow_redirects=True)
    return Fetcher(
        access,
        email,
        client=client,
        sleep=(sleeps.append if sleeps is not None else lambda s: None),
        confirm_vpn=confirm,
    )


def test_in_ranges():
    assert in_ranges("132.248.1.1", ["132.247.0.0/16", "132.248.0.0/16"])
    assert not in_ranges("8.8.8.8", ["132.248.0.0/16"])


def test_parse_landing():
    meta = parse_landing(
        '<meta name="citation_pdf_url" content="/x.pdf"><meta http-equiv="refresh" content="0;URL=\'/next\'">'
    )
    assert meta.pdf_urls == ["/x.pdf"]
    assert meta.refresh == "/next"
    assert (
        parse_landing('<input name="redirectURL" value="https%3A%2F%2Fa.b%2Fc">').redirect_input
        == "https://a.b/c"
    )


def test_crossref_links_skip_keyed_apis():
    message = {"link": [
        {"URL": "https://api.elsevier.com/x", "content-type": "application/pdf"},
        {"URL": "https://pub.example/x.pdf", "content-type": "application/pdf"},
        {"URL": "https://pub.example/x.xml", "content-type": "text/xml"},
    ]}  # fmt: skip
    assert crossref_pdf_links(message) == ["https://pub.example/x.pdf"]


def test_open_access_first(tmp_path):
    web = FakeWeb(tmp_path, ip=OUTSIDE, unpaywall_url="https://oa.example/a.pdf")
    fetched = fetcher_for(web, email="a@b.c").fetch(DOI, tmp_path / "out.pdf")
    assert fetched.source == "openaccess" and fetched.path.read_bytes().startswith(b"%PDF")
    assert not any("publisher.example" in u for u in web.requests)


def test_institutional_via_citation_pdf_url(tmp_path):
    web = FakeWeb(tmp_path)
    fetched = fetcher_for(web).fetch(DOI, tmp_path / "out.pdf")
    assert (fetched.source, fetched.via) == ("institutional", "citation_pdf_url")


def test_outside_without_prompt_needs_vpn(tmp_path):
    with pytest.raises(FetchFailure) as info:
        fetcher_for(FakeWeb(tmp_path, ip=OUTSIDE)).fetch(DOI, tmp_path / "out.pdf")
    assert info.value.reason == "needs_vpn"
    assert "Activa el VPN" in str(info.value)


def test_prompt_then_vpn_connected(tmp_path):
    asked = []
    web = FakeWeb(tmp_path, ip=[OUTSIDE, INSIDE])
    fetched = fetcher_for(web, confirm=lambda hint: asked.append(hint) or True).fetch(
        DOI, tmp_path / "o.pdf"
    )
    assert asked == ["Activa el VPN"] and fetched.source == "institutional"


def test_prompt_skipped(tmp_path):
    with pytest.raises(FetchFailure) as info:
        fetcher_for(FakeWeb(tmp_path, ip=OUTSIDE), confirm=lambda hint: False).fetch(
            DOI, tmp_path / "o.pdf"
        )
    assert info.value.reason == "needs_vpn"


@pytest.mark.parametrize(("response", "reason", "text"), [
    ("denied", "access_denied", "suscripción"),
    ("blocked", "blocked", "sb pdf open"),
])  # fmt: skip
def test_failures(tmp_path, response, reason, text):
    with pytest.raises(FetchFailure) as info:
        fetcher_for(FakeWeb(tmp_path, pdf_response=response)).fetch(DOI, tmp_path / "o.pdf")
    assert info.value.reason == reason and text in str(info.value)
    assert not (tmp_path / "o.pdf").exists()


def test_courtesy_pause_and_limit(tmp_path):
    sleeps = []
    access = ACCESS.model_copy(update={"max_downloads_per_run": 1})
    fetcher = fetcher_for(FakeWeb(tmp_path), access=access, sleeps=sleeps)
    fetcher.fetch(DOI, tmp_path / "a.pdf")
    assert sleeps and all(s <= 10 for s in sleeps)
    with pytest.raises(FetchFailure) as info:
        fetcher.fetch(DOI, tmp_path / "b.pdf")
    assert info.value.reason == "limit"


# --- pipeline -----------------------------------------------------------------


def ingestor_for(lib, web: FakeWeb, **options):
    client = httpx.Client(transport=httpx.MockTransport(web), follow_redirects=True)
    metadata = MetadataClient(lib.cache_dir, client=client, retries=0)
    access = ACCESS.model_copy(update={"seconds_between_downloads": 0})
    fetcher = Fetcher(access, None, client=client, sleep=lambda s: None)
    opts = IngestOptions(today=dt.date(2026, 10, 4), **options)
    return Ingestor(lib, load_config(lib.home), metadata, opts, fetcher=fetcher)


def test_ingest_by_doi_downloads(lib, tmp_path):
    [result] = ingestor_for(lib, FakeWeb(tmp_path)).run([], [f"https://doi.org/{DOI}"])
    assert result.outcome == "ingested", result.message
    paper = lib.read_paper(result.citekey).meta
    assert paper.pdf.source == "institutional"
    assert (lib.pdfs_dir / f"{result.citekey}.pdf").is_file()
    assert lib.inbox_pdfs() == []


def test_failed_download_registers_awaiting_then_retry(lib, tmp_path):
    [first] = ingestor_for(lib, FakeWeb(tmp_path, pdf_response="denied")).run([], [DOI])
    assert first.outcome == "awaiting"
    paper = lib.read_paper(first.citekey).meta
    assert paper.status == "awaiting_pdf" and paper.pdf is None and paper.title == TITLE
    log = json.loads((lib.cache_dir / "fetch.json").read_text())
    assert log[DOI]["reason"] == "access_denied"
    assert run_checks(lib.home).ok

    ingestor = ingestor_for(lib, FakeWeb(tmp_path))
    assert ingestor.pending_dois() == [DOI]
    [second] = ingestor.run([], ingestor.pending_dois())
    assert second.outcome == "attached", second.message
    assert lib.read_paper(first.citekey).meta.status == "needs_processing"
    assert DOI not in json.loads((lib.cache_dir / "fetch.json").read_text())


def test_awaiting_record_gets_pdf_dropped_in_inbox(lib, tmp_path):
    web = FakeWeb(tmp_path, pdf_response="blocked")
    [first] = ingestor_for(lib, web).run([], [DOI])
    (lib.inbox_dir / "descargado-a-mano.pdf").write_bytes(web.pdf_bytes)
    [second] = ingestor_for(lib, FakeWeb(tmp_path)).run(lib.inbox_pdfs())
    assert second.outcome == "attached" and second.citekey == first.citekey


def test_doi_already_present_is_not_downloaded(lib, tmp_path):
    ingestor_for(lib, FakeWeb(tmp_path)).run([], [DOI])
    web = FakeWeb(tmp_path)
    [again] = ingestor_for(lib, web).run([], [DOI.upper()])
    assert again.outcome == "duplicate"
    assert not any("publisher.example" in u for u in web.requests)


def test_unknown_doi(lib, tmp_path):
    [result] = ingestor_for(lib, FakeWeb(tmp_path, works={})).run([], ["10.9999/nope"])
    assert result.outcome == "error" and "no existe" in result.message


def test_dry_run_doi(lib, tmp_path):
    web = FakeWeb(tmp_path)
    [result] = ingestor_for(lib, web, dry_run=True).run([], [DOI])
    assert result.outcome == "awaiting"
    assert list(lib.papers_dir.glob("*.md")) == []
    assert not any("publisher.example" in u for u in web.requests)


def test_publisher_page_forbidden_is_blocked(tmp_path):
    web = FakeWeb(tmp_path)
    original = web.__call__

    def forbidden(request):
        if str(request.url) == LANDING:
            return httpx.Response(
                403, text="<html>bot check</html>", headers={"content-type": "text/html"}
            )
        return original(request)

    client = httpx.Client(transport=httpx.MockTransport(forbidden), follow_redirects=True)
    fetcher = Fetcher(ACCESS, None, client=client, sleep=lambda s: None)
    with pytest.raises(FetchFailure) as info:
        fetcher.fetch(DOI, tmp_path / "o.pdf")
    assert info.value.reason == "blocked"


def test_challenge_page_with_200_is_blocked(tmp_path):
    web = FakeWeb(tmp_path)
    original = web.__call__

    def challenge(request):
        if str(request.url) == LANDING:
            return httpx.Response(
                200, text="<title>Client Challenge</title>", headers={"content-type": "text/html"}
            )
        return original(request)

    client = httpx.Client(transport=httpx.MockTransport(challenge), follow_redirects=True)
    with pytest.raises(FetchFailure) as info:
        Fetcher(ACCESS, None, client=client, sleep=lambda s: None).fetch(DOI, tmp_path / "o.pdf")
    assert info.value.reason == "blocked"


def test_unreachable_publisher_is_not_reported_as_offline(tmp_path):
    web = FakeWeb(tmp_path)

    def slow_publisher(request):
        if request.url.host == "publisher.example":
            raise httpx.ReadTimeout("timed out", request=request)
        return web(request)

    client = httpx.Client(transport=httpx.MockTransport(slow_publisher), follow_redirects=True)
    fetcher = Fetcher(ACCESS, None, client=client, sleep=lambda s: None)
    fetcher.inside_institution = lambda refresh=False: True
    with pytest.raises(FetchFailure) as info:
        fetcher.fetch(DOI, tmp_path / "o.pdf")
    assert info.value.reason == "unreachable"
    assert "publisher.example no respondió" in str(info.value) and "doi.org" not in str(info.value)

    def offline(request):
        raise httpx.ConnectError("sin red", request=request)

    client = httpx.Client(transport=httpx.MockTransport(offline), follow_redirects=True)
    fetcher = Fetcher(ACCESS, None, client=client, sleep=lambda s: None)
    fetcher.inside_institution = lambda refresh=False: True
    with pytest.raises(FetchFailure) as info:
        fetcher.fetch(DOI, tmp_path / "o.pdf")
    assert info.value.reason == "offline" and "doi.org" in str(info.value)
