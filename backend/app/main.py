import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import answers, applications, autofill, board, jd, jobs, profile
from app.services import board_sync
from app.services.board_sync import (
    claim_background_lock, cleanup_postings, harvester_loop, retention_loop, scout_loop)


async def _keep_background(loop):
    """Start the loop again if it exits. A crashed checker used to stay dead
    while /health and the Job Board kept serving the last saved listings."""
    board_sync.guard_stdio()
    while True:
        try:
            await loop()
        except asyncio.CancelledError:
            raise
        except Exception:
            board_sync._log_exc()
        await asyncio.sleep(board_sync.WORKER_IDLE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # create tables + seed the "default" profile on startup (T11)
    cleanup_postings()
    lock = claim_background_lock()  # T29: one harvester per DB, however many servers
    if lock is None:
        print("[board] another process runs the harvester for this DB; serving the API only")
    loops = (harvester_loop, scout_loop, retention_loop) if lock else ()
    tasks = [asyncio.create_task(_keep_background(loop)) for loop in loops]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if lock:
            lock.close()


app = FastAPI(title="Resume Agent", lifespan=lifespan)
# The autofill extension (T12) and the Vite dev frontend call us cross-origin.
# Scope to chrome-extension:// (any unpacked id) + localhost — not "*".
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome-extension://[a-p]+|http://localhost:\d+)$",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(jobs.router)
app.include_router(applications.router)
app.include_router(jd.router)
app.include_router(profile.router)
app.include_router(autofill.router)
app.include_router(answers.router)
app.include_router(board.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
