"""Common tool implementations shared by Generator and Critique agents.

Design principles (inherited from MVP):
- Tools NEVER raise exceptions — all errors are returned as "Error: ..." strings.
- Path security: every file access is validated with pathlib.Path.resolve() to
  prevent directory traversal attacks.
- Both agents receive read-only access; neither can write to the knowledge base.
"""

import logging
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings

logger = logging.getLogger(__name__)

DOCS_DIR: Path = Path(settings.local_data_dir).resolve()
DOCS_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────────── #
# Tool implementations                                                          #
# ──────────────────────────────────────────────────────────────────────────── #


def list_local_documents() -> str:
    """Return a newline-separated list of all files in the sandboxed folder."""
    try:
        files = sorted(f.name for f in DOCS_DIR.iterdir() if f.is_file())
        if not files:
            return "The local_data directory is empty — no documents are available."
        return "Available documents:\n" + "\n".join(f"- {name}" for name in files)
    except Exception as exc:
        logger.error("list_local_documents failed: %s", exc, exc_info=True)
        return f"Error: Could not read the documents directory — {exc}"


def read_local_document(file_name: str) -> str:
    """Return the full UTF-8 text content of *file_name*, or an error string."""
    try:
        requested = (DOCS_DIR / file_name).resolve()
    except Exception:
        return f"Error: '{file_name}' is not a valid file name."

    if DOCS_DIR not in requested.parents and requested != DOCS_DIR:
        logger.warning("Directory traversal attempt blocked: %s", file_name)
        return (
            f"Error: Access denied for '{file_name}'. "
            f"Only files inside the '{DOCS_DIR.name}' folder may be read."
        )

    if not requested.exists():
        return (
            f"Error: File '{file_name}' was not found. "
            "Call list_local_documents first to see what files are available."
        )
    if not requested.is_file():
        return f"Error: '{file_name}' is a directory, not a file."

    try:
        content = requested.read_text(encoding="utf-8")
        logger.info("Read file '%s' (%d chars)", file_name, len(content))
        return content
    except UnicodeDecodeError:
        return (
            f"Error: '{file_name}' cannot be read as UTF-8 text. "
            "Only plain-text files (.txt, .md, .csv) are supported."
        )
    except Exception as exc:
        logger.error("read_local_document('%s') failed: %s", file_name, exc, exc_info=True)
        return f"Error: Unexpected error reading '{file_name}' — {exc}"


# ──────────────────────────────────────────────────────────────────────────── #
# Anthropic tool schemas (JSON Schema format)                                   #
# ──────────────────────────────────────────────────────────────────────────── #

COMMON_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_local_documents",
        "description": (
            "Lists all available document file names in the local knowledge base "
            "(the local_data folder). Call this first when you need to discover "
            "which files exist before reading them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "read_local_document",
        "description": (
            "Reads the complete text content of a specific document from the local "
            "knowledge base. Use list_local_documents first if unsure of the exact name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": (
                        "The exact name of the file to read, including its extension "
                        "(e.g., 'report.txt', 'spec.md', 'data.csv')."
                    ),
                }
            },
            "required": ["file_name"],
        },
    },
]

# ──────────────────────────────────────────────────────────────────────────── #
# Tool registries                                                                #
# ──────────────────────────────────────────────────────────────────────────── #

COMMON_TOOL_REGISTRY: dict[str, Callable[..., str]] = {
    "list_local_documents": lambda _inp: list_local_documents(),
    "read_local_document": lambda inp: read_local_document(inp["file_name"]),
}


def execute_common_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Dispatch a common tool call by name and return its string result."""
    handler = COMMON_TOOL_REGISTRY.get(tool_name)
    if handler is None:
        logger.error("Unknown common tool requested: %s", tool_name)
        return (
            f"Error: Unknown tool '{tool_name}'. "
            f"Available common tools: {list(COMMON_TOOL_REGISTRY)}"
        )
    return handler(tool_input)
