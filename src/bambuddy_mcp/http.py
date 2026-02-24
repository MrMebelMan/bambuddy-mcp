"""HTTP execution logic for API calls."""

import base64
import json
import os
import re
import tempfile
import time
from urllib.parse import urljoin

import httpx
from mcp.types import ImageContent, TextContent

from bambuddy_mcp.config import Config


def build_url(base_url: str, path_template: str, arguments: dict) -> tuple[str, dict]:
    """Fill path parameters and return (url, remaining_args)."""
    remaining = dict(arguments)

    def replacer(match: re.Match) -> str:
        param_name = match.group(1)
        value = remaining.pop(param_name, match.group(0))
        return str(value)

    filled_path = re.sub(r"\{(\w+)\}", replacer, path_template)
    url = urljoin(base_url, filled_path)
    return url, remaining


MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


async def execute_api_call(
    config: Config,
    tool_def: dict,
    arguments: dict,
    client: httpx.AsyncClient,
    embed_image: bool = False,
) -> list[TextContent | ImageContent]:
    """Execute an API call and return the response as MCP content."""
    url, remaining_args = build_url(config.base_url, tool_def["path"], arguments)

    headers: dict[str, str] = {}
    if config.api_key:
        headers["X-API-Key"] = config.api_key

    method = tool_def["method"]
    query_param_names = tool_def.get("query_params", set())

    # Split remaining args into query params and body params
    query_params = {k: v for k, v in remaining_args.items() if k in query_param_names}
    body_params = {
        k: v for k, v in remaining_args.items() if k not in query_param_names
    }

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
                    value if not isinstance(value, (dict, list)) else json.dumps(value)
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
        return [
            TextContent(
                type="text", text=f"HTTP {response.status_code} Error:\n{result}"
            )
        ]

    # Handle image responses
    if content_type.startswith("image/"):
        mime_type = content_type.split(";")[0].strip()
        if embed_image:
            b64_data = base64.b64encode(response.content).decode("ascii")
            return [ImageContent(type="image", data=b64_data, mimeType=mime_type)]
        ext = MIME_TO_EXT.get(mime_type, ".bin")
        name = tool_def.get("name", "image")
        ts = int(time.time())
        path = os.path.join(tempfile.gettempdir(), f"bambuddy_{name}_{ts}{ext}")
        with open(path, "wb") as f:
            f.write(response.content)
        size_kb = len(response.content) / 1024
        return [
            TextContent(
                type="text",
                text=f"Image saved to {path} ({size_kb:.0f}KB, {mime_type})",
            )
        ]

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


async def fetch_openapi_spec(base_url: str, client: httpx.AsyncClient) -> dict:
    """Fetch the OpenAPI spec from the running Bambuddy server."""
    url = urljoin(base_url, "/openapi.json")
    response = await client.get(url, timeout=10)
    response.raise_for_status()
    return response.json()
