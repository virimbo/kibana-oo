from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Kibana (we connect through Kibana, not directly to ES)
    kibana_url: str = "https://kibana-prod.cicd.s15m.nl"
    kibana_space: str = "koop-plooi-prod"
    es_log_index: str = "logs-*"
    es_metric_index: str = "logs-*"

    # Data views the user can choose to query (comma-separated ES index patterns).
    # Acts as a whitelist — only these patterns may be searched.
    data_views: str = "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp"
    default_data_view: str = "logs-*"

    # Dashboard
    dashboard_cache_ttl: int = 60          # seconds; summary cache TTL
    dashboard_timezone: str = "Europe/Amsterdam"
    dashboard_admins: str = ""             # comma-separated admin usernames/emails
    # Views treated as a superset of others — excluded from rollup totals to avoid
    # double counting (still shown as their own per-system tile).
    dashboard_superset_views: str = "logs-*"
    # Index patterns where TLS certificate monitoring data (Heartbeat / Synthetics)
    # lives. Used by the certificate-expiry cards. Read-only discovery.
    cert_index: str = "heartbeat-*,synthetics-*"

    # Document processing pipelines (Verwerkingsstraat): OVS = oude (old),
    # NVS = nieuwe (new). Query strings attributing documents to each pipeline.
    # Tune these to match how your logs label the pipelines.
    pipeline_ovs_query: str = 'OVS OR "oude verwerkingsstraat"'
    pipeline_nvs_query: str = 'NVS OR "nieuwe verwerkingsstraat"'

    # Public portal base, used to turn document paths into clickable links.
    portal_base_url: str = "https://open.overheid.nl"
    # Best-effort source fields used to identify a document in drill-down lists.
    doc_url_fields: str = "url.full,url.original,url.path"
    doc_id_fields: str = "document.id,documentId,dossier.id,identifier,id"
    doc_title_fields: str = "title,titel,document.title,name"
    doc_action_fields: str = "event.action,event.type,action,operation,mutatie"
    pipeline_doc_size: int = 100
    # Extract a document identifier from the log text and turn it into a portal link.
    # Default matches KOOP "ronl-..." identifiers seen in repository log messages.
    doc_id_regex: str = r"ronl-[A-Za-z0-9-]+"
    doc_link_template: str = "https://open.overheid.nl/documenten/{id}"
    # Document management (aanleverloket) link for the tracer — the id is the UUID.
    doculoket_link_template: str = "https://doculoket.overheid.nl/#/aanleveren/{id}"

    # Documents activity tab: which logs count as document events, and how many to feed.
    document_event_query: str = "ronl OR document OR bestand OR upload OR publicatie OR versie"
    document_event_size: int = 200
    # Best-effort source fields for a document's organization (tune to your logs).
    doc_org_fields: str = "organisatie,bronorganisatie,publisher,organization,source.organization,verantwoordelijke,bron,afzender"
    # Known document sources (bron) for the errors-by-source table.
    processing_sources: str = "aanleverloket,dpc,oep-ob,oep,plooi-api,ronl-archief,ronl,roo,woo-idx"

    # Ollama
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1:8b"

    # Backend
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def data_view_list(self) -> list[str]:
        """Parsed, de-duplicated list of allowed data view patterns."""
        seen: list[str] = []
        for view in self.data_views.split(","):
            view = view.strip()
            if view and view not in seen:
                seen.append(view)
        return seen or [self.es_log_index]

    @property
    def processing_source_list(self) -> list[str]:
        """Known sources, longest-first so 'ronl-archief' wins over 'ronl'."""
        items = [s.strip() for s in self.processing_sources.split(",") if s.strip()]
        return sorted(items, key=len, reverse=True)

    @property
    def admin_list(self) -> list[str]:
        seen: list[str] = []
        for name in self.dashboard_admins.split(","):
            name = name.strip()
            if name and name not in seen:
                seen.append(name)
        return seen

    @property
    def rollup_views(self) -> list[str]:
        """Data views used for rollup totals (superset views excluded)."""
        superset = {v.strip() for v in self.dashboard_superset_views.split(",") if v.strip()}
        return [v for v in self.data_view_list if v not in superset]

    @property
    def rollup_index(self) -> str:
        """Comma-joined ES index string for the rollup query."""
        return ",".join(self.rollup_views) or self.es_log_index


settings = Settings()
