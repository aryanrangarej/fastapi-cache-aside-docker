import json
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

import asyncpg
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
import redis.asyncio as aioredis

# Environment configurations with sensible defaults for Docker
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_DB = os.getenv("POSTGRES_DB", "app_db")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Cache configuration
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))  # 60-second Time-to-Live default

# Global client connection holders
db_pool: Optional[asyncpg.Pool] = None
redis_client: Optional[aioredis.Redis] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager to initialize and gracefully tear down
    connections to PostgreSQL and Redis.
    """
    global db_pool, redis_client

    # Initialize PostgreSQL connection pool
    db_pool = await asyncpg.create_pool(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_DB,
        min_size=2,
        max_size=10,
    )

    # Initialize Redis client
    redis_client = aioredis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,  # Automatically decode bytes to strings
    )

    # Automatically set up sample schema and seed data on startup
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                price NUMERIC(10, 2) NOT NULL
            );
            """
        )
        count = await conn.fetchval("SELECT COUNT(*) FROM items;")
        if count == 0:
            await conn.execute(
                """
                INSERT INTO items (name, description, price)
                VALUES 
                    ('Mechanical Keyboard', 'RGB Hot-swappable mechanical keyboard', 99.99),
                    ('Wireless Mouse', 'Ergonomic 2.4GHz wireless mouse', 49.50),
                    ('4K Monitor', '27-inch IPS UHD display', 299.00);
                """
            )

    yield

    # Teardown: close pools
    if db_pool:
        await db_pool.close()
    if redis_client:
        await redis_client.aclose()


app = FastAPI(
    title="Cache-Aside Demonstration API",
    description="FastAPI service showcasing Cache-Aside pattern with Redis and PostgreSQL",
    version="1.0.0",
    lifespan=lifespan,
)


class ItemCreate(BaseModel):
    name: str
    description: str
    price: float


@app.get("/")
async def root():
    return {
        "message": "Cache-Aside Architecture Demo",
        "documentation": "/docs",
        "endpoints": {
            "get_item": "/items/{item_id}",
            "create_item": "/items (POST)",
            "health": "/health",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint to verify connectivity to both Postgres and Redis."""
    postgres_status = "healthy"
    redis_status = "healthy"

    try:
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1;")
    except Exception as exc:
        postgres_status = f"unhealthy: {str(exc)}"

    try:
        await redis_client.ping()
    except Exception as exc:
        redis_status = f"unhealthy: {str(exc)}"

    return {
        "status": "ok" if postgres_status == "healthy" and redis_status == "healthy" else "degraded",
        "postgres": postgres_status,
        "redis": redis_status,
    }


# ============================================================================
# CACHE-ASIDE PATTERN IMPLEMENTATION
# ============================================================================
@app.get("/items/{item_id}")
async def get_item(item_id: int):
    """
    Fetch an item demonstrating the Cache-Aside pattern:
    1. Check Redis cache first.
    2. On CACHE HIT -> Return cached data directly.
    3. On CACHE MISS -> Query PostgreSQL database.
    4. HYDRATE CACHE -> Store DB result in Redis with a 60-second TTL.
    """
    cache_key = f"item:{item_id}"
    start_time = time.perf_counter()

    # ------------------------------------------------------------------------
    # STEP 1: CACHE LOOKUP
    # Check if the requested resource exists in the Redis cache.
    # ------------------------------------------------------------------------
    cached_data = await redis_client.get(cache_key)

    if cached_data is not None:
        # ====================================================================
        # [CACHE HIT]
        # Data was found in Redis! Return it immediately without touching
        # the persistent database.
        # ====================================================================
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        item = json.loads(cached_data)

        # Retrieve remaining TTL for demonstration/debugging purposes
        ttl_remaining = await redis_client.ttl(cache_key)

        return {
            "source": "cache",
            "cache_status": "HIT",
            "response_time_ms": round(elapsed_ms, 2),
            "ttl_remaining_seconds": ttl_remaining,
            "data": item,
        }

    # ========================================================================
    # [CACHE MISS]
    # Data was NOT found in Redis. We must query the PostgreSQL database.
    # ========================================================================
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, description, price FROM items WHERE id = $1;",
            item_id,
        )

    # If the item does not exist in the database either, return 404
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item with id {item_id} not found in database",
        )

    # Format record for JSON serialization
    item = {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "price": float(row["price"]),
    }

    # ========================================================================
    # [CACHE HYDRATION]
    # Store the queried database record into Redis with a 60-second TTL.
    # Subsequent requests within 60s will now result in a CACHE HIT.
    # ========================================================================
    await redis_client.setex(
        name=cache_key,
        time=CACHE_TTL_SECONDS,
        value=json.dumps(item),
    )

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    return {
        "source": "database",
        "cache_status": "MISS",
        "response_time_ms": round(elapsed_ms, 2),
        "ttl_set_seconds": CACHE_TTL_SECONDS,
        "data": item,
    }


@app.post("/items", status_code=status.HTTP_201_CREATED)
async def create_item(item: ItemCreate):
    """
    Helper route to create a new item in PostgreSQL.
    """
    async with db_pool.acquire() as conn:
        new_id = await conn.fetchval(
            """
            INSERT INTO items (name, description, price)
            VALUES ($1, $2, $3)
            RETURNING id;
            """,
            item.name,
            item.description,
            item.price,
        )

    return {
        "message": "Item created successfully",
        "item_id": new_id,
        "data": {
            "id": new_id,
            "name": item.name,
            "description": item.description,
            "price": item.price,
        },
    }
