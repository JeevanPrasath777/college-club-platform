import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import SystemRole, TimetablePeriod, TimetableStructure, User
from app.schemas import TimetableStructureCreate, TimetableStructureOut

router = APIRouter(prefix="/api/timetable/structures", tags=["timetable structure"])


def validate_periods(periods):
    ordered = sorted(periods, key=lambda period: period.period_number)
    if len({period.period_number for period in ordered}) != len(ordered):
        raise HTTPException(status_code=400, detail="Period numbers must be unique")
    previous_end = None
    for period in ordered:
        if period.end_time <= period.start_time:
            raise HTTPException(status_code=400, detail=f"{period.label}: end time must be after start time")
        if previous_end is not None and period.start_time < previous_end:
            raise HTTPException(status_code=400, detail="Periods must be chronological and must not overlap")
        previous_end = period.end_time
    return ordered


def to_output(structure: TimetableStructure) -> TimetableStructureOut:
    result = TimetableStructureOut.model_validate(structure)
    gaps = []
    ordered = sorted(structure.periods, key=lambda period: period.period_number)
    for previous, current in zip(ordered, ordered[1:]):
        if previous.end_time < current.start_time:
            gaps.append(f"Gap between {previous.label} and {current.label}.")
    result.warnings = gaps
    return result


def save_periods(structure: TimetableStructure, body: TimetableStructureCreate):
    periods = validate_periods(body.periods)
    structure.periods.clear()
    for period in periods:
        structure.periods.append(
            TimetablePeriod(
                period_number=period.period_number,
                label=period.label.strip(),
                start_time=period.start_time.strftime("%H:%M"),
                end_time=period.end_time.strftime("%H:%M"),
                period_type=period.period_type,
            )
        )


@router.get("/active", response_model=TimetableStructureOut)
def active_structure(
    on_date: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    selected_date = on_date or date.today()
    structures = (
        db.query(TimetableStructure)
        .filter(TimetableStructure.is_active.is_(True), TimetableStructure.effective_from <= selected_date)
        .order_by(TimetableStructure.effective_from.desc())
        .all()
    )
    matches = [structure for structure in structures if selected_date.weekday() in structure.working_days]
    if not matches:
        raise HTTPException(status_code=404, detail="No active timetable structure applies to this date")
    latest_effective_date = max(structure.effective_from for structure in matches)
    matches = [structure for structure in matches if structure.effective_from == latest_effective_date]
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="More than one active timetable structure applies to this date")
    return to_output(matches[0])


@router.get("", response_model=list[TimetableStructureOut])
def list_structures(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(TimetableStructure).order_by(TimetableStructure.effective_from.desc()).all()
    return [to_output(row) for row in rows]


@router.post("", response_model=TimetableStructureOut, status_code=201)
def create_structure(
    body: TimetableStructureCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(SystemRole.SUPER_ADMIN)),
):
    periods = validate_periods(body.periods)
    structure = TimetableStructure(
        name=body.name.strip(),
        scope=body.scope.strip(),
        legacy_working_days=json.dumps(body.working_days),
        working_days_json=json.dumps(body.working_days),
        effective_from=body.effective_from,
        is_active=False,
        created_by_id=user.id,
    )
    for period in periods:
        structure.periods.append(
            TimetablePeriod(
                period_number=period.period_number,
                label=period.label.strip(),
                start_time=period.start_time.strftime("%H:%M"),
                end_time=period.end_time.strftime("%H:%M"),
                period_type=period.period_type,
            )
        )
    db.add(structure)
    db.flush()
    write_audit(db, user, "create_timetable_structure", "timetable_structure", structure.id, body.model_dump(mode="json"))
    db.commit()
    db.refresh(structure)
    return to_output(structure)


@router.put("/{structure_id}", response_model=TimetableStructureOut)
def update_structure(
    structure_id: int,
    body: TimetableStructureCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(SystemRole.SUPER_ADMIN)),
):
    structure = db.query(TimetableStructure).filter(TimetableStructure.id == structure_id).first()
    if not structure:
        raise HTTPException(status_code=404, detail="Timetable structure not found")
    validate_periods(body.periods)
    if structure.is_active:
        days = set(body.working_days)
        active_others = db.query(TimetableStructure).filter(
            TimetableStructure.is_active.is_(True),
            TimetableStructure.id != structure.id,
            TimetableStructure.effective_from == body.effective_from,
        ).all()
        if any(days.intersection(other.working_days) for other in active_others):
            raise HTTPException(status_code=409, detail="Deactivate overlapping active structures before changing working days")
    structure.name = body.name.strip()
    structure.scope = body.scope.strip()
    structure.legacy_working_days = json.dumps(body.working_days)
    structure.working_days_json = json.dumps(body.working_days)
    structure.effective_from = body.effective_from
    structure.periods.clear()
    db.flush()
    save_periods(structure, body)
    write_audit(db, user, "update_timetable_structure", "timetable_structure", structure.id, body.model_dump(mode="json"))
    db.commit()
    db.refresh(structure)
    return to_output(structure)


@router.post("/{structure_id}/activate", response_model=TimetableStructureOut)
def activate_structure(
    structure_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(SystemRole.SUPER_ADMIN)),
):
    structure = db.query(TimetableStructure).filter(TimetableStructure.id == structure_id).first()
    if not structure:
        raise HTTPException(status_code=404, detail="Timetable structure not found")
    days = set(structure.working_days)
    conflicts = db.query(TimetableStructure).filter(
        TimetableStructure.is_active.is_(True),
        TimetableStructure.id != structure.id,
        TimetableStructure.effective_from == structure.effective_from,
    ).all()
    for active in conflicts:
        if days.intersection(active.working_days):
            raise HTTPException(
                status_code=409,
                detail=f"Deactivate '{active.name}' first; active structures cannot overlap working days",
            )
    structure.is_active = True
    write_audit(db, user, "activate_timetable_structure", "timetable_structure", structure.id)
    db.commit()
    db.refresh(structure)
    return to_output(structure)


@router.post("/{structure_id}/deactivate", response_model=TimetableStructureOut)
def deactivate_structure(
    structure_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(SystemRole.SUPER_ADMIN)),
):
    structure = db.query(TimetableStructure).filter(TimetableStructure.id == structure_id).first()
    if not structure:
        raise HTTPException(status_code=404, detail="Timetable structure not found")
    structure.is_active = False
    write_audit(db, user, "deactivate_timetable_structure", "timetable_structure", structure.id)
    db.commit()
    db.refresh(structure)
    return to_output(structure)


@router.delete("/{structure_id}")
def delete_structure(
    structure_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(SystemRole.SUPER_ADMIN)),
):
    structure = db.query(TimetableStructure).filter(TimetableStructure.id == structure_id).first()
    if not structure:
        raise HTTPException(status_code=404, detail="Timetable structure not found")
    if structure.is_active:
        raise HTTPException(status_code=409, detail="Deactivate the structure before deleting it")
    write_audit(db, user, "delete_timetable_structure", "timetable_structure", structure.id)
    db.delete(structure)
    db.commit()
    return {"ok": True}
