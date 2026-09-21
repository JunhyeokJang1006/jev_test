"""Luna Realms FastAPI 애플리케이션."""

from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .api import router


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["luna-realms-api"] = "luna-realms-api"
    stage: Literal["bootstrap"] = "bootstrap"


app = FastAPI(title="Luna Realms API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(router)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """프로세스 생존 확인. DB/AI 준비 여부를 의미하지 않는다."""
    return HealthResponse(stage="bootstrap")
