from config import Settings


def test_dashboard_defaults():
    s = Settings()
    assert s.dashboard_cache_ttl == 60
    assert s.dashboard_timezone == "Europe/Amsterdam"
    assert s.dashboard_superset_views == "logs-*"


def test_admin_list_parsing():
    s = Settings(dashboard_admins="a@x.nl, b@y.nl ,a@x.nl")
    assert s.admin_list == ["a@x.nl", "b@y.nl"]  # trimmed + de-duped


def test_rollup_views_excludes_superset():
    s = Settings(
        data_views="logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp",
        dashboard_superset_views="logs-*",
    )
    assert s.rollup_views == ["ds-prod5-koop-plooi*", "ds-prod5-koop-sp"]
    assert s.rollup_index == "ds-prod5-koop-plooi*,ds-prod5-koop-sp"
