"""Tests for HTTP execution."""

import os

import pytest
import respx
from httpx import Response

from bambuddy_mcp.config import Config
from bambuddy_mcp.http import build_url, execute_api_call, fetch_openapi_spec


class TestBuildUrl:
    def test_interpolates_path_params(self):
        url, remaining = build_url(
            "http://api.local",
            "/items/{item_id}/details/{detail_id}",
            {"item_id": "123", "detail_id": "456", "extra": "value"},
        )
        assert url == "http://api.local/items/123/details/456"
        assert remaining == {"extra": "value"}

    def test_no_path_params(self):
        url, remaining = build_url("http://api.local", "/items", {"limit": 10})
        assert url == "http://api.local/items"
        assert remaining == {"limit": 10}

    def test_empty_arguments(self):
        url, remaining = build_url("http://api.local", "/items/{id}", {})
        assert url == "http://api.local/items/{id}"  # unfilled
        assert remaining == {}


class TestExecuteApiCall:
    @pytest.fixture
    def config(self):
        return Config(base_url="http://test.local", api_key="key123", direct_mode=False)

    @pytest.fixture
    def tool_def(self):
        return {
            "name": "get_item",
            "path": "/items/{id}",
            "method": "get",
            "query_params": {"include"},
            "has_file_upload": False,
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_json_response(self, config, tool_def):
        respx.get("http://test.local/items/123").mock(
            return_value=Response(
                200,
                json={"id": "123", "name": "Test"},
                headers={"content-type": "application/json"},
            )
        )

        import httpx

        async with httpx.AsyncClient() as client:
            result = await execute_api_call(config, tool_def, {"id": "123"}, client)

        assert len(result) == 1
        assert result[0].type == "text"
        assert '"id": "123"' in result[0].text

    @pytest.mark.asyncio
    @respx.mock
    async def test_image_response_saves_to_file(self, config, tool_def):
        respx.get("http://test.local/items/123").mock(
            return_value=Response(
                200,
                content=b"\x89PNG\r\n",
                headers={"content-type": "image/png"},
            )
        )

        import httpx

        async with httpx.AsyncClient() as client:
            result = await execute_api_call(config, tool_def, {"id": "123"}, client)

        assert len(result) == 1
        assert result[0].type == "text"
        assert "Image saved to" in result[0].text
        assert ".png" in result[0].text
        # Clean up
        path = result[0].text.split("Image saved to ")[1].split(" ")[0]
        os.unlink(path)

    @pytest.mark.asyncio
    @respx.mock
    async def test_image_response_embed(self, config, tool_def):
        respx.get("http://test.local/items/123").mock(
            return_value=Response(
                200,
                content=b"\x89PNG\r\n",
                headers={"content-type": "image/png"},
            )
        )

        import httpx

        async with httpx.AsyncClient() as client:
            result = await execute_api_call(
                config, tool_def, {"id": "123"}, client, embed_image=True
            )

        assert len(result) == 1
        assert result[0].type == "image"
        assert result[0].mimeType == "image/png"

    @pytest.mark.asyncio
    @respx.mock
    async def test_error_response(self, config, tool_def):
        respx.get("http://test.local/items/123").mock(
            return_value=Response(
                404,
                text="Not found",
                headers={"content-type": "text/plain"},
            )
        )

        import httpx

        async with httpx.AsyncClient() as client:
            result = await execute_api_call(config, tool_def, {"id": "123"}, client)

        assert "HTTP 404 Error" in result[0].text

    @pytest.mark.asyncio
    @respx.mock
    async def test_api_key_header(self, config, tool_def):
        route = respx.get("http://test.local/items/123").mock(
            return_value=Response(
                200,
                json={},
                headers={"content-type": "application/json"},
            )
        )

        import httpx

        async with httpx.AsyncClient() as client:
            await execute_api_call(config, tool_def, {"id": "123"}, client)

        assert route.calls.last.request.headers["X-API-Key"] == "key123"

    @pytest.mark.asyncio
    @respx.mock
    async def test_query_params_sent_correctly(self, config, tool_def):
        respx.get("http://test.local/items/123").mock(
            return_value=Response(
                200,
                json={},
                headers={"content-type": "application/json"},
            )
        )

        import httpx

        async with httpx.AsyncClient() as client:
            await execute_api_call(
                config, tool_def, {"id": "123", "include": "details"}, client
            )

        url = str(respx.calls.last.request.url)
        assert "include=details" in url


class TestFetchOpenapiSpec:
    @pytest.mark.asyncio
    @respx.mock
    async def test_fetches_spec(self):
        expected_spec = {"openapi": "3.0.0", "paths": {}}
        respx.get("http://test.local/openapi.json").mock(
            return_value=Response(200, json=expected_spec)
        )

        import httpx

        async with httpx.AsyncClient() as client:
            result = await fetch_openapi_spec("http://test.local", client)

        assert result == expected_spec

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_on_error(self):
        respx.get("http://test.local/openapi.json").mock(
            return_value=Response(500, text="Server error")
        )

        import httpx

        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_openapi_spec("http://test.local", client)
