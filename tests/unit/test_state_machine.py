"""Unit tests for the Analyzer state machine."""

import pytest

from fpe.analyzer import Analyzer, STATE_COMPLETED, STATE_FAILED, STATE_INCOMPLETE
from fpe.models import AnalysisState, ExecContext, PacketContext


class TestAnalyzer:
    @pytest.mark.asyncio
    async def test_missing_input_fails(self):
        """Analyzer should fail when src_ip and dst_ip are missing."""
        analyzer = Analyzer()
        result = await analyzer.analyze()
        assert result.status == STATE_FAILED

    @pytest.mark.asyncio
    async def test_missing_dst_ip_fails(self):
        """Analyzer should fail when dst_ip is empty."""
        analyzer = Analyzer()
        result = await analyzer.analyze(
            packet=PacketContext(src_ip="10.0.0.2", dst_ip=""),
        )
        assert result.status == STATE_FAILED

    @pytest.mark.asyncio
    async def test_analyzer_builds_result_structure(self):
        """Analyzer should return a well-formed AnalysisResult."""
        analyzer = Analyzer()
        packet = PacketContext(
            src_ip="10.0.0.2",
            dst_ip="8.8.8.8",
        )
        result = await analyzer.analyze(packet=packet)
        assert hasattr(result, "status")
        assert hasattr(result, "path")
        assert hasattr(result, "decision_chain")
        assert hasattr(result, "risks")
        assert hasattr(result, "confidence")
        assert hasattr(result, "summary")

    @pytest.mark.asyncio
    async def test_input_normalization(self):
        """Should log normalized input decision."""
        analyzer = Analyzer()
        packet = PacketContext(src_ip="10.0.0.2", dst_ip="8.8.8.8")
        result = await analyzer.analyze(packet=packet)
        assert len(result.decision_chain) >= 1
        assert result.decision_chain[0].state == "INIT"

    @pytest.mark.asyncio
    async def test_max_hops_terminates(self):
        """Should become INCOMPLETE when max_hops is reached."""
        analyzer = Analyzer()
        packet = PacketContext(src_ip="10.0.0.2", dst_ip="8.8.8.8")
        result = await analyzer.analyze(
            packet=packet,
            options={"max_hops": 0},
        )
        assert result.status == STATE_INCOMPLETE
