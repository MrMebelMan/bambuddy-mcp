"""Tests for the find_printer helper tool."""

import json

import pytest
import respx
from httpx import Response

from bambuddy_mcp.server import PRINTER_FIELDS, _find_printers


@pytest.fixture
def tool_map_with_printers():
    return {
        "list_printers": {
            "name": "list_printers",
            "path": "/api/v1/printers/",
            "method": "get",
            "query_params": set(),
            "has_file_upload": False,
        }
    }


@pytest.fixture
def sample_printers():
    return [
        {
            "id": 1,
            "name": "BOT717",
            "model": "X1C",
            "ip_address": "192.168.1.10",
            "is_active": True,
            "serial_number": "ABC123",
            "access_code": "secret",
        },
        {
            "id": 2,
            "name": "BOT100",
            "model": "P1S",
            "ip_address": "192.168.1.11",
            "is_active": False,
            "serial_number": "DEF456",
            "access_code": "secret2",
        },
        {
            "id": 3,
            "name": "MyPrinter",
            "model": "A1",
            "ip_address": "192.168.1.12",
            "is_active": True,
            "serial_number": "GHI789",
            "access_code": "secret3",
        },
    ]


class TestFindPrinters:
    @pytest.mark.asyncio
    @respx.mock
    async def test_exact_name_match(
        self, config, tool_map_with_printers, sample_printers
    ):
        respx.get("http://test.local:8000/api/v1/printers/").mock(
            return_value=Response(200, json=sample_printers)
        )
        result = await _find_printers("BOT717", config, tool_map_with_printers)
        data = json.loads(result[0].text)
        assert data["total_matches"] == 1
        assert data["printers"][0]["name"] == "BOT717"
        assert data["printers"][0]["id"] == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_case_insensitive(
        self, config, tool_map_with_printers, sample_printers
    ):
        respx.get("http://test.local:8000/api/v1/printers/").mock(
            return_value=Response(200, json=sample_printers)
        )
        result = await _find_printers("bot717", config, tool_map_with_printers)
        data = json.loads(result[0].text)
        assert data["total_matches"] == 1
        assert data["printers"][0]["name"] == "BOT717"

    @pytest.mark.asyncio
    @respx.mock
    async def test_substring_match(
        self, config, tool_map_with_printers, sample_printers
    ):
        respx.get("http://test.local:8000/api/v1/printers/").mock(
            return_value=Response(200, json=sample_printers)
        )
        result = await _find_printers("BOT", config, tool_map_with_printers)
        data = json.loads(result[0].text)
        assert data["total_matches"] == 2
        names = {p["name"] for p in data["printers"]}
        assert names == {"BOT717", "BOT100"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_matches(self, config, tool_map_with_printers, sample_printers):
        respx.get("http://test.local:8000/api/v1/printers/").mock(
            return_value=Response(200, json=sample_printers)
        )
        result = await _find_printers("NONEXISTENT", config, tool_map_with_printers)
        data = json.loads(result[0].text)
        assert data["total_matches"] == 0
        assert data["printers"] == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_essential_fields_only(
        self, config, tool_map_with_printers, sample_printers
    ):
        respx.get("http://test.local:8000/api/v1/printers/").mock(
            return_value=Response(200, json=sample_printers)
        )
        result = await _find_printers("BOT717", config, tool_map_with_printers)
        data = json.loads(result[0].text)
        printer = data["printers"][0]
        assert set(printer.keys()) == set(PRINTER_FIELDS)
        assert "serial_number" not in printer
        assert "access_code" not in printer

    @pytest.mark.asyncio
    async def test_missing_list_printers_tool(self, config):
        result = await _find_printers("BOT717", config, {})
        assert "none was found" in result[0].text

    @pytest.mark.asyncio
    @respx.mock
    async def test_http_error(self, config, tool_map_with_printers):
        respx.get("http://test.local:8000/api/v1/printers/").mock(
            return_value=Response(500, text="Internal Server Error")
        )
        result = await _find_printers("BOT717", config, tool_map_with_printers)
        assert "HTTP 500 Error" in result[0].text

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_api_key_header(self, config, tool_map_with_printers):
        route = respx.get("http://test.local:8000/api/v1/printers/").mock(
            return_value=Response(200, json=[])
        )
        await _find_printers("BOT717", config, tool_map_with_printers)
        assert route.calls.last.request.headers["X-API-Key"] == "test-key"

    @pytest.mark.asyncio
    @respx.mock
    async def test_handles_paginated_response(
        self, config, tool_map_with_printers, sample_printers
    ):
        respx.get("http://test.local:8000/api/v1/printers/").mock(
            return_value=Response(200, json={"data": sample_printers, "total": 3})
        )
        result = await _find_printers("BOT717", config, tool_map_with_printers)
        data = json.loads(result[0].text)
        assert data["total_matches"] == 1
        assert data["printers"][0]["name"] == "BOT717"
