from pydantic import BaseModel, Field


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=8, max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str


class MachineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    hostname: str = Field(min_length=1, max_length=255)


class MachineResponse(BaseModel):
    id: str
    name: str
    hostname: str
    status: str
    last_heartbeat_at: str | None


class MachineEnrollment(MachineResponse):
    agent_token: str


class TelemetryIn(BaseModel):
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)
    disk_percent: float = Field(ge=0, le=100)
    network_bytes_sent: int = Field(ge=0, default=0)
    network_bytes_received: int = Field(ge=0, default=0)
    uptime_seconds: int = Field(ge=0)
    services: dict[str, str] = Field(default_factory=dict)


class ServiceCheckCreate(BaseModel):
    service_name: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    severity: str = Field(default="critical", pattern="^(info|warning|critical)$")


class ServiceCheckResponse(BaseModel):
    id: int
    machine_id: str
    service_name: str
    severity: str
    enabled: bool


class AlertRuleUpdate(BaseModel):
    threshold: float = Field(ge=0, le=100)
    severity: str = Field(pattern="^(info|warning|critical)$")
    enabled: bool


class AlertRuleResponse(BaseModel):
    id: int
    machine_id: str
    metric: str
    threshold: float
    severity: str
    enabled: bool


class AlertResponse(BaseModel):
    id: int
    machine_id: str
    machine_name: str
    kind: str
    state: str
    severity: str
    message: str
    value: float | None
    created_at: str
    acknowledged_at: str | None
    resolved_at: str | None
