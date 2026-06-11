import digest


HEALTH = {
    "lookback_minutes": 1440,
    "confirmed_published": 5,
    "stuck": [
        {"id": "a3331f36-1206-4bdb-99db-e2f6803070b1", "verdict": "problem",
         "stuck_stage": "Indexing", "title": "Beslisnota subsidies cultuur 2025",
         "headline": "⛔ A problem occurred at Indexing — not yet live."},
        {"id": "5caff8b8-1c3e-4517-a95f-b21d8ca8746b", "verdict": "stuck",
         "stuck_stage": "Storage", "title": "Woo-besluit FSV lijst/RAM",
         "headline": "🕒 Not live yet — stuck at Storage, no progress for 11h 0m."},
    ],
}


def test_build_digest_with_at_risk():
    d = digest.build_digest(HEALTH)
    assert d["count"] == 2 and d["critical"] == 1
    assert "2 document" in d["subject"] and "1 critical" in d["subject"]
    # plain text mentions both documents + their marks
    assert "CRITICAL @ Indexing" in d["text"]
    assert "stuck @ Storage" in d["text"]
    assert "Beslisnota subsidies cultuur 2025" in d["text"]
    assert "already published" in d["text"]  # the reassurance line
    # html has a row per document and is escaped/linked
    assert d["html"].count("<tr>") == 2
    assert "open.overheid.nl/details/a3331f36" in d["html"]


def test_build_digest_all_clear():
    d = digest.build_digest({"lookback_minutes": 1440, "stuck": [], "confirmed_published": 0})
    assert d["count"] == 0 and d["critical"] == 0
    assert "all documents flowing normally" in d["subject"]
    assert "No documents at risk" in d["text"]
