"""Tool search functionality with fuzzy matching."""

import difflib


def search_tools(
    tool_defs: list[dict],
    query: str,
    category: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search tools by substring match on name + description, with fuzzy fallback."""
    candidates = tool_defs
    if category:
        cat_lower = category.lower()
        candidates = [t for t in candidates if t["tag"].lower() == cat_lower]

    query_lower = query.lower()

    # Substring match on name or description
    matches = [
        t
        for t in candidates
        if query_lower in t["name"].lower()
        or query_lower in t["description"].lower()
    ]

    # Fuzzy fallback if no substring matches
    if not matches:
        candidate_names = [t["name"] for t in candidates]
        fuzzy_names = difflib.get_close_matches(
            query_lower, candidate_names, n=limit, cutoff=0.4
        )
        fuzzy_set = set(fuzzy_names)
        matches = [t for t in candidates if t["name"] in fuzzy_set]

    return matches[:limit]
