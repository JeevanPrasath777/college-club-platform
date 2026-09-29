"""Seed demo college data into SQLite. Safe to re-run: skips if super admin exists."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import Base, SessionLocal, engine, run_schema_migrations
from app.models import (
    Attendance,
    Club,
    ClubMember,
    ClubRole,
    Event,
    EventCheckinSession,
    EventStatus,
    Registration,
    SystemRole,
    TimetableSlot,
    TimetableStructure,
    TimetablePeriod,
    User,
)
from app.security import hash_password
import json

Base.metadata.create_all(bind=engine)
run_schema_migrations()


def ensure_demo_checkin_event(db, club, club_admin, faculty, student):
    """Provide one live, registered event for an immediate event-day demo."""
    now = datetime.now()
    event = db.query(Event).filter(
        Event.club_id == club.id,
        Event.title == "Campus Welcome Mixer",
    ).first()
    if not event:
        event = Event(
            club_id=club.id,
            title="Campus Welcome Mixer",
            description="Meet campus clubs and try the live event check-in flow.",
            venue="Central Courtyard",
            start_at=now - timedelta(minutes=10),
            end_at=now + timedelta(hours=1),
            capacity=100,
            status=EventStatus.ONGOING,
            created_by_id=club_admin.id,
            approved_by_id=faculty.id,
            approval_comment="Approved for the live platform demo.",
        )
        db.add(event)
        db.flush()
    elif event.end_at <= now:
        # Reopen only this explicitly named demo fixture when its short window
        # has elapsed; preserve real event records and active demo sessions.
        event.start_at = now - timedelta(minutes=10)
        event.end_at = now + timedelta(hours=1)
        event.status = EventStatus.ONGOING
        db.query(Attendance).filter(Attendance.event_id == event.id).delete(synchronize_session=False)
        db.query(EventCheckinSession).filter(EventCheckinSession.event_id == event.id).delete(synchronize_session=False)
    registration = db.query(Registration).filter(
        Registration.event_id == event.id,
        Registration.student_id == student.id,
    ).first()
    if not registration:
        db.add(Registration(event_id=event.id, student_id=student.id))
    return event


def seed():
    db = SessionLocal()
    super_admin = db.query(User).filter(User.email == "superadmin@college.edu").first()
    if super_admin:
        # Repair a partially seeded demo database instead of treating the
        # presence of one account as proof that all demo data exists.
        demo_users = [
            ("admin@college.edu", "Karthik Menon", SystemRole.ADMIN, "Admin@123", "Admin", None),
            ("faculty@college.edu", "Dr. Anitha Rao", SystemRole.FACULTY, "Faculty@123", "CSE", None),
            ("faculty2@college.edu", "Dr. Vivek Iyer", SystemRole.FACULTY, "Faculty@123", "ECE", None),
            ("clubadmin@college.edu", "Meera Krishnan", SystemRole.CLUB_ADMIN, "ClubAdmin@123", "CSE", None),
            ("student@college.edu", "Arjun Patel", SystemRole.STUDENT, "Student@123", "CSE", "RA2411001001001"),
            ("student2@college.edu", "Nisha Verma", SystemRole.STUDENT, "Student@123", "CSE", "RA2411001001002"),
            ("student3@college.edu", "Rohan Das", SystemRole.STUDENT, "Student@123", "ECE", "RA2411001001003"),
        ]
        users = {super_admin.email: super_admin}
        for email, name, role, password, department, ra_number in demo_users:
            user = db.query(User).filter(User.email == email).first()
            if not user:
                user = User(
                    email=email,
                    full_name=name,
                    role=role,
                    hashed_password=hash_password(password),
                    department=department,
                    ra_number=ra_number,
                )
                db.add(user)
            elif role == SystemRole.STUDENT and (not user.ra_number or len(user.ra_number) != 15):
                user.ra_number = ra_number
            users[email] = user
        db.flush()
        faculty = users["faculty@college.edu"]
        faculty2 = users["faculty2@college.edu"]
        club_admin = users["clubadmin@college.edu"]
        student = users["student@college.edu"]
        student2 = users["student2@college.edu"]
        student3 = users["student3@college.edu"]
        student.class_mentor_id = faculty.id
        student2.class_mentor_id = faculty.id
        student3.class_mentor_id = faculty2.id
        for email, number in (
            ("student@college.edu", "RA2411001001001"),
            ("student2@college.edu", "RA2411001001002"),
            ("student3@college.edu", "RA2411001001003"),
        ):
            student = db.query(User).filter(User.email == email).first()
            if student and student.ra_number != number:
                student.ra_number = number
        coding = db.query(Club).filter(Club.name == "Coding Club").first()
        if not coding:
            coding = Club(
                name="Coding Club",
                description="Competitive programming, hackathons, and open-source.",
                category="Technical",
                club_admin_id=club_admin.id,
                faculty_coordinator_id=faculty.id,
            )
            db.add(coding)
        arts = db.query(Club).filter(Club.name == "Fine Arts Club").first()
        if not arts:
            arts = Club(
                name="Fine Arts Club",
                description="Studio practice, exhibitions, and campus culture.",
                category="Cultural",
                faculty_coordinator_id=faculty2.id,
            )
            db.add(arts)
        if not coding.faculty_coordinator_id:
            coding.faculty_coordinator_id = faculty.id
        if not coding.club_admin_id:
            coding.club_admin_id = club_admin.id
        if not arts.faculty_coordinator_id:
            arts.faculty_coordinator_id = faculty2.id
        db.flush()

        for member in (club_admin, student, student2):
            if not db.query(ClubMember).filter(
                ClubMember.club_id == coding.id, ClubMember.user_id == member.id
            ).first():
                db.add(ClubMember(club_id=coding.id, user_id=member.id))

        if coding and student2:
            role = db.query(ClubRole).filter(
                ClubRole.club_id == coding.id, ClubRole.name == "Event Coordinator"
            ).first()
            if not role:
                role = ClubRole(
                    club_id=coding.id,
                    name="Event Coordinator",
                    permissions=json.dumps(["create_events", "view_registrations", "mark_attendance"]),
                )
                db.add(role)
                db.flush()
            membership = db.query(ClubMember).filter(
                ClubMember.club_id == coding.id, ClubMember.user_id == student2.id
            ).first()
            if membership:
                membership.club_role_id = role.id

        now = datetime.now()
        start = now.replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=2)
        if not db.query(Event).filter(Event.club_id == coding.id, Event.title == "HackNight 2026").first():
            db.add(Event(
                club_id=coding.id,
                title="HackNight 2026",
                description="Overnight build sprint with faculty-approved OD window.",
                venue="Lab Block L3",
                start_at=start,
                end_at=start + timedelta(hours=4),
                capacity=40,
                status=EventStatus.APPROVED,
                created_by_id=club_admin.id,
                approved_by_id=faculty.id,
                approval_comment="Approved for CSE year 2.",
            ))
        if not db.query(Event).filter(Event.club_id == coding.id, Event.title == "Git Workshop").first():
            db.add(Event(
                club_id=coding.id,
                title="Git Workshop",
                description="Intro to git and GitHub for first-year students.",
                venue="Seminar Hall",
                start_at=start + timedelta(days=7),
                end_at=start + timedelta(days=7, hours=2),
                capacity=80,
                status=EventStatus.PENDING_FACULTY,
                created_by_id=club_admin.id,
            ))
        ensure_demo_checkin_event(db, coding, club_admin, faculty, student2)
        if not db.query(TimetableStructure).filter(TimetableStructure.is_active.is_(True)).first():
            slots = db.query(TimetableSlot).filter(
                TimetableSlot.department == "CSE",
                TimetableSlot.year == 2,
                TimetableSlot.section == "A",
                TimetableSlot.day_of_week == 0,
            ).order_by(TimetableSlot.period_number).all()
            if slots:
                structure = TimetableStructure(
                    name="Regular Weekday Schedule",
                    scope="College-wide",
                    working_days_json=json.dumps(list(range(5))),
                    effective_from=datetime.now().date(),
                    is_active=True,
                    created_by_id=super_admin.id,
                )
                db.add(structure)
                db.flush()
                for slot in slots:
                    db.add(TimetablePeriod(
                        structure_id=structure.id,
                        period_number=slot.period_number,
                        label=slot.subject or f"Period {slot.period_number}",
                        start_time=slot.start_time[:5],
                        end_time=slot.end_time[:5],
                        period_type="CLASS",
                    ))
        db.commit()
        print("Demo data checked and repaired: users, clubs, events, roles, and timetable setup are up to date.")
        db.close()
        return

    super_admin = User(
        email="superadmin@college.edu",
        hashed_password=hash_password("SuperAdmin@123"),
        full_name="Priya Narayanan",
        role=SystemRole.SUPER_ADMIN,
        department="CSE",
    )
    admin = User(
        email="admin@college.edu",
        hashed_password=hash_password("Admin@123"),
        full_name="Karthik Menon",
        role=SystemRole.ADMIN,
        department="Admin",
    )
    faculty = User(
        email="faculty@college.edu",
        hashed_password=hash_password("Faculty@123"),
        full_name="Dr. Anitha Rao",
        role=SystemRole.FACULTY,
        department="CSE",
    )
    faculty2 = User(
        email="faculty2@college.edu",
        hashed_password=hash_password("Faculty@123"),
        full_name="Dr. Vivek Iyer",
        role=SystemRole.FACULTY,
        department="ECE",
    )
    club_admin = User(
        email="clubadmin@college.edu",
        hashed_password=hash_password("ClubAdmin@123"),
        full_name="Meera Krishnan",
        role=SystemRole.CLUB_ADMIN,
        department="CSE",
    )
    student = User(
        email="student@college.edu",
        hashed_password=hash_password("Student@123"),
        full_name="Arjun Patel",
        role=SystemRole.STUDENT,
        ra_number="RA2411001001001",
        department="CSE",
        year=2,
        section="A",
    )
    student2 = User(
        email="student2@college.edu",
        hashed_password=hash_password("Student@123"),
        full_name="Nisha Verma",
        role=SystemRole.STUDENT,
        ra_number="RA2411001001002",
        department="CSE",
        year=2,
        section="A",
    )
    student3 = User(
        email="student3@college.edu",
        hashed_password=hash_password("Student@123"),
        full_name="Rohan Das",
        role=SystemRole.STUDENT,
        ra_number="RA2411001001003",
        department="ECE",
        year=3,
        section="B",
    )
    db.add_all([super_admin, admin, faculty, faculty2, club_admin, student, student2, student3])
    db.flush()
    student.class_mentor_id = faculty.id
    student2.class_mentor_id = faculty.id
    student3.class_mentor_id = faculty2.id

    coding = Club(
        name="Coding Club",
        description="Competitive programming, hackathons, and open-source.",
        category="Technical",
        club_admin_id=club_admin.id,
        faculty_coordinator_id=faculty.id,
    )
    arts = Club(
        name="Fine Arts Club",
        description="Studio practice, exhibitions, and campus culture.",
        category="Cultural",
        faculty_coordinator_id=faculty2.id,
    )
    db.add_all([coding, arts])
    db.flush()
    db.add(ClubMember(club_id=coding.id, user_id=club_admin.id))
    db.add(ClubMember(club_id=coding.id, user_id=student.id))
    db.add(ClubMember(club_id=coding.id, user_id=student2.id))
    role = ClubRole(
        club_id=coding.id,
        name="Event Coordinator",
        permissions=json.dumps(["create_events", "view_registrations", "mark_attendance"]),
    )
    db.add(role)
    db.flush()
    coordinator_member = db.query(ClubMember).filter(
        ClubMember.club_id == coding.id, ClubMember.user_id == student2.id
    ).first()
    if coordinator_member:
        coordinator_member.club_role_id = role.id

    start = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=2)
    approved = Event(
        club_id=coding.id,
        title="HackNight 2026",
        description="Overnight build sprint with faculty-approved OD window.",
        venue="Lab Block L3",
        start_at=start,
        end_at=start + timedelta(hours=4),
        capacity=40,
        status=EventStatus.APPROVED,
        created_by_id=club_admin.id,
        approved_by_id=faculty.id,
        approval_comment="Approved for CSE year 2.",
    )
    pending = Event(
        club_id=coding.id,
        title="Git Workshop",
        description="Intro to git and GitHub for first-year students.",
        venue="Seminar Hall",
        start_at=start + timedelta(days=7),
        end_at=start + timedelta(days=7, hours=2),
        capacity=80,
        status=EventStatus.PENDING_FACULTY,
        created_by_id=club_admin.id,
    )
    db.add_all([approved, pending])
    ensure_demo_checkin_event(db, coding, club_admin, faculty, student2)

    periods = [
        (1, "09:00", "10:00", "Data Structures"),
        (2, "10:00", "11:00", "Discrete Mathematics"),
        (3, "11:15", "12:15", "Digital Logic"),
        (4, "13:15", "14:15", "OOP Lab"),
    ]
    for day in range(5):
        for num, st, et, subj in periods:
            db.add(
                TimetableSlot(
                    department="CSE",
                    year=2,
                    section="A",
                    day_of_week=day,
                    period_number=num,
                    start_time=st,
                    end_time=et,
                    subject=subj,
                    faculty_id=faculty.id,
                )
            )
    structure = TimetableStructure(
        name="Regular Weekday Schedule",
        scope="College-wide",
        working_days_json=json.dumps(list(range(5))),
        effective_from=datetime.utcnow().date(),
        is_active=True,
        created_by_id=super_admin.id,
    )
    db.add(structure)
    db.flush()
    for number, label, start_time, end_time, period_type in [
        (1, "Period 1", "09:00", "10:00", "CLASS"),
        (2, "Period 2", "10:00", "11:00", "CLASS"),
        (3, "Period 3", "11:15", "12:15", "CLASS"),
        (4, "Lunch Break", "12:15", "13:15", "LUNCH_BREAK"),
        (5, "Period 4", "13:15", "14:15", "CLASS"),
    ]:
        db.add(
            TimetablePeriod(
                structure_id=structure.id,
                period_number=number,
                label=label,
                start_time=start_time,
                end_time=end_time,
                period_type=period_type,
            )
        )
    db.commit()
    db.close()
    print("Seed complete. Demo logins:")
    print("  SUPER_ADMIN  superadmin@college.edu / SuperAdmin@123")
    print("  ADMIN        admin@college.edu / Admin@123")
    print("  FACULTY      faculty@college.edu / Faculty@123")
    print("  CLUB_ADMIN   clubadmin@college.edu / ClubAdmin@123")
    print("  STUDENT      student@college.edu / Student@123")


if __name__ == "__main__":
    seed()
