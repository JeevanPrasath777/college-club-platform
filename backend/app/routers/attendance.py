import hashlib
import secrets
import string
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.certificates import generate_certificate_pdf, new_verification_id
from app.database import get_db
from app.deps import assert_club_access, get_current_user, notify
from app.models import (
    Attendance,
    Certificate,
    Club,
    Event,
    EventCheckinSession,
    EventStatus,
    Registration,
    SystemRole,
    User,
)
from app.schemas import (
    AttendanceMark,
    AttendanceOut,
    CheckInCodeOut,
    CertificateIssue,
    CertificateOut,
    StudentCheckIn,
)

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


@router.post("", response_model=AttendanceOut)
def mark(body: AttendanceMark, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    event = db.query(Event).filter(Event.id == body.event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if user.role == SystemRole.STUDENT:
        raise HTTPException(status_code=403, detail="Students cannot mark attendance")
    if user.role == SystemRole.CLUB_ADMIN:
        assert_club_access(db, user, event.club_id, permission="mark_attendance")
    elif user.role == SystemRole.FACULTY:
        club = db.query(Club).filter(Club.id == event.club_id).first()
        if not club or club.faculty_coordinator_id != user.id:
            raise HTTPException(status_code=403, detail="Only this club's Faculty Coordinator can mark attendance")
    elif user.role not in (SystemRole.ADMIN, SystemRole.SUPER_ADMIN):
        assert_club_access(db, user, event.club_id, permission="mark_attendance")
    registered = (
        db.query(Registration)
        .filter(Registration.event_id == body.event_id, Registration.student_id == body.student_id)
        .first()
    )
    if not registered:
        raise HTTPException(status_code=400, detail="Student is not registered for this event")
    row = (
        db.query(Attendance)
        .filter(Attendance.event_id == body.event_id, Attendance.student_id == body.student_id)
        .first()
    )
    if row:
        row.present = body.present
        row.marked_by_id = user.id
    else:
        row = Attendance(
            event_id=body.event_id,
            student_id=body.student_id,
            present=body.present,
            marked_by_id=user.id,
        )
        db.add(row)
    write_audit(db, user, "mark_attendance", "attendance", body.student_id, {"event_id": body.event_id})
    db.commit()
    db.refresh(row)
    student = db.query(User).filter(User.id == body.student_id).first()
    return AttendanceOut(
        id=row.id,
        event_id=row.event_id,
        student_id=row.student_id,
        present=row.present,
        marked_by_id=row.marked_by_id,
        marked_at=row.marked_at,
        student_name=student.full_name if student else None,
    )


@router.get("/event/{event_id}", response_model=list[AttendanceOut])
def list_event_attendance(event_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if user.role == SystemRole.STUDENT:
        raise HTTPException(status_code=403, detail="Use /api/attendance/me")
    if user.role == SystemRole.FACULTY:
        club = db.query(Club).filter(Club.id == event.club_id).first()
        if not club or club.faculty_coordinator_id != user.id:
            raise HTTPException(status_code=403, detail="Only this club's Faculty Coordinator can view attendance")
    elif user.role == SystemRole.CLUB_ADMIN:
        assert_club_access(db, user, event.club_id, permission="mark_attendance")
    elif user.role not in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN):
        assert_club_access(db, user, event.club_id, permission="mark_attendance")
    rows = db.query(Attendance).filter(Attendance.event_id == event_id).all()
    return [
        AttendanceOut(
            id=r.id,
            event_id=r.event_id,
            student_id=r.student_id,
            present=r.present,
            marked_by_id=r.marked_by_id,
            marked_at=r.marked_at,
            student_name=r.student.full_name,
        )
        for r in rows
    ]


@router.get("/me", response_model=list[AttendanceOut])
def my_attendance(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Attendance).filter(Attendance.student_id == user.id).all()
    return [
        AttendanceOut(
            id=r.id,
            event_id=r.event_id,
            student_id=r.student_id,
            present=r.present,
            marked_by_id=r.marked_by_id,
            marked_at=r.marked_at,
        )
        for r in rows
    ]


def _assert_attendance_manager(db: Session, user: User, event: Event):
    if user.role in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN):
        return
    if user.role == SystemRole.FACULTY:
        club = db.query(Club).filter(Club.id == event.club_id).first()
        if club and club.faculty_coordinator_id == user.id:
            return
        raise HTTPException(status_code=403, detail="Only this club's Faculty Coordinator can manage check-in")
    if user.role == SystemRole.CLUB_ADMIN:
        assert_club_access(db, user, event.club_id, permission="mark_attendance")
        return
    raise HTTPException(status_code=403, detail="Only event organizers can generate check-in codes")


@router.post("/event/{event_id}/check-in-code", response_model=CheckInCodeOut)
def create_check_in_code(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    _assert_attendance_manager(db, user, event)
    now = datetime.now()
    if event.status != EventStatus.ONGOING:
        raise HTTPException(status_code=409, detail="Start the approved event before generating a check-in code")
    if event.end_at <= now:
        raise HTTPException(status_code=409, detail="This event has already ended")

    code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    expires_at = min(now + timedelta(minutes=10), event.end_at)
    row = db.query(EventCheckinSession).filter(EventCheckinSession.event_id == event.id).first()
    if row:
        row.code_hash = hashlib.sha256(code.encode("ascii")).hexdigest()
        row.expires_at = expires_at
        row.created_by_id = user.id
        row.created_at = now
    else:
        row = EventCheckinSession(
            event_id=event.id,
            code_hash=hashlib.sha256(code.encode("ascii")).hexdigest(),
            expires_at=expires_at,
            created_by_id=user.id,
            created_at=now,
        )
        db.add(row)
    write_audit(db, user, "create_event_checkin_code", "event", event.id)
    db.commit()
    return CheckInCodeOut(
        event_id=event.id,
        event_title=event.title,
        code=code,
        expires_at=expires_at,
    )


@router.post("/check-in", response_model=AttendanceOut)
def student_check_in(
    body: StudentCheckIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != SystemRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can use event self check-in")
    event = db.query(Event).filter(Event.id == body.event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    now = datetime.now()
    if event.status != EventStatus.ONGOING or event.end_at <= now:
        raise HTTPException(status_code=409, detail="Check-in is available only while the event is running")
    registration = db.query(Registration).filter(
        Registration.event_id == event.id,
        Registration.student_id == user.id,
    ).first()
    if not registration:
        raise HTTPException(status_code=403, detail="Register for this event before checking in")
    session = db.query(EventCheckinSession).filter(
        EventCheckinSession.event_id == event.id,
        EventCheckinSession.expires_at > now,
    ).first()
    if not session:
        raise HTTPException(status_code=410, detail="The check-in code expired. Ask an organizer for a new code")
    submitted_hash = hashlib.sha256(body.code.encode("ascii")).hexdigest()
    if not secrets.compare_digest(submitted_hash, session.code_hash):
        raise HTTPException(status_code=400, detail="That check-in code is not valid")

    row = db.query(Attendance).filter(
        Attendance.event_id == event.id,
        Attendance.student_id == user.id,
    ).first()
    if row and row.present:
        raise HTTPException(status_code=409, detail="You are already checked in")
    if row:
        row.present = True
        row.marked_by_id = user.id
        row.marked_at = now
    else:
        row = Attendance(
            event_id=event.id,
            student_id=user.id,
            present=True,
            marked_by_id=user.id,
            marked_at=now,
        )
        db.add(row)
    write_audit(db, user, "student_event_check_in", "event", event.id)
    db.commit()
    db.refresh(row)
    return AttendanceOut(
        id=row.id,
        event_id=row.event_id,
        student_id=row.student_id,
        present=row.present,
        marked_by_id=row.marked_by_id,
        marked_at=row.marked_at,
        student_name=user.full_name,
    )


certs_router = APIRouter(prefix="/api/certificates", tags=["certificates"])


@certs_router.post("", response_model=CertificateOut, status_code=201)
def issue(body: CertificateIssue, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    event = db.query(Event).filter(Event.id == body.event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.status != EventStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Certificates can be issued only after the event is completed")
    if user.role == SystemRole.STUDENT:
        raise HTTPException(status_code=403, detail="Students cannot issue certificates")
    assert_club_access(db, user, event.club_id, permission="issue_certificates")
    att = (
        db.query(Attendance)
        .filter(
            Attendance.event_id == body.event_id,
            Attendance.student_id == body.student_id,
            Attendance.present.is_(True),
        )
        .first()
    )
    if not att:
        raise HTTPException(status_code=400, detail="Certificate requires marked present attendance")
    existing = (
        db.query(Certificate)
        .filter(Certificate.event_id == body.event_id, Certificate.student_id == body.student_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Certificate already issued")
    student = db.query(User).filter(User.id == body.student_id).first()
    if not student or student.role != SystemRole.STUDENT:
        raise HTTPException(status_code=404, detail="Student not found")
    club = db.query(Club).filter(Club.id == event.club_id).first()
    vid = new_verification_id()
    from datetime import datetime

    issued_at = datetime.utcnow()
    path = generate_certificate_pdf(
        student.full_name,
        student.ra_number or "",
        event.title,
        club.name if club else "",
        vid,
        issued_at,
        event.start_at,
        body.participation_role.strip(),
    )
    cert = Certificate(
        student_id=student.id,
        event_id=event.id,
        verification_id=vid,
        issued_by_id=user.id,
        issued_at=issued_at,
        pdf_path=path,
        participation_role=body.participation_role.strip(),
    )
    db.add(cert)
    notify(db, student.id, "Certificate issued", f"Certificate for {event.title} is ready.")
    write_audit(db, user, "issue_certificate", "certificate", vid)
    db.commit()
    db.refresh(cert)
    return CertificateOut(
        id=cert.id,
        student_id=cert.student_id,
        event_id=cert.event_id,
        verification_id=cert.verification_id,
        issued_by_id=cert.issued_by_id,
        issued_at=cert.issued_at,
        student_name=student.full_name,
        event_title=event.title,
        participation_role=cert.participation_role,
    )


@certs_router.get("/me", response_model=list[CertificateOut])
def my_certs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Certificate).filter(Certificate.student_id == user.id).all()
    return [
        CertificateOut(
            id=c.id,
            student_id=c.student_id,
            event_id=c.event_id,
            verification_id=c.verification_id,
            issued_by_id=c.issued_by_id,
            issued_at=c.issued_at,
            event_title=c.event.title,
            participation_role=c.participation_role,
        )
        for c in rows
    ]


@certs_router.get("/verify/{verification_id}")
def verify(verification_id: str, db: Session = Depends(get_db)):
    cert = db.query(Certificate).filter(Certificate.verification_id == verification_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return {
        "valid": True,
        "verification_id": cert.verification_id,
        "student": cert.student.full_name,
        "ra_number": cert.student.ra_number,
        "event": cert.event.title,
        "event_date": cert.event.start_at.date().isoformat(),
        "participation_role": cert.participation_role,
        "issued_at": cert.issued_at.isoformat(),
    }


from fastapi.responses import FileResponse


@certs_router.get("/{cert_id}/pdf")
def download_pdf(cert_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cert = db.query(Certificate).filter(Certificate.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Not found")
    if user.role == SystemRole.STUDENT and cert.student_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return FileResponse(cert.pdf_path, media_type="application/pdf", filename=f"{cert.verification_id}.pdf")
