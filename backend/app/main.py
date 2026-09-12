from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .database import Base, engine, get_session
from .models import Machine, User
from .schemas import AuthResponse, Credentials, MachineCreate, MachineEnrollment, MachineResponse
from .security import create_access_token, decode_access_token, hash_password, new_agent_token, verify_password


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="PulseWatch API", version="0.3.0", lifespan=lifespan)


def require_user(authorization: str = Header(default=""), session: Session = Depends(get_session)) -> User:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    user = session.get(User, decode_access_token(token))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    return user


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


@app.post("/machines", response_model=MachineEnrollment, status_code=status.HTTP_201_CREATED, tags=["machines"])
def register_machine(payload: MachineCreate, user: User = Depends(require_user), session: Session = Depends(get_session)) -> MachineEnrollment:
    agent_token = new_agent_token()
    machine = Machine(owner_id=user.id, name=payload.name, hostname=payload.hostname, agent_token_hash=hash_password(agent_token))
    session.add(machine)
    session.commit()
    session.refresh(machine)
    return MachineEnrollment(id=machine.id, name=machine.name, hostname=machine.hostname, status="pending", last_heartbeat_at=None, agent_token=agent_token)


@app.get("/machines", response_model=list[MachineResponse], tags=["machines"])
def list_machines(user: User = Depends(require_user), session: Session = Depends(get_session)) -> list[MachineResponse]:
    machines = session.scalars(select(Machine).where(Machine.owner_id == user.id).order_by(Machine.name)).all()
    return [MachineResponse(id=machine.id, name=machine.name, hostname=machine.hostname, status="pending" if machine.last_heartbeat_at is None else "online", last_heartbeat_at=machine.last_heartbeat_at.isoformat() if machine.last_heartbeat_at else None) for machine in machines]
