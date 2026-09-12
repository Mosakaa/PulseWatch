from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .database import Base, engine, get_session
from .models import User
from .schemas import AuthResponse, Credentials
from .security import create_access_token, hash_password, verify_password


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="PulseWatch API", version="0.3.0", lifespan=lifespan)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Report that the API process and its persistence layer are ready."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "service": "pulsewatch-api",
        "database": "connected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED, tags=["authentication"])
def register(credentials: Credentials, session: Session = Depends(get_session)) -> AuthResponse:
    email = credentials.email.lower()
    if session.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account already uses this email")
    user = User(email=email, password_hash=hash_password(credentials.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return AuthResponse(access_token=create_access_token(user.id), email=user.email)


@app.post("/auth/login", response_model=AuthResponse, tags=["authentication"])
def login(credentials: Credentials, session: Session = Depends(get_session)) -> AuthResponse:
    user = session.scalar(select(User).where(User.email == credentials.email.lower()))
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return AuthResponse(access_token=create_access_token(user.id), email=user.email)
