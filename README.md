# FPE

FPE is a network forwarding path analysis tool. The current implementation is being rebuilt in Go around a local SQLite knowledge base and an MCP server:

```text
collector -> SQLite knowledge base -> MCP tools -> LLM analysis/reporting
```

The Go program handles deterministic work such as network data collection, route/rule lookup, OVS flow walking, group expansion, and path segment calculation. The LLM consumes MCP tool results to explain uncertain branches, connect incomplete cross-host clues, and generate reports or topology diagrams.

## Current Status

This repository has moved from the previous Python implementation to a Go implementation.

Main components:

- `cmd/collect`: collects Linux network, OVS, VRF, and FRR data into SQLite.
- `cmd/serve`: starts an MCP server backed by a collected SQLite database.
- `internal/collector`: local and SSH command collection logic.
- `internal/db`: SQLite schema, writers, and query helpers.
- `internal/walker`: packet completion and forwarding path calculation.
- `internal/mcp`: MCP server and tool registration.

## Quick Start

Run without building:

```bash
go run . collect
go run . serve --db <host>.db
```

Build a binary:

```bash
go build -o fpe .
```

Collect from a remote host:

```bash
./fpe collect --ssh 192.168.1.10 --user root --key ~/.ssh/id_ed25519
```

Start Streamable HTTP MCP transport:

```bash
./fpe serve --db 192_168_1_10.db --transport mcp --addr :8080
```

See [USE.md](./USE.md) for command examples, [docs/FPE_Go_重构设计.md](./docs/FPE_Go_重构设计.md) for the current Go architecture, and [docs/v1](./docs/v1/README.md) for the planned SD-WAN diagnosis agent design.
