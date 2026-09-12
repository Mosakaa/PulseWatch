import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, get_session
from .models import Alert, AlertRule, Machine, ServiceCheck, Telemetry, User
from .schemas import (AlertResponse, AlertRuleResponse, AlertRuleUpdate, AuthResponse,
                      Credentials, MachineCreate, MachineEnrollment, MachineResponse,
                      ServiceCheckCreate, ServiceCheckResponse, TelemetryIn)
from .security import create_access_token, decode_access_token, hash_password, new_agent_token, verify_password
from .services.alert_engine import evaluate_service_checks, evaluate_threshold_rules
from .services.machine_status import refresh_machine_statuses
from .realtime import manager


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    watcher = asyncio.create_task(heartbeat_watcher())
    yield
    watcher.cancel()


app = FastAPI(title="PulseWatch API", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def heartbeat_watcher() -> None:
    while True:
        await asyncio.sleep(15)
        with SessionLocal() as session:
            alerts = refresh_machine_statuses(session)
            session.flush()
            session.commit()
            for alert in alerts:
                machine = session.get(Machine, alert.machine_id)
                if machine is not None:
                    await manager.broadcast(machine.owner_id, {"type": "alert.created", "machine_id": machine.id, "alert_id": alert.id})


def require_user(authorization: str = Header(default=""), session: Session = Depends(get_session)) -> User:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    user = session.get(User, decode_access_token(token))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    return user


def require_agent(x_machine_id: str, x_agent_token: str, session: Session) -> Machine:
    machine = session.get(Machine, x_machine_id)
    if machine is None or not x_agent_token or not verify_password(x_agent_token, machine.agent_token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent credentials")
    return machine


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
    session.flush()
    for metric in ("cpu_percent", "memory_percent", "disk_percent"):
        session.add(AlertRule(machine_id=machine.id, metric=metric, threshold=90, severity="warning"))
    session.commit()
    session.refresh(machine)
    return MachineEnrollment(id=machine.id, name=machine.name, hostname=machine.hostname, status="pending", last_heartbeat_at=None, agent_token=agent_token)


@app.get("/machines", response_model=list[MachineResponse], tags=["machines"])
def list_machines(user: User = Depends(require_user), session: Session = Depends(get_session)) -> list[MachineResponse]:
    machines = session.scalars(select(Machine).where(Machine.owner_id == user.id).order_by(Machine.name)).all()
    refresh_machine_statuses(session)
    session.commit()
    return [MachineResponse(id=machine.id, name=machine.name, hostname=machine.hostname, status=machine.status, last_heartbeat_at=machine.last_heartbeat_at.isoformat() if machine.last_heartbeat_at else None) for machine in machines]


@app.post("/agent/telemetry", status_code=status.HTTP_202_ACCEPTED, tags=["agents"])
async def ingest_telemetry(payload: TelemetryIn, x_machine_id: str = Header(default=""), x_agent_token: str = Header(default=""), session: Session = Depends(get_session)) -> dict[str, str]:
    machine = require_agent(x_machine_id, x_agent_token, session)
    telemetry = Telemetry(machine_id=machine.id, **payload.model_dump())
    session.add(telemetry)
    machine.last_heartbeat_at = datetime.now(timezone.utc)
    machine.status = "online"
    session.flush()
    alerts = evaluate_threshold_rules(session, machine, telemetry)
    alerts.extend(evaluate_service_checks(session, machine, telemetry))
    session.flush()
    session.commit()
    await manager.broadcast(machine.owner_id, {"type": "telemetry.received", "machine_id": machine.id})
    for alert in alerts:
        await manager.broadcast(machine.owner_id, {"type": "alert.created", "machine_id": machine.id, "alert_id": alert.id})
    return {"status": "accepted"}


@app.post("/agent/heartbeat", status_code=status.HTTP_202_ACCEPTED, tags=["agents"])
async def receive_heartbeat(x_machine_id: str = Header(default=""), x_agent_token: str = Header(default=""), session: Session = Depends(get_session)) -> dict[str, str]:
    machine = require_agent(x_machine_id, x_agent_token, session)
    machine.last_heartbeat_at = datetime.now(timezone.utc)
    machine.status = "online"
    active_alert = session.scalar(select(Alert).where(Alert.machine_id == machine.id, Alert.kind == "heartbeat", Alert.state == "active"))
    if active_alert is not None:
        active_alert.state = "resolved"
        active_alert.resolved_at = datetime.now(timezone.utc)
    session.commit()
    await manager.broadcast(machine.owner_id, {"type": "heartbeat.received", "machine_id": machine.id})
    return {"status": "accepted"}


@app.websocket("/ws/events")
async def dashboard_events(websocket: WebSocket, token: str = Query()):
    try:
        user_id = decode_access_token(token)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)


@app.get("/machines/{machine_id}/telemetry", tags=["telemetry"])
def telemetry_history(machine_id: str, limit: int = 60, user: User = Depends(require_user), session: Session = Depends(get_session)) -> list[dict]:
    machine = session.get(Machine, machine_id)
    if machine is None or machine.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")
    rows = session.scalars(select(Telemetry).where(Telemetry.machine_id == machine.id).order_by(desc(Telemetry.collected_at)).limit(min(limit, 500))).all()
    return [{"collected_at": row.collected_at.isoformat(), "cpu_percent": row.cpu_percent, "memory_percent": row.memory_percent, "disk_percent": row.disk_percent, "network_bytes_sent": row.network_bytes_sent, "network_bytes_received": row.network_bytes_received, "uptime_seconds": row.uptime_seconds} for row in reversed(rows)]


@app.get("/machines/{machine_id}/services", response_model=list[ServiceCheckResponse], tags=["services"])
def list_service_checks(machine_id: str, user: User = Depends(require_user), session: Session = Depends(get_session)) -> list[ServiceCheck]:
    machine = session.get(Machine, machine_id)
    if machine is None or machine.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")
    return session.scalars(select(ServiceCheck).where(ServiceCheck.machine_id == machine.id).order_by(ServiceCheck.service_name)).all()


@app.post("/machines/{machine_id}/services", response_model=ServiceCheckResponse, status_code=status.HTTP_201_CREATED, tags=["services"])
def create_service_check(machine_id: str, payload: ServiceCheckCreate, user: User = Depends(require_user), session: Session = Depends(get_session)) -> ServiceCheck:
    machine = session.get(Machine, machine_id)
    if machine is None or machine.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")
    existing = session.scalar(select(ServiceCheck).where(ServiceCheck.machine_id == machine.id, ServiceCheck.service_name == payload.service_name))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Service is already monitored")
    check = ServiceCheck(machine_id=machine.id, service_name=payload.service_name, severity=payload.severity)
    session.add(check)
    session.commit()
    session.refresh(check)
    return check


@app.get("/machines/{machine_id}/rules", response_model=list[AlertRuleResponse], tags=["alerts"])
def list_alert_rules(machine_id: str, user: User = Depends(require_user), session: Session = Depends(get_session)) -> list[AlertRule]:
    machine = session.get(Machine, machine_id)
    if machine is None or machine.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")
    return session.scalars(select(AlertRule).where(AlertRule.machine_id == machine.id)).all()


@app.put("/alert-rules/{rule_id}", response_model=AlertRuleResponse, tags=["alerts"])
def update_alert_rule(rule_id: int, payload: AlertRuleUpdate, user: User = Depends(require_user), session: Session = Depends(get_session)) -> AlertRule:
    rule = session.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found")
    machine = session.get(Machine, rule.machine_id)
    if machine is None or machine.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found")
    rule.threshold = payload.threshold
    rule.severity = payload.severity
    rule.enabled = payload.enabled
    session.commit()
    return rule


@app.get("/alerts", response_model=list[AlertResponse], tags=["alerts"])
def list_alerts(user: User = Depends(require_user), session: Session = Depends(get_session)) -> list[AlertResponse]:
    rows = session.execute(select(Alert, Machine.name).join(Machine).where(Machine.owner_id == user.id).order_by(desc(Alert.created_at)).limit(100)).all()
    return [AlertResponse(id=alert.id, machine_id=alert.machine_id, machine_name=name, kind=alert.kind, state=alert.state, severity=alert.severity, message=alert.message, value=alert.value, created_at=alert.created_at.isoformat(), acknowledged_at=alert.acknowledged_at.isoformat() if alert.acknowledged_at else None, resolved_at=alert.resolved_at.isoformat() if alert.resolved_at else None) for alert, name in rows]


@app.post("/alerts/{alert_id}/acknowledge", response_model=AlertResponse, tags=["alerts"])
async def acknowledge_alert(alert_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)) -> AlertResponse:
    row = session.execute(select(Alert, Machine.name).join(Machine).where(Alert.id == alert_id, Machine.owner_id == user.id)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    alert, machine_name = row
    if alert.state == "active":
        alert.state = "acknowledged"
        alert.acknowledged_at = datetime.now(timezone.utc)
        alert.acknowledged_by_id = user.id
        session.commit()
        await manager.broadcast(user.id, {"type": "alert.acknowledged", "machine_id": alert.machine_id, "alert_id": alert.id})
    return AlertResponse(id=alert.id, machine_id=alert.machine_id, machine_name=machine_name, kind=alert.kind, state=alert.state, severity=alert.severity, message=alert.message, value=alert.value, created_at=alert.created_at.isoformat(), acknowledged_at=alert.acknowledged_at.isoformat() if alert.acknowledged_at else None, resolved_at=alert.resolved_at.isoformat() if alert.resolved_at else None)
