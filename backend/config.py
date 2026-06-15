from datetime import date

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
    # Public hosts whose TLS certificate we ACTIVELY probe (independent of Kibana),
    # so the expiry countdown and any trust/chain/hostname issues are always
    # visible. Comma-separated host[:port]. Read-only outbound TLS.
    cert_probe_hosts: str = "open.overheid.nl,doculoket.overheid.nl"
    cert_probe_timeout: float = 6.0        # seconds; keep short so it never stalls the card
    cert_check_revocation: bool = True     # best-effort OCSP revocation check per cert
    # Daily proactive TLS audit: re-checks every host on this interval and alerts
    # (via the digest webhook / email) when a host's grade is WARN or CRITICAL.
    cert_audit_interval_hours: float = 24.0
    cert_alert_enabled: bool = True

    # Document processing pipelines (Verwerkingsstraat): OVS = oude (old),
    # NVS = nieuwe (new). Query strings attributing documents to each pipeline.
    # Tune these to match how your logs label the pipelines.
    pipeline_ovs_query: str = 'OVS OR "oude verwerkingsstraat"'
    pipeline_nvs_query: str = 'NVS OR "nieuwe verwerkingsstraat"'

    # ── Reliable per-document pipeline (NVS/OVS) attribution ───────────────────
    # Per-document NVS/OVS is classified in order of TRUST. Configure either layer
    # to make it authoritative — when a trusted signal is set but a document
    # matches neither pipeline, it is reported as unknown ('—') rather than guessed.
    #
    # 1) A dedicated field your logs carry. Set its (dotted) name(s),
    #    comma-separated, and the values that mean each pipeline. Empty = skip.
    pipeline_field: str = ""                      # e.g. "labels.pipeline,data_stream.dataset"
    pipeline_nvs_values: str = "nvs,nieuwe verwerkingsstraat,nieuwe"
    pipeline_ovs_values: str = "ovs,oude verwerkingsstraat,oude"
    # 2) The index / data-stream the events live in (structural, reliable). List
    #    the substrings that identify each pipeline's index. Empty = skip.
    pipeline_nvs_index: str = ""                  # e.g. "koop-plooi,nvs"
    pipeline_ovs_index: str = ""                  # e.g. "koop-sp,ovs"
    # 3) Publication-date cutoff — the pipeline switchover. A document active/
    #    published ON OR AFTER this date is NVS (nieuwe verwerkingsstraat); before
    #    it, OVS (oude). This is the authoritative business rule for KOOP Plooi.
    #    Set empty to disable. (ISO date, e.g. 2026-04-28.)
    pipeline_nvs_cutoff: str = "2026-04-28"

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
    # Public open-data portal (open.overheid.nl). The metadata API resolves a
    # document's official title + publication metadata that the logs don't carry;
    # the details template is the human-browsable page. Best-effort, cached.
    portal_meta_api: str = "https://open.overheid.nl/overheid/openbaarmakingen/api/v0/zoek/{id}"
    portal_details_template: str = "https://open.overheid.nl/details/{id}"
    portal_meta_timeout: float = 6.0       # seconds; keep short — it must never stall a trace
    portal_meta_ttl: int = 3600            # seconds; published metadata changes slowly
    # On a corporate/VPN network that intercepts TLS, the portal's certificate
    # won't validate against the container's CA bundle and every lookup fails
    # (no titles, every published doc looks "not live"). This endpoint is public,
    # read-only and carries no credentials, so on a TLS-verification failure we
    # retry once without verification rather than lose all enrichment.
    portal_meta_insecure_fallback: bool = True

    # Documents activity tab: which logs count as document events, and how many to feed.
    document_event_query: str = "ronl OR document OR bestand OR upload OR publicatie OR versie"
    document_event_size: int = 200
    # Pipeline-health scan: look back this far for documents that entered the
    # pipeline but never finished ("stuck"), scanning up to N recent events.
    pipeline_health_lookback_minutes: int = 1440  # 24h
    pipeline_health_scan_size: int = 1000
    # Verify at most this many flagged candidates against the public portal
    # (cached, best-effort) to drop false 'stuck' alarms for live documents.
    pipeline_health_verify_max: int = 40
    # ── Incident tracking (only genuinely stuck/failed docs, durable) ──────────
    # A document is only an INCIDENT once it has gone silent (no new log events)
    # for at least this long AND is not live — so a document still moving through
    # the pipeline (e.g. a transient error at Intake that clears in minutes) is
    # never flagged. This is the settle/grace period.
    incident_settle_minutes: int = 45
    # Open incidents are persisted here so genuine problems stay visible for days
    # — across restarts and beyond the scan window — until they are actually
    # resolved (published or progressed). Put this on a mounted volume.
    incident_db_path: str = "/app/data/incidents.db"
    # Per scan, re-check at most this many open incidents that fell outside the
    # scan window against the public portal to auto-resolve published ones.
    incident_reverify_max: int = 60
    # Best-effort source fields for a document's organization (tune to your logs).
    doc_org_fields: str = "organisatie,bronorganisatie,publisher,organization,source.organization,verantwoordelijke,bron,afzender"
    # Known document sources (bron) for the errors-by-source table.
    processing_sources: str = "aanleverloket,dpc,oep-ob,oep,plooi-api,ronl-archief,ronl,roo,woo-idx"

    # Chat intelligence: when a question names a document id (UUID or ronl-…),
    # trace it across this wide window instead of the narrow selected range —
    # so "why was this published twice?" finds events from hours/days earlier.
    chat_doc_scan_days: int = 30
    chat_doc_scan_size: int = 200
    # When a generic question finds nothing in the selected view+window, broaden
    # the search to all views over this many minutes (default 24h) before giving up.
    chat_widen_minutes: int = 1440
    # A health/status question reuses the dashboard's cached snapshot + pipeline
    # health. If that data is cold and the cluster is slow, don't let it stall the
    # whole answer — time-box it and degrade to a plain log search after this many
    # seconds. The SSE keepalive ping keeps the connection open meanwhile.
    chat_health_timeout: float = 25.0
    # Seconds between SSE keepalive pings on /chat. Keeps proxies from closing a
    # slow streaming answer (e.g. a long local-LLM generation) as idle.
    chat_sse_ping_seconds: int = 10

    # Ollama
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1:8b"
    # Robustness: Ollama's default context window is only 2048 tokens. A prompt
    # that exceeds it is SILENTLY truncated from the front (cutting off the real
    # question), after which the model often returns an EMPTY answer. We set the
    # window explicitly and bound the output so a large log context can never
    # produce a blank response. num_ctx must comfortably exceed the trimmed
    # prompt budget below.
    ollama_num_ctx: int = 8192
    ollama_num_predict: int = 1024
    # Hard cap on the characters of log context sent to the model, so the prompt
    # can never overflow the context window no matter how many log lines were
    # gathered. At ~4 chars/token this stays well under num_ctx with headroom for
    # the system prompt, the question, and the generated answer.
    chat_context_char_budget: int = 16000

    # Mistral (OpenAI-compatible API)
    mistral_api_key: str = ""
    mistral_base_url: str = "https://api.mistral.ai/v1"
    mistral_model: str = "mistral-large-latest"

    # LLM Provider selection: "ollama" or "mistral"
    llm_provider: str = "ollama"

    # ── Notifications / daily digest ──────────────────────────
    # Email (SMTP). For Gmail use an app password (plain login is blocked).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    digest_recipients: str = ""        # comma-separated email addresses
    # Slack / Teams / Discord / generic incoming webhook (recommended — easiest).
    digest_webhook_url: str = ""
    # Service-account credentials for the unattended daily digest (send_digest.py).
    digest_kibana_user: str = ""
    digest_kibana_password: str = ""

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

    @staticmethod
    def _csv_lower(value: str) -> list[str]:
        return [v.strip().lower() for v in value.split(",") if v.strip()]

    @property
    def pipeline_nvs_value_list(self) -> list[str]:
        return self._csv_lower(self.pipeline_nvs_values)

    @property
    def pipeline_ovs_value_list(self) -> list[str]:
        return self._csv_lower(self.pipeline_ovs_values)

    @property
    def pipeline_nvs_index_list(self) -> list[str]:
        return self._csv_lower(self.pipeline_nvs_index)

    @property
    def pipeline_ovs_index_list(self) -> list[str]:
        return self._csv_lower(self.pipeline_ovs_index)

    @property
    def pipeline_nvs_cutoff_date(self) -> date | None:
        """Parsed NVS/OVS switchover date, or None if unset/invalid."""
        raw = (self.pipeline_nvs_cutoff or "").strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None

    @property
    def pipeline_reliable_configured(self) -> bool:
        """True when a trusted pipeline signal (field, index, or date cutoff) is
        configured — in which case classification is authoritative (a document
        that matches none is reported as unknown, never free-text guessed)."""
        return bool(
            self.pipeline_field
            or self.pipeline_nvs_index_list
            or self.pipeline_ovs_index_list
            or self.pipeline_nvs_cutoff_date
        )

    @property
    def processing_source_list(self) -> list[str]:
        """Known sources, longest-first so 'ronl-archief' wins over 'ronl'."""
        items = [s.strip() for s in self.processing_sources.split(",") if s.strip()]
        return sorted(items, key=len, reverse=True)

    @property
    def digest_recipient_list(self) -> list[str]:
        return [e.strip() for e in self.digest_recipients.split(",") if e.strip()]

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
