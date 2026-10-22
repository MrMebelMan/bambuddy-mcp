"""Tests for the MCP server wiring (in-process client)."""

import importlib.metadata
import json
from dataclasses import replace

import httpx
import pytest
import respx
from httpx import Response
from mcp import Client

from bambuddy_mcp.openapi import parse_openapi_to_tools
from bambuddy_mcp.server import build_server

BASE = "http://test.local:8000"


@pytest.fixture
def tool_defs():
    spec = {
        "paths": {
            "/api/v1/printers/": {
                "get": {
                    "operationId": "list_printers_api_v1_printers__get",
                    "summary": "List printers",
                    "tags": ["printers"],
                }
            },
            "/api/v1/printers/{printer_id}": {
                "get": {
                    "operationId": "get_printer_api_v1_printers__printer_id__get",
                    "summary": "Get printer",
                    "tags": ["printers"],
                    "parameters": [
                        {
                            "name": "printer_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                }
            },
        },
        "components": {"schemas": {}},
    }
    return parse_openapi_to_tools(spec)


PRINTERS = [{"id": 1, "name": "X1C", "serial_number": "SECRET123", "model": "X1C"}]


def _json(result):
    assert not result.is_error
    return json.loads(result.content[0].text)


class TestProxyMode:
    async def test_server_info_version(self, config, tool_defs):
        async with Client(build_server(config, tool_defs)) as client:
            assert client.server_info.name == "bambuddy"
            assert client.server_info.version == importlib.metadata.version(
                "bambuddy-mcp"
            )

    async def test_lists_meta_tools(self, config, tool_defs):
        async with Client(build_server(config, tool_defs)) as client:
            result = await client.list_tools()
        names = [t.name for t in result.tools]
        assert names == [
            "list_categories",
            "search_tools",
            "execute_tool",
            "find_printer",
        ]
        execute = result.tools[2]
        assert execute.input_schema["required"] == ["name"]
        assert "access_code, serial_number" in execute.description

    async def test_list_categories(self, config, tool_defs):
        async with Client(build_server(config, tool_defs)) as client:
            result = await client.call_tool("list_categories", {})
        assert _json(result) == {"total_tools": 2, "categories": ["printers"]}

    async def test_search_tools(self, config, tool_defs):
        async with Client(build_server(config, tool_defs)) as client:
            result = await client.call_tool("search_tools", {"query": "get_printer"})
        found = _json(result)
        assert found[0]["name"] == "get_printer"
        assert "printer_id" in found[0]["input_schema"]["properties"]

    @respx.mock
    async def test_execute_tool_censors(self, config, tool_defs):
        route = respx.get(f"{BASE}/api/v1/printers/1").mock(
            return_value=Response(200, json=PRINTERS[0])
        )
        async with Client(build_server(config, tool_defs)) as client:
            result = await client.call_tool(
                "execute_tool",
                {"name": "get_printer", "arguments": {"printer_id": 1}},
            )
        assert route.called
        assert route.calls[0].request.headers["X-API-Key"] == "test-key"
        assert _json(result)["serial_number"] == "SE*****23"

    async def test_execute_unknown_tool(self, config, tool_defs):
        async with Client(build_server(config, tool_defs)) as client:
            result = await client.call_tool("execute_tool", {"name": "nope"})
        assert not result.is_error
        assert result.content[0].text.startswith("Unknown tool: nope")

    @respx.mock
    async def test_find_printer(self, config, tool_defs):
        respx.get(f"{BASE}/api/v1/printers/").mock(
            return_value=Response(200, json=PRINTERS)
        )
        async with Client(build_server(config, tool_defs)) as client:
            result = await client.call_tool("find_printer", {"name": "x1"})
        assert _json(result)["printers"] == [{"id": 1, "name": "X1C", "model": "X1C"}]

    async def test_unknown_meta_tool(self, config, tool_defs):
        async with Client(build_server(config, tool_defs)) as client:
            result = await client.call_tool("bogus", {})
        assert result.content[0].text == "Unknown meta-tool: bogus"

    @respx.mock
    async def test_http_failure_is_error_result(self, config, tool_defs):
        respx.get(f"{BASE}/api/v1/printers/").mock(
            side_effect=httpx.ConnectError("boom")
        )
        async with Client(build_server(config, tool_defs)) as client:
            result = await client.call_tool("execute_tool", {"name": "list_printers"})
        assert result.is_error
        assert "boom" in result.content[0].text


class TestDirectMode:
    @pytest.fixture
    def direct_config(self, config):
        return replace(config, direct_mode=True)

    async def test_lists_spec_tools(self, direct_config, tool_defs):
        async with Client(build_server(direct_config, tool_defs)) as client:
            result = await client.list_tools()
        assert [t.name for t in result.tools] == ["list_printers", "get_printer"]
        assert result.tools[1].input_schema == tool_defs[1]["input_schema"]

    @respx.mock
    async def test_call_spec_tool(self, direct_config, tool_defs):
        respx.get(f"{BASE}/api/v1/printers/1").mock(
            return_value=Response(200, json=PRINTERS[0])
        )
        async with Client(build_server(direct_config, tool_defs)) as client:
            result = await client.call_tool("get_printer", {"printer_id": 1})
        assert _json(result)["name"] == "X1C"

    async def test_unknown_tool(self, direct_config, tool_defs):
        async with Client(build_server(direct_config, tool_defs)) as client:
            result = await client.call_tool("nope", {})
        assert result.content[0].text == "Unknown tool: nope"
