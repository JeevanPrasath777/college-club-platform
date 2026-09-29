from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.database import get_db
from app.deps import get_current_user, notify, require_roles
from app.models import SystemRole, User
from app.schemas import ProfileUpdate, UserCreate, UserOut, UserUpdate
from app.security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


def _validate_student_fields(role: SystemRole, ra_number: str | None):
    if role == SystemRole.STUDENT and not ra_number:
        raise HTTPException(status_code=400, detail="Students must have a unique RA Number")
    if role == SystemRole.STUDENT and (len(ra_number) != 15 or not ra_number.isascii() or not ra_number.isalnum()):
        raise HTTPException(status_code=400, detail="Student RA Number must contain exactly 15 letters or digits")
    if role != SystemRole.STUDENT and ra_number:
        raise HTTPException(status_code=400, detail="RA Number is only for students")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.full_name:
        user.full_name = body.full_name
    if user.role == SystemRole.STUDENT:
        if body.department is not None:
            user.department = body.department
        if body.year is not None:
            user.year = body.year
        if body.section is not None:
            user.section = body.section
    if body.password:
        user.hashed_password = hash_password(body.password)
    write_audit(db, user, "update_profile", "user", user.id)
    db.commit()
    db.refresh(user)
    return user


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    q: str | None = None,
    role: SystemRole | None = None,
    department: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    if user.role == SystemRole.STUDENT:
        raise HTTPException(status_code=403, detail="Students cannot list all users")
    query = db.query(User)
    if user.role == SystemRole.FACULTY:
        query = query.filter(User.class_mentor_id == user.id, User.role == SystemRole.STUDENT)
    elif user.role == SystemRole.CLUB_ADMIN:
        raise HTTPException(status_code=403, detail="Use club member endpoints")
    if role:
        query = query.filter(User.role == role)
    if department:
        query = query.filter(User.department == department)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(User.full_name.ilike(like), User.email.ilike(like), User.ra_number.ilike(like))
        )
    return query.order_by(User.id).offset((page - 1) * page_size).limit(page_size).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(SystemRole.SUPER_ADMIN, SystemRole.ADMIN)),
):
    if actor.role == SystemRole.ADMIN and body.role in (SystemRole.SUPER_ADMIN, SystemRole.ADMIN):
        raise HTTPException(status_code=403, detail="Admins cannot create admin accounts")
    _validate_student_fields(body.role, body.ra_number)
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    if body.ra_number and db.query(User).filter(User.ra_number == body.ra_number).first():
        raise HTTPException(status_code=409, detail="RA Number already exists")
    if body.class_mentor_id:
        mentor = db.query(User).filter(User.id == body.class_mentor_id).first()
        if not mentor or mentor.role != SystemRole.FACULTY or not mentor.is_active:
            raise HTTPException(status_code=400, detail="class_mentor_id must be an active FACULTY user")
    user = User(
        email=body.email.lower(),
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        ra_number=body.ra_number,
        department=body.department,
        year=body.year,
        section=body.section,
        class_mentor_id=body.class_mentor_id,
    )
    db.add(user)
    db.flush()
    notify(db, user.id, "Account created", f"Your {body.role.value.replace('_', ' ').title()} account is ready.")
    write_audit(db, actor, "create_user", "user", user.id, {"role": body.role.value})
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(SystemRole.SUPER_ADMIN, SystemRole.ADMIN)),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if actor.role == SystemRole.ADMIN and target.role == SystemRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Cannot modify Super Admin")
    resulting_role = body.role if body.role is not None else target.role
    resulting_ra_number = body.ra_number if body.ra_number is not None else target.ra_number
    _validate_student_fields(resulting_role, resulting_ra_number)
    old_role = target.role
    if body.role is not None:
        if actor.role != SystemRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Only Super Admin can change system roles")
        target.role = body.role
    for field in ("full_name", "is_active", "department", "year", "section", "class_mentor_id"):
        val = getattr(body, field)
        if val is not None:
            setattr(target, field, val)
    if body.ra_number is not None:
        body.ra_number = body.ra_number.upper()
        existing = db.query(User).filter(User.ra_number == body.ra_number, User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=409, detail="RA Number already exists")
        target.ra_number = body.ra_number
    if body.password:
        target.hashed_password = hash_password(body.password)
    if body.class_mentor_id is not None:
        mentor = db.query(User).filter(User.id == body.class_mentor_id).first()
        if not mentor or mentor.role != SystemRole.FACULTY or not mentor.is_active:
            raise HTTPException(status_code=400, detail="class_mentor_id must be an active FACULTY user")
    if body.role is not None and body.role != old_role:
        notify(db, target.id, "System role updated", f"Your account role is now {body.role.value.replace('_', ' ').title()}.")
    write_audit(db, actor, "update_user", "user", target.id)
    db.commit()
    db.refresh(target)
    return target
