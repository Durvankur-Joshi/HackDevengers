from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(default="ok", example="ok")


class SystemInfoResponse(BaseModel):
    name: str
    version: str
    status: str
    environment: str
