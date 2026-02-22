"""
Bambuddy MCP Server

Dynamically exposes all Bambuddy REST API endpoints as MCP tools.
Fetches the OpenAPI spec from the running server at startup.

Environment variables:
    BAMBUDDY_URL     - Base URL of Bambuddy (default: http://localhost:8000)
    BAMBUDDY_API_KEY - API key for authentication (optional if auth disabled)
"""

import asyncio
import json
import os
import re
import sys
from urllib.parse import urljoin

import base64

import httpx
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import ImageContent, TextContent, Tool

BAMBUDDY_URL = os.environ.get("BAMBUDDY_URL", "http://localhost:8000")
BAMBUDDY_API_KEY = os.environ.get("BAMBUDDY_API_KEY", "")

# ---------------------------------------------------------------------------
# OpenAPI → MCP tool conversion
# ---------------------------------------------------------------------------


def _clean_tool_name(operation_id: str) -> str:
    """Convert FastAPI operation IDs to readable tool names.

    FastAPI generates IDs like 'get_printer_api_v1_printers__printer_id__get'.
    We strip the 'api_v1_..._method' suffix and keep the semantic prefix.
    """
    name = re.sub(r"_(get|post|put|patch|delete)$", "", operation_id)
    match = re.match(r"^(.+?)_api_v1_", name)
    if match:
        name = match.group(1)
    return name


def _resolve_ref(ref: str, spec: dict) -> dict:
    """Resolve a $ref pointer like '#/components/schemas/Foo'."""
    parts = ref.lstrip("#/").split("/")
    node = spec
    for part in parts:
        node = node[part]
    return node


def _resolve_schema(schema: dict, spec: dict, depth: int = 0) -> dict:
    """Recursively resolve $ref in a schema, up to a depth limit."""
    if depth > 3:
        return schema
    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        resolved = _resolve_ref(schema["$ref"], spec)
        return _resolve_schema(resolved, spec, depth + 1)

    result = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            result[key] = {
                k: _resolve_schema(v, spec, depth + 1) for k, v in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            result[key] = _resolve_schema(value, spec, depth + 1)
        elif key == "anyOf" and isinstance(value, list):
            non_null = [v for v in value if v != {"type": "null"}]
            if len(non_null) == 1:
                result.update(_resolve_schema(non_null[0], spec, depth + 1))
            else:
                result[key] = [_resolve_schema(v, spec, depth + 1) for v in value]
        elif key == "allOf" and isinstance(value, list):
            for item in value:
                result.update(_resolve_schema(item, spec, depth + 1))
        else:
            result[key] = value

    return result


def _build_input_schema(
    path: str, method: str, operation: dict, spec: dict
) -> tuple[dict, set[str]]:
    """Build a JSON Schema for the tool's input from OpenAPI parameters + body.

    Returns (input_schema, query_param_names) so the executor knows which
    parameters should be sent as query params vs JSON body.
    """
    properties: dict = {}
    required: list[str] = []
    query_param_names: set[str] = set()

    for param in operation.get("parameters", []):
        if param.get("in") == "header":
            continue
        name = param["name"]
        schema = _resolve_schema(param.get("schema", {}), spec)
        schema.pop("title", None)
        properties[name] = schema
        if param.get("required"):
            required.append(name)
        if param.get("in") == "query":
            query_param_names.add(name)

    body = operation.get("requestBody", {})
    body_content = body.get("content", {})

    if "application/json" in body_content:
        body_schema = body_content["application/json"].get("schema", {})
        resolved = _resolve_schema(body_schema, spec)
        if resolved.get("type") == "object" and "properties" in resolved:
            for prop_name, prop_schema in resolved["properties"].items():
                prop_schema.pop("title", None)
                properties[prop_name] = prop_schema
            required.extend(resolved.get("required", []))
        elif resolved:
            properties["body"] = resolved

    elif "multipart/form-data" in body_content:
        body_schema = body_content["multipart/form-data"].get("schema", {})
        resolved = _resolve_schema(body_schema, spec)
        if resolved.get("type") == "object" and "properties" in resolved:
            for prop_name, prop_schema in resolved["properties"].items():
                prop_schema.pop("title", None)
                if prop_schema.get("format") == "binary":
                    prop_schema = {
                        "type": "string",
                        "description": "File path to upload",
                    }
                properties[prop_name] = prop_schema
            required.extend(resolved.get("required", []))

    input_schema: dict = {"type": "object", "properties": properties}
    if required:
        input_schema["required"] = list(dict.fromkeys(required))
    return input_schema, query_param_names


def _build_tool_description(path: str, method: str, operation: dict) -> str:
    """Build a description from the OpenAPI operation."""
    parts = []
    summary = operation.get("summary", "")
    description = operation.get("description", "")
    tag = operation.get("tags", [""])[0]

    parts.append(f"[{tag}] {method.upper()} {path}")
    if summary:
        parts.append(summary)
    if description and description != summary:
        parts.append(description)
    return "\n".join(parts)


def parse_openapi_to_tools(spec: dict) -> list[dict]:
    """Parse an OpenAPI spec into a list of tool definitions."""
    tools = []
    seen_names: dict[str, int] = {}

    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue

            operation_id = operation.get("operationId", f"{method}_{path}")
            name = _clean_tool_name(operation_id)

            if name in seen_names:
                seen_names[name] += 1
                name = f"{name}_{seen_names[name]}"
            else:
                seen_names[name] = 0

            input_schema, query_param_names = _build_input_schema(
                path, method, operation, spec
            )

            tools.append(
                {
                    "name": name,
                    "description": _build_tool_description(path, method, operation),
                    "input_schema": input_schema,
                    "query_params": query_param_names,
                    "path": path,
                    "method": method,
                    "has_file_upload": "multipart/form-data"
                    in operation.get("requestBody", {}).get("content", {}),
                }
            )

    return tools


# ---------------------------------------------------------------------------
# HTTP execution
# ---------------------------------------------------------------------------


def _build_url(path_template: str, arguments: dict) -> tuple[str, dict]:
    """Fill path parameters and return (url, remaining_args)."""
    remaining = dict(arguments)

    def replacer(match: re.Match) -> str:
        param_name = match.group(1)
        value = remaining.pop(param_name, match.group(0))
        return str(value)

    filled_path = re.sub(r"\{(\w+)\}", replacer, path_template)
    url = urljoin(BAMBUDDY_URL, filled_path)
    return url, remaining


async def execute_api_call(
    tool_def: dict,
    arguments: dict,
    client: httpx.AsyncClient,
) -> list[TextContent | ImageContent]:
    """Execute an API call and return the response as MCP content."""
    url, remaining_args = _build_url(tool_def["path"], arguments)

    headers: dict[str, str] = {}
    if BAMBUDDY_API_KEY:
        headers["X-API-Key"] = BAMBUDDY_API_KEY

    method = tool_def["method"]
    query_param_names = tool_def.get("query_params", set())

    # Split remaining args into query params and body params
    query_params = {k: v for k, v in remaining_args.items() if k in query_param_names}
    body_params = {k: v for k, v in remaining_args.items() if k not in query_param_names}

    if method in ("get", "delete"):
        response = await client.request(
            method.upper(), url, params=remaining_args, headers=headers
        )
    elif tool_def.get("has_file_upload"):
        files = {}
        data = {}
        for key, value in body_params.items():
            if isinstance(value, str) and os.path.isfile(value):
                files[key] = open(value, "rb")
            else:
                data[key] = (
                    value
                    if not isinstance(value, (dict, list))
                    else json.dumps(value)
                )
        try:
            response = await client.request(
                method.upper(),
                url,
                files=files,
                data=data,
                params=query_params,
                headers=headers,
            )
        finally:
            for f in files.values():
                f.close()
    else:
        response = await client.request(
            method.upper(),
            url,
            json=body_params or None,
            params=query_params,
            headers=headers,
        )

    content_type = response.headers.get("content-type", "")

    # Handle error responses as text
    if response.status_code >= 400:
        try:
            body = response.json()
            result = json.dumps(body, indent=2)
        except Exception:
            result = response.text
        return [TextContent(type="text", text=f"HTTP {response.status_code} Error:\n{result}")]

    # Handle image responses as ImageContent
    if content_type.startswith("image/"):
        mime_type = content_type.split(";")[0].strip()
        b64_data = base64.b64encode(response.content).decode("ascii")
        return [ImageContent(type="image", data=b64_data, mimeType=mime_type)]

    # Handle other binary responses
    if content_type.startswith(("application/octet-stream", "video/", "audio/")):
        b64_data = base64.b64encode(response.content).decode("ascii")
        return [
            TextContent(
                type="text",
                text=f"Binary response ({content_type}, {len(response.content)} bytes), base64-encoded:\n{b64_data}",
            )
        ]

    # Handle JSON/text responses
    try:
        body = response.json()
        result = json.dumps(body, indent=2)
    except Exception:
        result = response.text

    return [TextContent(type="text", text=result)]


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------


async def fetch_openapi_spec(client: httpx.AsyncClient) -> dict:
    """Fetch the OpenAPI spec from the running Bambuddy server."""
    url = urljoin(BAMBUDDY_URL, "/openapi.json")
    response = await client.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


async def main():
    server = Server("bambuddy")

    async with httpx.AsyncClient() as client:
        try:
            spec = await fetch_openapi_spec(client)
        except Exception as e:
            print(
                f"Error: Could not fetch OpenAPI spec from {BAMBUDDY_URL}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)

    tool_defs = parse_openapi_to_tools(spec)
    tool_map = {t["name"]: t for t in tool_defs}
    print(f"Loaded {len(tool_defs)} tools from OpenAPI spec", file=sys.stderr)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["input_schema"],
            )
            for t in tool_defs
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent]:
        if name not in tool_map:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        async with httpx.AsyncClient(timeout=30) as client:
            return await execute_api_call(tool_map[name], arguments or {}, client)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
