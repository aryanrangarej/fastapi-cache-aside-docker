# FastAPI Cache-Aside Pattern with Docker Compose

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker Compose](https://img.shields.io/badge/Docker_Compose-Enabled-2496ED?style=flat&logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat&logo=redis&logoColor=white)](https://redis.io)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A production-ready demonstration of the **Cache-Aside (Lazy Loading)** architecture pattern using **FastAPI**, **PostgreSQL**, and **Redis**, fully containerized and orchestrated with **Docker Compose**.

---

## 🏛️ Architecture & Pattern Overview

The **Cache-Aside** pattern ensures that the application only loads data into cache on-demand:
1. **Cache Read First**: When a client requests data, the FastAPI application first queries Redis.
2. **Cache Hit**: If present in Redis, the data is returned immediately without querying PostgreSQL.
3. **Cache Miss**: If absent in Redis, the application queries PostgreSQL.
4. **Cache Hydration**: The retrieved database record is stored in Redis with an expiration Time-to-Live (**TTL = 60s**).
5. **Subsequent Reads**: Any requests within the 60-second window are served with sub-millisecond latency from Redis.

```
       [Client]
          │
          │ GET /items/1
          ▼
     [FastAPI]
    ┌─────┴────────────────┐
    │ 1. Check Cache       │
    ▼                      │
 [Redis]                   │
  ├─ HIT: Return Data ─────┘
  └─ MISS ─────────────────┐
                           │ 2. Query Database
                           ▼
                      [PostgreSQL]
                           │
                           │ 3. Return DB Record
                           ▼
     [FastAPI] ◄───────────┘
    ┌─────┴────────────────┐
    │ 4. Hydrate Redis     │ (TTL = 60s)
    ▼                      │
 [Redis]                   │ 5. Return Response to Client
                           ▼
                        [Client]
```

---

## 📁 Project Structure

```
.
├── app.py                 # FastAPI application with Cache-Aside logic & lifecycle
├── Dockerfile             # Multi-stage optimized Python 3.11-slim container image
├── docker-compose.yml     # Multi-container orchestration (App, Postgres, Redis)
├── requirements.txt       # Project dependencies (FastAPI, uvicorn, redis, asyncpg)
├── .env.example           # Configurable environment variable template
├── .dockerignore          # Prevents build context bloat
├── .gitignore             # Shields secrets, logs, and cache from version control
├── LICENSE                # MIT License
└── README.md              # Project documentation
```

---

## ⚙️ Environment Configuration

Copy `.env.example` to `.env` if you wish to customize port bindings or credentials:

```bash
cp .env.example .env
```

| Variable | Default | Description |
| :--- | :--- | :--- |
| `HOST_APP_PORT` | `8000` | Port on host bound to FastAPI |
| `HOST_POSTGRES_PORT` | `5433` | Port on host bound to PostgreSQL *(5433 to avoid conflicts)* |
| `HOST_REDIS_PORT` | `6379` | Port on host bound to Redis |
| `CACHE_TTL_SECONDS` | `60` | Expiration TTL for cached items |
| `POSTGRES_DB` | `app_db` | PostgreSQL database name |
| `POSTGRES_USER` | `postgres` | PostgreSQL username |
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL password |

---

## 🚀 Getting Started

### 1. Build and Start Services
Run:

```bash
docker compose up --build
```

*(Add `-d` to run in detached background mode)*

Docker Compose initializes:
- `fastapi_cache_aside_app` on `http://localhost:8000`
- `postgres_db` on `localhost:5433`
- `redis_cache` on `localhost:6379`
- `cache_aside_network` custom bridge virtual network

---

## 🧪 Testing the Cache-Aside Flow

The service automatically initializes the schema and populates sample items on startup.

### 1. Initial Request (Cache Miss)
```bash
curl http://localhost:8000/items/1
```

**Output:**
```json
{
  "source": "database",
  "cache_status": "MISS",
  "response_time_ms": 4.15,
  "ttl_set_seconds": 60,
  "data": {
    "id": 1,
    "name": "Mechanical Keyboard",
    "description": "RGB Hot-swappable mechanical keyboard",
    "price": 99.99
  }
}
```

### 2. Subsequent Request (Cache Hit)
Execute the exact same request within 60 seconds:
```bash
curl http://localhost:8000/items/1
```

**Output:**
```json
{
  "source": "cache",
  "cache_status": "HIT",
  "response_time_ms": 1.0,
  "ttl_remaining_seconds": 55,
  "data": {
    "id": 1,
    "name": "Mechanical Keyboard",
    "description": "RGB Hot-swappable mechanical keyboard",
    "price": 99.99
  }
}
```

### 3. Verify Redis Directly
```bash
# View stored value
docker compose exec redis redis-cli GET item:1

# Check remaining TTL
docker compose exec redis redis-cli TTL item:1
```

### 4. Interactive Swagger Documentation
Open [http://localhost:8000/docs](http://localhost:8000/docs) in your browser.

---

## 🛑 Teardown

To stop and remove containers and network:
```bash
docker compose down
```

To also delete persistent database and cache volumes:
```bash
docker compose down -v
```

---

## 📄 License
This project is open source and available under the [MIT License](LICENSE).
