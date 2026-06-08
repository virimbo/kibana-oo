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


settings = Settings()
