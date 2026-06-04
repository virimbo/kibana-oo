from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Elasticsearch
    elasticsearch_url: str = "https://elasticsearch-prod.cicd.s15m.nl:9200"
    elasticsearch_api_key: str | None = None
    elasticsearch_user: str | None = None
    elasticsearch_password: str | None = None
    kibana_space: str = "koop-plooi-prod"
    es_log_index: str = "filebeat-*,logs-*"
    es_metric_index: str = "metricbeat-*,metrics-*"

    # Ollama
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1:8b"

    # Backend
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
