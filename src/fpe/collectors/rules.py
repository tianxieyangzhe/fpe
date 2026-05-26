"""IP policy routing rule collection and matching."""

from __future__ import annotations

import re
import logging
from typing import Any

from fpe.command.executor import RemoteExecutor, list_network_namespaces, list_network_vrfs
from fpe.models import RuleInfo, RuleMatch, RuleMatchResult

logger = logging.getLogger(__name__)


def get_ip_rules(
    executor: RemoteExecutor,
) -> list[RuleMatch]:
    """Collect all IP policy routing rules (legacy, no namespace support)."""
    raw = executor.run("ip rule show")
    return parse_rules(raw)


def get_rules(
    executor: RemoteExecutor,
    namespace: str | None = None,
    vrf: str | None = None,
) -> list[RuleInfo]:
    """Collect IP rules from one or all network scopes.

    When *namespace* is ``None``, auto-discovers all namespaces (root +
    named) and collects rules from each.  When *namespace* is given
    (including ``""`` for root), collects only from that scope.
    """
    if namespace is None:
        return _collect_rules_all_scopes(executor, vrf)
    return _collect_rules_single_scope(executor, namespace, vrf)


def _collect_rules_all_scopes(
    executor: RemoteExecutor,
    vrf: str | None,
) -> list[RuleInfo]:
    results: list[RuleInfo] = []
    ns_scopes = ["", *list_network_namespaces(executor)]
    for ns in ns_scopes:
        if vrf is not None:
            results.extend(_collect_rules_single_scope(executor, ns, vrf))
        else:
            # Auto-discover VRFs within this namespace
            results.extend(_collect_rules_single_scope(executor, ns, None))
            for discovered_vrf in list_network_vrfs(executor, ns):
                results.extend(_collect_rules_single_scope(executor, ns, discovered_vrf))
    return results


def _collect_rules_single_scope(
    executor: RemoteExecutor,
    namespace: str | None,
    vrf: str | None,
) -> list[RuleInfo]:
    ns_for_rule = namespace if namespace else None
    raw = executor.run_in_context("ip rule show", namespace=namespace, vrf=vrf)
    parsed = parse_rules(raw)
    return [
        RuleInfo(
            priority=r.priority,
            table=r.table,
            raw=r.raw,
            namespace=ns_for_rule,
            vrf=vrf,
        )
        for r in parsed
    ]


def match_ip_rules(
    rules: list[RuleMatch],
    packet: dict[str, Any],
) -> RuleMatchResult:
    """Match rules against a packet context and return matched rules."""
    matched: list[RuleMatch] = []
    has_unresolved = False
    warnings: list[str] = []

    for rule in rules:
        fields: list[str] = []
        unresolved: list[str] = []

        raw_lower = rule.raw.lower()
        src_ip = (packet.get("src_ip") or "").lower()
        dst_ip = (packet.get("dst_ip") or "").lower()
        ingress_if = (packet.get("ingress_if") or "").lower()
        fwmark = (packet.get("fwmark") or "").lower()

        if "from" in raw_lower:
            if src_ip and src_ip in raw_lower:
                fields.append(f"src={src_ip}")
            else:
                unresolved.append("from")
        if "to" in raw_lower:
            if dst_ip and dst_ip in raw_lower:
                fields.append(f"dst={dst_ip}")
            else:
                unresolved.append("to")
        if "iif" in raw_lower:
            if ingress_if and ingress_if in raw_lower:
                fields.append(f"iif={ingress_if}")
            else:
                unresolved.append("iif")
        if "fwmark" in raw_lower:
            if fwmark and fwmark in raw_lower:
                fields.append(f"fwmark={fwmark}")
            else:
                unresolved.append("fwmark")

        if unresolved:
            has_unresolved = True

        matched.append(
            RuleMatch(
                priority=rule.priority,
                table=rule.table,
                matched_fields=fields,
                unresolved_fields=unresolved,
                raw=rule.raw,
            )
        )

    return RuleMatchResult(
        matches=matched,
        has_unresolved_rules=has_unresolved,
        warnings=warnings,
    )


def parse_rules(raw: str) -> list[RuleMatch]:
    rules: list[RuleMatch] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        m = re.match(r"(\d+):\s+(.+)", line)
        if not m:
            continue

        priority = int(m.group(1))
        rest = m.group(2)

        table_m = re.search(r"table\s+(\S+)", rest)
        lookup_m = re.search(r"lookup\s+(\S+)", rest)
        if table_m:
            table = table_m.group(1)
        elif lookup_m:
            table = lookup_m.group(1)
        else:
            table = "main"

        rules.append(
            RuleMatch(
                priority=priority,
                table=table,
                matched_fields=[],
                unresolved_fields=[],
                raw=line,
            )
        )

    return rules
