from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import SystemRole, TimetableSlot, User
from app.schemas import TimetableCreate, TimetableOut

router = APIRouter(prefix="/api/timetable", tags=["timetable"])


@router.get("", response_model=list[TimetableOut])
def list_slots(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    department: str | None = None,
    year: int | None = None,
    section: str | None = None,
):
    query = db.query(TimetableSlot)
    if user.role == SystemRole.STUDENT:
        query = query.filter(
            TimetableSlot.department == user.department,
            TimetableSlot.year == user.year,
            TimetableSlot.section == user.section,
        )
    else:
        if department:
            query = query.filter(TimetableSlot.department == department)
        if year is not None:
            query = query.filter(TimetableSlot.year == year)
        if section:
            query = query.filter(TimetableSlot.section == section)
    return query.order_by(TimetableSlot.day_of_week, TimetableSlot.period_number).all()


@router.post("", response_model=TimetableOut, status_code=201)
def create_slot(
    body: TimetableCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(SystemRole.SUPER_ADMIN)),
):
    existing = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.department == body.department,
            TimetableSlot.year == body.year,
            TimetableSlot.section == body.section,
            TimetableSlot.day_of_week == body.day_of_week,
            TimetableSlot.period_number == body.period_number,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Slot already exists")
    slot = TimetableSlot(**body.model_dump())
    db.add(slot)
    write_audit(db, user, "create_timetable_slot", "timetable", None, body.model_dump())
    db.commit()
    db.refresh(slot)
    return slot


@router.put("/{slot_id}", response_model=TimetableOut)
def update_slot(
    slot_id: int,
    body: TimetableCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(SystemRole.SUPER_ADMIN)),
):
    slot = db.query(TimetableSlot).filter(TimetableSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    for k, v in body.model_dump().items():
        setattr(slot, k, v)
    write_audit(db, user, "update_timetable_slot", "timetable", slot.id)
    db.commit()
    db.refresh(slot)
    return slot


@router.delete("/{slot_id}")
def delete_slot(
    slot_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(SystemRole.SUPER_ADMIN)),
):
    slot = db.query(TimetableSlot).filter(TimetableSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    db.delete(slot)
    write_audit(db, user, "delete_timetable_slot", "timetable", slot_id)
    db.commit()
    return {"ok": True}


@router.post("/{slot_id}")
def reject_non_super_write_alias(slot_id: int, user: User = Depends(get_current_user)):
    if user.role != SystemRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Non-Super-Admin cannot edit the master timetable")
    raise HTTPException(status_code=405, detail="Use PUT to update")
