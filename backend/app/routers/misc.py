from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.database import get_db
from app.deps import assert_club_access, get_current_user, notify
from app.models import Announcement, AnnouncementScope, AuditLog, Badge, Club, Notification, SystemRole, User, UserBadge
from app.schemas import AnnouncementCreate, AnnouncementOut, BadgeAward, BadgeCreate, BadgeOut, NotificationOut, UserBadgeOut

badges_router = APIRouter(prefix="/api/badges", tags=["badges"])


@badges_router.post("", response_model=BadgeOut, status_code=201)
def create_badge(body: BadgeCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    assert_club_access(db, user, body.club_id, permission="issue_badges")
    if user.role not in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN, SystemRole.CLUB_ADMIN):
        raise HTTPException(status_code=403, detail="Only club administrators can define badge types")
    badge = Badge(club_id=body.club_id, name=body.name, description=body.description)
    db.add(badge)
    write_audit(db, user, "create_badge", "badge", None, {"club_id": body.club_id})
    db.commit()
    db.refresh(badge)
    return badge


@badges_router.get("", response_model=list[BadgeOut])
def list_badges(club_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Badge)
    if club_id:
        q = q.filter(Badge.club_id == club_id)
    return q.all()


@badges_router.post("/award", response_model=UserBadgeOut)
def award(body: BadgeAward, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    badge = db.query(Badge).filter(Badge.id == body.badge_id).first()
    if not badge:
        raise HTTPException(status_code=404, detail="Badge not found")
    assert_club_access(db, user, badge.club_id, permission="issue_badges")
    student = db.query(User).filter(User.id == body.user_id, User.role == SystemRole.STUDENT).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    existing = db.query(UserBadge).filter(UserBadge.user_id == body.user_id, UserBadge.badge_id == body.badge_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Badge already awarded")
    ub = UserBadge(user_id=body.user_id, badge_id=body.badge_id, awarded_by_id=user.id)
    db.add(ub)
    notify(db, body.user_id, "Badge awarded", f"You received the {badge.name} badge.")
    write_audit(db, user, "award_badge", "badge", badge.id, {"user_id": body.user_id})
    db.commit()
    db.refresh(ub)
    return UserBadgeOut(
        id=ub.id,
        user_id=ub.user_id,
        badge_id=ub.badge_id,
        awarded_at=ub.awarded_at,
        badge_name=badge.name,
        club_id=badge.club_id,
    )


@badges_router.get("/me", response_model=list[UserBadgeOut])
def my_badges(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(UserBadge).filter(UserBadge.user_id == user.id).all()
    return [
        UserBadgeOut(
            id=r.id,
            user_id=r.user_id,
            badge_id=r.badge_id,
            awarded_at=r.awarded_at,
            badge_name=r.badge.name,
            club_id=r.badge.club_id,
        )
        for r in rows
    ]


notify_router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@notify_router.get("", response_model=list[NotificationOut])
def list_notes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
        .all()
    )


@notify_router.post("/{nid}/read")
def mark_read(nid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = db.query(Notification).filter(Notification.id == nid, Notification.user_id == user.id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Not found")
    n.is_read = True
    db.commit()
    return {"ok": True}


announce_router = APIRouter(prefix="/api/announcements", tags=["announcements"])


@announce_router.post("", response_model=AnnouncementOut, status_code=201)
def create_announcement(body: AnnouncementCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.scope == AnnouncementScope.GLOBAL:
        if user.role not in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN):
            raise HTTPException(status_code=403, detail="Only Admin/Super Admin can post global announcements")
    elif body.scope == AnnouncementScope.ROLE:
        if user.role not in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN, SystemRole.FACULTY):
            raise HTTPException(status_code=403, detail="Cannot target system roles")
    elif body.scope == AnnouncementScope.CLUB:
        if not body.club_id:
            raise HTTPException(status_code=400, detail="club_id required")
        assert_club_access(db, user, body.club_id, permission="post_announcements")
    row = Announcement(
        title=body.title,
        body=body.body,
        scope=body.scope,
        club_id=body.club_id,
        target_role=body.target_role,
        created_by_id=user.id,
    )
    db.add(row)
    write_audit(db, user, "create_announcement", "announcement", None, {"scope": body.scope.value})
    db.commit()
    db.refresh(row)
    return row


@announce_router.get("", response_model=list[AnnouncementOut])
def list_announcements(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Announcement).order_by(Announcement.created_at.desc()).all()
    visible = []
    from app.deps import user_club_ids

    club_ids = user_club_ids(db, user)
    for a in rows:
        if a.scope == AnnouncementScope.GLOBAL:
            visible.append(a)
        elif a.scope == AnnouncementScope.ROLE and a.target_role == user.role:
            visible.append(a)
        elif a.scope == AnnouncementScope.CLUB and a.club_id in club_ids:
            visible.append(a)
    return visible


analytics_router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@analytics_router.get("")
def analytics(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import Attendance, ClubMember, Event, EventStatus, ODRequest, ODStatus, Registration

    if user.role == SystemRole.STUDENT:
        raise HTTPException(status_code=403, detail="Students do not have analytics dashboards")
    data = {
        "users": db.query(User).count(),
        "clubs": db.query(Club).count(),
        "events": db.query(Event).count(),
        "approved_events": db.query(Event).filter(Event.status == EventStatus.APPROVED).count(),
        "pending_events": db.query(Event).filter(Event.status == EventStatus.PENDING_FACULTY).count(),
        "registrations": db.query(Registration).count(),
        "od_pending": db.query(ODRequest).filter(ODRequest.status == ODStatus.PENDING).count(),
        "od_approved": db.query(ODRequest).filter(ODRequest.status == ODStatus.APPROVED).count(),
    }
    club_query = db.query(Club)
    if user.role == SystemRole.CLUB_ADMIN:
        club_query = club_query.filter(Club.club_admin_id == user.id)
    clubs = club_query.order_by(Club.name).all()
    per_club = []
    for club in clubs:
        completed = db.query(Event).filter(
            Event.club_id == club.id, Event.status == EventStatus.COMPLETED
        ).all()
        completed_ids = [event.id for event in completed]
        present_count = db.query(Attendance).filter(
            Attendance.event_id.in_(completed_ids or [-1]), Attendance.present.is_(True)
        ).count()
        per_club.append({
            "club_id": club.id,
            "club_name": club.name,
            "member_count": db.query(ClubMember).filter(ClubMember.club_id == club.id).count(),
            "events_held": len(completed),
            "average_attendance": round(present_count / len(completed), 2) if completed else 0,
        })
    data["per_club"] = per_club
    student_query = db.query(User).filter(User.role == SystemRole.STUDENT)
    if user.role == SystemRole.FACULTY:
        student_query = student_query.filter(User.class_mentor_id == user.id)
    elif user.role == SystemRole.CLUB_ADMIN:
        club_ids = [club.id for club in clubs]
        student_query = student_query.join(ClubMember, ClubMember.user_id == User.id).filter(
            ClubMember.club_id.in_(club_ids or [-1])
        ).distinct()
    students = student_query.order_by(User.full_name).all()
    per_student = []
    for student in students:
        attended = db.query(Attendance.event_id).filter(
            Attendance.student_id == student.id, Attendance.present.is_(True)
        ).distinct().count()
        decided_od = db.query(ODRequest).filter(
            ODRequest.student_id == student.id, ODRequest.status != ODStatus.PENDING
        ).count()
        approved_od = db.query(ODRequest).filter(
            ODRequest.student_id == student.id, ODRequest.status == ODStatus.APPROVED
        ).count()
        per_student.append({
            "student_id": student.id,
            "student_name": student.full_name,
            "ra_number": student.ra_number,
            "events_attended": attended,
            "od_approval_rate": round(approved_od / decided_od, 3) if decided_od else None,
        })
    data["per_student"] = per_student
    pending_query = db.query(Event).filter(Event.status == EventStatus.PENDING_FACULTY)
    if user.role == SystemRole.FACULTY:
        assigned_ids = [club.id for club in db.query(Club).filter(Club.faculty_coordinator_id == user.id).all()]
        pending_query = pending_query.filter(Event.club_id.in_(assigned_ids or [-1]))
    elif user.role == SystemRole.CLUB_ADMIN:
        pending_query = pending_query.filter(Event.club_id.in_([club.id for club in clubs] or [-1]))
    pending_events = pending_query.order_by(Event.start_at).limit(50).all()
    data["pending_approval_queue"] = [
        {"event_id": event.id, "event_title": event.title, "club_name": event.club.name, "start_at": event.start_at.isoformat()}
        for event in pending_events
    ]
    data["most_active_clubs"] = sorted(per_club, key=lambda row: (row["events_held"], row["member_count"]), reverse=True)[:5]
    if user.role == SystemRole.CLUB_ADMIN:
        ids = [c.id for c in clubs]
        data["clubs"] = len(ids)
        data["events"] = db.query(Event).filter(Event.club_id.in_(ids or [-1])).count()
        data["approved_events"] = (
            db.query(Event).filter(Event.club_id.in_(ids or [-1]), Event.status == EventStatus.APPROVED).count()
        )
        event_ids = [e.id for e in db.query(Event).filter(Event.club_id.in_(ids or [-1])).all()]
        data["registrations"] = db.query(Registration).filter(Registration.event_id.in_(event_ids or [-1])).count()
        data["od_pending"] = None
        data["od_approved"] = None
        data["users"] = None
    return data


audit_router = APIRouter(prefix="/api/audit", tags=["audit"])


@audit_router.get("")
def list_audit(db: Session = Depends(get_db), user: User = Depends(get_current_user), page: int = 1, page_size: int = 50):
    if user.role != SystemRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Audit logs are Super Admin only")
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "actor_id": r.actor_id,
                "actor_name": r.actor.full_name if r.actor else None,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "details": r.details,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


regs_router = APIRouter(prefix="/api/registrations", tags=["registrations"])


@regs_router.get("/me")
def my_registrations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import Registration

    rows = db.query(Registration).filter(Registration.student_id == user.id).all()
    return [
        {
            "id": r.id,
            "event_id": r.event_id,
            "student_id": r.student_id,
            "registered_at": r.registered_at.isoformat(),
            "event_title": r.event.title,
            "event_status": r.event.status.value,
            "start_at": r.event.start_at.isoformat(),
            "end_at": r.event.end_at.isoformat(),
            "has_od": r.od_request is not None,
        }
        for r in rows
    ]


@regs_router.get("")
def all_registrations(db: Session = Depends(get_db), user: User = Depends(get_current_user), q: str | None = None, page: int = 1, page_size: int = 30):
    from app.models import Registration
    from sqlalchemy import or_

    if user.role not in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN, SystemRole.FACULTY):
        raise HTTPException(status_code=403, detail="Forbidden")
    query = db.query(Registration)
    if q:
        like = f"%{q}%"
        query = query.join(User, Registration.student_id == User.id).filter(
            or_(User.full_name.ilike(like), User.ra_number.ilike(like))
        )
    rows = query.order_by(Registration.registered_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return [
        {
            "id": r.id,
            "event_id": r.event_id,
            "student_id": r.student_id,
            "registered_at": r.registered_at.isoformat(),
            "event_title": r.event.title,
            "student_name": r.student.full_name,
            "ra_number": r.student.ra_number,
        }
        for r in rows
    ]


search_router = APIRouter(prefix="/api/search", tags=["search"])


@search_router.get("")
def search(q: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import Event, EventStatus

    like = f"%{q}%"
    clubs = db.query(Club).filter(Club.name.ilike(like)).limit(10).all()
    events_q = db.query(Event).filter(Event.title.ilike(like))
    if user.role == SystemRole.STUDENT:
        events_q = events_q.filter(Event.status == EventStatus.APPROVED)
    events = events_q.limit(10).all()
    users = []
    if user.role in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN, SystemRole.FACULTY):
        users = (
            db.query(User)
            .filter(User.full_name.ilike(like) | User.email.ilike(like) | User.ra_number.ilike(like))
            .limit(10)
            .all()
        )
    return {
        "clubs": [{"id": c.id, "name": c.name} for c in clubs],
        "events": [{"id": e.id, "title": e.title, "status": e.status.value} for e in events],
        "users": [{"id": u.id, "full_name": u.full_name, "role": u.role.value, "ra_number": u.ra_number} for u in users],
    }
