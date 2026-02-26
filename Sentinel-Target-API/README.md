# Sentinel-Target-API

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)
![Uvicorn](https://img.shields.io/badge/Uvicorn-ASGI-4B8BBE)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-Metrics-E6522C?logo=prometheus&logoColor=white)
![Structlog](https://img.shields.io/badge/Logging-Structlog-6A1B9A)
![Google%20GenAI](https://img.shields.io/badge/AI-Gemini%202.5%20Flash-4285F4?logo=google&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

A fault-injection FastAPI target service with Prometheus instrumentation and an AI-powered observer agent for anomaly detection, root-cause analysis, and controlled remediation.

## Key Features

- **Agentic AIOps**: Uses Gemini 2.5 Flash to perform autonomous Root Cause Analysis (RCA).
- **Observability-First**: Full instrumentation with Prometheus metrics and Structured JSON logging.
- **Closed-Loop Remediation**: Automatically "heals" infrastructure failures via whitelisted system actions.

---

## What this project does

- Exposes a FastAPI service with controlled stress endpoints:
    - `/stress/cpu`
    - `/stress/memory`
    - `/stress/latency`
    - `/stress/crash`
- Exposes Prometheus metrics on `/metrics`.
- Emits structured JSON logs using `structlog`.
- Runs a separate `observer_agent.py` process that:
    - Polls Prometheus metrics,
    - Detects anomalies via threshold rules,
    - Uses Gemini (or local model fallback) for diagnosis,
    - Executes only whitelisted remediation commands.

---

## System architecture

```mermaid
flowchart LR
    User[Engineer / Tester] -->|HTTP| API[FastAPI Target Service\napp/main.py]

    API -->|/metrics| Prom[Prometheus\n:9090]
    Prom -->|PromQL query| Obs[Sentinel Observer\nobserver_agent.py]

    Obs -->|diagnosis request| Gemini[Gemini API\n(gemini-2.5-flash)]
    Obs -->|fallback request| LocalAI[Local LLM API\nLM Studio / OpenAI-like endpoint]

    Obs -->|docker logs --tail| DockerLogs[(Container Logs)]
    Obs -->|whitelisted commands| DockerCtl[Docker / Compose]
    DockerCtl --> API

    API -->|JSON logs| DockerLogs
```

---

## Repository layout

```text
Sentinel-Target-API/
├── app/
│   └── main.py                   # FastAPI app + stress endpoints + metrics + structured logs
├── observer_agent.py             # Prometheus polling + AI diagnosis + remediation engine
├── docker-compose.yaml           # API + Prometheus services
├── Dockerfile                    # API image build
├── prometheus.yml                # Prometheus scrape config
├── requirements.txt              # API dependencies
├── requirements-observer.txt     # Observer dependencies
├── .env.template                 # Environment template
└── README.md
```

---

## Endpoints

| Endpoint                                      | Purpose                               |
| --------------------------------------------- | ------------------------------------- |
| `GET /health`                                 | Liveness check                        |
| `GET /metrics`                                | Prometheus scrape endpoint            |
| `GET /stress/cpu?duration=5`                  | CPU saturation simulation             |
| `GET /stress/memory?megabytes=10`             | Memory growth / leak simulation       |
| `GET /stress/latency?min_delay=1&max_delay=5` | Artificial latency simulation         |
| `GET /stress/crash`                           | Random unhandled exception simulation |

---

## How to run

### 1) Prerequisites

- Docker + Docker Compose
- Python 3.10+ (for `observer_agent.py`)
- (Optional) Gemini API key and/or local LM Studio endpoint

### 2) Configure environment

Create `.env` from template:

```bash
cp .env.template .env
```

On Windows CMD:

```bat
copy .env.template .env
```

Update values in `.env` as needed:

```dotenv
PROMETHEUS_URL=http://localhost:9090
GEMINI_API_KEY=your_gemini_key
LM_STUDIO_URL=http://localhost:1234/api/v1/chat
CPU_THRESHOLD=0.5
LATENCY_THRESHOLD=2.0
```

> Note: `LATENCY_THRESHOLD` is used by `observer_agent.py` and can be added manually even if not present in `.env.template`.

### 3) Start API + Prometheus

```bash
docker compose up --build -d
```

Verify:

- API health: `http://localhost:8000/health`
- API metrics: `http://localhost:8000/metrics`
- Prometheus UI: `http://localhost:9090`

### 4) Run observer agent

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-observer.txt
python observer_agent.py
```

Windows CMD:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-observer.txt
python observer_agent.py
```

### 5) Trigger failure modes (demo)

```bash
# CPU pressure (10s)
curl "http://localhost:8000/stress/cpu?duration=10"

# Latency spike
curl "http://localhost:8000/stress/latency?min_delay=2&max_delay=4"

# Crash simulation
curl "http://localhost:8000/stress/crash"
```

---

## Demo logs (proof of behavior)

### A) API service logs (structured JSON)

```log
{"method": "GET", "path": "/health", "status": 200, "duration_s": 0.0019, "event": "request_processed", "level": "info", "logger": "app.main", "timestamp": "2026-02-26T12:05:18.403771Z"}
{"duration": 10, "event": "cpu_stress_started", "level": "info", "logger": "app.main", "timestamp": "2026-02-26T12:06:02.114202Z"}
{"duration": 10, "primes_found": 108742, "event": "cpu_stress_completed", "level": "info", "logger": "app.main", "timestamp": "2026-02-26T12:06:12.118449Z"}
{"method": "GET", "path": "/stress/cpu", "status": 200, "duration_s": 10.0047, "event": "request_processed", "level": "info", "logger": "app.main", "timestamp": "2026-02-26T12:06:12.119023Z"}
{"exception_type": "ConnectionError", "event": "crash_stress_triggered", "level": "warning", "logger": "app.main", "timestamp": "2026-02-26T12:06:34.019312Z"}
{"error": "Simulated ConnectionError: Database unreachable", "path": "/stress/crash", "type": "ConnectionError", "event": "unhandled_exception", "level": "error", "logger": "app.main", "timestamp": "2026-02-26T12:06:34.020114Z"}
{"method": "GET", "path": "/stress/crash", "status": 500, "duration_s": 0.0023, "event": "request_processed", "level": "info", "logger": "app.main", "timestamp": "2026-02-26T12:06:34.020532Z"}
```

### B) Observer logs (detection + AI diagnosis + action)

```log
Starting SentinelObserver... Polling every 30 seconds.
Thresholds - CPU: 0.5, Latency: 2.0s
[2026-02-26 12:06:30] CPU: 0.7314, P90 Latency: 2.61s

[!] Anomalous activity detected. Consulting Gemini/Local AI...
[*] Attempting analysis with model: gemini-2.5-flash (gemini)

============================================================
🤖 AI DIAGNOSIS REPORT
============================================================
Model Used       : gemini-2.5-flash
Severity         : High
Root Cause       : CPU and request latency surged after synthetic stress traffic; one endpoint also triggered an unhandled exception.
Remediation Step : docker-compose restart
============================================================

[!] WARNING: About to execute system command: docker-compose restart
[*] AI-Suggested Action: Executing docker-compose restart...
[*] Command executed successfully.
[*] Waiting 30 seconds for the service to stabilize...
[+] Healing was successful! The service is healthy.
Sleeping for 60 seconds after anomaly detection...
```

---

## Prometheus queries used by observer

- CPU rate (1m):
    - `rate(process_cpu_seconds_total[1m])`
- P90 request latency (1m):
    - `histogram_quantile(0.90, sum(rate(http_request_duration_seconds_bucket[1m])) by (le))`

---

## Safe remediation model

`observer_agent.py` executes only a strict allowlist:

- `docker-compose restart`
- `docker-compose stop`
- `docker-compose up -d`
- `docker restart sentinel-target-api`
- `docker stop sentinel-target-api`

Any non-whitelisted command is refused.

---

## Troubleshooting

- Prometheus query errors:
    - Confirm `PROMETHEUS_URL` points to active Prometheus.
- No AI diagnosis from Gemini:
    - Ensure `GEMINI_API_KEY` is valid.
- Local fallback model errors:
    - Check `LM_STUDIO_URL` and response schema compatibility.
- Docker log collection fails:
    - Verify Docker daemon is running and container name matches `sentinel-target-api`.

---

## Notes

- The stress endpoints intentionally create instability; do not expose this service publicly.
- For production-like experiments, isolate this stack in a dedicated test environment.

---

Author: Abdulhadi Muntashir – Aspiring Cloud/MLOps Engineer.

[Connect on LinkedIn](https://www.linkedin.com/in/abdulhadi-muntashir/)
