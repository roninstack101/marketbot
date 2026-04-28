# ClaudBot — AI Agent System for Business Automation

A production-ready AI agent that understands tasks, plans execution steps,
runs tools, stores memory, enforces safety approvals, and improves outputs
through a feedback loop.

---

## Architecture Overview

```
User / Client
     │
     ▼
┌──────────────────────────────────────────────────┐
│              FastAPI  (port 8000)                 │
│  POST /api/v1/tasks      ← submit task            │
│  GET  /api/v1/tasks/:id  ← poll status + output  │
│  POST /api/v1/approvals/:id/approve              │
│  GET  /api/v1/history    ← past memories          │
└──────────────────────────────────────────────────┘
     │  enqueues job
     ▼
┌──────────────────────────────────────────────────┐
│             Redis  (Celery broker)                │
└──────────────────────────────────────────────────┘
     │  worker picks up
     ▼
┌──────────────────────────────────────────────────┐
│         Celery Worker  (async via asyncio.run)    │
│                                                   │
│  ┌────────────────────────────────────────────┐   │
│  │        LangGraph Agent Pipeline            │   │
│  │                                            │   │
│  │  START → Planner → Executor ─┬─→ Critic → END │
│  │                    ↑         │                 │
│  │                    └─ loop   └─→ END (approval)│
│  └────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
     │  reads/writes
     ▼
┌──────────────────────────────────────────────────┐
│           PostgreSQL (tasks, approvals, memories) │
└──────────────────────────────────────────────────┘
```

### Agent nodes

| Node | Role |
|------|------|
| **Planner** | Decomposes the user task into ordered steps; retrieves memory context |
| **Executor** | Runs each step by dispatching to a tool; enforces the approval gate |
| **Critic** | Scores the output (1–10), requests targeted revisions (max 2 cycles) |

### Tools

| Tool | Description | Requires Approval |
|------|-------------|:-----------------:|
| `generate_campaign` | LLM-powered marketing campaign copy | No |
| `write_email` | Drafts professional email from a brief | No |
| `send_email` | Actually sends email via SMTP | **Yes** |
| `store_data` | Saves key/value to memories table | No |
| `retrieve_data` | Fetches stored records by keyword | No |
| `delete_data` | Permanently removes a record | **Yes** |

---

## Quickstart (Local)

### 1. Clone and set up environment

```bash
git clone <repo-url> claudbot && cd claudbot
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in at minimum:
- `OPENROUTER_API_KEY` (or `ANTHROPIC_API_KEY`)
- `LLM_MODEL`
- PostgreSQL and Redis connection details

### 2. Start infrastructure

```bash
# Option A – Docker Compose (recommended for local dev)
docker compose up -d postgres redis

# Option B – use existing Postgres/Redis, just update .env
```

### 3. Apply database schema

```bash
psql -U claudbot -d claudbot -f migrations/init.sql

# Or let SQLAlchemy auto-create tables on first startup (FastAPI lifespan does this)
```

### 4. Start the API server

```bash
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs` for the interactive API docs.

### 5. Start the Celery worker

```bash
celery -A app.worker.celery_app worker --loglevel=info --concurrency=4
```

### 6. (Optional) Celery Flower monitoring

```bash
celery -A app.worker.celery_app flower --port=5555
# Open http://localhost:5555
```

### 7. Run all services via Docker Compose

```bash
docker compose up -d
# API:    http://localhost:8000/docs
# Flower: http://localhost:5555  (admin / adminpassword)
```

---

## Example API calls

### Submit a task

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "user_task": "Write a Q2 summer sale email campaign for our fashion brand targeting existing customers. Tone: friendly.",
    "created_by": "alice"
  }'
```

Response (202):
```json
{
  "id": "3f7a2c1d-...",
  "status": "pending",
  "message": "Task accepted. Poll /tasks/{id} for progress."
}
```

### Poll for status

```bash
curl http://localhost:8000/api/v1/tasks/3f7a2c1d-...
```

Possible statuses:
- `pending` – queued
- `running` – agent is executing
- `pending_approval` – waiting for human sign-off
- `complete` – finished, `final_output` is populated
- `failed` / `rejected` – see `error` field

### Approve a pending action

```bash
# List pending approvals
curl http://localhost:8000/api/v1/approvals

# Approve
curl -X POST http://localhost:8000/api/v1/approvals/<approval-id>/approve \
  -H "Content-Type: application/json" \
  -d '{"approved_by": "alice"}'

# Reject
curl -X POST http://localhost:8000/api/v1/approvals/<approval-id>/reject \
  -H "Content-Type: application/json" \
  -d '{"approved_by": "alice", "rejection_reason": "Wrong audience segment"}'
```

### Search memory

```bash
curl "http://localhost:8000/api/v1/history/search?q=summer+campaign"
```

---

## Project Structure

```
claudbot/
├── app/
│   ├── main.py              # FastAPI app, lifespan, router registration
│   ├── config.py            # Pydantic-settings (reads .env)
│   ├── database.py          # Async + sync SQLAlchemy engine factories
│   ├── logging_config.py    # Structured JSON logging (structlog)
│   │
│   ├── models/
│   │   └── task.py          # SQLAlchemy ORM: Task, Approval, Memory
│   ├── schemas/
│   │   └── task.py          # Pydantic v2 request/response schemas
│   │
│   ├── api/
│   │   ├── tasks.py         # POST/GET /tasks
│   │   ├── approvals.py     # GET/POST /approvals
│   │   └── history.py       # GET /history, /history/search
│   │
│   ├── agent/
│   │   ├── state.py         # AgentState TypedDict
│   │   ├── graph.py         # LangGraph StateGraph definition
│   │   ├── llm_client.py    # litellm wrapper with retry logic
│   │   ├── nodes/
│   │   │   ├── planner.py
│   │   │   ├── executor.py
│   │   │   └── critic.py
│   │   └── prompts/
│   │       ├── planner.py
│   │       ├── executor.py
│   │       └── critic.py
│   │
│   ├── tools/
│   │   ├── __init__.py      # TOOL_REGISTRY
│   │   ├── campaign.py      # generate_campaign
│   │   ├── email_writer.py  # write_email, send_email
│   │   └── storage.py       # store_data, retrieve_data, delete_data
│   │
│   ├── memory/
│   │   └── store.py         # retrieve_relevant_memories, save_task_memory_sync
│   ├── safety/
│   │   └── approval.py      # create/check/resolve approval requests
│   └── worker/
│       ├── celery_app.py    # Celery factory
│       └── tasks.py         # execute_task, resume_task
│
├── migrations/
│   └── init.sql             # DB schema (run once)
├── tests/
│   ├── test_tools.py
│   └── test_agent.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Deploy on Oracle Cloud Free Tier (Single VM)

### Provisioning

1. Create an **Ampere A1** instance (4 OCPUs, 24 GB RAM – always free).
2. OS: Ubuntu 22.04.
3. Open ports in the Security List:
   - TCP 22 (SSH)
   - TCP 8000 (API)
   - TCP 5555 (Flower – restrict to your IP)

### Server setup

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker ubuntu
# Log out and back in

git clone <repo> claudbot && cd claudbot
cp .env.example .env
nano .env           # Fill in your API keys and passwords
```

### Run with Docker Compose

```bash
docker compose up -d
docker compose logs -f  # watch logs
```

### Reverse proxy with Nginx (HTTPS)

```bash
sudo apt install -y nginx certbot python3-certbot-nginx

# /etc/nginx/sites-available/claudbot
server {
    server_name your-domain.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
sudo certbot --nginx -d your-domain.com
```

### Systemd auto-restart (optional, if not using Docker)

```bash
# If running bare-metal instead of Docker
sudo nano /etc/systemd/system/claudbot.service
# [Unit] Description=ClaudBot API
# [Service] WorkingDirectory=/home/ubuntu/claudbot
#           ExecStart=/home/ubuntu/claudbot/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# [Install] WantedBy=multi-user.target

sudo systemctl enable --now claudbot
```

---

## Running Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

For DB-level tests:
```bash
CLAUDBOT_RUN_DB_TESTS=1 pytest tests/ -v
```

---

## Switching LLM Provider

Edit `.env`:

```bash
# OpenRouter (recommended – access to many models)
LLM_MODEL=openrouter/anthropic/claude-3.5-sonnet
OPENROUTER_API_KEY=sk-or-...

# Anthropic direct
LLM_MODEL=claude-3-5-sonnet-20241022
ANTHROPIC_API_KEY=sk-ant-...

# Google Gemini
LLM_MODEL=gemini/gemini-1.5-pro
GOOGLE_API_KEY=AI...
```

`litellm` handles the provider routing automatically.

---

## Scaling Notes

The system is intentionally sized for ~15 concurrent users on a single VM.
When you outgrow it:

| Bottleneck | Solution |
|------------|----------|
| More concurrent tasks | Increase `CELERY_CONCURRENCY` or add worker replicas |
| Memory search quality | Enable `pgvector`, store embeddings, switch to cosine similarity |
| High API latency | Add a read replica for queries; cache frequent memory lookups in Redis |
| Multi-tenant isolation | Add a `workspace_id` column to all tables; filter all queries |
| Audit trail | Add a separate `audit_log` table; write to it from every state transition |
| Auth | Add JWT middleware in `app/main.py`; issue tokens per user |

---

## Adding a New Tool

1. Create `app/tools/my_tool.py` with an `async def my_tool(**kwargs) -> str:` function.
2. Register it in `app/tools/__init__.py`:
   ```python
   from app.tools.my_tool import my_tool
   TOOL_REGISTRY["my_tool"] = my_tool
   ```
3. Add a description to the `PLANNER_SYSTEM` prompt in `app/agent/prompts/planner.py`.
4. If it needs approval, add it to `APPROVAL_REQUIRED_TOOLS` in `.env`.

That's it – the planner will start using the tool automatically.
