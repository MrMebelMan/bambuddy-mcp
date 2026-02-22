# CLAUDE.md

## Project Overview

Bambuddy MCP Server — a single-file Python MCP server that dynamically exposes the Bambuddy REST API as MCP tools. It reads the OpenAPI spec from a running Bambuddy instance at startup and generates tools for all endpoints.

## Key Files

- `bambuddy_mcp.py` — The MCP server (single file, no submodules)
- `pyproject.toml` — Package metadata and dependencies

## Development

```bash
# Install dependencies
uv sync

# Run the server (needs a running Bambuddy instance)
BAMBUDDY_URL=http://localhost:8000 uv run bambuddy_mcp.py

# Test initialization via stdio
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | uv run bambuddy_mcp.py
```

## Architecture

The server uses the low-level MCP `Server` class (not `FastMCP`) so it can register tools with raw JSON schemas parsed directly from the OpenAPI spec. This avoids needing to generate Python functions with type annotations for 430+ endpoints.

### Tool Generation Pipeline

1. `parse_openapi_to_tools()` — Iterates all OpenAPI paths/methods, builds tool definitions
2. `_clean_tool_name()` — Converts FastAPI operation IDs to readable names (e.g. `get_printer_api_v1_printers__printer_id__get` → `get_printer`)
3. `_build_input_schema()` — Merges path params, query params, and request body into a single JSON Schema. Also tracks which params are query params for correct HTTP dispatch.
4. `_resolve_schema()` — Recursively resolves `$ref` pointers in the OpenAPI spec (depth-limited to 3)

### HTTP Execution

`execute_api_call()` handles the HTTP request:
- Path params are interpolated into the URL
- Query params (tracked from OpenAPI `in: query`) go as URL params
- Remaining params go as JSON body for POST/PUT/PATCH
- File uploads use multipart/form-data
- Auth via `X-API-Key` header
- Image responses (`image/*`) are returned as `ImageContent` with base64 data
- Other binary responses (video, audio, octet-stream) are returned as base64-encoded text

## Important

This server exposes 430+ tools which can consume a large amount of context.

## Dependencies

- `mcp` — Official MCP Python SDK
- `httpx` — Async HTTP client
