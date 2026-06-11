#!/usr/bin/env bash
#
# KIBANA-OO — installer / launcher (Linux, macOS, and Git Bash on Windows).
#
# The bash counterpart of start.bat: it preflight-checks Docker, prepares a
# private .env, builds and starts the stack, pulls the local LLM model, and
# verifies the services answer before telling you it's ready.
#
# Safe to re-run: it never overwrites an existing .env and only pulls the model
# if it isn't present yet.

set -euo pipefail

# ── pretty output ──────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
  BLUE=$'\033[0;34m'; NC=$'\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; BLUE=''; NC=''
fi
info()    { echo "${BLUE}[INFO]${NC} $1"; }
ok()      { echo "${GREEN}[ OK ]${NC} $1"; }
warn()    { echo "${YELLOW}[WARN]${NC} $1" >&2; }
error()   { echo "${RED}[ERROR]${NC} $1" >&2; }

# Run from the script's own directory so relative paths always resolve.
cd "$(dirname "$0")"

# ── configuration ──────────────────────────────────────────────────────────
COMPOSE_PROJECT="kibana-oo"
OLLAMA_CONTAINER="kibana-oo-ollama"
FRONTEND_URL="http://localhost:3000"
BACKEND_URL="http://localhost:8000"
DEFAULT_MODEL="llama3.1:8b"

# ── docker preflight ───────────────────────────────────────────────────────
require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    error "Docker is not installed."
    error "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    error "Docker is installed but not running."
    error "Open Docker Desktop, wait until it says 'Running', then re-run this script."
    exit 1
  fi
  # Compose v2 is a docker subcommand; v1 'docker-compose' is EOL.
  if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    warn "Using legacy docker-compose v1; upgrading to Docker Compose v2 is recommended."
    COMPOSE="docker-compose"
  else
    error "Docker Compose is not available. Install Docker Desktop (it bundles Compose v2)."
    exit 1
  fi
  ok "Docker is running ($(docker --version | awk '{print $3}' | tr -d ','))."
}

# ── .env handling (security-sensitive) ─────────────────────────────────────
prepare_env() {
  if [[ ! -f .env.example ]]; then
    error ".env.example is missing — cannot create configuration."
    exit 1
  fi
  if [[ ! -f .env ]]; then
    info "Creating .env from .env.example…"
    cp .env.example .env
    ok "Created .env."
  else
    info ".env already exists — keeping your settings."
  fi

  # .env holds Kibana credentials and any API keys: keep it owner-only.
  chmod 600 .env 2>/dev/null \
    && ok "Locked down .env permissions (600)." \
    || warn "Could not chmod .env (non-POSIX filesystem?) — keep it private manually."

  # Warn loudly if real credentials haven't been filled in yet. We read .env
  # without printing any secret values.
  if grep -qE '^[[:space:]]*ELASTICSEARCH_PASSWORD[[:space:]]*=[[:space:]]*$' .env \
     || grep -qiE '^[[:space:]]*ELASTICSEARCH_PASSWORD[[:space:]]*=[[:space:]]*(your|changeme)' .env; then
    warn "ELASTICSEARCH_PASSWORD looks empty/placeholder in .env."
    warn "Edit .env and set your Kibana username and password before logging in."
  fi
}

# Read a KEY=value from .env without sourcing it (avoids executing arbitrary
# content). Prints the value, or nothing if the key is absent.
env_get() {
  local key="$1"
  sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" .env 2>/dev/null | head -n1 | tr -d '\r'
}

# ── stack lifecycle ────────────────────────────────────────────────────────
start_stack() {
  info "Building and starting services (this can take a few minutes the first time)…"
  $COMPOSE up --build -d
  ok "Containers are up."
}

pull_model() {
  local model
  model="$(env_get OLLAMA_MODEL)"
  [[ -n "$model" ]] || model="$DEFAULT_MODEL"

  info "Waiting for Ollama to accept connections…"
  local i
  for i in $(seq 1 30); do
    if docker exec "$OLLAMA_CONTAINER" ollama list >/dev/null 2>&1; then
      break
    fi
    sleep 2
    if [[ "$i" == "30" ]]; then
      warn "Ollama did not become ready in time; you can pull the model later with:"
      warn "  docker exec $OLLAMA_CONTAINER ollama pull $model"
      return 0
    fi
  done

  if docker exec "$OLLAMA_CONTAINER" ollama list 2>/dev/null | grep -q "${model%%:*}"; then
    ok "LLM model '$model' already present."
  else
    info "Downloading LLM model '$model' (first time only, can take several minutes)…"
    docker exec "$OLLAMA_CONTAINER" ollama pull "$model" \
      && ok "Model '$model' ready." \
      || warn "Model pull failed; retry later with: docker exec $OLLAMA_CONTAINER ollama pull $model"
  fi
}

# ── health checks ──────────────────────────────────────────────────────────
http_ok() {
  # True if the URL answers with any HTTP status (service is listening).
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -o /dev/null --max-time 5 "$url" 2>/dev/null
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O /dev/null --timeout=5 "$url" 2>/dev/null
  else
    return 0  # no http client available — skip the check rather than fail
  fi
}

wait_for() {
  local name="$1" url="$2" i
  info "Waiting for $name…"
  for i in $(seq 1 30); do
    if http_ok "$url"; then ok "$name is responding."; return 0; fi
    sleep 2
  done
  warn "$name did not respond at $url yet — it may still be warming up."
  return 0
}

# ── main ───────────────────────────────────────────────────────────────────
main() {
  echo
  echo "============================================"
  echo "   KIBANA-OO — AI Log Assistant installer"
  echo "============================================"
  echo

  require_docker
  prepare_env
  start_stack
  pull_model
  wait_for "Backend" "$BACKEND_URL/health" || true
  wait_for "Frontend" "$FRONTEND_URL" || true

  echo
  echo "============================================"
  ok "KIBANA-OO is ready."
  echo "   Open:  $FRONTEND_URL"
  echo "   Log in with your Kibana username/password."
  echo
  echo "   Stop with:   $COMPOSE down"
  echo "   Logs with:   $COMPOSE logs -f backend"
  echo "============================================"
}

main "$@"
