"""Tests for OpenAPI parsing."""

from bambuddy_mcp.openapi import (
    clean_tool_name,
    resolve_ref,
    resolve_schema,
    build_input_schema,
    parse_openapi_to_tools,
)


class TestCleanToolName:
    def test_strips_api_v1_suffix(self):
        assert (
            clean_tool_name("get_printer_api_v1_printers__printer_id__get")
            == "get_printer"
        )

    def test_strips_method_suffix(self):
        assert clean_tool_name("create_item_post") == "create_item"

    def test_simple_name_unchanged(self):
        assert clean_tool_name("get_status") == "get_status"

    def test_preserves_underscores_in_name(self):
        assert (
            clean_tool_name("get_print_job_api_v1_jobs__job_id__get") == "get_print_job"
        )


class TestResolveRef:
    def test_resolves_component_schema(self):
        spec = {"components": {"schemas": {"Item": {"type": "object"}}}}
        result = resolve_ref("#/components/schemas/Item", spec)
        assert result == {"type": "object"}

    def test_resolves_nested_path(self):
        spec = {"components": {"schemas": {"models": {"Item": {"type": "string"}}}}}
        result = resolve_ref("#/components/schemas/models/Item", spec)
        assert result == {"type": "string"}


class TestResolveSchema:
    def test_resolves_ref(self):
        spec = {
            "components": {"schemas": {"Item": {"type": "object", "properties": {}}}}
        }
        schema = {"$ref": "#/components/schemas/Item"}
        result = resolve_schema(schema, spec)
        assert result["type"] == "object"

    def test_depth_limit(self):
        """Prevents infinite recursion on circular refs."""
        spec = {"components": {"schemas": {"A": {"$ref": "#/components/schemas/A"}}}}
        schema = {"$ref": "#/components/schemas/A"}
        # Should not raise, returns partial result due to depth limit
        result = resolve_schema(schema, spec, depth=3)
        assert "$ref" in result

    def test_anyof_simplification(self):
        """anyOf with single non-null type is simplified."""
        spec = {}
        schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        result = resolve_schema(schema, spec)
        assert result.get("type") == "string"
        assert "anyOf" not in result

    def test_anyof_multiple_types_preserved(self):
        """anyOf with multiple non-null types is preserved."""
        spec = {}
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
        result = resolve_schema(schema, spec)
        assert "anyOf" in result
        assert len(result["anyOf"]) == 2

    def test_allof_merged(self):
        """allOf schemas are merged (shallow - later overwrites earlier)."""
        spec = {}
        schema = {
            "allOf": [
                {"type": "object"},
                {"properties": {"b": {"type": "integer"}}},
            ]
        }
        result = resolve_schema(schema, spec)
        assert result.get("type") == "object"
        assert "b" in result.get("properties", {})


class TestBuildInputSchema:
    def test_path_params(self, sample_openapi_spec):
        operation = sample_openapi_spec["paths"]["/api/v1/items/{item_id}"]["get"]
        schema, query_params = build_input_schema(
            "/api/v1/items/{item_id}", "get", operation, sample_openapi_spec
        )

        assert "item_id" in schema["properties"]
        assert "item_id" in schema.get("required", [])
        assert "include_details" in query_params

    def test_query_params_tracked(self, sample_openapi_spec):
        operation = sample_openapi_spec["paths"]["/api/v1/items/{item_id}"]["get"]
        schema, query_params = build_input_schema(
            "/api/v1/items/{item_id}", "get", operation, sample_openapi_spec
        )

        assert "include_details" in query_params
        assert "item_id" not in query_params  # path param, not query

    def test_json_body_merged(self):
        spec = {"components": {"schemas": {}}}
        operation = {
            "parameters": [],
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "count": {"type": "integer"},
                            },
                            "required": ["name"],
                        }
                    }
                }
            },
        }
        schema, query_params = build_input_schema("/items", "post", operation, spec)

        assert "name" in schema["properties"]
        assert "count" in schema["properties"]
        assert "name" in schema.get("required", [])


class TestParseOpenapiToTools:
    def test_generates_tool_definitions(self, sample_openapi_spec):
        tools = parse_openapi_to_tools(sample_openapi_spec)

        assert len(tools) == 1
        assert tools[0]["name"] == "get_item"
        assert tools[0]["method"] == "get"
        assert tools[0]["path"] == "/api/v1/items/{item_id}"

    def test_handles_duplicate_names(self):
        """Duplicate tool names get numbered suffixes."""
        spec = {
            "paths": {
                "/a": {"get": {"operationId": "get_item_api_v1_a_get", "tags": [""]}},
                "/b": {"get": {"operationId": "get_item_api_v1_b_get", "tags": [""]}},
            },
            "components": {"schemas": {}},
        }
        tools = parse_openapi_to_tools(spec)
        names = [t["name"] for t in tools]
        assert "get_item" in names
        assert "get_item_1" in names

    def test_extracts_tag(self, sample_openapi_spec):
        tools = parse_openapi_to_tools(sample_openapi_spec)
        assert tools[0]["tag"] == "items"

    def test_detects_file_upload(self):
        spec = {
            "paths": {
                "/upload": {
                    "post": {
                        "operationId": "upload_file_post",
                        "tags": ["uploads"],
                        "requestBody": {
                            "content": {
                                "multipart/form-data": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "file": {
                                                "type": "string",
                                                "format": "binary",
                                            }
                                        },
                                    }
                                }
                            }
                        },
                    }
                }
            },
            "components": {"schemas": {}},
        }
        tools = parse_openapi_to_tools(spec)
        assert tools[0]["has_file_upload"] is True
