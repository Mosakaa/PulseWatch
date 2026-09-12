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
