import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.database import Base, get_db
from app.main import app
from app.models import Club, Event, EventStatus, SystemRole, TimetableSlot, User
from app.security import hash_password

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(engine, "connect")
def _fk(dbapi_connection, _):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


TestingSession = sessionmaker(bind=engine)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db):
    def override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_user(db, email, role, password="Passw0rd!", **kwargs):
    u = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=email.split("@")[0],
        role=role,
        **kwargs,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def login(client, email, password="Passw0rd!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_login_and_role(client, db):
    make_user(db, "sa@c.edu", SystemRole.SUPER_ADMIN)
    headers = login(client, "sa@c.edu")
    me = client.get("/api/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "SUPER_ADMIN"


def test_unique_ra_number(client, db):
    sa = make_user(db, "sa@c.edu", SystemRole.SUPER_ADMIN)
    h = login(client, "sa@c.edu")
    fac = make_user(db, "f@c.edu", SystemRole.FACULTY)
    body = {
        "email": "s1@c.edu",
        "password": "Passw0rd!",
        "full_name": "S One",
        "role": "STUDENT",
        "ra_number": "RA0000000000001",
        "department": "CSE",
        "year": 1,
        "section": "A",
        "class_mentor_id": fac.id,
    }
    assert client.post("/api/users", json=body, headers=h).status_code == 201
    body["email"] = "s2@c.edu"
    r = client.post("/api/users", json=body, headers=h)
    assert r.status_code == 409


def test_student_cannot_register_unapproved_event(client, db):
    fac = make_user(db, "f@c.edu", SystemRole.FACULTY)
    ca = make_user(db, "ca@c.edu", SystemRole.CLUB_ADMIN)
    st = make_user(
        db,
        "st@c.edu",
        SystemRole.STUDENT,
        ra_number="RA0000000000009",
        department="CSE",
        year=2,
        section="A",
        class_mentor_id=fac.id,
    )
    club = Club(name="C1", club_admin_id=ca.id)
    db.add(club)
    db.commit()
    db.refresh(club)
    start = datetime.utcnow() + timedelta(days=1)
    ev = Event(
        club_id=club.id,
        title="Pending",
        start_at=start,
        end_at=start + timedelta(hours=2),
        capacity=10,
        status=EventStatus.PENDING_FACULTY,
        created_by_id=ca.id,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    hs = login(client, "st@c.edu")
    r = client.post(f"/api/events/{ev.id}/register", headers=hs)
    assert r.status_code == 403


def test_club_admin_cannot_approve_event_or_od(client, db):
    fac = make_user(db, "f@c.edu", SystemRole.FACULTY)
    ca = make_user(db, "ca@c.edu", SystemRole.CLUB_ADMIN)
    st = make_user(
        db,
        "st@c.edu",
        SystemRole.STUDENT,
        ra_number="RA0000000000008",
        department="CSE",
        year=2,
        section="A",
        class_mentor_id=fac.id,
    )
    club = Club(name="C2", club_admin_id=ca.id, faculty_coordinator_id=fac.id)
    db.add(club)
    db.commit()
    db.refresh(club)
    start = datetime.utcnow() + timedelta(days=1)
    ev = Event(
        club_id=club.id,
        title="NeedApprove",
        start_at=start,
        end_at=start + timedelta(hours=2),
        capacity=10,
        status=EventStatus.PENDING_FACULTY,
        created_by_id=ca.id,
    )
    db.add(ev)
    db.commit()
    hca = login(client, "ca@c.edu")
    r = client.post(f"/api/events/{ev.id}/approve", json={"comment": "no"}, headers=hca)
    assert r.status_code == 403
    hf = login(client, "f@c.edu")
    assert client.post(f"/api/events/{ev.id}/approve", json={"comment": "ok"}, headers=hf).status_code == 200
    hs = login(client, "st@c.edu")
    reg = client.post(f"/api/events/{ev.id}/register", headers=hs)
    assert reg.status_code == 201
    od = client.post("/api/od", json={"registration_id": reg.json()["id"], "reason": "lab"}, headers=hs)
    assert od.status_code == 201
    deny = client.post(f"/api/od/{od.json()['id']}/approve", json={"comment": "x"}, headers=hca)
    assert deny.status_code == 403


def test_od_requires_registration_and_snapshots(client, db):
    fac = make_user(db, "f@c.edu", SystemRole.FACULTY)
    ca = make_user(db, "ca@c.edu", SystemRole.CLUB_ADMIN)
    st = make_user(
        db,
        "st@c.edu",
        SystemRole.STUDENT,
        ra_number="RA0000000000007",
        department="CSE",
        year=2,
        section="A",
        class_mentor_id=fac.id,
    )
    club = Club(name="C3", club_admin_id=ca.id)
    db.add(club)
    db.commit()
    db.refresh(club)
    # Event on next weekday 10:00-12:00 overlapping period 2
    start = datetime.utcnow().replace(hour=10, minute=0, second=0, microsecond=0)
    while start.weekday() > 4:
        start += timedelta(days=1)
    start += timedelta(days=1)
    while start.weekday() > 4:
        start += timedelta(days=1)
    ev = Event(
        club_id=club.id,
        title="Approved",
        start_at=start,
        end_at=start + timedelta(hours=2),
        capacity=5,
        status=EventStatus.APPROVED,
        created_by_id=ca.id,
        approved_by_id=fac.id,
    )
    db.add(ev)
    db.add(
        TimetableSlot(
            department="CSE",
            year=2,
            section="A",
            day_of_week=start.weekday(),
            period_number=2,
            start_time="10:00",
            end_time="11:00",
            subject="Math",
            faculty_id=fac.id,
        )
    )
    db.commit()
    db.refresh(ev)
    hs = login(client, "st@c.edu")
    bad = client.post("/api/od", json={"registration_id": 9999, "reason": "x"}, headers=hs)
    assert bad.status_code == 403
    reg = client.post(f"/api/events/{ev.id}/register", headers=hs)
    assert reg.status_code == 201
    od = client.post("/api/od", json={"registration_id": reg.json()["id"], "reason": "event"}, headers=hs)
    assert od.status_code == 201
    assert len(od.json()["periods"]) >= 1
    assert od.json()["periods"][0]["subject"] == "Math"
    mut = client.patch(f"/api/od/{od.json()['id']}/periods", json={}, headers=hs)
    assert mut.status_code == 403
    hf = login(client, "f@c.edu")
    ok = client.post(f"/api/od/{od.json()['id']}/approve", json={"comment": "ok"}, headers=hf)
    assert ok.status_code == 200
    assert ok.json()["status"] == "APPROVED"


def test_non_super_admin_cannot_edit_timetable(client, db):
    make_user(db, "ad@c.edu", SystemRole.ADMIN)
    h = login(client, "ad@c.edu")
    r = client.post(
        "/api/timetable",
        json={
            "department": "CSE",
            "year": 1,
            "section": "A",
            "day_of_week": 0,
            "period_number": 1,
            "start_time": "09:00",
            "end_time": "10:00",
            "subject": "X",
        },
        headers=h,
    )
    assert r.status_code == 403


def test_dynamic_roles_cannot_gain_system_privileges(client, db):
    sa = make_user(db, "sa@c.edu", SystemRole.SUPER_ADMIN)
    ca = make_user(db, "ca@c.edu", SystemRole.CLUB_ADMIN)
    fac = make_user(db, "f@c.edu", SystemRole.FACULTY)
    hsa = login(client, "sa@c.edu")
    club = client.post(
        "/api/clubs",
        json={"name": "Robotics", "description": "", "category": "Tech", "club_admin_id": ca.id, "faculty_coordinator_id": fac.id},
        headers=hsa,
    )
    assert club.status_code == 201
    hca = login(client, "ca@c.edu")
    role = client.post(
        f"/api/clubs/{club.json()['id']}/roles",
        json={"name": "Hacker", "permissions": ["approve_events", "approve_od", "manage_timetable", "create_events"]},
        headers=hca,
    )
    assert role.status_code == 201
    perms = role.json()["permissions"]
    assert "approve_events" not in perms
    assert "approve_od" not in perms
    assert "manage_timetable" not in perms
    assert "create_events" in perms


def test_capacity_and_duplicate_registration(client, db):
    fac = make_user(db, "f@c.edu", SystemRole.FACULTY)
    ca = make_user(db, "ca@c.edu", SystemRole.CLUB_ADMIN)
    st = make_user(db, "st@c.edu", SystemRole.STUDENT, ra_number="RA0000000000005", department="CSE", year=1, section="A", class_mentor_id=fac.id)
    st2 = make_user(db, "st2@c.edu", SystemRole.STUDENT, ra_number="RA0000000000006", department="CSE", year=1, section="A", class_mentor_id=fac.id)
    club = Club(name="C4", club_admin_id=ca.id)
    db.add(club)
    db.commit()
    db.refresh(club)
    start = datetime.utcnow() + timedelta(days=3)
    ev = Event(
        club_id=club.id,
        title="Tiny",
        start_at=start,
        end_at=start + timedelta(hours=1),
        capacity=1,
        status=EventStatus.APPROVED,
        created_by_id=ca.id,
        approved_by_id=fac.id,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    h1 = login(client, "st@c.edu")
    h2 = login(client, "st2@c.edu")
    assert client.post(f"/api/events/{ev.id}/register", headers=h1).status_code == 201
    assert client.post(f"/api/events/{ev.id}/register", headers=h1).status_code == 409
    assert client.post(f"/api/events/{ev.id}/register", headers=h2).status_code == 409


def test_cross_club_denied(client, db):
    ca1 = make_user(db, "ca1@c.edu", SystemRole.CLUB_ADMIN)
    ca2 = make_user(db, "ca2@c.edu", SystemRole.CLUB_ADMIN)
    sa = make_user(db, "sa@c.edu", SystemRole.SUPER_ADMIN)
    hsa = login(client, "sa@c.edu")
    fac = make_user(db, "f@c.edu", SystemRole.FACULTY)
    c1 = client.post("/api/clubs", json={"name": "Alpha", "club_admin_id": ca1.id, "faculty_coordinator_id": fac.id}, headers=hsa).json()
    client.post("/api/clubs", json={"name": "Beta", "club_admin_id": ca2.id, "faculty_coordinator_id": fac.id}, headers=hsa)
    h2 = login(client, "ca2@c.edu")
    r = client.post(
        f"/api/clubs/{c1['id']}/members",
        json={"user_id": ca2.id},
        headers=h2,
    )
    assert r.status_code == 403
