"""Shared test fixtures."""

import pytest

from bambuddy_mcp.config import Config


@pytest.fixture
def config():
    """Test configuration."""
    return Config(
        base_url="http://test.local:8000",
        api_key="test-key",
        direct_mode=False,
    )


@pytest.fixture
def sample_openapi_spec():
    """Minimal OpenAPI spec for testing."""
    return {
        "paths": {
            "/api/v1/items/{item_id}": {
                "get": {
                    "operationId": "get_item_api_v1_items__item_id__get",
                    "summary": "Get an item",
                    "tags": ["items"],
                    "parameters": [
                        {
                            "name": "item_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "include_details",
                            "in": "query",
                            "schema": {"type": "boolean"},
                        },
                    ],
                }
            }
        },
        "components": {"schemas": {}},
    }


@pytest.fixture
def sample_tool_defs():
    """Pre-parsed tool definitions for search tests."""
    return [
        {
            "name": "get_item",
            "description": "[items] GET /api/v1/items/{item_id}\nGet an item",
            "tag": "items",
            "input_schema": {},
        },
        {
            "name": "list_items",
            "description": "[items] GET /api/v1/items\nList all items",
            "tag": "items",
            "input_schema": {},
        },
        {
            "name": "get_user",
            "description": "[users] GET /api/v1/users/{user_id}\nGet user",
            "tag": "users",
            "input_schema": {},
        },
    ]
