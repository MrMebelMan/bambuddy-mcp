"""MCP Server setup and main entry point."""

import asyncio
import importlib.metadata
import json
import sys

import httpx
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ImageContent,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

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


def build_server(config: Config, tool_defs: list[dict]) -> Server:
    """Create the MCP server exposing the given tool definitions."""
    tool_map = {t["name"]: t for t in tool_defs}

    async def call_tool_direct(
        name: str, arguments: dict
    ) -> list[TextContent | ImageContent]:
        if name not in tool_map:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        args = dict(arguments)
        embed_image = args.pop("embed_image", False)
        async with httpx.AsyncClient(timeout=30) as client:
            return await execute_api_call(
                config,
                tool_map[name],
                args,
                client,
                embed_image=embed_image,
            )

    censored = []
    if config.censor_access_code:
        censored.append("access_code")
    if config.censor_serial:
        censored.append("serial_number")
    if config.censor_model_filename:
        censored.append("model filenames (.3mf/.gcode)")
    if censored:
        censor_note = (
            f" The Bambuddy MCP server is censoring: {', '.join(censored)}. "
            "Users can disable this in their MCP server config via BAMBUDDY_CENSOR_* env vars."
        )
    else:
        censor_note = ""

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
            embed_image = arguments.get("embed_image", False)
            if tool_name not in tool_map:
                return [
                    TextContent(
                        type="text",
                        text=f"Unknown tool: {tool_name}. Use search_tools to find available tools.",
                    )
                ]
            async with httpx.AsyncClient(timeout=30) as client:
                return await execute_api_call(
                    config,
                    tool_map[tool_name],
                    tool_args,
                    client,
                    embed_image=embed_image,
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

    if config.direct_mode:
        # Direct mode: expose all 430+ tools individually
        tools = [
            Tool(
                name=t["name"],
                description=t["description"],
                input_schema=t["input_schema"],
            )
            for t in tool_defs
        ]
        dispatch = call_tool_direct
    else:
        # Proxy mode (default): expose 4 meta-tools for discovery + execution
        tools = [
            Tool(
                name="list_categories",
                description="List all available tool categories and the total tool count. Use this first to understand what's available.",
                input_schema={"type": "object", "properties": {}},
            ),
            Tool(
                name="search_tools",
                description="Search for tools by keyword. Returns matching tool names, descriptions, and input schemas. Use this to find the right tool before calling execute_tool.",
                input_schema={
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
                description=f"Execute a Bambuddy API tool by name. Use search_tools first to find the tool name and its required arguments. Images are saved to disk by default — use xdg-open to show them to the user. Only set embed_image=true if you need to analyze the image content yourself.{censor_note}",
                input_schema={
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
                        "embed_image": {
                            "type": "boolean",
                            "description": "Set to true to embed image data in the response instead of saving to a file (default: false)",
                            "default": False,
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
                input_schema={
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
        dispatch = call_tool_proxy

    async def on_list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=tools)

    async def on_call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult:
        try:
            content = await dispatch(params.name, params.arguments or {})
        except (httpx.HTTPError, OSError, ValueError) as e:
            return CallToolResult(
                content=[TextContent(type="text", text=str(e))], is_error=True
            )
        return CallToolResult(content=content)

    return Server(
        "bambuddy",
        version=importlib.metadata.version("bambuddy-mcp"),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def main():
    """Main entry point for the Bambuddy MCP server."""
    config = Config.from_env()

    async with httpx.AsyncClient() as client:
        try:
            spec = await fetch_openapi_spec(config.base_url, client)
        except (httpx.HTTPError, ValueError) as e:
            print(
                f"Error: Could not fetch OpenAPI spec from {config.base_url}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)

    tool_defs = parse_openapi_to_tools(spec)
    mode = "direct" if config.direct_mode else "proxy"
    print(
        f"Loaded {len(tool_defs)} tools from OpenAPI spec (mode: {mode})",
        file=sys.stderr,
    )

    server = build_server(config, tool_defs)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def run():
    """Sync entry point for console_scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
