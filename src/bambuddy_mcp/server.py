"""MCP Server setup and main entry point."""

import asyncio
import json
import sys

import httpx
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import ImageContent, TextContent, Tool

from bambuddy_mcp.config import Config
from bambuddy_mcp.http import build_url, execute_api_call, fetch_openapi_spec
from bambuddy_mcp.openapi import parse_openapi_to_tools
from bambuddy_mcp.search import search_tools

PRINTER_FIELDS = ("id", "name", "model", "ip_address", "is_active")


async def _find_printers(
    name_query: str,
    config: Config,
    tool_map: dict,
) -> list[TextContent]:
    """Look up printers by name using the list_printers endpoint."""
    list_tool = tool_map.get("list_printers")
    if list_tool is None:
        return [
            TextContent(
                type="text",
                text=(
                    "The find_printer tool requires a 'list_printers' endpoint "
                    "in the Bambuddy API, but none was found. "
                    "Use search_tools to look for printer-related tools manually."
                ),
            )
        ]

    url, _ = build_url(config.base_url, list_tool["path"], {})
    headers: dict[str, str] = {}
    if config.api_key:
        headers["X-API-Key"] = config.api_key

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers)

    if response.status_code >= 400:
        return [
            TextContent(
                type="text",
                text=f"HTTP {response.status_code} Error fetching printers: {response.text}",
            )
        ]

    printers = response.json()

    # Handle paginated responses wrapped in an envelope
    if isinstance(printers, dict):
        for key in ("data", "items", "results", "printers"):
            if key in printers and isinstance(printers[key], list):
                printers = printers[key]
                break

    if not isinstance(printers, list):
        printers = [printers]

    # Filter by name (case-insensitive substring match)
    query_lower = name_query.lower()
    matches = [
        p
        for p in printers
        if isinstance(p, dict) and query_lower in p.get("name", "").lower()
    ]

    # Project to essential fields only
    results = [
        {field: p[field] for field in PRINTER_FIELDS if field in p} for p in matches
    ]

    output = {
        "query": name_query,
        "total_matches": len(results),
        "printers": results,
    }
    return [TextContent(type="text", text=json.dumps(output, indent=2))]


async def main():
    """Main entry point for the Bambuddy MCP server."""
    config = Config.from_env()
    server = Server("bambuddy")

    async with httpx.AsyncClient() as client:
        try:
            spec = await fetch_openapi_spec(config.base_url, client)
        except Exception as e:
            print(
                f"Error: Could not fetch OpenAPI spec from {config.base_url}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)

    tool_defs = parse_openapi_to_tools(spec)
    tool_map = {t["name"]: t for t in tool_defs}
    mode = "direct" if config.direct_mode else "proxy"
    print(
        f"Loaded {len(tool_defs)} tools from OpenAPI spec (mode: {mode})",
        file=sys.stderr,
    )

    if config.direct_mode:
        # Direct mode: expose all 430+ tools individually

        @server.list_tools()
        async def list_tools_direct() -> list[Tool]:
            return [
                Tool(
                    name=t["name"],
                    description=t["description"],
                    inputSchema=t["input_schema"],
                )
                for t in tool_defs
            ]

        @server.call_tool()
        async def call_tool_direct(
            name: str, arguments: dict
        ) -> list[TextContent | ImageContent]:
            if name not in tool_map:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            async with httpx.AsyncClient(timeout=30) as client:
                return await execute_api_call(
                    config, tool_map[name], arguments or {}, client
                )

    else:
        # Proxy mode (default): expose 3 meta-tools for discovery + execution

        @server.list_tools()
        async def list_tools_proxy() -> list[Tool]:
            return [
                Tool(
                    name="list_categories",
                    description="List all available tool categories and the total tool count. Use this first to understand what's available.",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="search_tools",
                    description="Search for tools by keyword. Returns matching tool names, descriptions, and input schemas. Use this to find the right tool before calling execute_tool.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search keyword to match against tool names and descriptions",
                            },
                            "category": {
                                "type": "string",
                                "description": "Optional category to filter by (from list_categories)",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max results to return (default 10)",
                                "default": 10,
                            },
                        },
                        "required": ["query"],
                    },
                ),
                Tool(
                    name="execute_tool",
                    description="Execute a Bambuddy API tool by name. Use search_tools first to find the tool name and its required arguments.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "The tool name (from search_tools results)",
                            },
                            "arguments": {
                                "type": "object",
                                "description": "Arguments to pass to the tool (see input_schema from search_tools)",
                                "default": {},
                            },
                        },
                        "required": ["name"],
                    },
                ),
                Tool(
                    name="find_printer",
                    description=(
                        "Find a printer by name. Returns printer details including "
                        "the printer_id needed by other tools. Use this when you "
                        "know a printer's name but need its ID."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Printer name or partial name to search for (case-insensitive)",
                            },
                        },
                        "required": ["name"],
                    },
                ),
            ]

        @server.call_tool()
        async def call_tool_proxy(
            name: str, arguments: dict
        ) -> list[TextContent | ImageContent]:
            if name == "list_categories":
                tags = sorted({t["tag"] for t in tool_defs if t["tag"]})
                result = {
                    "total_tools": len(tool_defs),
                    "categories": tags,
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            if name == "search_tools":
                query = arguments.get("query", "")
                category = arguments.get("category")
                limit = arguments.get("limit", 10)
                matches = search_tools(tool_defs, query, category, limit)
                results = [
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "input_schema": t["input_schema"],
                    }
                    for t in matches
                ]
                return [TextContent(type="text", text=json.dumps(results, indent=2))]

            if name == "execute_tool":
                tool_name = arguments.get("name", "")
                tool_args = arguments.get("arguments", {})
                if tool_name not in tool_map:
                    return [
                        TextContent(
                            type="text",
                            text=f"Unknown tool: {tool_name}. Use search_tools to find available tools.",
                        )
                    ]
                async with httpx.AsyncClient(timeout=30) as client:
                    return await execute_api_call(
                        config, tool_map[tool_name], tool_args, client
                    )

            if name == "find_printer":
                printer_name = arguments.get("name", "")
                if not printer_name:
                    return [
                        TextContent(
                            type="text",
                            text="The 'name' parameter is required for find_printer.",
                        )
                    ]
                return await _find_printers(printer_name, config, tool_map)

            return [TextContent(type="text", text=f"Unknown meta-tool: {name}")]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def run():
    """Sync entry point for console_scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
