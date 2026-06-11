import portal


# A trimmed copy of a real open.overheid.nl openbaarmakingen API payload shape.
SAMPLE = {
    "document": {
        "pid": "https://open.overheid.nl/documenten/756f05d4-667c-465b-a1c0-1e68d80b37f0",
        "verantwoordelijke": {"label": "ministerie van Binnenlandse Zaken en Koninkrijksrelaties"},
        "publisher": {"label": "ministerie van BZK"},
        "titelcollectie": {"officieleTitel": "Aanbiedingsbrief bij Beantwoording schriftelijke Kamervragen"},
        "classificatiecollectie": {
            "documentsoorten": [{"label": "Kamerbrief"}],
            "informatiecategorieen": [{"label": "inspanningsverplichting art 3.1 Woo"}],
        },
    },
    "plooiIntern": {"publicatiestatus": "gepubliceerd"},
    "versies": [{
        "openbaarmakingsdatum": "2026-06-09",
        "bestanden": [{"label": "PDF", "mime-type": "application/pdf",
                       "bestandsnaam": "Aanbiedingsbrief.pdf", "grootte": 114009, "paginas": 1}],
    }],
}


def test_is_portal_id_only_matches_uuid():
    assert portal.is_portal_id("756f05d4-667c-465b-a1c0-1e68d80b37f0") is True
    assert portal.is_portal_id("ronl-archief-abc123") is False
    assert portal.is_portal_id("") is False
    assert portal.is_portal_id(None) is False


def test_extract_meta_pulls_official_title_and_metadata():
    m = portal.extract_meta(SAMPLE)
    assert m["title"] == "Aanbiedingsbrief bij Beantwoording schriftelijke Kamervragen"
    assert m["organization"] == "ministerie van Binnenlandse Zaken en Koninkrijksrelaties"
    assert m["type"] == "Kamerbrief"
    assert m["category"] == "inspanningsverplichting art 3.1 Woo"
    assert m["status"] == "gepubliceerd"
    assert m["published"] == "2026-06-09"
    assert m["pages"] == 1
    assert m["link"].endswith("/756f05d4-667c-465b-a1c0-1e68d80b37f0")


def test_extract_meta_falls_back_to_filename_title():
    payload = {"versies": [{"bestanden": [{"bestandsnaam": "Besluit X.pdf"}]}]}
    m = portal.extract_meta(payload)
    assert m["title"] == "Besluit X.pdf"
    assert m["organization"] is None
    assert m["type"] is None


def test_extract_meta_is_total_garbage_safe():
    m = portal.extract_meta({})
    assert m["title"] is None
    assert m["link"] is None  # filled in by fetch_document_meta, not extract_meta


async def test_fetch_document_meta_skips_non_uuid(monkeypatch):
    # Must not even touch the cache / network for a non-portal id.
    assert await portal.fetch_document_meta("ronl-archief-x") is None


async def test_fetch_document_meta_retries_insecurely_on_tls_error(monkeypatch):
    """On a VPN/proxy that intercepts TLS, the cert won't verify. Because this is
    a public, credential-free GET, we retry once without verification rather than
    lose every title and report live documents as 'not live'."""
    uid = "756f05d4-667c-465b-a1c0-1e68d80b37f0"
    portal._meta_cache.clear()
    seen_verify = []

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return SAMPLE

    class _Client:
        def __init__(self, *a, verify=True, **k): self.verify = verify
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k):
            seen_verify.append(self.verify)
            if self.verify:
                raise portal.httpx.ConnectError(
                    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
            return _Resp()

    monkeypatch.setattr(portal.httpx, "AsyncClient", _Client)
    meta = await portal.fetch_document_meta(uid)
    assert meta is not None
    assert meta["status"] == "gepubliceerd"          # enrichment recovered
    assert seen_verify == [True, False]               # tried secure, then insecure


async def test_fetch_document_meta_no_insecure_retry_for_plain_connect_error(monkeypatch):
    """A non-TLS connection error (host down) must NOT trigger the insecure
    retry — only certificate failures do."""
    uid = "22222222-3333-4444-5555-666666666666"
    portal._meta_cache.clear()
    seen_verify = []

    class _Client:
        def __init__(self, *a, verify=True, **k): self.verify = verify
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k):
            seen_verify.append(self.verify)
            raise portal.httpx.ConnectError("Connection refused")

    monkeypatch.setattr(portal.httpx, "AsyncClient", _Client)
    assert await portal.fetch_document_meta(uid) is None
    assert seen_verify == [True]                      # no insecure retry


async def test_fetch_document_meta_negative_caches_failures(monkeypatch):
    uid = "11111111-2222-3333-4444-555555555555"
    portal._meta_cache.clear()
    calls = {"n": 0}

    class _Boom:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k):
            calls["n"] += 1
            raise portal.httpx.ConnectError("down")

    monkeypatch.setattr(portal.httpx, "AsyncClient", lambda *a, **k: _Boom())
    assert await portal.fetch_document_meta(uid) is None
    assert await portal.fetch_document_meta(uid) is None  # served from negative cache
    assert calls["n"] == 1  # second call did not hit the network
