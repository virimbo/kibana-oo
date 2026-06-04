from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Kibana (we connect through Kibana, not directly to ES)
    kibana_url: str = "https://kibana-prod.cicd.s15m.nl"
    kibana_space: str = "koop-plooi-prod"
    es_log_index: str = "logs-*"
    es_metric_index: str = "logs-*"

    # Ollama
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1:8b"

    # Backend
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
