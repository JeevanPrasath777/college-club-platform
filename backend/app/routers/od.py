from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.database import get_db
from app.deps import get_current_user, notify
from app.models import Event, EventStatus, ODRequest, ODStatus, Registration, SystemRole, User
from app.schemas import ODCreate, ODDecision, ODOut, PeriodOut
from app.timetable_overlap import snapshot_overlapping_periods

router = APIRouter(prefix="/api/od", tags=["od"])


def od_to_out(od: ODRequest) -> ODOut:
    return ODOut(
        id=od.id,
        registration_id=od.registration_id,
        student_id=od.student_id,
        event_id=od.event_id,
        mentor_id=od.mentor_id,
        status=od.status,
        student_reason=od.student_reason,
        mentor_comment=od.mentor_comment,
        decided_at=od.decided_at,
        created_at=od.created_at,
        periods=[PeriodOut.model_validate(p) for p in od.periods],
        student_name=od.student.full_name if od.student else None,
        event_title=od.event.title if od.event else None,
        event_start_at=od.event.start_at if od.event else None,
        event_end_at=od.event.end_at if od.event else None,
        event_venue=od.event.venue if od.event else None,
        student_ra_number=od.student.ra_number if od.student else None,
    )


@router.post("", response_model=ODOut, status_code=201)
def request_od(body: ODCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != SystemRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can request OD")
    reg = db.query(Registration).filter(Registration.id == body.registration_id).first()
    if not reg or reg.student_id != user.id:
        raise HTTPException(status_code=403, detail="OD requires your own event registration")
    existing = db.query(ODRequest).filter(ODRequest.registration_id == reg.id).first()
    if existing:
        raise HTTPException(status_code=409, detail="OD already requested for this registration")
    event = db.query(Event).filter(Event.id == reg.event_id).first()
    if not event or event.status != EventStatus.APPROVED:
        raise HTTPException(status_code=400, detail="OD can be requested only for an approved event")
    if not user.class_mentor_id:
        raise HTTPException(status_code=400, detail="A Class Mentor must be assigned before requesting OD")
    snapshots = snapshot_overlapping_periods(db, user, event.start_at, event.end_at)
    od = ODRequest(
        registration_id=reg.id,
        student_id=user.id,
        event_id=event.id,
        mentor_id=user.class_mentor_id,
        student_reason=body.reason,
        status=ODStatus.PENDING,
    )
    db.add(od)
    db.flush()
    for snap in snapshots:
        snap.od_request_id = od.id
        db.add(snap)
    if user.class_mentor_id:
        notify(db, user.class_mentor_id, "OD request pending", f"{user.full_name} requested OD for {event.title}.")
    write_audit(db, user, "create_od", "od", od.id, {"periods": len(snapshots)})
    db.commit()
    db.refresh(od)
    return od_to_out(od)


@router.get("", response_model=list[ODOut])
def list_od(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    status: ODStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    query = db.query(ODRequest)
    if user.role == SystemRole.STUDENT:
        query = query.filter(ODRequest.student_id == user.id)
    elif user.role == SystemRole.FACULTY:
        query = query.filter(ODRequest.mentor_id == user.id)
    elif user.role == SystemRole.CLUB_ADMIN:
        raise HTTPException(status_code=403, detail="Club Admin cannot view or approve OD")
    elif user.role not in (SystemRole.ADMIN, SystemRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Forbidden")
    if status:
        query = query.filter(ODRequest.status == status)
    items = query.order_by(ODRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return [od_to_out(x) for x in items]


@router.post("/{od_id}/approve", response_model=ODOut)
def approve_od(od_id: int, body: ODDecision, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == SystemRole.CLUB_ADMIN:
        raise HTTPException(status_code=403, detail="Club Admin cannot approve OD")
    od = db.query(ODRequest).filter(ODRequest.id == od_id).first()
    if not od:
        raise HTTPException(status_code=404, detail="OD not found")
    if od.status != ODStatus.PENDING:
        raise HTTPException(status_code=409, detail="This OD request has already been decided")
    if user.role == SystemRole.SUPER_ADMIN:
        pass
    elif user.role == SystemRole.FACULTY:
        if od.mentor_id != user.id:
            raise HTTPException(status_code=403, detail="Only the student's Class Mentor can approve this OD")
    else:
        raise HTTPException(status_code=403, detail="Only Class Mentor can approve OD")
    od.status = ODStatus.APPROVED
    od.mentor_comment = body.comment
    od.decided_at = datetime.utcnow()
    notify(db, od.student_id, "OD approved", f"Your OD for {od.event.title} was approved.")
    write_audit(db, user, "approve_od", "od", od.id)
    db.commit()
    db.refresh(od)
    return od_to_out(od)


@router.post("/{od_id}/reject", response_model=ODOut)
def reject_od(od_id: int, body: ODDecision, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == SystemRole.CLUB_ADMIN:
        raise HTTPException(status_code=403, detail="Club Admin cannot reject OD")
    od = db.query(ODRequest).filter(ODRequest.id == od_id).first()
    if not od:
        raise HTTPException(status_code=404, detail="OD not found")
    if od.status != ODStatus.PENDING:
        raise HTTPException(status_code=409, detail="This OD request has already been decided")
    if user.role == SystemRole.SUPER_ADMIN:
        pass
    elif user.role == SystemRole.FACULTY:
        if od.mentor_id != user.id:
            raise HTTPException(status_code=403, detail="Only the student's Class Mentor can reject this OD")
    else:
        raise HTTPException(status_code=403, detail="Only Class Mentor can reject OD")
    od.status = ODStatus.REJECTED
    od.mentor_comment = body.comment
    od.decided_at = datetime.utcnow()
    notify(db, od.student_id, "OD rejected", f"Your OD for {od.event.title} was rejected.")
    write_audit(db, user, "reject_od", "od", od.id)
    db.commit()
    db.refresh(od)
    return od_to_out(od)


@router.patch("/{od_id}/periods")
def block_period_mutation(od_id: int, user: User = Depends(get_current_user)):
    raise HTTPException(status_code=403, detail="OD period snapshots are immutable")
