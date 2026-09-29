from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, Token
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_access_token(str(user.id), user.role.value)
    write_audit(db, user, "login", "user", user.id)
    db.commit()
    return Token(
        access_token=token,
        role=user.role,
        user={
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
            "ra_number": user.ra_number,
            "department": user.department,
            "year": user.year,
            "section": user.section,
            "class_mentor_id": user.class_mentor_id,
        },
    )
