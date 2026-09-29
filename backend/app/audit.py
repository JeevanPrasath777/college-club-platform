import json

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def write_audit(
    db: Session,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    details: dict | str | None = None,
) -> None:
    payload = details if isinstance(details, str) else json.dumps(details or {})
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=payload,
        )
    )
