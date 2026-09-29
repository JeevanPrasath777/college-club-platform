from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine, run_schema_migrations
from app.routers import auth, clubs, events, messages, od, timetable, timetable_structures, users
from app.routers.attendance import certs_router, router as attendance_router
from app.routers.misc import (
    analytics_router,
    announce_router,
    audit_router,
    badges_router,
    notify_router,
    regs_router,
    search_router,
)

Base.metadata.create_all(bind=engine)
run_schema_migrations()

app = FastAPI(title=settings.app_name, version="1.0.0")
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(clubs.router)
app.include_router(events.router)
app.include_router(od.router)
app.include_router(timetable.router)
app.include_router(timetable_structures.router)
app.include_router(messages.router)
app.include_router(attendance_router)
app.include_router(certs_router)
app.include_router(badges_router)
app.include_router(notify_router)
app.include_router(announce_router)
app.include_router(analytics_router)
app.include_router(audit_router)
app.include_router(regs_router)
app.include_router(search_router)


@app.get("/api/health")
def health():
    return {"ok": True}
