# Bambuddy MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that exposes the full [Bambuddy](https://github.com/maziggy/bambuddy) REST API as tools for AI assistants like Claude.

Bambuddy is a self-hosted print archive and management system for Bambu Lab 3D printers. This MCP server dynamically generates tools from Bambuddy's OpenAPI spec at startup, giving your AI assistant access to **430+ API endpoints** — without flooding the context window. Only 3 lightweight meta-tools are loaded; the AI discovers and calls specific endpoints on demand. Capabilities include:

- Printer management and real-time status monitoring
- Print archives, library, and file management
- Print queue scheduling and control
- Filament/spool inventory tracking
- Camera streaming and snapshots
- Project management
- Notifications (Discord, Telegram, Email, etc.)
- And much more

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A running [Bambuddy](https://github.com/maziggy/bambuddy) instance

## Installation

```bash
uv pip install bambuddy-mcp
```

Or install from source:

```bash
git clone https://github.com/maziggy/bambuddy-mcp.git
cd bambuddy-mcp
uv sync
```

## Configuration

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "bambuddy": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/bambuddy-mcp", "bambuddy_mcp.py"],
      "env": {
        "BAMBUDDY_URL": "http://localhost:8000",
        "BAMBUDDY_API_KEY": "your-api-key"
      }
    }
  }
}
```

### NixOS

On NixOS, use the system Python to avoid dynamic linking issues:

```json
{
  "mcpServers": {
    "bambuddy": {
      "command": "nix-shell",
      "args": [
        "-p", "uv",
        "--run", "UV_PYTHON=/run/current-system/sw/bin/python3 uv --directory /path/to/bambuddy-mcp run bambuddy_mcp.py"
      ],
      "env": {
        "BAMBUDDY_URL": "http://localhost:8000",
        "BAMBUDDY_API_KEY": "your-api-key"
      }
    }
  }
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BAMBUDDY_URL` | `http://localhost:8000` | Base URL of your Bambuddy instance |
| `BAMBUDDY_API_KEY` | _(empty)_ | API key for authentication (create in Bambuddy Settings) |
| `BAMBUDDY_DIRECT_MODE` | `false` | Set to `true` to expose all 430+ tools directly instead of the 3 meta-tools |

> **Note:** By default, the server exposes 3 meta-tools (`list_categories`, `search_tools`, `execute_tool`) that let AI assistants discover and call API endpoints on demand. Set `BAMBUDDY_DIRECT_MODE=true` to expose all 430+ tools directly (uses significantly more context).

## How It Works

On startup, the server fetches the OpenAPI spec from your running Bambuddy instance (`/openapi.json`), parses all 430+ endpoints, and indexes them by category.

By default, only **3 meta-tools** are registered with the AI assistant — not all 430+:

| Meta-tool | Purpose |
|-----------|---------|
| `list_categories` | Browse available API categories |
| `search_tools` | Find tools by keyword (with fuzzy matching) |
| `execute_tool` | Call any discovered tool by name |

This keeps the context window small while still providing full API coverage. The AI searches for what it needs, inspects the input schema, and executes — all on demand.

When a tool is called, the server makes the corresponding HTTP request to Bambuddy and returns the response. JSON responses are returned as text, while binary responses (e.g. camera snapshots) are returned as native MCP `ImageContent` with base64-encoded data so AI assistants can see, process, and display them directly.

## Example Usage

Once configured, you can ask your AI assistant things like:

- "What printers are connected?"
- "Show me the status of my A1 Mini"
- "List my recent print archives"
- "Add the benchy to the print queue"
- "What filament spools do I have?"
- "Check the print progress"
- "Turn on the chamber light"

