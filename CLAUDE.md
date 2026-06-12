# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FPE is a network forwarding path analysis tool. The Go implementation follows a pipeline:

```
collector -> SQLite knowledge base -> MCP tools -> LLM analysis/reporting
```

- **Go handles deterministic work**: network data collection, route/rule lookup, OVS flow walking, group expansion, path segment calculation.
- **LLM handles uncertain work**: explaining ambiguous branches, connecting incomplete cross-host clues, generating reports and Mermaid topology diagrams.

## Commands

```bash
# Build
go build -o fpe .

# Local collection (output: <hostname>.db)
go run . collect
go run . collect mynode.db

# SSH remote collection
go run . collect --ssh 1.2.3.4 --user root --key ~/.ssh/id_ed25519

# Serve (stdio, for Claude Desktop)
go run . serve --db node1.db

# Serve (Streamable HTTP, recommended for MCP 2025 spec)
go run . serve --db node1.db --transport mcp --addr :8080

# Serve (SSE)
go run . serve --db node1.db --transport sse --addr :8000
```

There are no tests yet (`*_test.go` files do not exist).

## Architecture

The program has two subcommands wired through `cobra` in `main.go`:

### `collect` — cmd/collect/collect.go

Orchestrates full network state capture. Uses an `Executor` interface (`internal/collector/executor.go`) with `LocalExecutor` and `SSHExecutor` implementations.

Collection flow per host:
1. Root namespace: interfaces, IP rules, routes, neighbors
2. Discover network namespaces via `ip netns list`
3. If `ANPOSNS` exists: interfaces, rules, routes, neighbors + FRR vtysh output
4. VRF discovery within each namespace: VRF-specific routes, rules, neighbors; interface VRF fields updated
5. OVS: bridges, ports, flows, groups, FDB, tunnel ARP (not namespace-scoped)
6. FRR: collected only inside `ANPOSNS` via `vtysh` (show ip route, bfd peers, running-config, bgp summary, bgp ipv4 unicast, ip ospf neighbor)

### `serve` — cmd/serve/serve.go

Loads a single SQLite DB and starts an MCP server. One server per host DB; multi-machine analysis uses multiple MCP servers (different ports).

### internal/collector

Per-file responsibility — each file collects one category of data by running shell commands via an `Executor` and parsing JSON output:
- `interfaces.go` — `ip -json link show` + `ip -json addr show`
- `rules.go` — `ip -json rule show`
- `routes.go` — `ip -json route show table all`
- `neighbors.go` — `ip -json neigh show`
- `namespaces.go` — `ip netns list`
- `vrf.go` — VRF device discovery + per-VRF routes/rules/neighbors
- `ovs.go` — `ovs-vsctl` + `ovs-ofctl` + `ovs-appctl` commands
- `frr.go` — `vtysh -c "<command>"` inside ANPOSNS
- `executor.go` — `Executor` interface, `LocalExecutor`, `SSHExecutor`

All namespace-context commands use `buildNSCmd(ns, cmd)` helper which wraps with `ip netns exec <ns>`.

### internal/db

- `schema.go` — SQLite DDL (12 tables, indexed by namespace/VRF/bridge/port for query performance)
- `writer.go` — `Open()`, all `Insert*` / `Update*` methods, and Go struct definitions for every table row
- `query.go` — All `Get*` / lookup methods used by the walker and MCP tools

One DB file = one snapshot of a host. No `snapshots` table — the DB file itself is the snapshot. JSON-encoded fields are used for arrays/objects (flags, IPs, next_hops, match_fields, action_list, options).
Uses `modernc.org/sqlite` (pure Go, no CGO required).

### internal/walker

Core forwarding path computation:

1. **`packet.go`** — `ResolvePacket()` infers missing fields (proto defaults to TCP, src_mac from interface, dst_mac from neighbor table, in_port from OVS port mapping). Inferred fields are recorded in `Uncertain []string`.

2. **`rules.go`** — `matchRules()` walks IP rules by priority ASC, matches `from_prefix` against `src_ip`, returns the lookup `table_id` (defaults to `"main"`).

3. **`routes.go`** — `lpmRoute()` finds the longest prefix match route covering `dst_ip` within `namespace + table_id`.

4. **`ovs.go`** — `walkOVS()` / `walkOVSTable()` walk the OVS pipeline: match flows by priority DESC, handle `goto_table`, `resubmit`, `group` expansion, `output` (with port type detection: vxlan/geneve/patch/physical/local), and `drop`. Fields like `ct_state` and `reg*` that can't be determined locally are marked `uncertain`.

5. **`chain.go`** — `Walk()` ties it together: rules → route → OVS/kernel device → cross-namespace veth traversal. Returns a `WalkResult` with all possible `PathLeaf` branches, each annotated with certainty.

6. **`types.go`** — Core data types: `PacketTuple`, `Hop`, `PathSegment`, `PathLeaf`, `WalkResult`. All have `Certainty` fields ("certain"/"uncertain") for LLM interpretation.

### internal/mcp

- `server.go` — Creates MCP server, registers all tools, dispatches to `stdio`/`sse`/`mcp` transports via `github.com/modelcontextprotocol/go-sdk`.
- `tools.go` — 11 MCP tools registered with JSON Schema input types. The primary analysis flow is `resolve_packet` → `get_path_segments`.

### internal/logs

Thin wrapper around `go.uber.org/zap` with package-level `Info[f]`, `Debug[f]`, `Warn[f]`, `Error[f]` functions. Initialized once in `main()` with development mode.

## Key Design Decisions

- **OVS priority**: When a device appears in both `interfaces` and `ovs_ports`, the walker uses the OVS view — OVS-managed physical ports have their kernel interface as an OVS port.
- **ANPOSNS convention**: FRR runs exclusively in the `ANPOSNS` namespace. If that namespace doesn't exist, FRR collection is skipped entirely.
- **One DB per host**: Multi-machine analysis requires running separate MCP servers on different ports; the LLM queries each and stitches cross-machine paths.
- **JSON-encoded columns**: Arrays and maps in SQLite are stored as JSON strings, unmarshaled on read. This avoids complex junction tables for fields like `next_hops`, `match_fields`, `flags`.

## Dependencies

| Purpose | Library |
|---------|---------|
| CLI | `github.com/spf13/cobra` |
| SQLite | `modernc.org/sqlite` (pure Go, no CGO) |
| MCP server | `github.com/modelcontextprotocol/go-sdk` |
| SSH | `golang.org/x/crypto/ssh` |
| Logging | `go.uber.org/zap` |
| IP/CIDR | stdlib `net/netip` |
