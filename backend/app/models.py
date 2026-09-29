import enum
import json
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class SystemRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    FACULTY = "FACULTY"
    CLUB_ADMIN = "CLUB_ADMIN"
    STUDENT = "STUDENT"


class EventStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_FACULTY = "PENDING_FACULTY"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ONGOING = "ONGOING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ODStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AnnouncementScope(str, enum.Enum):
    GLOBAL = "GLOBAL"
    CLUB = "CLUB"
    ROLE = "ROLE"


ALLOWED_CLUB_PERMISSIONS = {
    "manage_members",
    "create_events",
    "edit_events",
    "view_registrations",
    "mark_attendance",
    "issue_certificates",
    "issue_badges",
    "post_announcements",
    "view_club_analytics",
}

FORBIDDEN_CLUB_PERMISSIONS = {
    "approve_events",
    "approve_od",
    "manage_timetable",
    "manage_users",
    "assign_system_roles",
    "global_announcements",
    "super_admin",
}


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum(SystemRole), nullable=False, index=True)
    ra_number = Column(String(64), unique=True, nullable=True, index=True)
    department = Column(String(128), nullable=True, index=True)
    year = Column(Integer, nullable=True)
    section = Column(String(16), nullable=True)
    class_mentor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    mentor = relationship("User", remote_side=[id], foreign_keys=[class_mentor_id])
    clubs_admin = relationship("Club", back_populates="club_admin", foreign_keys="Club.club_admin_id")
    memberships = relationship("ClubMember", back_populates="user", foreign_keys="ClubMember.user_id")

    __table_args__ = (
        Index("ix_users_class_section", "department", "year", "section"),
        CheckConstraint(
            "role != 'STUDENT' OR (ra_number IS NOT NULL AND length(ra_number) = 15 "
            "AND ra_number NOT GLOB '*[^A-Za-z0-9]*')",
            name="ck_student_ra_format",
        ),
    )


class Club(Base):
    __tablename__ = "clubs"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text, default="")
    category = Column(String(128), default="General")
    club_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    faculty_coordinator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    club_admin = relationship("User", foreign_keys=[club_admin_id], back_populates="clubs_admin")
    faculty_coordinator = relationship("User", foreign_keys=[faculty_coordinator_id])
    members = relationship("ClubMember", back_populates="club", cascade="all, delete-orphan")
    roles = relationship("ClubRole", back_populates="club", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="club")


class ClubRole(Base):
    __tablename__ = "club_roles"

    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    permissions = Column(Text, default="[]")  # JSON list of club-scoped permissions
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    club = relationship("Club", back_populates="roles")
    members = relationship("ClubMember", back_populates="club_role")

    __table_args__ = (UniqueConstraint("club_id", "name", name="uq_club_role_name"),)


class ClubMember(Base):
    __tablename__ = "club_members"

    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    club_role_id = Column(Integer, ForeignKey("club_roles.id"), nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    club = relationship("Club", back_populates="members")
    user = relationship("User", back_populates="memberships")
    club_role = relationship("ClubRole", back_populates="members")

    __table_args__ = (UniqueConstraint("club_id", "user_id", name="uq_club_member"),)


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    venue = Column(String(255), default="")
    start_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime, nullable=False)
    capacity = Column(Integer, nullable=False, default=50)
    status = Column(Enum(EventStatus), default=EventStatus.PENDING_FACULTY, nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approval_comment = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    club = relationship("Club", back_populates="events")
    created_by = relationship("User", foreign_keys=[created_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    registrations = relationship("Registration", back_populates="event")

    __table_args__ = (CheckConstraint("capacity > 0", name="ck_event_capacity"),)


class Registration(Base):
    __tablename__ = "registrations"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    registered_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    event = relationship("Event", back_populates="registrations")
    student = relationship("User")
    od_request = relationship("ODRequest", back_populates="registration", uselist=False)

    __table_args__ = (UniqueConstraint("event_id", "student_id", name="uq_event_student"),)


class ODRequest(Base):
    __tablename__ = "od_requests"

    id = Column(Integer, primary_key=True)
    registration_id = Column(Integer, ForeignKey("registrations.id"), unique=True, nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    mentor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(Enum(ODStatus), default=ODStatus.PENDING, nullable=False, index=True)
    student_reason = Column(Text, default="")
    mentor_comment = Column(Text, default="")
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    registration = relationship("Registration", back_populates="od_request")
    student = relationship("User", foreign_keys=[student_id])
    event = relationship("Event")
    mentor = relationship("User", foreign_keys=[mentor_id])
    periods = relationship("ODPeriodSnapshot", back_populates="od_request", cascade="all, delete-orphan")


class ODPeriodSnapshot(Base):
    __tablename__ = "od_period_snapshots"

    id = Column(Integer, primary_key=True)
    od_request_id = Column(Integer, ForeignKey("od_requests.id", ondelete="CASCADE"), nullable=False)
    timetable_slot_id = Column(Integer, nullable=True)
    day_of_week = Column(Integer, nullable=False)
    period_number = Column(Integer, nullable=False)
    start_time = Column(String(8), nullable=False)
    end_time = Column(String(8), nullable=False)
    subject = Column(String(255), nullable=False)
    department = Column(String(128), nullable=True)
    year = Column(Integer, nullable=True)
    section = Column(String(16), nullable=True)
    frozen_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    od_request = relationship("ODRequest", back_populates="periods")


class TimetableStructure(Base):
    __tablename__ = "timetable_structures"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    scope = Column(String(128), nullable=False, default="College-wide")
    # Kept for compatibility with existing SQLite databases whose original
    # NOT NULL column was named `working_days`.
    legacy_working_days = Column("working_days", Text, nullable=False, default="[0,1,2,3,4]")
    working_days_json = Column(Text, nullable=False, default="[0,1,2,3,4]")
    effective_from = Column(Date, nullable=False)
    is_active = Column(Boolean, nullable=False, default=False, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    periods = relationship("TimetablePeriod", back_populates="structure", cascade="all, delete-orphan", order_by="TimetablePeriod.period_number")
    created_by = relationship("User")

    @property
    def working_days(self):
        try:
            days = json.loads(self.working_days_json or "[]")
            return days if isinstance(days, list) else []
        except (TypeError, json.JSONDecodeError):
            return []


class TimetablePeriod(Base):
    __tablename__ = "timetable_periods"

    id = Column(Integer, primary_key=True)
    structure_id = Column(Integer, ForeignKey("timetable_structures.id", ondelete="CASCADE"), nullable=False)
    period_number = Column(Integer, nullable=False)
    label = Column(String(128), nullable=False)
    start_time = Column(String(5), nullable=False)
    end_time = Column(String(5), nullable=False)
    period_type = Column(String(24), nullable=False, default="CLASS")
    structure = relationship("TimetableStructure", back_populates="periods")

    @property
    def duration_minutes(self):
        start = time.fromisoformat(self.start_time)
        end = time.fromisoformat(self.end_time)
        return int((datetime.combine(date.min, end) - datetime.combine(date.min, start)).total_seconds() // 60)

    __table_args__ = (
        UniqueConstraint("structure_id", "period_number", name="uq_structure_period_number"),
        CheckConstraint("period_type IN ('CLASS', 'SHORT_BREAK', 'LUNCH_BREAK')", name="ck_timetable_period_type"),
    )


class TimetableSlot(Base):
    __tablename__ = "timetable_slots"

    id = Column(Integer, primary_key=True)
    department = Column(String(128), nullable=False)
    year = Column(Integer, nullable=False)
    section = Column(String(16), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Mon
    period_number = Column(Integer, nullable=False)
    start_time = Column(String(8), nullable=False)
    end_time = Column(String(8), nullable=False)
    subject = Column(String(255), nullable=False)
    faculty_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    faculty = relationship("User")

    __table_args__ = (
        UniqueConstraint(
            "department", "year", "section", "day_of_week", "period_number",
            name="uq_timetable_slot",
        ),
        Index("ix_timetable_class", "department", "year", "section", "day_of_week"),
    )


class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    present = Column(Boolean, default=True, nullable=False)
    marked_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    marked_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    event = relationship("Event")
    student = relationship("User", foreign_keys=[student_id])
    marked_by = relationship("User", foreign_keys=[marked_by_id])

    __table_args__ = (UniqueConstraint("event_id", "student_id", name="uq_attendance"),)


class EventCheckinSession(Base):
    __tablename__ = "event_checkin_sessions"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), unique=True, nullable=False)
    code_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    event = relationship("Event")
    created_by = relationship("User")


class Certificate(Base):
    __tablename__ = "certificates"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    verification_id = Column(String(64), unique=True, nullable=False, index=True)
    issued_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    issued_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    pdf_path = Column(String(512), nullable=False)
    participation_role = Column(String(64), nullable=False, default="Participant")

    student = relationship("User", foreign_keys=[student_id])
    event = relationship("Event")
    issued_by = relationship("User", foreign_keys=[issued_by_id])

    __table_args__ = (UniqueConstraint("student_id", "event_id", name="uq_certificate"),)


class Badge(Base):
    __tablename__ = "badges"

    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    club = relationship("Club")

    __table_args__ = (UniqueConstraint("club_id", "name", name="uq_badge_name"),)


class UserBadge(Base):
    __tablename__ = "user_badges"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    badge_id = Column(Integer, ForeignKey("badges.id"), nullable=False)
    awarded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    awarded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", foreign_keys=[user_id])
    badge = relationship("Badge")
    awarded_by = relationship("User", foreign_keys=[awarded_by_id])

    __table_args__ = (UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, default="")
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    participant_a_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    participant_b_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")
    participant_a = relationship("User", foreign_keys=[participant_a_id])
    participant_b = relationship("User", foreign_keys=[participant_b_id])
    event = relationship("Event")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship("User")


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, default="")
    scope = Column(Enum(AnnouncementScope), nullable=False)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=True)
    target_role = Column(Enum(SystemRole), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    club = relationship("Club")
    created_by = relationship("User")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(128), nullable=False, index=True)
    entity_type = Column(String(64), nullable=False, index=True)
    entity_id = Column(String(64), nullable=True)
    details = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    actor = relationship("User")
