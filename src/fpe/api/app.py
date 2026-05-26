"""FastAPI application entry point."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from fpe.analyzer import Analyzer
from fpe.models import ExecContext, PacketContext

app = FastAPI(
    title="FPE - Flow Path Explorer",
    version="0.1.0",
    description="AI-powered network link analysis API",
)


class AnalyzeRequest(BaseModel):
    """Request model for POST /api/v1/analyze."""

    query: str = ""
    packet: dict[str, Any] = {}
    exec_ctx: dict[str, Any] = {}
    options: dict[str, Any] = {}


@app.post("/api/v1/analyze")
async def analyze(req: AnalyzeRequest) -> dict[str, Any]:
    """Execute a complete flow analysis."""
    packet = PacketContext(**req.packet)
    exec_ctx = ExecContext(**req.exec_ctx)

    analyzer = Analyzer()
    result = await analyzer.analyze(
        host=exec_ctx.host,
        packet=packet,
        exec_ctx=exec_ctx,
        options=req.options,
    )

    return result.model_dump()


@app.get("/api/v1/healthz")
async def healthz() -> dict[str, bool]:
    """Health check endpoint."""
    return {"ok": True}
