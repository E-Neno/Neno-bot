from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

from app.routers import chat, context, debug, memory, platform, proactive, relationship, session, stats, system
from app.services.proactive_scheduler import start_proactive_scheduler, stop_proactive_scheduler
from app.storage.db import init_db
from app.storage.relationship import init_relationship_tables
from app.utils.logging_utils import configure_safe_logging

configure_safe_logging()

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(context.router)
app.include_router(session.router)
app.include_router(memory.router)
app.include_router(relationship.router)
app.include_router(platform.router)
app.include_router(stats.router)
app.include_router(proactive.router)
app.include_router(debug.router)
app.include_router(chat.router)


@app.on_event("startup")
async def startup_event():
    init_db()
    init_relationship_tables()
    start_proactive_scheduler()


@app.on_event("shutdown")
async def shutdown_event():
    await stop_proactive_scheduler()
