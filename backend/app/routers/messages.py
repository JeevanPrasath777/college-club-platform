from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.database import get_db
from app.deps import get_current_user, notify
from app.models import Club, Conversation, Event, Message, SystemRole, User
from app.schemas import MessageCreate, MessageReply

router = APIRouter(prefix="/api/messages", tags=["messages"])
CHAT_ROLES = {SystemRole.FACULTY, SystemRole.CLUB_ADMIN}


def validate_pair(db: Session, sender: User, recipient: User, event_id: int | None):
    if sender.id == recipient.id or sender.role not in CHAT_ROLES or recipient.role not in CHAT_ROLES:
        raise HTTPException(status_code=403, detail="Messaging is available between Faculty and Club Admin accounts")
    if sender.role == recipient.role == SystemRole.FACULTY:
        if event_id and not db.query(Event).filter(Event.id == event_id).first():
            raise HTTPException(status_code=404, detail="Event not found")
        return
    faculty = sender if sender.role == SystemRole.FACULTY else recipient
    club_admin = sender if sender.role == SystemRole.CLUB_ADMIN else recipient
    clubs = db.query(Club).filter(
        Club.club_admin_id == club_admin.id,
        Club.faculty_coordinator_id == faculty.id,
    )
    if event_id:
        clubs = clubs.filter(Club.id == db.query(Event.club_id).filter(Event.id == event_id).scalar_subquery())
    if not clubs.first():
        raise HTTPException(status_code=403, detail="Faculty and Club Admin must share an assigned club")


def conversation_out(conversation: Conversation, current_user_id: int):
    other = conversation.participant_b if conversation.participant_a_id == current_user_id else conversation.participant_a
    latest = conversation.messages[-1] if conversation.messages else None
    return {
        "id": conversation.id,
        "other_user_id": other.id,
        "other_user_name": other.full_name,
        "event_id": conversation.event_id,
        "event_title": conversation.event.title if conversation.event else None,
        "latest_message": latest.body if latest else "",
        "updated_at": (latest.created_at if latest else conversation.updated_at).isoformat(),
    }


def message_out(message: Message):
    return {
        "id": message.id,
        "sender_id": message.sender_id,
        "sender_name": message.sender.full_name,
        "body": message.body,
        "created_at": message.created_at.isoformat(),
    }


@router.get("")
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role not in CHAT_ROLES:
        raise HTTPException(status_code=403, detail="Messaging is for Faculty and Club Admin accounts")
    rows = db.query(Conversation).filter(
        or_(Conversation.participant_a_id == user.id, Conversation.participant_b_id == user.id)
    ).order_by(Conversation.updated_at.desc()).all()
    return [conversation_out(row, user.id) for row in rows]


@router.post("")
def send_message(body: MessageCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    recipient = db.query(User).filter(User.id == body.recipient_id, User.is_active.is_(True)).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")
    validate_pair(db, user, recipient, body.event_id)
    a_id, b_id = sorted((user.id, recipient.id))
    conversation_query = db.query(Conversation).filter(
        Conversation.participant_a_id == a_id,
        Conversation.participant_b_id == b_id,
    )
    conversation_query = conversation_query.filter(
        Conversation.event_id.is_(None) if body.event_id is None else Conversation.event_id == body.event_id
    )
    conversation = conversation_query.first()
    if not conversation:
        conversation = Conversation(
            participant_a_id=a_id,
            participant_b_id=b_id,
            event_id=body.event_id,
        )
        db.add(conversation)
        db.flush()
    message = Message(conversation_id=conversation.id, sender_id=user.id, body=body.body.strip())
    db.add(message)
    conversation.updated_at = datetime.utcnow()
    notify(db, recipient.id, "New message", f"{user.full_name} sent you a message.")
    write_audit(db, user, "send_message", "conversation", conversation.id)
    db.commit()
    db.refresh(conversation)
    return {"conversation": conversation_out(conversation, user.id), "message": message_out(message)}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        or_(Conversation.participant_a_id == user.id, Conversation.participant_b_id == user.id),
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {**conversation_out(conversation, user.id), "messages": [message_out(m) for m in conversation.messages]}


@router.post("/{conversation_id}")
def reply(
    conversation_id: int,
    body: MessageReply,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        or_(Conversation.participant_a_id == user.id, Conversation.participant_b_id == user.id),
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    recipient_id = conversation.participant_b_id if conversation.participant_a_id == user.id else conversation.participant_a_id
    recipient = db.query(User).filter(User.id == recipient_id, User.is_active.is_(True)).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient is unavailable")
    validate_pair(db, user, recipient, conversation.event_id)
    message = Message(conversation_id=conversation.id, sender_id=user.id, body=body.body.strip())
    db.add(message)
    conversation.updated_at = datetime.utcnow()
    notify(db, recipient.id, "New message", f"{user.full_name} sent you a message.")
    write_audit(db, user, "reply_message", "conversation", conversation.id)
    db.commit()
    db.refresh(conversation)
    return {"conversation": conversation_out(conversation, user.id), "message": message_out(message)}
