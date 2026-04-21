import hashlib
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, UserSession


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, digest_hex = stored_hash.split("$", 1)
    except ValueError:
        return False

    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return secrets.compare_digest(actual, expected)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User) -> str:
    raw_token = secrets.token_urlsafe(32)
    session = UserSession(user_id=user.id, token_hash=_hash_token(raw_token))
    db.add(session)
    db.commit()
    return raw_token


def destroy_session(db: Session, token: str) -> None:
    stmt = select(UserSession).where(UserSession.token_hash == _hash_token(token))
    session = db.execute(stmt).scalar_one_or_none()
    if session:
        db.delete(session)
        db.commit()


def get_user_by_email(db: Session, email: str) -> User | None:
    stmt = select(User).where(User.email == normalize_email(email))
    return db.execute(stmt).scalar_one_or_none()


def get_user_by_token(db: Session, token: str) -> User | None:
    stmt = (
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(UserSession.token_hash == _hash_token(token))
    )
    return db.execute(stmt).scalar_one_or_none()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = get_user_by_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")

    return user
