# PulseWatch

PulseWatch is a distributed infrastructure monitoring and alerting platform. Lightweight agents collect machine telemetry and send it to a FastAPI ingestion service. The React dashboard will present live machine health, telemetry history, and incidents without needing a refresh.

## Architecture

```text
Monitoring agents -> FastAPI ingestion API -> PostgreSQL
                                      |-> alert engine -> email / Discord
                                      |-> WebSocket -> React dashboard
```

## Repository layout

- `backend/` - FastAPI API, WebSocket service, alerting, and persistence.
- `agent/` - Python host-monitoring agent.
- `dashboard/` - React + TypeScript operations dashboard.
- `.github/workflows/` - continuous integration.

## Run locally

Start the foundational services with Docker:

```bash
docker compose up --build
```

The API health check is available at `http://localhost:8000/health` and the dashboard at `http://localhost:5173`.

## Enroll an agent

Register an account and machine through the API docs at `http://localhost:8000/docs`. The enrollment response contains a machine ID and a one-time-displayed agent token. Set them in `agent/.env` using `agent/.env.example` as a guide, then run:

```bash
cd agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a; source .env; set +a
python pulsewatch_agent.py
```

## Discord notifications

Set `DISCORD_WEBHOOK_URL` to a Discord channel webhook before starting the API or Docker Compose. PulseWatch delivers new threshold, service-down, and heartbeat incidents to that channel. Notification delivery is best-effort and never prevents the agent telemetry path from succeeding.

## Database migrations

The application schema is versioned with Alembic. Run migrations before starting the API locally:

```bash
cd backend
alembic upgrade head
```

Docker starts the API only after applying `alembic upgrade head`.

## Failure demonstrations

Run the complete resilience demonstration against a running API:

```bash
pip install -r demo/requirements.txt
python demo/pulsewatch_demo.py
```

The script enrolls three simulated machines, brings them online, opens and acknowledges a CPU incident, opens and resolves an `nginx` service incident, proves local telemetry buffering and replay after a simulated outage, then stops and restores an agent heartbeat. It waits 65 seconds for the intentional heartbeat outage by default; use `--heartbeat-wait-seconds 0` when you only want to exercise the other paths.

To demonstrate a real service failure, configure `PULSEWATCH_SERVICES=nginx` for an enrolled agent, then stop and restart that service on the monitored host. To demonstrate outage detection, stop the agent process and wait 60 seconds for its heartbeat incident.

The agent writes telemetry to a local SQLite buffer before it sends it. Stop the API or disconnect the monitored machine from the network, let a few collection intervals pass, then restore connectivity. The agent replays buffered samples in collection order. Set `PULSEWATCH_BUFFER_PATH` and `PULSEWATCH_BUFFER_MAX_ROWS` to choose the buffer location and maximum retained sample count.

To run the API without Docker:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Roadmap

- Machine registration with scoped agent tokens
- Telemetry ingestion and historical charts
- Heartbeat-based offline detection
- Configurable alert policies and alert history
- Email and Discord notifications
- AWS deployment with infrastructure as code
