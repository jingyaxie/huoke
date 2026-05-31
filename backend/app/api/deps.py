from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db


def db_session(session: Session = Depends(get_db)) -> Session:
    return session

