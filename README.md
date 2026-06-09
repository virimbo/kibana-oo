# KIBANA-OO — AI Log Assistant

Ask questions about your Kibana logs in plain language. KIBANA-OO uses LLAMA (AI model running on your computer) to search and summarize your Elasticsearch logs.

> **Developers:** see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full architecture, data-flow diagrams, modules, endpoints, configuration, and the monitoring dashboard design.

## What you need

- **Windows 10/11**
- **Docker Desktop** — download from https://www.docker.com/products/docker-desktop/
- **16 GB RAM** (minimum)
- **Your Kibana username and password**

## How to start (3 steps)

### Step 1: Install Docker Desktop

1. Download from https://www.docker.com/products/docker-desktop/
2. Install and restart your computer if asked
3. Open Docker Desktop and wait until it says "Running" (green icon in taskbar)

### Step 2: Fill in your credentials

1. Open the `KIBANA-OO` folder
2. Double-click `start.bat`
3. It will open a file called `.env` in Notepad
4. Change these two lines:
   ```
   ELASTICSEARCH_USER=your-kibana-username
   ELASTICSEARCH_PASSWORD=your-kibana-password
   ```
   Replace `your-kibana-username` and `your-kibana-password` with your real Kibana login
5. Save the file (Ctrl+S) and close Notepad

### Step 3: Start KIBANA-OO

1. Double-click `start.bat` again
2. Wait a few minutes (first time it downloads the AI model, ~5 GB)
3. Your browser opens automatically to http://localhost:3000
4. Start asking questions!

## Example questions you can ask

- "Are there any errors in the last hour?"
- "Show me recent log activity"
- "What happened in the last 30 minutes?"
- "Are there any warnings from service X?"
- "Summarize today's errors"

## How to stop

Double-click `stop.bat`

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Docker is not running" | Open Docker Desktop and wait for it to start |
| Page won't load | Wait 1-2 minutes, the services are still starting |
| "Connection error" in chat | Check that Docker Desktop is running |
| Wrong/no results | Make sure your username and password in `.env` are correct |
| Very slow answers | Normal without a GPU — the AI model runs on CPU |

## Architecture (for developers)

```
Browser (localhost:3000)
    |
    v
Frontend (React) --> Backend (FastAPI) --> Elasticsearch (your Kibana cluster)
                         |
                         v
                     Ollama (LLAMA 3.1 AI model)
```

All services run locally in Docker containers. No data leaves your machine — the AI model runs entirely on your computer.
