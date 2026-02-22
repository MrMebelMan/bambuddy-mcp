# Bambuddy MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that exposes the full [Bambuddy](https://github.com/maziggy/bambuddy) REST API as tools for AI assistants like Claude.

Bambuddy is a self-hosted print archive and management system for Bambu Lab 3D printers. This MCP server dynamically generates tools from Bambuddy's OpenAPI spec at startup, giving your AI assistant access to **430+ API endpoints** covering:

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

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BAMBUDDY_URL` | `http://localhost:8000` | Base URL of your Bambuddy instance |
| `BAMBUDDY_API_KEY` | _(empty)_ | API key for authentication (create in Bambuddy Settings) |


> **Note:** This server exposes 430+ tools which can consume a large amount of context in AI assistants.

## How It Works

On startup, the server:

1. Fetches the OpenAPI spec from your running Bambuddy instance (`/openapi.json`)
2. Parses all endpoints and converts them to MCP tools with proper input schemas
3. Registers tools with clean names derived from the API operation IDs

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

