#!/usr/bin/env python3
"""
Generate MCP tool wrappers from a SpeedPy OpenAPI schema.

Reads an OpenAPI 3.0 YAML/JSON schema and emits Python code that registers
FastMCP tools backed by the ``_api_get`` helper from ``speedpy_mcp.py``.

Usage:
    # Generate from a local schema file:
    uv run python manage.py spectacular --file /tmp/speedpy-openapi.yaml --validate
    python examples/mcp_server/generate_mcp_tools.py /tmp/speedpy-openapi.yaml

    # Write to the checked-in generated file:
    python examples/mcp_server/generate_mcp_tools.py /tmp/speedpy-openapi.yaml \
        -o examples/mcp_server/generated_tools.py

    # Check mode — fail if the generated output differs (CI):
    python examples/mcp_server/generate_mcp_tools.py /tmp/speedpy-openapi.yaml \
        -o examples/mcp_server/generated_tools.py --check

    # Filter by tag:
    python examples/mcp_server/generate_mcp_tools.py /tmp/speedpy-openapi.yaml \
        --tags teams,products

    # Filter by operation ID:
    python examples/mcp_server/generate_mcp_tools.py /tmp/speedpy-openapi.yaml \
        --operations listTeams,getTeam,listTeamMembers

Only GET endpoints are generated. Use ``--unsafe`` to see which write
operations were skipped (they require manual implementation).
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

import json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CAMEL_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE_2 = re.compile(r"([a-z0-9])([A-Z])")


def _camel_to_snake(name: str) -> str:
    s = _CAMEL_RE_1.sub(r"\1_\2", name)
    return _CAMEL_RE_2.sub(r"\1_\2", s).lower()


_PY_TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
}


def _openapi_type_to_python(schema: dict) -> str:
    return _PY_TYPE_MAP.get(schema.get("type", "string"), "str")


def _extract_scopes(security: list[dict]) -> list[str]:
    """Pull OAuth2 scopes from a security requirement list."""
    scopes: list[str] = []
    for entry in security:
        for scheme, scope_list in entry.items():
            if scheme == "oauth2" and scope_list:
                scopes.extend(scope_list)
    return sorted(set(scopes))


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------


def load_schema(path: str) -> dict:
    """Load an OpenAPI schema from a YAML or JSON file."""
    text = Path(path).read_text()
    if path.endswith((".yaml", ".yml")):
        if yaml is None:
            print(
                "ERROR: PyYAML is required for YAML schemas. "
                "Install with: pip install pyyaml",
                file=sys.stderr,
            )
            sys.exit(1)
        return yaml.safe_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if yaml is not None:
            return yaml.safe_load(text)
        raise


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

_HEADER = '''\
"""
Auto-generated MCP tool wrappers from SpeedPy OpenAPI schema.

DO NOT EDIT — regenerate with:
    python examples/mcp_server/generate_mcp_tools.py <schema> -o <this-file>

Depends on ``speedpy_mcp.mcp`` (FastMCP instance) and ``speedpy_mcp._api_get``.
"""

from __future__ import annotations

from speedpy_mcp import _api_get, mcp
'''


def generate_tool_code(
    schema: dict,
    *,
    tags: set[str] | None = None,
    operations: set[str] | None = None,
    unsafe: bool = False,
) -> str:
    """Return Python source code registering MCP tools for matching operations."""

    paths: dict = schema.get("paths", {})
    seen_names: dict[str, str] = {}  # snake_name -> operationId
    blocks: list[str] = []

    for path, methods in sorted(paths.items()):
        for method, op in sorted(methods.items()):
            if not isinstance(op, dict):
                continue

            operation_id = op.get("operationId")
            if not operation_id:
                continue

            # --- filters ---
            op_tags = op.get("tags", [])

            if tags and not set(op_tags) & tags:
                continue
            if operations and operation_id not in operations:
                continue

            is_safe = method.lower() == "get"
            if not is_safe:
                if unsafe:
                    print(
                        f"WARNING: skipping {method.upper()} {path} "
                        f"({operation_id}) — write operations require "
                        f"manual implementation.",
                        file=sys.stderr,
                    )
                continue

            # --- tool name ---
            tool_name = _camel_to_snake(operation_id)

            if tool_name in seen_names:
                print(
                    f"ERROR: tool name collision — {operation_id!r} and "
                    f"{seen_names[tool_name]!r} both produce {tool_name!r}",
                    file=sys.stderr,
                )
                sys.exit(1)
            seen_names[tool_name] = operation_id

            # --- parameters ---
            params = op.get("parameters", [])
            path_params = [p for p in params if p.get("in") == "path"]
            query_params = [p for p in params if p.get("in") == "query"]

            # Build function signature
            func_params: list[str] = []
            for p in path_params:
                py_type = _openapi_type_to_python(p.get("schema", {}))
                func_params.append(f"{p['name']}: {py_type}")
            for p in query_params:
                py_type = _openapi_type_to_python(p.get("schema", {}))
                if not p.get("required", False):
                    func_params.append(f"{p['name']}: {py_type} | None = None")
                else:
                    func_params.append(f"{p['name']}: {py_type}")

            sig = ", ".join(func_params)

            # --- docstring ---
            summary = op.get("summary", "")
            description = op.get("description", "")
            scopes = _extract_scopes(op.get("security", []))

            doc_parts = []
            if summary:
                doc_parts.append(summary)
            if description and description != summary:
                doc_parts.append("")
                # Wrap long descriptions
                for line in description.splitlines():
                    doc_parts.extend(textwrap.wrap(line, 72) or [""])

            # Args section
            if path_params or query_params:
                doc_parts.append("")
                doc_parts.append("Args:")
                for p in path_params + query_params:
                    p_desc = p.get("description", "")
                    required = p.get("required", False)
                    suffix = "" if required else " (optional)"
                    doc_parts.append(f"    {p['name']}: {p_desc}{suffix}")

            doc_parts.append("")
            doc_parts.append(f"Endpoint: {method.upper()} {path}")
            if scopes:
                doc_parts.append(f"Requires scope: {', '.join(scopes)}")

            docstring = "\n    ".join(doc_parts)

            # --- function body ---
            # Build the URL path with f-string substitution
            url_path = path
            for p in path_params:
                url_path = url_path.replace(
                    "{" + p["name"] + "}", "{" + p["name"] + "}"
                )

            # Query string handling
            has_query = bool(query_params)
            body_lines = []

            if has_query:
                body_lines.append("    params = {}")
                for p in query_params:
                    if p.get("required", False):
                        body_lines.append(
                            f"    params[{p['name']!r}] = {p['name']}"
                        )
                    else:
                        body_lines.append(
                            f"    if {p['name']} is not None:"
                        )
                        body_lines.append(
                            f"        params[{p['name']!r}] = {p['name']}"
                        )
                # Build query string
                body_lines.append(
                    '    qs = "&".join(f"{k}={v}" for k, v in params.items())'
                )
                if path_params:
                    body_lines.append(
                        f'    url = f"{url_path}"'
                    )
                else:
                    body_lines.append(f'    url = "{url_path}"')
                body_lines.append(
                    '    return _api_get(f"{url}?{qs}") if qs else _api_get(url)'
                )
            else:
                if path_params:
                    body_lines.append(f'    return _api_get(f"{url_path}")')
                else:
                    body_lines.append(f'    return _api_get("{url_path}")')

            body = "\n".join(body_lines)

            block = f'''
@mcp.tool()
def {tool_name}({sig}) -> dict:
    """{docstring}
    """
{body}
'''
            blocks.append(block)

    return _HEADER + "\n".join(blocks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate MCP tool wrappers from an OpenAPI schema.",
    )
    parser.add_argument("schema", help="Path to OpenAPI YAML/JSON schema file.")
    parser.add_argument(
        "-o",
        "--output",
        help="Write generated code to this file (default: stdout).",
    )
    parser.add_argument(
        "--tags",
        help="Comma-separated list of tags to include (default: all).",
    )
    parser.add_argument(
        "--operations",
        help="Comma-separated list of operation IDs to include (default: all).",
    )
    parser.add_argument(
        "--unsafe",
        action="store_true",
        help="Show skipped non-GET operations (they require manual implementation).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check mode: fail if the generated output differs from -o file.",
    )

    args = parser.parse_args()

    schema = load_schema(args.schema)
    tag_set = set(args.tags.split(",")) if args.tags else None
    op_set = set(args.operations.split(",")) if args.operations else None

    code = generate_tool_code(
        schema, tags=tag_set, operations=op_set, unsafe=args.unsafe
    )

    if args.output:
        output_path = Path(args.output)

        if args.check:
            if not output_path.exists():
                print(
                    f"CHECK FAILED: {args.output} does not exist.",
                    file=sys.stderr,
                )
                sys.exit(1)
            existing = output_path.read_text()
            if existing != code:
                print(
                    f"CHECK FAILED: {args.output} is stale. "
                    "Regenerate with:\n"
                    f"  python {__file__} {args.schema} -o {args.output}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"OK: {args.output} is up to date.", file=sys.stderr)
        else:
            output_path.write_text(code)
            print(f"Wrote {args.output}", file=sys.stderr)
    else:
        if args.check:
            print("ERROR: --check requires -o/--output.", file=sys.stderr)
            sys.exit(1)
        sys.stdout.write(code)


if __name__ == "__main__":
    main()
