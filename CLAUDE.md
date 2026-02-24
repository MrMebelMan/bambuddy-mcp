# CLAUDE.md

## Project Overview

Bambuddy MCP Server — a Python MCP server that dynamically exposes the Bambuddy REST API as MCP tools. It reads the OpenAPI spec from a running Bambuddy instance at startup and generates tools for all endpoints.

## Project Structure

```
src/bambuddy_mcp/
├── __init__.py      # Package entry point, exports main() and run()
├── config.py        # Configuration dataclass (env vars)
├── openapi.py       # OpenAPI → MCP tool conversion
├── search.py        # Tool search with fuzzy matching
├── http.py          # HTTP execution logic
└── server.py        # MCP server setup, main() and run() entry points

tests/
├── conftest.py      # Shared fixtures
├── test_config.py   # Config tests
├── test_openapi.py  # OpenAPI parsing tests
├── test_search.py   # Search tests
└── test_http.py     # HTTP execution tests (respx mocked)
```

## Development

```bash
# Install dependencies
uv sync
# On NixOS: nix-shell -p uv --run "uv sync"

# Lint & format (run after editing Python files)
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Run tests
uv run pytest -v

# Run the server (needs a running Bambuddy instance)
BAMBUDDY_URL=http://localhost:8000 uv run python -m bambuddy_mcp

# Test initialization via stdio
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | uv run python -m bambuddy_mcp
```

## Architecture

The server uses the low-level MCP `Server` class (not `FastMCP`) so it can register tools with raw JSON schemas parsed directly from the OpenAPI spec. This avoids needing to generate Python functions with type annotations for 430+ endpoints.

### Module Breakdown

- **config.py** — `Config` dataclass with `from_env()` for loading `BAMBUDDY_URL`, `BAMBUDDY_API_KEY`, `BAMBUDDY_DIRECT_MODE`
- **openapi.py** — Tool generation pipeline:
  - `parse_openapi_to_tools()` — Iterates all OpenAPI paths/methods
  - `clean_tool_name()` — Converts FastAPI operation IDs to readable names
  - `build_input_schema()` — Merges path/query/body params into JSON Schema
  - `resolve_schema()` — Recursively resolves `$ref` pointers (depth-limited)
- **search.py** — `search_tools()` with substring + fuzzy matching
- **http.py** — `execute_api_call()` for HTTP execution, `fetch_openapi_spec()` for spec loading
- **server.py** — MCP server setup with direct/proxy mode handlers; `main()` is async entry point, `run()` is sync wrapper for console script

### HTTP Execution

`execute_api_call()` handles the HTTP request:
- Path params are interpolated into the URL
- Query params (tracked from OpenAPI `in: query`) go as URL params
- Remaining params go as JSON body for POST/PUT/PATCH
- File uploads use multipart/form-data
- Auth via `X-API-Key` header
- Image responses (`image/*`) are returned as `ImageContent` with base64 data
- Other binary responses (video, audio, octet-stream) are returned as base64-encoded text

## Modes

- **Proxy mode** (default) — Exposes 4 meta-tools (`list_categories`, `search_tools`, `execute_tool`, `find_printer`) that let the AI discover and call tools on demand, keeping context usage minimal.
- **Direct mode** (`BAMBUDDY_DIRECT_MODE=true`) — Exposes all 430+ tools directly. Uses more context but avoids the indirection layer.

## Build & Dependencies

Built with `hatchling`. Console script entry point: `bambuddy-mcp`

- `mcp` — Official MCP Python SDK
- `httpx` — Async HTTP client
- `pytest`, `pytest-asyncio`, `respx`, `ruff` — Testing & linting (dev)
