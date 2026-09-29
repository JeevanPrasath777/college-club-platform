import json
from datetime import datetime, time
from typing import Iterable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    ALLOWED_CLUB_PERMISSIONS,
    FORBIDDEN_CLUB_PERMISSIONS,
    Club,
    ClubMember,
    Notification,
    SystemRole,
    User,
)
from app.security import decode_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(creds.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    return user


def require_roles(*roles: SystemRole):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient privileges")
        return user

    return checker


def parse_permissions(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []


def sanitize_club_permissions(perms: Iterable[str]) -> list[str]:
    cleaned = []
    for p in perms:
        if p in FORBIDDEN_CLUB_PERMISSIONS:
            continue
        if p in ALLOWED_CLUB_PERMISSIONS:
            cleaned.append(p)
    return sorted(set(cleaned))


def user_club_ids(db: Session, user: User) -> set[int]:
    if user.role in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN):
        return {c.id for c in db.query(Club).all()}
    ids = set()
    if user.role == SystemRole.CLUB_ADMIN:
        ids.update(c.id for c in db.query(Club).filter(Club.club_admin_id == user.id).all())
    memberships = db.query(ClubMember).filter(ClubMember.user_id == user.id).all()
    ids.update(m.club_id for m in memberships)
    return ids


def assert_club_access(db: Session, user: User, club_id: int, permission: str | None = None) -> Club:
    club = db.query(Club).filter(Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    if user.role in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN):
        return club
    if user.role == SystemRole.CLUB_ADMIN and club.club_admin_id == user.id:
        return club
    member = (
        db.query(ClubMember)
        .filter(ClubMember.club_id == club_id, ClubMember.user_id == user.id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=403, detail="Cross-club access denied")
    if permission:
        if user.role == SystemRole.CLUB_ADMIN and club.club_admin_id == user.id:
            return club
        perms = parse_permissions(member.club_role.permissions if member.club_role else "[]")
        if permission not in perms:
            raise HTTPException(status_code=403, detail=f"Missing club permission: {permission}")
    return club


def notify(db: Session, user_id: int, title: str, body: str = "") -> None:
    db.add(Notification(user_id=user_id, title=title, body=body))


def parse_hhmm(value: str) -> time:
    parts = value.split(":")
    return time(int(parts[0]), int(parts[1]))


def time_ranges_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end
