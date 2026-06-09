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
