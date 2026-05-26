"""CLI entry point for FPE."""

from __future__ import annotations

import asyncio
from typing import Optional

import typer

from fpe.analyzer import Analyzer
from fpe.models import ExecContext, PacketContext
from fpe.renderer import render_json, render_text

app = typer.Typer(
    name="fpe",
    help="Flow Path Explorer — AI-powered network link analysis",
)


@app.command()
def analyze(
    src_ip: str = typer.Option(..., "--src-ip", help="Source IP address"),
    dst_ip: str = typer.Option(..., "--dst-ip", help="Destination IP address"),
    protocol: Optional[str] = typer.Option(
        None, "--protocol", help="Protocol (e.g., icmp, tcp, udp)"
    ),
    ingress_if: Optional[str] = typer.Option(
        None, "--ingress-if", help="Ingress interface name"
    ),
    namespace: Optional[str] = typer.Option(
        None, "--namespace", help="Namespace to run analysis in"
    ),
    vrf: Optional[str] = typer.Option(None, "--vrf", help="VRF name"),
    host: Optional[str] = typer.Option(
        None, "--host", help="Target host for SSH (default: local)"
    ),
    max_hops: int = typer.Option(16, "--max-hops", help="Maximum hop count"),
    output: str = typer.Option(
        "text", "--output", help="Output format: text or json"
    ),
) -> None:
    """Analyze a network flow path."""
    packet = PacketContext(
        src_ip=src_ip,
        dst_ip=dst_ip,
        protocol=protocol,
        ingress_if=ingress_if,
    )
    exec_ctx = ExecContext(
        namespace=namespace,
        vrf=vrf,
        host=host,
    )

    async def run() -> None:
        analyzer = Analyzer()
        result = await analyzer.analyze(
            packet=packet,
            exec_ctx=exec_ctx,
            options={"max_hops": max_hops},
            host=host,
        )

        if output == "json":
            typer.echo(render_json(result))
        else:
            typer.echo(render_text(result))

    asyncio.run(run())
