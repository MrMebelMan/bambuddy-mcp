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


_MODEL_FILE_RE = re.compile(r"^(.+?)((?:\.gcode)?\.3mf|\.gcode)$", re.IGNORECASE)


def _mask_partial(value: str) -> str:
    """Mask a string keeping first 2 + last 2 chars."""
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def _mask_model_filename(value: str) -> str:
    """Mask the name portion of a 3mf/gcode filename."""
    m = _MODEL_FILE_RE.match(value)
    if not m:
        return value
    return _mask_partial(m.group(1)) + m.group(2)


def censor_response(data, config: Config):
    """Recursively censor sensitive fields in API response data."""
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if k == "access_code" and config.censor_access_code and isinstance(v, str):
                result[k] = "********"
            elif k == "serial_number" and config.censor_serial and isinstance(v, str):
                result[k] = _mask_partial(v)
            else:
                result[k] = censor_response(v, config)
        return result
    if isinstance(data, list):
        return [censor_response(item, config) for item in data]
    if (
        isinstance(data, str)
        and config.censor_model_filename
        and _MODEL_FILE_RE.match(data)
    ):
        return _mask_model_filename(data)
    return data


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
            body = censor_response(body, config)
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
        if embed_image and not config.censor_model_filename:
            b64_data = base64.b64encode(response.content).decode("ascii")
            return [ImageContent(type="image", data=b64_data, mimeType=mime_type)]
        ext = MIME_TO_EXT.get(mime_type, ".bin")
        name = tool_def.get("name", "image")
        ts = int(time.time())
        path = os.path.join(tempfile.gettempdir(), f"bambuddy_{name}_{ts}{ext}")
        with open(path, "wb") as f:
            f.write(response.content)
        size_kb = len(response.content) / 1024
        msg = f"Image saved to {path} ({size_kb:.0f}KB, {mime_type})"
        if embed_image and config.censor_model_filename:
            msg += (
                "\nNote: Image embedding was blocked by the Bambuddy MCP server "
                "because model filename censoring is enabled "
                "(BAMBUDDY_CENSOR_MODEL_FILENAME=true in MCP server config). "
                "Use xdg-open to show the saved file to the user."
            )
        return [TextContent(type="text", text=msg)]

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
        body = censor_response(body, config)
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
