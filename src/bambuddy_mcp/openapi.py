"""OpenAPI to MCP tool conversion functions."""

import re


def clean_tool_name(operation_id: str) -> str:
    """Convert FastAPI operation IDs to readable tool names.

    FastAPI generates IDs like 'get_printer_api_v1_printers__printer_id__get'.
    We strip the 'api_v1_..._method' suffix and keep the semantic prefix.
    """
    name = re.sub(r"_(get|post|put|patch|delete)$", "", operation_id)
    match = re.match(r"^(.+?)_api_v1_", name)
    if match:
        name = match.group(1)
    return name


def resolve_ref(ref: str, spec: dict) -> dict:
    """Resolve a $ref pointer like '#/components/schemas/Foo'."""
    parts = ref.lstrip("#/").split("/")
    node = spec
    for part in parts:
        node = node[part]
    return node


def resolve_schema(schema: dict, spec: dict, depth: int = 0) -> dict:
    """Recursively resolve $ref in a schema, up to a depth limit."""
    if depth > 3:
        return schema
    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        resolved = resolve_ref(schema["$ref"], spec)
        return resolve_schema(resolved, spec, depth + 1)

    result = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            result[key] = {
                k: resolve_schema(v, spec, depth + 1) for k, v in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            result[key] = resolve_schema(value, spec, depth + 1)
        elif key == "anyOf" and isinstance(value, list):
            non_null = [v for v in value if v != {"type": "null"}]
            if len(non_null) == 1:
                result.update(resolve_schema(non_null[0], spec, depth + 1))
            else:
                result[key] = [resolve_schema(v, spec, depth + 1) for v in value]
        elif key == "allOf" and isinstance(value, list):
            for item in value:
                result.update(resolve_schema(item, spec, depth + 1))
        else:
            result[key] = value

    return result


def build_input_schema(
    path: str, method: str, operation: dict, spec: dict
) -> tuple[dict, set[str]]:
    """Build a JSON Schema for the tool's input from OpenAPI parameters + body.

    Returns (input_schema, query_param_names) so the executor knows which
    parameters should be sent as query params vs JSON body.
    """
    properties: dict = {}
    required: list[str] = []
    query_param_names: set[str] = set()

    for param in operation.get("parameters", []):
        if param.get("in") == "header":
            continue
        name = param["name"]
        schema = resolve_schema(param.get("schema", {}), spec)
        schema.pop("title", None)
        properties[name] = schema
        if param.get("required"):
            required.append(name)
        if param.get("in") == "query":
            query_param_names.add(name)

    body = operation.get("requestBody", {})
    body_content = body.get("content", {})

    if "application/json" in body_content:
        body_schema = body_content["application/json"].get("schema", {})
        resolved = resolve_schema(body_schema, spec)
        if resolved.get("type") == "object" and "properties" in resolved:
            for prop_name, prop_schema in resolved["properties"].items():
                prop_schema.pop("title", None)
                properties[prop_name] = prop_schema
            required.extend(resolved.get("required", []))
        elif resolved:
            properties["body"] = resolved

    elif "multipart/form-data" in body_content:
        body_schema = body_content["multipart/form-data"].get("schema", {})
        resolved = resolve_schema(body_schema, spec)
        if resolved.get("type") == "object" and "properties" in resolved:
            for prop_name, prop_schema in resolved["properties"].items():
                prop_schema.pop("title", None)
                if prop_schema.get("format") == "binary":
                    prop_schema = {
                        "type": "string",
                        "description": "File path to upload",
                    }
                properties[prop_name] = prop_schema
            required.extend(resolved.get("required", []))

    input_schema: dict = {"type": "object", "properties": properties}
    if required:
        input_schema["required"] = list(dict.fromkeys(required))
    return input_schema, query_param_names


def build_tool_description(path: str, method: str, operation: dict) -> str:
    """Build a description from the OpenAPI operation."""
    parts = []
    summary = operation.get("summary", "")
    description = operation.get("description", "")
    tag = operation.get("tags", [""])[0]

    parts.append(f"[{tag}] {method.upper()} {path}")
    if summary:
        parts.append(summary)
    if description and description != summary:
        parts.append(description)
    return "\n".join(parts)


def parse_openapi_to_tools(spec: dict) -> list[dict]:
    """Parse an OpenAPI spec into a list of tool definitions."""
    tools = []
    seen_names: dict[str, int] = {}

    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue

            operation_id = operation.get("operationId", f"{method}_{path}")
            name = clean_tool_name(operation_id)

            if name in seen_names:
                seen_names[name] += 1
                name = f"{name}_{seen_names[name]}"
            else:
                seen_names[name] = 0

            input_schema, query_param_names = build_input_schema(
                path, method, operation, spec
            )

            tools.append(
                {
                    "name": name,
                    "description": build_tool_description(path, method, operation),
                    "input_schema": input_schema,
                    "query_params": query_param_names,
                    "path": path,
                    "method": method,
                    "tag": operation.get("tags", [""])[0],
                    "has_file_upload": "multipart/form-data"
                    in operation.get("requestBody", {}).get("content", {}),
                }
            )

    return tools
