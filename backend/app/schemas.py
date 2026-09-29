from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import AnnouncementScope, EventStatus, ODStatus, SystemRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: SystemRole
    user: dict


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    role: SystemRole
    ra_number: Optional[str] = None
    department: Optional[str] = None
    year: Optional[int] = None
    section: Optional[str] = None
    class_mentor_id: Optional[int] = None

    @field_validator("ra_number")
    @classmethod
    def valid_ra_number(cls, value):
        if value is not None and (len(value) != 15 or not value.isascii() or not value.isalnum()):
            raise ValueError("RA Number must contain exactly 15 letters or digits")
        return value.upper() if value else value


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    department: Optional[str] = None
    year: Optional[int] = None
    section: Optional[str] = None
    class_mentor_id: Optional[int] = None
    ra_number: Optional[str] = None
    role: Optional[SystemRole] = None
    password: Optional[str] = None

    @field_validator("ra_number")
    @classmethod
    def valid_ra_number(cls, value):
        if value is not None and (len(value) != 15 or not value.isascii() or not value.isalnum()):
            raise ValueError("RA Number must contain exactly 15 letters or digits")
        return value.upper() if value else value


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: SystemRole
    ra_number: Optional[str]
    department: Optional[str]
    year: Optional[int]
    section: Optional[str]
    class_mentor_id: Optional[int]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ClubCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "General"
    club_admin_id: Optional[int] = None
    faculty_coordinator_id: Optional[int] = None


class ClubUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    club_admin_id: Optional[int] = None
    faculty_coordinator_id: Optional[int] = None
    is_active: Optional[bool] = None


class ClubOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    category: Optional[str]
    club_admin_id: Optional[int]
    faculty_coordinator_id: Optional[int] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ClubRoleCreate(BaseModel):
    name: str
    permissions: list[str] = []


class ClubRoleOut(BaseModel):
    id: int
    club_id: int
    name: str
    permissions: list[str] = []

    class Config:
        from_attributes = True


class MemberAdd(BaseModel):
    user_id: int
    club_role_id: Optional[int] = None


class EventCreate(BaseModel):
    club_id: int
    title: str
    description: str = ""
    venue: str = ""
    start_at: datetime
    end_at: datetime
    capacity: int = Field(gt=0, default=50)


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    venue: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    capacity: Optional[int] = Field(default=None, gt=0)


class EventDecision(BaseModel):
    comment: str = ""


class EventOut(BaseModel):
    id: int
    club_id: int
    title: str
    description: Optional[str]
    venue: Optional[str]
    start_at: datetime
    end_at: datetime
    capacity: int
    status: EventStatus
    created_by_id: int
    approved_by_id: Optional[int]
    approval_comment: Optional[str]
    created_at: datetime
    registered_count: int = 0

    class Config:
        from_attributes = True


class RegistrationOut(BaseModel):
    id: int
    event_id: int
    student_id: int
    registered_at: datetime
    student_name: Optional[str] = None
    event_title: Optional[str] = None
    ra_number: Optional[str] = None

    class Config:
        from_attributes = True


class ODCreate(BaseModel):
    registration_id: int
    reason: str = ""


class ODDecision(BaseModel):
    comment: str = ""


class PeriodOut(BaseModel):
    id: int
    day_of_week: int
    period_number: int
    start_time: str
    end_time: str
    subject: str
    department: Optional[str]
    year: Optional[int]
    section: Optional[str]
    frozen_at: datetime

    class Config:
        from_attributes = True


class ODOut(BaseModel):
    id: int
    registration_id: int
    student_id: int
    event_id: int
    mentor_id: Optional[int]
    status: ODStatus
    student_reason: Optional[str]
    mentor_comment: Optional[str]
    decided_at: Optional[datetime]
    created_at: datetime
    periods: list[PeriodOut] = []
    student_name: Optional[str] = None
    event_title: Optional[str] = None
    event_start_at: Optional[datetime] = None
    event_end_at: Optional[datetime] = None
    event_venue: Optional[str] = None
    student_ra_number: Optional[str] = None

    class Config:
        from_attributes = True


class TimetableCreate(BaseModel):
    department: str
    year: int
    section: str
    day_of_week: int = Field(ge=0, le=6)
    period_number: int = Field(ge=1)
    start_time: str
    end_time: str
    subject: str
    faculty_id: Optional[int] = None


class TimetableOut(BaseModel):
    id: int
    department: str
    year: int
    section: str
    day_of_week: int
    period_number: int
    start_time: str
    end_time: str
    subject: str
    faculty_id: Optional[int]

    class Config:
        from_attributes = True


class TimetablePeriodInput(BaseModel):
    period_number: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=128)
    start_time: time
    end_time: time
    period_type: Literal["CLASS", "SHORT_BREAK", "LUNCH_BREAK"] = "CLASS"


class TimetableStructureCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scope: str = Field(default="College-wide", max_length=128)
    working_days: list[int] = Field(min_length=1, max_length=7)
    effective_from: date
    periods: list[TimetablePeriodInput] = Field(min_length=1)

    @field_validator("working_days")
    @classmethod
    def unique_valid_days(cls, value):
        if any(day < 0 or day > 6 for day in value) or len(set(value)) != len(value):
            raise ValueError("Working days must be unique values from 0 (Monday) to 6 (Sunday)")
        return sorted(value)


class TimetablePeriodOut(BaseModel):
    id: int
    period_number: int
    label: str
    start_time: str
    end_time: str
    period_type: str
    duration_minutes: int

    class Config:
        from_attributes = True


class TimetableStructureOut(BaseModel):
    id: int
    name: str
    scope: str
    working_days: list[int]
    effective_from: date
    is_active: bool
    periods: list[TimetablePeriodOut]
    warnings: list[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class AttendanceMark(BaseModel):
    event_id: int
    student_id: int
    present: bool = True


class AttendanceOut(BaseModel):
    id: int
    event_id: int
    student_id: int
    present: bool
    marked_by_id: int
    marked_at: datetime
    student_name: Optional[str] = None

    class Config:
        from_attributes = True


class CheckInCodeOut(BaseModel):
    event_id: int
    event_title: str
    code: str
    expires_at: datetime


class StudentCheckIn(BaseModel):
    event_id: int
    code: str = Field(min_length=8, max_length=8, pattern=r"^[A-Z0-9]{8}$")


class CertificateIssue(BaseModel):
    event_id: int
    student_id: int
    participation_role: str = Field(default="Participant", min_length=1, max_length=64)


class CertificateOut(BaseModel):
    id: int
    student_id: int
    event_id: int
    verification_id: str
    issued_by_id: int
    issued_at: datetime
    student_name: Optional[str] = None
    event_title: Optional[str] = None
    participation_role: str = "Participant"

    class Config:
        from_attributes = True


class BadgeCreate(BaseModel):
    club_id: int
    name: str
    description: str = ""


class BadgeAward(BaseModel):
    user_id: int
    badge_id: int


class BadgeOut(BaseModel):
    id: int
    club_id: int
    name: str
    description: Optional[str]

    class Config:
        from_attributes = True


class UserBadgeOut(BaseModel):
    id: int
    user_id: int
    badge_id: int
    awarded_at: datetime
    badge_name: Optional[str] = None
    club_id: Optional[int] = None

    class Config:
        from_attributes = True


class NotificationOut(BaseModel):
    id: int
    user_id: int
    title: str
    body: Optional[str]
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    recipient_id: int
    body: str = Field(min_length=1, max_length=4000)
    event_id: Optional[int] = None

    @field_validator("body")
    @classmethod
    def non_blank_message(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be blank")
        return value


class MessageReply(BaseModel):
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def non_blank_message(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be blank")
        return value


class AnnouncementCreate(BaseModel):
    title: str
    body: str = ""
    scope: AnnouncementScope
    club_id: Optional[int] = None
    target_role: Optional[SystemRole] = None


class AnnouncementOut(BaseModel):
    id: int
    title: str
    body: Optional[str]
    scope: AnnouncementScope
    club_id: Optional[int]
    target_role: Optional[SystemRole]
    created_by_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    department: Optional[str] = None
    year: Optional[int] = None
    section: Optional[str] = None
    password: Optional[str] = None


class Paginated(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
