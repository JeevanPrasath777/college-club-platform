from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.database import get_db
from app.deps import assert_club_access, get_current_user, notify
from app.models import Club, Event, EventStatus, Registration, SystemRole, User
from app.schemas import EventCreate, EventDecision, EventOut, EventUpdate, RegistrationOut

router = APIRouter(prefix="/api/events", tags=["events"])


def event_to_out(db: Session, event: Event) -> EventOut:
    count = db.query(Registration).filter(Registration.event_id == event.id).count()
    data = EventOut.model_validate(event)
    data.registered_count = count
    return data


def _as_local_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def can_manage_event(db: Session, user: User, event: Event, permission: str = "edit_events"):
    if user.role in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN):
        return
    if user.role == SystemRole.CLUB_ADMIN:
        club = db.query(Club).filter(Club.id == event.club_id).first()
        if club and club.club_admin_id == user.id:
            return
        raise HTTPException(status_code=403, detail="Cross-club access denied")
    assert_club_access(db, user, event.club_id, permission=permission)


@router.get("", response_model=list[EventOut])
def list_events(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    q: str | None = None,
    status: EventStatus | None = None,
    club_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = db.query(Event)
    if user.role == SystemRole.STUDENT:
        # Keep active events visible to registered students so they can find
        # event-day information after an organizer starts the event.
        query = query.filter(Event.status.in_((EventStatus.APPROVED, EventStatus.ONGOING)))
    if user.role == SystemRole.CLUB_ADMIN:
        club_ids = [c.id for c in db.query(Club).filter(Club.club_admin_id == user.id).all()]
        query = query.filter(Event.club_id.in_(club_ids or [-1]))
    if user.role == SystemRole.FACULTY:
        club_ids = [
            c.id
            for c in db.query(Club).filter(Club.faculty_coordinator_id == user.id).all()
        ]
        query = query.filter(Event.club_id.in_(club_ids or [-1]))
    if status:
        query = query.filter(Event.status == status)
    if club_id:
        query = query.filter(Event.club_id == club_id)
    if q:
        query = query.filter(Event.title.ilike(f"%{q}%"))
    events = query.order_by(Event.start_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return [event_to_out(db, e) for e in events]


@router.post("", response_model=EventOut, status_code=201)
def create_event(body: EventCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    start_at = _as_local_naive(body.start_at)
    end_at = _as_local_naive(body.end_at)
    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="Event end must be after start")
    if start_at <= datetime.now():
        raise HTTPException(status_code=400, detail="Event start must be in the future")
    club = assert_club_access(db, user, body.club_id, permission="create_events")
    if not club.is_active:
        raise HTTPException(status_code=409, detail="Events cannot be created for an archived club")
    if not club.faculty_coordinator_id:
        raise HTTPException(status_code=400, detail="Assign a Faculty Coordinator to this club before submitting events")
    if user.role not in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN, SystemRole.CLUB_ADMIN):
        assert_club_access(db, user, body.club_id, permission="create_events")
    if user.role == SystemRole.STUDENT:
        raise HTTPException(status_code=403, detail="Students cannot create events")
    if user.role == SystemRole.FACULTY:
        raise HTTPException(status_code=403, detail="Faculty approve events; they do not create club events")
    event = Event(
        club_id=club.id,
        title=body.title,
        description=body.description,
        venue=body.venue,
        start_at=start_at,
        end_at=end_at,
        capacity=body.capacity,
        status=EventStatus.PENDING_FACULTY,
        created_by_id=user.id,
    )
    db.add(event)
    db.flush()
    if club.faculty_coordinator_id:
        notify(
            db,
            club.faculty_coordinator_id,
            "Event pending approval",
            f"{event.title} from {club.name} awaits your approval.",
        )
    write_audit(db, user, "create_event", "event", event.id, {"status": event.status.value})
    db.commit()
    db.refresh(event)
    return event_to_out(db, event)


@router.patch("/{event_id}", response_model=EventOut)
def update_event(event_id: int, body: EventUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    can_manage_event(db, user, event, "edit_events")
    if event.status in (EventStatus.ONGOING, EventStatus.COMPLETED, EventStatus.CANCELLED):
        raise HTTPException(status_code=409, detail="Ongoing, completed, or cancelled events cannot be edited")
    if event.status == EventStatus.APPROVED and user.role == SystemRole.CLUB_ADMIN:
        raise HTTPException(status_code=400, detail="Approved events cannot be edited by Club Admin; request a new event")
    for field in ("title", "description", "venue", "start_at", "end_at", "capacity"):
        val = getattr(body, field)
        if val is not None:
            if field in ("start_at", "end_at"):
                val = _as_local_naive(val)
            setattr(event, field, val)
    if event.end_at <= event.start_at:
        raise HTTPException(status_code=400, detail="Event end must be after start")
    if event.start_at <= datetime.now() and event.status != EventStatus.ONGOING:
        raise HTTPException(status_code=400, detail="Event start must be in the future")
    if event.status == EventStatus.REJECTED:
        if not any(getattr(body, field) is not None for field in ("title", "description", "venue", "start_at", "end_at", "capacity")):
            raise HTTPException(status_code=400, detail="Edit the event details before resubmitting it")
        event.status = EventStatus.PENDING_FACULTY
        event.approved_by_id = None
        event.approval_comment = ""
        club = db.query(Club).filter(Club.id == event.club_id).first()
        if club and club.faculty_coordinator_id:
            notify(db, club.faculty_coordinator_id, "Event resubmitted", f"{event.title} was resubmitted for approval.")
    write_audit(db, user, "update_event", "event", event.id)
    db.commit()
    db.refresh(event)
    return event_to_out(db, event)


@router.post("/{event_id}/approve", response_model=EventOut)
def approve_event(
    event_id: int,
    body: EventDecision,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in (SystemRole.FACULTY, SystemRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Only the assigned Faculty Coordinator or Super Admin can approve events")
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.status != EventStatus.PENDING_FACULTY:
        raise HTTPException(status_code=409, detail="Only pending events can be approved")
    club = db.query(Club).filter(Club.id == event.club_id).first()
    if user.role == SystemRole.FACULTY and (not club or club.faculty_coordinator_id != user.id):
        raise HTTPException(status_code=403, detail="Only this club's assigned Faculty Coordinator can approve")
    event.status = EventStatus.APPROVED
    event.approved_by_id = user.id
    event.approval_comment = body.comment
    if club and club.club_admin_id:
        notify(db, club.club_admin_id, "Event approved", f"{event.title} was approved.")
    write_audit(db, user, "approve_event", "event", event.id)
    db.commit()
    db.refresh(event)
    return event_to_out(db, event)


@router.post("/{event_id}/reject", response_model=EventOut)
def reject_event(
    event_id: int,
    body: EventDecision,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in (SystemRole.FACULTY, SystemRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Only the assigned Faculty Coordinator or Super Admin can reject events")
    if not body.comment.strip():
        raise HTTPException(status_code=400, detail="Please provide a rejection reason")
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.status != EventStatus.PENDING_FACULTY:
        raise HTTPException(status_code=409, detail="Only pending events can be rejected")
    club = db.query(Club).filter(Club.id == event.club_id).first()
    if user.role == SystemRole.FACULTY and (not club or club.faculty_coordinator_id != user.id):
        raise HTTPException(status_code=403, detail="Only this club's assigned Faculty Coordinator can reject")
    event.status = EventStatus.REJECTED
    event.approved_by_id = user.id
    event.approval_comment = body.comment.strip()
    if club and club.club_admin_id:
        notify(db, club.club_admin_id, "Event needs changes", f"{event.title} was rejected: {body.comment.strip()}")
    write_audit(db, user, "reject_event", "event", event.id)
    db.commit()
    db.refresh(event)
    return event_to_out(db, event)


@router.post("/{event_id}/start", response_model=EventOut)
def start_event(event_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    can_manage_event(db, user, event, "edit_events")
    if event.status != EventStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Only approved events can be started")
    if datetime.now() < event.start_at:
        raise HTTPException(status_code=400, detail="An event cannot start before its scheduled time")
    event.status = EventStatus.ONGOING
    write_audit(db, user, "start_event", "event", event.id)
    db.commit()
    db.refresh(event)
    return event_to_out(db, event)


@router.post("/{event_id}/complete", response_model=EventOut)
def complete_event(event_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    can_manage_event(db, user, event, "edit_events")
    if event.status != EventStatus.ONGOING:
        raise HTTPException(status_code=409, detail="Only ongoing events can be completed")
    if datetime.now() < event.end_at:
        raise HTTPException(status_code=400, detail="An event cannot be completed before its scheduled end")
    event.status = EventStatus.COMPLETED
    write_audit(db, user, "complete_event", "event", event.id)
    db.commit()
    db.refresh(event)
    return event_to_out(db, event)


@router.post("/{event_id}/cancel", response_model=EventOut)
def cancel_event(event_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    can_manage_event(db, user, event, "edit_events")
    if event.status in (EventStatus.COMPLETED, EventStatus.CANCELLED):
        raise HTTPException(status_code=409, detail="Event is already completed or cancelled")
    event.status = EventStatus.CANCELLED
    write_audit(db, user, "cancel_event", "event", event.id)
    db.commit()
    db.refresh(event)
    return event_to_out(db, event)


@router.post("/{event_id}/register", response_model=RegistrationOut, status_code=201)
def register_event(event_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != SystemRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can register for events")
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.status != EventStatus.APPROVED:
        raise HTTPException(status_code=403, detail="Students cannot register for unapproved events")
    if event.start_at <= datetime.now():
        raise HTTPException(status_code=409, detail="Registration is closed because the event has started")
    existing = (
        db.query(Registration)
        .filter(Registration.event_id == event_id, Registration.student_id == user.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already registered")
    count = db.query(Registration).filter(Registration.event_id == event_id).count()
    if count >= event.capacity:
        raise HTTPException(status_code=409, detail="Event is at full capacity")
    try:
        reg = Registration(event_id=event_id, student_id=user.id)
        db.add(reg)
        db.flush()
        write_audit(db, user, "register_event", "registration", reg.id, {"event_id": event_id})
        notify(db, user.id, "Event registration confirmed", f"You are registered for {event.title}.")
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate registration blocked")
    db.refresh(reg)
    return RegistrationOut(
        id=reg.id,
        event_id=reg.event_id,
        student_id=reg.student_id,
        registered_at=reg.registered_at,
        student_name=user.full_name,
        event_title=event.title,
        ra_number=user.ra_number,
    )


@router.get("/{event_id}/registrations", response_model=list[RegistrationOut])
def list_registrations(event_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if user.role == SystemRole.STUDENT:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user.role == SystemRole.CLUB_ADMIN:
        can_manage_event(db, user, event, "view_registrations")
    regs = db.query(Registration).filter(Registration.event_id == event_id).all()
    out = []
    for r in regs:
        out.append(
            RegistrationOut(
                id=r.id,
                event_id=r.event_id,
                student_id=r.student_id,
                registered_at=r.registered_at,
                student_name=r.student.full_name,
                event_title=event.title,
                ra_number=r.student.ra_number,
            )
        )
    return out
