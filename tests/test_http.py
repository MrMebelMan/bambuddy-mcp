"""Tests for HTTP execution."""

import os

import pytest
import respx
from httpx import Response

from bambuddy_mcp.config import Config
from bambuddy_mcp.http import (
    build_url,
    censor_response,
    execute_api_call,
    fetch_openapi_spec,
)


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
        return Config(
            base_url="http://test.local",
            api_key="key123",
            direct_mode=False,
            censor_access_code=True,
            censor_serial=True,
            censor_model_filename=False,
        )

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
    async def test_image_embed_blocked_by_filename_censoring(self, tool_def):
        cfg = Config(
            base_url="http://test.local",
            api_key="key123",
            direct_mode=False,
            censor_access_code=True,
            censor_serial=True,
            censor_model_filename=True,
        )
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
                cfg, tool_def, {"id": "123"}, client, embed_image=True
            )

        assert result[0].type == "text"
        assert "Image saved to" in result[0].text
        assert "BAMBUDDY_CENSOR_MODEL_FILENAME" in result[0].text
        # Clean up
        path = result[0].text.split("Image saved to ")[1].split(" ")[0]
        os.unlink(path)

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


class TestCensorResponse:
    @pytest.fixture
    def all_on(self):
        return Config(
            base_url="http://test.local",
            api_key="",
            direct_mode=False,
            censor_access_code=True,
            censor_serial=True,
            censor_model_filename=True,
        )

    @pytest.fixture
    def all_off(self):
        return Config(
            base_url="http://test.local",
            api_key="",
            direct_mode=False,
            censor_access_code=False,
            censor_serial=False,
            censor_model_filename=False,
        )

    @pytest.fixture
    def tool_def(self):
        return {
            "name": "get_item",
            "path": "/items/{id}",
            "method": "get",
            "query_params": set(),
            "has_file_upload": False,
        }

    def test_masks_serial_number(self, all_on):
        data = {"serial_number": "01S1234579", "name": "BOT717"}
        result = censor_response(data, all_on)
        assert result["serial_number"] == "01******79"
        assert result["name"] == "BOT717"

    def test_serial_disabled(self, all_off):
        data = {"serial_number": "01S1234579"}
        assert censor_response(data, all_off)["serial_number"] == "01S1234579"

    def test_masks_access_code(self, all_on):
        data = {"access_code": "mysecret", "id": 1}
        result = censor_response(data, all_on)
        assert result["access_code"] == "********"
        assert result["id"] == 1

    def test_access_code_disabled(self, all_off):
        data = {"access_code": "mysecret"}
        assert censor_response(data, all_off)["access_code"] == "mysecret"

    def test_short_serial_fully_masked(self, all_on):
        data = {"serial_number": "AB"}
        assert censor_response(data, all_on)["serial_number"] == "**"

    def test_four_char_serial(self, all_on):
        data = {"serial_number": "ABCD"}
        assert censor_response(data, all_on)["serial_number"] == "****"

    def test_recursive_list(self, all_on):
        data = [
            {"serial_number": "01S1234579", "name": "P1"},
            {"serial_number": "99X9876543", "name": "P2"},
        ]
        result = censor_response(data, all_on)
        assert result[0]["serial_number"] == "01******79"
        assert result[1]["serial_number"] == "99******43"

    def test_nested_dict(self, all_on):
        data = {"printer": {"serial_number": "01S1234579"}}
        assert censor_response(data, all_on)["printer"]["serial_number"] == "01******79"

    def test_no_sensitive_fields_unchanged(self, all_on):
        data = {"id": 1, "name": "test", "model": "X1C"}
        assert censor_response(data, all_on) == data

    def test_non_string_values_unchanged(self, all_on):
        data = {"serial_number": 12345}
        assert censor_response(data, all_on)["serial_number"] == 12345

    def test_model_filename_gcode_3mf(self, all_on):
        data = {"subtask_name": "Sextoy_Biggus_Dickus.gcode.3mf"}
        result = censor_response(data, all_on)
        assert result["subtask_name"] == "Se****************us.gcode.3mf"

    def test_model_filename_3mf(self, all_on):
        data = {"file": "MyModel.3mf"}
        result = censor_response(data, all_on)
        assert result["file"] == "My***el.3mf"

    def test_model_filename_gcode(self, all_on):
        data = {"name": "benchy.gcode"}
        result = censor_response(data, all_on)
        assert result["name"] == "be**hy.gcode"

    def test_model_filename_disabled(self, all_off):
        data = {"subtask_name": "Sextoy_Biggus_Dickus.gcode.3mf"}
        result = censor_response(data, all_off)
        assert result["subtask_name"] == "Sextoy_Biggus_Dickus.gcode.3mf"

    def test_model_filename_in_list(self, all_on):
        data = ["test.gcode.3mf", "not_a_model"]
        result = censor_response(data, all_on)
        assert result[0] == "****.gcode.3mf"
        assert result[1] == "not_a_model"

    def test_non_model_string_unchanged(self, all_on):
        data = {"name": "BOT717", "state": "PRINTING"}
        assert censor_response(data, all_on) == data

    @pytest.mark.asyncio
    @respx.mock
    async def test_censoring_in_api_response(self, tool_def):
        cfg = Config(
            base_url="http://test.local",
            api_key="key123",
            direct_mode=False,
            censor_access_code=True,
            censor_serial=True,
            censor_model_filename=True,
        )
        respx.get("http://test.local/items/123").mock(
            return_value=Response(
                200,
                json={"serial_number": "01S1234579", "access_code": "secret"},
                headers={"content-type": "application/json"},
            )
        )

        import httpx

        async with httpx.AsyncClient() as client:
            result = await execute_api_call(cfg, tool_def, {"id": "123"}, client)

        assert "01******79" in result[0].text
        assert "secret" not in result[0].text

    @pytest.mark.asyncio
    @respx.mock
    async def test_censoring_all_disabled(self, tool_def):
        cfg = Config(
            base_url="http://test.local",
            api_key="key123",
            direct_mode=False,
            censor_access_code=False,
            censor_serial=False,
            censor_model_filename=False,
        )
        respx.get("http://test.local/items/123").mock(
            return_value=Response(
                200,
                json={"serial_number": "01S1234579", "access_code": "secret"},
                headers={"content-type": "application/json"},
            )
        )

        import httpx

        async with httpx.AsyncClient() as client:
            result = await execute_api_call(cfg, tool_def, {"id": "123"}, client)

        assert "01S1234579" in result[0].text
        assert "secret" in result[0].text
