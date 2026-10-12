# Implementation Plan — ESP-IDF v6.1 MCP Build Server

**Objective**: Let agents build MiniGauge56 (ESP32-S3) through Espressif's local Tools MCP server on ESP-IDF v6.1, without leaking private data into git.

## Confirmed Architecture & Design Decisions

> [!NOTE]
> **Server**: official `idf.py mcp-server` (ESP-IDF >= v6.0, `eim` >= 0.8.1, `mcp` feature installed). Local stdio, no network, no credentials.

> [!NOTE]
> **Registration**: committed [.mcp.json](../.mcp.json), no paths: `eim run "idf.py mcp-server" v6.1`. Contributors approve it on first use.

> [!WARNING]
> **Version pin side effect**: `eim run ... v6.1` also switches the global `eim select` to v6.1 (observed with eim 0.20.0). Re-run `eim select <version>` if another default is needed.

> [!WARNING]
> **Stdout banner**: `eim run` prints environment-setup lines to stdout before the JSON-RPC stream. If a client rejects it, switch to a wrapper that exports the environment quietly.

## Phases

```mermaid
flowchart LR
  P0[Phase 0: Audit secrets/paths] --> P1[Phase 1: .mcp.json + docs] --> P2[Phase 2: Hook hardening] --> P3[Phase 3: Verify build via MCP]
```

| Phase | Content | Status |
| :--- | :--- | :--- |
| 0 | Audit tracked files; untrack `sdkconfig.old` | Done |
| 1 | `.mcp.json`, [docs/CONSTRAINTS.md](CONSTRAINTS.md) section 3, [docs/TOO.MD](TOO.MD) section 6, README link, v6 skill note | Done |
| 2 | `.githooks/pre-commit` blocks home paths and credential patterns in all staged text files | Done |
| 3 | Approve server in `claude`, `clean_project` + `build_project` | Pending user approval |

## Verification Plan

- Automated: `claude mcp list` shows `esp-idf-eim` connected; `project://status` reports `idf_version: v6.1`; `bash .githooks/pre-commit` exits 0 on the staged set and 1 on a file containing a fake home path.
- Build: via MCP `clean_project` then `build_project`, or `eim run "idf.py fullclean build" v6.1`.
- Manual: confirm no `/Users/<name>` or `/home/<name>` in `git ls-files` content.
