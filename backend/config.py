from datetime import date

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Kibana (we connect through Kibana, not directly to ES)
    kibana_url: str = "https://kibana-prod.cicd.s15m.nl"
    kibana_space: str = "koop-plooi-prod"
    # OIDC issuer used to initiate Kibana login (GET /api/security/oidc/initiate_login?iss=…).
    # Kibana's provider-selector POST route is disabled server-side, so we initiate via the
    # issuer instead of a hardcoded provider name. Change here / in .env if SSO moves again.
    kibana_oidc_issuer: str = "https://sso-gn2.cicd.s15m.nl/realms/SP"
    es_log_index: str = "logs-*"
    es_metric_index: str = "logs-*"

    # Data views the user can choose to query (comma-separated ES index patterns).
    # Acts as a whitelist — only these patterns may be searched.
    data_views: str = "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp,apm-*"
    default_data_view: str = "logs-*"

    # ── Observability overview (Beheer → Observability) ──────────────────────
    # Ingestion-freshness thresholds for the "Datastroom" signal: the age of the
    # newest log is OK up to _ok_minutes, a warning up to _warn_minutes, else
    # critical. Additive; the page is a read-only roll-up of existing facts.
    obs_fresh_ok_minutes: int = 15
    obs_fresh_warn_minutes: int = 60

    # Dashboard
    dashboard_cache_ttl: int = 60          # seconds; summary cache TTL
    dashboard_timezone: str = "Europe/Amsterdam"
    dashboard_admins: str = ""             # comma-separated admin usernames/emails
    # Super admins (comma-separated emails): the root of trust. They have EVERY
    # feature implicitly and are the only ones who can manage the authorisation
    # matrix. Defined here in config so it can never be revoked via the UI.
    super_admins: str = ""
    # Views treated as a superset of others — excluded from rollup totals to avoid
    # double counting (still shown as their own per-system tile).
    dashboard_superset_views: str = "logs-*"
    # Index patterns where TLS certificate monitoring data (Heartbeat / Synthetics)
    # lives. Used by the certificate-expiry cards. Read-only discovery.
    cert_index: str = "heartbeat-*,synthetics-*"
    # Public hosts whose TLS certificate we ACTIVELY probe (independent of Kibana),
    # so the expiry countdown and any trust/chain/hostname issues are always
    # visible. Comma-separated host[:port]. Read-only outbound TLS.
    cert_probe_hosts: str = ("open.overheid.nl,doculoket.overheid.nl,"
                             "open-acc.overheid.nl,doculoket-acc.overheid.nl,"
                             "gateway-zoek.koop-plooi-tst.test5.s15m.nl,"
                             "gateway-service.koop-plooi-tst.test5.s15m.nl")
    cert_probe_timeout: float = 6.0        # seconds; keep short so it never stalls the card
    cert_check_revocation: bool = True     # best-effort OCSP revocation check per cert
    # Daily proactive TLS audit: re-checks every host on this interval and alerts
    # (via the digest webhook / email) when a host's grade is WARN or CRITICAL.
    cert_audit_interval_hours: float = 24.0
    cert_alert_enabled: bool = True

    # ── Aanleverfouten monitor (documents rejected at delivery/intake) ──
    # Documents that failed at the doculoket/aanlever stage ("aanleverfout") and
    # were never published. Detected in the logs, reconciled against the portal
    # (a published doc = fixed & re-delivered), tracked as durable incidents.
    # See aanlever.py + docs/aanleverfouten.md.
    aanlever_enabled: bool = True
    aanlever_data_view: str = "ds-prod5-koop-plooi*"
    aanlever_lookback_hours: float = 48.0
    # Detection — structured-field-first (option D). If the logs carry a status
    # field, set its dotted name + the values that mean "rejected"; it then takes
    # precedence. Leave the field empty to use the stage+pattern fallback below.
    aanlever_status_field: str = ""
    aanlever_status_values: str = "aanleverfout,afgekeurd,geweigerd,rejected,invalid"
    # Fallback signal: an ERROR at an intake/aanlever service, OR a message matching
    # these phrases. Tune to the real ds-prod5-koop-plooi logs.
    aanlever_services: str = "doculoket,aanlever,aanlevering,gateway,ingest,intake"
    aanlever_patterns: str = ("aanleverfout,afgekeurd,geweigerd,validatie,validation,"
                              "schema,herstel,opnieuw aanleveren,rejected,invalid,niet geldig")
    aanlever_settle_minutes: int = 10     # error must persist this long to count
    aanlever_alert_enabled: bool = True   # alert (webhook/email) on NEW aanleverfouten

    # ── RabbitMQ DLQ monitor ──────────────────────────────────────────────
    # Read-only Management-API monitoring of dead-letter queues. Inert until the
    # api_url + user + password are set. See rabbitmq_dlq.py + docs/rabbitmq-dlq.md.
    rabbitmq_api_url: str = "https://rabbitmq.koop-plooi-prd.prod5.s15m.nl"
    rabbitmq_user: str = ""
    rabbitmq_password: str = ""
    rabbitmq_dlq_suffix: str = ".dlq"     # queues ending in this are dead-letter queues
    rabbitmq_critical_messages: int = 100  # a DLQ at/above this depth is CRITICAL
    rabbitmq_poll_interval_minutes: float = 5.0
    rabbitmq_alert_enabled: bool = True
    rabbitmq_timeout: float = 10.0

    # ── DLQ Intelligence (read-only peek + smart verdict) ─────────────────────
    # Additive & OFF by default. When true, dlq_intel peeks dead-lettered messages
    # (read-only, requeued untouched) to explain WHY they failed and produce a smart
    # verdict (depth + age + trend + reason). Feeds the dashboard card, the DLQ
    # Intelligence page and the alert content. See dlq_intel.py.
    dlq_intel_enabled: bool = False
    dlq_intel_interval: int = 90        # seconds between intelligence passes
    dlq_intel_peek_max: int = 20        # max messages peeked per queue per pass
    dlq_intel_parked_days: float = 2.0  # oldest-age beyond this = "geparkeerd" warn
    dlq_intel_grow_delta: int = 5       # depth rise vs prior sample → "growing"
    dlq_intel_history: int = 50         # depth samples kept per queue (trend)

    # ── Regression test (post-release health gate for the public portal) ──
    # A robust, data-driven suite run after a prod release to confirm
    # open.overheid.nl still works. See regression.py for the default checks.
    regression_target_url: str = "https://open.overheid.nl"
    # A known, published document (UUID) used by the content-correctness checks.
    regression_known_doc_id: str = "1a7e9fc7-0be6-4815-90a9-e733d79a5f07"
    # Keep at most this many runs; pruning drops oldest PASS first (failures live
    # longest) and never removes the most recent run.
    regression_history_cap: int = 1000
    # Set to enable the token-authenticated CI trigger (POST /regression/trigger
    # with header X-Regression-Token). Empty = endpoint disabled.
    regression_trigger_token: str = ""
    regression_alert_enabled: bool = True   # alert via webhook/email when a run FAILs

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
    # Trust gate for the "stuck document" health signal. A document is only ever
    # "at-risk" once its NEWEST event is older than this — a doc whose latest event
    # is younger is still within normal processing time (in-flight), NOT stuck. This
    # stops a freshly-submitted, still-moving document from being counted.
    pipeline_settle_minutes: int = 90
    # Exclude APM traces (data_stream.dataset: apm.*) from document queries — they are
    # microservice errors, not documents; their hex ids were inflating the stuck count.
    pipeline_exclude_apm: bool = True
    # Open incidents older than this are auto-resolved ('stale') — they are no
    # longer actionable and would otherwise pile up as a historic backlog that
    # inflates the count. Draining them keeps the list + count ACTIONABLE.
    incident_max_age_hours: int = 72
    # Observability "Publicatie" thresholds (configurable so "critical" is
    # meaningful): n==0 ok, obs_stuck_warn ≤ n < obs_stuck_crit warn, ≥ crit.
    obs_stuck_warn: int = 1
    obs_stuck_crit: int = 25
    # Open incidents are persisted here so genuine problems stay visible for days
    # — across restarts and beyond the scan window — until they are actually
    # resolved (published or progressed). Put this on a mounted volume.
    incident_db_path: str = "/app/data/incidents.db"
    # Shared database for feature run/audit logs (regression runs, etc.) — one
    # file, a table per feature. Put it on the same mounted volume. See db.py.
    app_db_path: str = "/app/data/kibana_oo.db"
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
    # CPU-only host: the 8B model timed out here (no GPU, ~160 MiB free RAM), so the
    # local default is the smaller llama3.2:3b — it actually responds on CPU. The
    # bigger win is keeping it resident (OLLAMA_KEEP_ALIVE=-1 on the ollama
    # container, see docker-compose.yml) so chats don't pay a ~2-min reload each
    # time. Switch back to llama3.1:8b only on a GPU host. (Mistral is unaffected.)
    ollama_model: str = "llama3.2:3b"
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

    # LLM robustness timeouts (apply to both providers). These guarantee the chat
    # can never hang: a short connect timeout means an unreachable provider fails
    # in seconds (not minutes), and the first-token deadline means a provider that
    # accepts the connection but then stalls is abandoned so the recovery path
    # (non-streaming retry → local model → deterministic summary) takes over.
    llm_connect_timeout: float = 8.0        # seconds to establish the connection
    llm_read_timeout: float = 600.0         # seconds between bytes once flowing (long answers OK)
    llm_first_token_timeout: float = 30.0   # seconds to wait for the FIRST streamed token

    # LLM Provider selection: "ollama" or "mistral"
    llm_provider: str = "ollama"

    # ── PII redaction (before the LLM) ────────────────────────────────────────
    # When true, the SHARED context builders mask obvious personal data (emails,
    # IP addresses, JWT/bearer-like tokens) from the log context BEFORE it reaches
    # any provider — especially the Mistral cloud. Document ids, service names,
    # HTTP status codes, ISO timestamps and *.overheid.nl hostnames are preserved
    # for analysis. See redact.py. Flip to false to roll back instantly.
    llm_redact_pii: bool = True

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

    # ── SmartContextPanel (hover → right-side card intelligence) ──────────────
    # Additive, off by default. When true, hovering/focusing a dashboard card
    # opens a right-side panel with component info + vault TODOs + optional AI.
    # Flip to false (or leave default) to roll back instantly. See
    # context_engine.py + context_api.py + docs/KIBANA-OO/Smart context paneel.md.
    smart_context_enabled: bool = False
    # Path to the Obsidian vault to read component notes/TODOs from. Empty =
    # auto-discover docs/KIBANA-OO relative to the code (local dev). In a
    # container, mount the vault and set SMART_CONTEXT_VAULT_PATH.
    smart_context_vault_path: str = ""
    # Runbook ("WAT TE DOEN NU"): warn that the runbook note is possibly outdated
    # when its `bijgewerkt:` date is older than this many days.
    smart_context_runbook_stale_days: int = 180

    # ── Uptime / availability monitor (Beschikbaarheid) ───────────────────────
    # Background HTTP probe of a configured list of sites (PROD/ACC/TEST), shown
    # as a prominent top-of-dashboard board. Additive & off by default. See
    # uptime.py + uptime_api.py + docs/KIBANA-OO/Beschikbaarheid (uptime).md.
    uptime_enabled: bool = False
    # One target per line: `name | env | url | expected | internal?`
    #   expected = acceptable status tokens (2xx,3xx,4xx,5xx) or codes (200,302)
    #   internal = VPN-only host → a connect failure is "unreachable" (grey),
    #              not "down" (red); public hosts treat a failure as "down".
    uptime_targets: str = (
        "open.overheid.nl | PROD | https://open.overheid.nl | 2xx,3xx\n"
        "doculoket.overheid.nl | PROD | https://doculoket.overheid.nl | 2xx,3xx\n"
        "admin (login) | PROD | https://admin-main-admin.koop-plooi-prd.prod5.s15m.nl/login | 2xx,3xx | internal\n"
        "open-acc.overheid.nl | ACC | https://open-acc.overheid.nl | 2xx,3xx\n"
        "doculoket-acc.overheid.nl | ACC | https://doculoket-acc.overheid.nl | 2xx,3xx\n"
        "gateway-zoek (test) | TEST | https://gateway-zoek.koop-plooi-tst.test5.s15m.nl/ | 2xx,3xx,401,404 | internal\n"
        "gateway-service (test) | TEST | https://gateway-service.koop-plooi-tst.test5.s15m.nl/ | 2xx,3xx,401,404 | internal"
    )
    uptime_interval: int = 60            # seconds between full probe cycles
    uptime_timeout: float = 8.0          # per-request timeout (seconds)
    uptime_degraded_ms: int = 2000       # slower than this (but up) = DEGRADED
    uptime_settle_minutes: float = 2.0   # DOWN must persist this long before alerting
    uptime_alert_enabled: bool = True    # alert (webhook/email) when a site goes DOWN
    uptime_history: int = 30             # rolling samples kept per site (sparkline/uptime%)

    # ── Service health (backend microservices) ────────────────────────────────
    # Additive & OFF by default. Read-only HTTP-probes the KOOP/Plooi backend
    # services (Spring actuators + service/UI endpoints), grouped per service, shown
    # as a dedicated dashboard card. Internal/VPN-honest: a connect-fail is
    # "unreachable" (grey), a 5xx / actuator DOWN is "down" (red). See
    # service_health.py + docs/KIBANA-OO/Service health.md.
    service_health_enabled: bool = False
    service_health_interval: int = 60        # seconds between probe cycles
    service_health_timeout: float = 8.0      # per-request timeout (seconds)
    service_health_degraded_ms: int = 2500   # slower than this (but up) = degraded

    # Edge / ingress HTTP health (PROD): 5xx, gateway errors (502/503/504),
    # time-outs (504), elevated latency — from the ingress access logs; plus pod
    # restarts (Prometheus, best-effort). Read-only, additive. See edge_health.py.
    edge_enabled: bool = True
    edge_data_view: str = "ds-prod5-koop-plooi*"   # ingress/nginx access logs
    edge_status_field: str = "status"              # HTTP status code
    edge_latency_field: str = "request_time"       # nginx request_time, in SECONDS
    edge_window_minutes: int = 15
    edge_min_requests: int = 50                    # ignore tiny samples for the ratio
    edge_5xx_ratio_warn: float = 1.0               # percent of requests
    edge_5xx_ratio_crit: float = 5.0
    edge_gateway_warn: int = 1                      # 502/503/504 count in the window
    edge_gateway_crit: int = 20
    edge_latency_warn_ms: int = 1000
    edge_latency_crit_ms: int = 3000
    edge_pod_restarts_warn: int = 1                 # via Prometheus, last 1h
    edge_pod_restarts_crit: int = 5
    edge_pod_restart_query: str = "sum(increase(kube_pod_container_status_restarts_total[1h]))"
    # One service per line: `Name | url | url …`. `kind` is inferred (actuator if the
    # URL contains "actuator", else service). Empty → no services probed.
    service_health_targets: str = (
        "Harvester | https://harvester-production-actuator.koop-plooi-prd.prod5.s15m.nl/actuator | https://harvester-production-service.koop-plooi-prd.prod5.s15m.nl/locations\n"
        "Sitemapvalidator | https://msvc-sitemapsvalidator.koop-plooi-prd.prod5.s15m.nl/validator/rapport\n"
        "Publicatiebeheer | https://msvc-publicatiebeheer.koop-plooi-prd.prod5.s15m.nl\n"
        "Antivirus | https://antivirus-production-actuator.koop-plooi-prd.prod5.s15m.nl/actuator | https://antivirus-production-service.koop-plooi-prd.prod5.s15m.nl/\n"
        "Jaeger | https://jaeger-koop.koop-plooi-prd.prod5.s15m.nl\n"
        "Dictionary | https://dictionary-actuator.koop-plooi-prd.prod5.s15m.nl | https://dictionary-service.koop-plooi-prd.prod5.s15m.nl/lijsten/Publisher\n"
        "Registration | https://registration-production-actuator.koop-plooi-prd.prod5.s15m.nl | https://registration-production-service.koop-plooi-prd.prod5.s15m.nl/processen\n"
        "Repository | https://repository-production-actuator.koop-plooi-prd.prod5.s15m.nl/actuator | https://repository-production-service.koop-plooi-prd.prod5.s15m.nl/\n"
        "DCN | https://production-dcn-actuator.koop-plooi-prd.prod5.s15m.nl/actuator/hawtio/ | https://production-dcn-admin.koop-plooi-prd.prod5.s15m.nl/statistieken\n"
        "Admin | https://admin-main-admin.koop-plooi-prd.prod5.s15m.nl/home\n"
        "Search | https://search-production-actuator.koop-plooi-prd.prod5.s15m.nl/actuator | https://search-production-service.koop-plooi-prd.prod5.s15m.nl/api/v1/_zoek\n"
        "RabbitMQ | https://rabbitmq.koop-plooi-prd.prod5.s15m.nl/\n"
        "Solr | https://plooi-solr.koop-plooi-prd.prod5.s15m.nl/solr/\n"
        "Keycloak | https://keycloak-admin.koop-plooi-prd.prod5.s15m.nl\n"
        "Documentopslag | https://msvc-documentopslag.koop-plooi-prd.prod5.s15m.nl"
    )

    # Document health signals (Documents page intelligence)
    doc_error_threshold: int = 10      # errors at/above this = critical spike
    doc_error_spike_pct: int = 100     # errors up by ≥ this % (and > 0) = warning spike
    doc_stall_min_prior: int = 1       # prior-window events needed to call 0-now a "stall"
    doc_volume_swing_pct: int = 60     # |events pct change| at/above this = volume signal

    # Monitoring Targets registry (admin-configurable; additive, off by default)
    monitor_enabled: bool = False
    monitor_interval: int = 60        # seconds between poll cycles
    monitor_timeout: int = 8          # per-check HTTP timeout
    monitor_flap_threshold: int = 2   # consecutive reds before alerting

    # ── Background monitor service-session (unattended ES-based checks) ────────
    # Additive & DORMANT by default. When BOTH user + password are set, the
    # background poll loop logs in via Keycloak once (cached for
    # service_sid_ttl_minutes) and passes the resulting `sid` into run_once so
    # ES-based checks (e.g. log-freshness) actually run unattended. Empty =
    # unchanged behaviour (sid=None, ES checks dormant). Use a READ-ONLY service
    # account. Never raises into the loop. See service_session.py.
    monitor_service_user: str = ""
    monitor_service_password: str = ""
    service_sid_ttl_minutes: int = 30   # re-login when the cached sid is older than this

    # ── Unified alerting (admin-managed RED-state email alerts) ───────────────
    # Additive & OFF by default. When true, a background engine reads the existing
    # monitors (uptime/dlq/cert) read-only and sends admin-configured email alerts
    # with per-scope toggles, cooldown, and recovery. When the engine owns alerting
    # the three legacy inline alerters should be turned OFF (set *_ALERT_ENABLED=
    # false) to avoid duplicate mail. Roll back instantly with ALERTS_ENABLED=false.
    # See alerts.py + alerts_api.py + docs/KIBANA-OO/Alerting (meldingen).md.
    alerts_enabled: bool = False
    alerts_interval: int = 60               # seconds between evaluation passes
    alerts_cooldown_minutes: int = 60       # default per-card anti-spam cooldown
    alerts_default_threshold: str = "warn"  # "critical" or "warn" — min severity to alert (warn = also alert on warnings)
    # ── ES-fed alert categories (need a background service-session sid) ─────────
    # Stuck-document + per-service error-rate/5xx-spike alerts read the dashboard's
    # cached health/snapshot. They stay dormant while no service sid exists.
    #   * error-rate: a service with ≥ alert_errorrate_min error-log hits in the
    #     window is a WARN; ≥ alert_errorrate_crit is CRITICAL.
    #   * stuck docs: cap the per-scan item count to avoid an alert storm; beyond
    #     the cap one summary item is emitted instead.
    alert_errorrate_min: int = 50
    alert_errorrate_crit: int = 200
    alert_stuck_docs_max: int = 25
    # ── Burst control (anti-alert-storm) ──────────────────────────────────────
    # When a single scan would dispatch more than this many NEW alerts of the SAME
    # category (e.g. 26 stuck documents on first activation), send ONE consolidated
    # summary instead of N individual messages. Dedup is untouched — every item's
    # state is still recorded so none re-alert next scan. <= 0 disables the cap
    # (unlimited/old behaviour).
    alert_burst_max: int = 5
    # Comma-separated emails used to SEED the admin-editable recipient list on first
    # run. Empty → seed from digest_recipients. Admin edits live in kibana_oo.db.
    alerts_recipient_seed: str = ""

    # ── Infra / Grafana deep-links ────────────────────────────────────────────
    # One per line: `name | url | env?`. Shown as one-click cards that open the
    # external dashboard in a new tab (admin uses their own Grafana SSO; we store
    # no credentials). See infra_api.py + docs/KIBANA-OO/Grafana en infrastructuur.md.
    grafana_links: str = (
        "CloudNativePG (cnpg-cluster-v5) | "
        "https://grafana-prod.cicd.s15m.nl/d/cloudnative-pg/cloudnativepg?orgId=49"
        "&from=now-7d&to=now&timezone=browser&var-DS_PROMETHEUS=koop-plooi-proxy"
        "&var-operatorNamespace=&var-namespace=koop-plooi-prd&var-cluster=cnpg-cluster-v5"
        "&var-instances=$__all&refresh=30s | PROD"
    )

    # ── Security hardening (sessions, login rate limit, API docs) ─────────────
    # Sessions expire on an absolute TTL and after an idle gap (whichever hits
    # first), so a leaked token can't live forever. Login is rate-limited per
    # client IP to blunt credential-stuffing. API docs are gated OFF by default
    # so the OpenAPI surface isn't exposed in production. See session.py,
    # ratelimit.py + the security-headers middleware in main.py.
    session_ttl_minutes: int = 720          # absolute session lifetime (12h)
    session_idle_minutes: int = 240         # idle timeout — no activity for this long
    login_rate_max: int = 12                # max login attempts per window per IP
    login_rate_window_seconds: int = 60     # sliding window for the login limiter
    expose_api_docs: bool = False           # gate /docs, /redoc, /openapi.json

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
    def aanlever_service_list(self) -> list[str]:
        return self._csv_lower(self.aanlever_services)

    @property
    def aanlever_pattern_list(self) -> list[str]:
        return [p.strip() for p in self.aanlever_patterns.split(",") if p.strip()]

    @property
    def aanlever_status_value_list(self) -> list[str]:
        return [v.strip() for v in self.aanlever_status_values.split(",") if v.strip()]

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
    def alerts_recipient_seed_list(self) -> list[str]:
        """Seed recipients for first run: explicit seed, else the digest list."""
        raw = self.alerts_recipient_seed or self.digest_recipients
        return [e.strip() for e in raw.split(",") if e.strip()]

    @property
    def admin_list(self) -> list[str]:
        seen: list[str] = []
        for name in self.dashboard_admins.split(","):
            name = name.strip()
            if name and name not in seen:
                seen.append(name)
        return seen

    @property
    def super_admin_list(self) -> list[str]:
        return [n.strip().lower() for n in self.super_admins.split(",") if n.strip()]

    @property
    def rabbitmq_configured(self) -> bool:
        return bool(self.rabbitmq_api_url and self.rabbitmq_user and self.rabbitmq_password)

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
