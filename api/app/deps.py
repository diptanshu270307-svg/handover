from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User


def get_current_user(
    db: Session = Depends(get_db),
    x_user_id: str | None = Header(default=None),
) -> User:
    if x_user_id:
        user = db.get(User, x_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    user = db.scalar(select(User).order_by(User.created_at.asc()))
    if not user:
        raise HTTPException(status_code=404, detail="No users in database; run seed script first.")
    return user
