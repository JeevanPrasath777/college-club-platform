import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.database import get_db
from app.deps import assert_club_access, get_current_user, notify, parse_permissions, require_roles, sanitize_club_permissions, user_club_ids
from app.models import Club, ClubMember, ClubRole, SystemRole, User
from app.schemas import ClubCreate, ClubOut, ClubRoleCreate, ClubRoleOut, ClubUpdate, MemberAdd

router = APIRouter(prefix="/api/clubs", tags=["clubs"])


@router.get("", response_model=list[ClubOut])
def list_clubs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    query = db.query(Club)
    if user.role not in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN, SystemRole.FACULTY, SystemRole.STUDENT):
        ids = user_club_ids(db, user)
        query = query.filter(Club.id.in_(ids or {-1}))
    if user.role == SystemRole.STUDENT:
        pass  # students may browse active clubs
        query = query.filter(Club.is_active.is_(True))
    if q:
        query = query.filter(Club.name.ilike(f"%{q}%"))
    return query.order_by(Club.name).offset((page - 1) * page_size).limit(page_size).all()


@router.post("", response_model=ClubOut, status_code=201)
def create_club(
    body: ClubCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(SystemRole.SUPER_ADMIN, SystemRole.ADMIN)),
):
    if not body.club_admin_id:
        raise HTTPException(status_code=400, detail="Assign a Club Admin when creating a club")
    if not body.faculty_coordinator_id:
        raise HTTPException(status_code=400, detail="Assign an active Faculty Coordinator when creating a club")
    if db.query(Club).filter(Club.name == body.name).first():
        raise HTTPException(status_code=409, detail="Club name exists")
    if body.club_admin_id:
        admin = db.query(User).filter(User.id == body.club_admin_id).first()
        if not admin or admin.role != SystemRole.CLUB_ADMIN or not admin.is_active:
            raise HTTPException(status_code=400, detail="club_admin_id must be an active CLUB_ADMIN user")
    if body.faculty_coordinator_id:
        coordinator = db.query(User).filter(User.id == body.faculty_coordinator_id).first()
        if not coordinator or coordinator.role != SystemRole.FACULTY or not coordinator.is_active:
            raise HTTPException(status_code=400, detail="faculty_coordinator_id must be an active FACULTY user")
    club = Club(
        name=body.name,
        description=body.description,
        category=body.category,
        club_admin_id=body.club_admin_id,
        faculty_coordinator_id=body.faculty_coordinator_id,
    )
    db.add(club)
    db.flush()
    if body.club_admin_id:
        db.add(ClubMember(club_id=club.id, user_id=body.club_admin_id))
        notify(db, body.club_admin_id, "Club Admin assigned", f"You manage the {club.name} club.")
    notify(db, body.faculty_coordinator_id, "Faculty Coordinator assigned", f"You coordinate events for {club.name}.")
    write_audit(db, actor, "create_club", "club", club.id)
    db.commit()
    db.refresh(club)
    return club


@router.patch("/{club_id}", response_model=ClubOut)
def update_club(
    club_id: int,
    body: ClubUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(SystemRole.SUPER_ADMIN, SystemRole.ADMIN, SystemRole.CLUB_ADMIN)),
):
    club = assert_club_access(db, actor, club_id)
    if actor.role == SystemRole.CLUB_ADMIN and club.club_admin_id != actor.id:
        raise HTTPException(status_code=403, detail="Cross-club access denied")
    if actor.role == SystemRole.CLUB_ADMIN and body.club_admin_id is not None:
        raise HTTPException(status_code=403, detail="Club Admin cannot reassign club ownership")
    if actor.role == SystemRole.CLUB_ADMIN and body.faculty_coordinator_id is not None:
        raise HTTPException(status_code=403, detail="Only Admin or Super Admin can assign a Faculty Coordinator")
    if body.name is not None and body.name != club.name:
        if db.query(Club).filter(Club.name == body.name, Club.id != club.id).first():
            raise HTTPException(status_code=409, detail="Club name already exists")
    if body.club_admin_id is not None:
        new_admin = db.query(User).filter(User.id == body.club_admin_id).first()
        if not new_admin or new_admin.role != SystemRole.CLUB_ADMIN or not new_admin.is_active:
            raise HTTPException(status_code=400, detail="club_admin_id must be an active CLUB_ADMIN user")
    if body.faculty_coordinator_id is not None:
        coordinator = db.query(User).filter(User.id == body.faculty_coordinator_id).first()
        if not coordinator or coordinator.role != SystemRole.FACULTY or not coordinator.is_active:
            raise HTTPException(status_code=400, detail="faculty_coordinator_id must be an active FACULTY user")
    previous_admin_id = club.club_admin_id
    previous_coordinator_id = club.faculty_coordinator_id
    for field in ("name", "description", "category", "club_admin_id", "faculty_coordinator_id", "is_active"):
        val = getattr(body, field)
        if val is not None:
            setattr(club, field, val)
    if body.club_admin_id is not None:
        if previous_admin_id and previous_admin_id != body.club_admin_id:
            db.query(ClubMember).filter(
                ClubMember.club_id == club_id, ClubMember.user_id == previous_admin_id
            ).delete(synchronize_session=False)
        membership = db.query(ClubMember).filter(
            ClubMember.club_id == club_id, ClubMember.user_id == body.club_admin_id
        ).first()
        if not membership:
            db.add(ClubMember(club_id=club_id, user_id=body.club_admin_id))
        if previous_admin_id != body.club_admin_id:
            notify(db, body.club_admin_id, "Club Admin assigned", f"You manage the {club.name} club.")
    if body.faculty_coordinator_id is not None and previous_coordinator_id != body.faculty_coordinator_id:
        notify(db, body.faculty_coordinator_id, "Faculty Coordinator assigned", f"You coordinate events for {club.name}.")
    write_audit(db, actor, "update_club", "club", club.id)
    db.commit()
    db.refresh(club)
    return club


@router.post("/{club_id}/join")
def join_club(club_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != SystemRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students self-join clubs")
    club = db.query(Club).filter(Club.id == club_id, Club.is_active.is_(True)).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    existing = db.query(ClubMember).filter(ClubMember.club_id == club_id, ClubMember.user_id == user.id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Already a member")
    db.add(ClubMember(club_id=club_id, user_id=user.id))
    write_audit(db, user, "join_club", "club", club_id)
    db.commit()
    return {"ok": True}


@router.get("/{club_id}/members")
def list_members(club_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    assert_club_access(db, user, club_id)
    members = db.query(ClubMember).filter(ClubMember.club_id == club_id).all()
    result = []
    for m in members:
        result.append(
            {
                "id": m.id,
                "user_id": m.user_id,
                "full_name": m.user.full_name,
                "email": m.user.email,
                "system_role": m.user.role.value,
                "club_role_id": m.club_role_id,
                "club_role_name": m.club_role.name if m.club_role else None,
                "joined_at": m.joined_at.isoformat(),
            }
        )
    return result


@router.post("/{club_id}/members", status_code=201)
def add_member(
    club_id: int,
    body: MemberAdd,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    club = assert_club_access(db, user, club_id, permission="manage_members")
    if user.role == SystemRole.CLUB_ADMIN and club.club_admin_id != user.id and user.role not in (
        SystemRole.SUPER_ADMIN,
        SystemRole.ADMIN,
    ):
        pass
    target = db.query(User).filter(User.id == body.user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    existing = db.query(ClubMember).filter(ClubMember.club_id == club_id, ClubMember.user_id == body.user_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Already a member")
    if body.club_role_id:
        role = db.query(ClubRole).filter(ClubRole.id == body.club_role_id, ClubRole.club_id == club_id).first()
        if not role:
            raise HTTPException(status_code=400, detail="Role does not belong to this club")
    member = ClubMember(club_id=club_id, user_id=body.user_id, club_role_id=body.club_role_id)
    db.add(member)
    write_audit(db, user, "add_club_member", "club", club_id, {"user_id": body.user_id})
    db.commit()
    return {"ok": True, "id": member.id}


@router.delete("/{club_id}/members/{user_id}")
def remove_member(club_id: int, user_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    assert_club_access(db, user, club_id, permission="manage_members")
    member = db.query(ClubMember).filter(ClubMember.club_id == club_id, ClubMember.user_id == user_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    db.delete(member)
    write_audit(db, user, "remove_club_member", "club", club_id, {"user_id": user_id})
    db.commit()
    return {"ok": True}


@router.get("/{club_id}/roles", response_model=list[ClubRoleOut])
def list_roles(club_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    assert_club_access(db, user, club_id)
    roles = db.query(ClubRole).filter(ClubRole.club_id == club_id).all()
    return [
        ClubRoleOut(id=r.id, club_id=r.club_id, name=r.name, permissions=parse_permissions(r.permissions))
        for r in roles
    ]


@router.post("/{club_id}/roles", response_model=ClubRoleOut, status_code=201)
def create_role(
    club_id: int,
    body: ClubRoleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assert_club_access(db, user, club_id, permission="manage_members")
    if user.role not in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN, SystemRole.CLUB_ADMIN):
        raise HTTPException(status_code=403, detail="Only club admins can define dynamic roles")
    perms = sanitize_club_permissions(body.permissions)
    role = ClubRole(club_id=club_id, name=body.name, permissions=json.dumps(perms))
    db.add(role)
    write_audit(db, user, "create_club_role", "club_role", None, {"club_id": club_id, "permissions": perms})
    db.commit()
    db.refresh(role)
    return ClubRoleOut(id=role.id, club_id=role.club_id, name=role.name, permissions=perms)


@router.patch("/{club_id}/roles/{role_id}", response_model=ClubRoleOut)
def update_role(
    club_id: int,
    role_id: int,
    body: ClubRoleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assert_club_access(db, user, club_id, permission="manage_members")
    if user.role not in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN, SystemRole.CLUB_ADMIN):
        raise HTTPException(status_code=403, detail="Only club admins can update dynamic roles")
    role = db.query(ClubRole).filter(ClubRole.id == role_id, ClubRole.club_id == club_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    perms = sanitize_club_permissions(body.permissions)
    role.name = body.name
    role.permissions = json.dumps(perms)
    write_audit(db, user, "update_club_role", "club_role", role.id, {"permissions": perms})
    db.commit()
    return ClubRoleOut(id=role.id, club_id=role.club_id, name=role.name, permissions=perms)


@router.patch("/{club_id}/members/{user_id}/role")
def assign_member_role(
    club_id: int,
    user_id: int,
    body: MemberAdd,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    club = assert_club_access(db, user, club_id, permission="manage_members")
    member = db.query(ClubMember).filter(ClubMember.club_id == club_id, ClubMember.user_id == user_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if body.club_role_id:
        role = db.query(ClubRole).filter(ClubRole.id == body.club_role_id, ClubRole.club_id == club_id).first()
        if not role:
            raise HTTPException(status_code=400, detail="Role does not belong to this club")
        member.club_role_id = role.id
    else:
        member.club_role_id = None
    notify(db, member.user_id, "Club role updated", f"Your role for {club.name} was updated.")
    db.commit()
    return {"ok": True}
