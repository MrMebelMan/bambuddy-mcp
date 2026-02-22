"""Tests for tool search functionality."""

import pytest

from bambuddy_mcp.search import search_tools


class TestSearchTools:
    def test_substring_match_name(self, sample_tool_defs):
        results = search_tools(sample_tool_defs, "item")
        names = [r["name"] for r in results]
        assert "get_item" in names
        assert "list_items" in names

    def test_substring_match_description(self, sample_tool_defs):
        results = search_tools(sample_tool_defs, "List all")
        assert len(results) == 1
        assert results[0]["name"] == "list_items"

    def test_category_filter(self, sample_tool_defs):
        results = search_tools(sample_tool_defs, "get", category="users")
        assert len(results) == 1
        assert results[0]["name"] == "get_user"

    def test_category_filter_case_insensitive(self, sample_tool_defs):
        results = search_tools(sample_tool_defs, "get", category="USERS")
        assert len(results) == 1
        assert results[0]["name"] == "get_user"

    def test_fuzzy_fallback(self, sample_tool_defs):
        """Falls back to fuzzy matching when no substring match."""
        results = search_tools(sample_tool_defs, "gt_itm")  # typo
        # Should still find "get_item" via fuzzy match
        names = [r["name"] for r in results]
        assert "get_item" in names

    def test_limit(self, sample_tool_defs):
        results = search_tools(sample_tool_defs, "get", limit=1)
        assert len(results) == 1

    def test_empty_query_matches_all(self, sample_tool_defs):
        results = search_tools(sample_tool_defs, "")
        assert len(results) == 3

    def test_no_matches_returns_empty(self, sample_tool_defs):
        results = search_tools(sample_tool_defs, "xyznonexistent")
        assert len(results) == 0
