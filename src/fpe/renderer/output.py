"""Output rendering — text and JSON formatters."""

from __future__ import annotations

from fpe.models import AnalysisResult


def render_text(result: AnalysisResult) -> str:
    """Render analysis result as human-readable text."""
    lines = [
        f"Status: {result.status}",
        f"Confidence: {result.confidence:.2f}",
        "",
        "Path:",
    ]

    for node in result.path:
        lines.append(
            f"  [{node.hop_index}] {node.obj_type} {node.obj_name}"
            f"  (reason: {node.reason})"
        )

    if result.risks:
        lines.extend(["", "Risks detected:"])
        for risk in result.risks:
            lines.append(f"  [{risk.severity}] {risk.code}: {risk.message}")

    if result.summary:
        lines.extend(["", "Summary:", f"  {result.summary}"])

    if result.mermaid:
        lines.extend(["", "Mermaid:", result.mermaid])

    return "\n".join(lines)


def render_json(result: AnalysisResult) -> str:
    """Render analysis result as JSON."""
    return result.model_dump_json(indent=2)
