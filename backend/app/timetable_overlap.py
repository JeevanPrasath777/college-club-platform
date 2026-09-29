from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.deps import parse_hhmm, time_ranges_overlap
from app.models import ODPeriodSnapshot, TimetableSlot, TimetableStructure, User


def snapshot_overlapping_periods(db: Session, student: User, event_start: datetime, event_end: datetime) -> list[ODPeriodSnapshot]:
    """Server-side overlap: weekly master timetable vs event window. Snapshots are immutable after insert."""
    snapshots: list[ODPeriodSnapshot] = []
    cursor = event_start.date()
    end_date = event_end.date()
    while cursor <= end_date:
        day = cursor.weekday()
        structures = (
            db.query(TimetableStructure)
            .filter(
                TimetableStructure.is_active.is_(True),
                TimetableStructure.effective_from <= cursor,
            )
            .order_by(TimetableStructure.effective_from.desc())
            .all()
        )
        structures = [structure for structure in structures if day in structure.working_days]
        if structures:
            periods = [
                period for period in structures[0].periods if period.period_type == "CLASS"
            ]
            slots = [
                (None, period.period_number, period.start_time, period.end_time, period.label)
                for period in periods
            ]
        else:
            legacy_slots = [] if not student.department or student.year is None or not student.section else (
                db.query(TimetableSlot)
                .filter(
                    TimetableSlot.department == student.department,
                    TimetableSlot.year == student.year,
                    TimetableSlot.section == student.section,
                    TimetableSlot.day_of_week == day,
                )
                .all()
            )
            slots = [
                (slot.id, slot.period_number, slot.start_time, slot.end_time, slot.subject)
                for slot in legacy_slots
            ]
        for slot_id, period_number, start_time, end_time, label in slots:
            s_t = parse_hhmm(start_time)
            e_t = parse_hhmm(end_time)
            slot_start = datetime.combine(cursor, s_t)
            slot_end = datetime.combine(cursor, e_t)
            if slot_end <= slot_start:
                slot_end += timedelta(days=1)
            if time_ranges_overlap(event_start, event_end, slot_start, slot_end):
                snapshots.append(
                    ODPeriodSnapshot(
                        timetable_slot_id=slot_id,
                        day_of_week=day,
                        period_number=period_number,
                        start_time=start_time,
                        end_time=end_time,
                        subject=label,
                        department=student.department,
                        year=student.year,
                        section=student.section,
                    )
                )
        cursor += timedelta(days=1)
    return snapshots
