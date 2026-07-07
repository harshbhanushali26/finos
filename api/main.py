"""
FinOS — FastAPI application entry point (api/main.py)

Responsibilities:
- Create the FastAPI app instance
- Register all routers under /api/v1/
- Call create_db() on startup
- Mount frontend/ as static files
- CORS for local development
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.database import create_db
from api.routes import auth, chat, transactions, categories, analytics, budget, export, insights, payment_methods


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup tasks before the app begins accepting requests."""
    create_db()
    yield



app = FastAPI(
    title="FinOS API",
    version="1.0.0",
    description="Personal AI finance platform",
    lifespan=lifespan,
)


# ── CORS ───────────────────────────────────────────────────────────────────
# Allow all origins in development. Tighten in production.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ────────────────────────────────────────────────────────────────

PREFIX = "/api/v1"

app.include_router(auth.router,             prefix=PREFIX)
app.include_router(transactions.router,     prefix=PREFIX)
app.include_router(categories.router,       prefix=PREFIX)
app.include_router(analytics.router,        prefix=PREFIX)
app.include_router(budget.router,           prefix=PREFIX)
app.include_router(export.router,           prefix=PREFIX)
app.include_router(chat.router,             prefix=PREFIX)
app.include_router(insights.router,         prefix=PREFIX)
app.include_router(payment_methods.router,  prefix=PREFIX)

# ── Static files ───────────────────────────────────────────────────────────
# Served at / — index.html is the SPA shell
# Mount last so API routes take priority

try:
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
except RuntimeError:
    pass    # frontend/ doesn't exist yet — that's fine during Phase 2


