"""Shared utilities for Generator and Critique ReAct agent services.

Centralising these helpers eliminates the duplication that existed between
generator_agent.py and critique_agent.py, and provides a single uniform
adapter for tool dispatch (fixing the inconsistent sync/async calling
convention).
"""

from __future__ import annotations

import asyncio
from typing import Any

from anthropic.types import Message


def extract_text(message: Message) -> str:
    """Return the text of the first TextBlock in a Claude response.

    Extended-thinking responses may contain ThinkingBlock entries before the
    final TextBlock — this function skips non-text blocks automatically.
    """
    for block in message.content:
        if hasattr(block, "text"):
            return block.text
    return ""


def serialize_content(content: Any) -> Any:
    """Convert Anthropic SDK content blocks to JSON-serialisable dicts.

    Required before appending assistant turns to an AgentSession: the SDK
    returns typed dataclasses (TextBlock, ToolUseBlock, ThinkingBlock) that
    are not directly JSON-serialisable.  Preserving thinking blocks is
    necessary for extended-thinking API continuity.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return [
            block.model_dump() if hasattr(block, "model_dump") else block
            for block in content
        ]
    return content


async def call_handler(handler: Any, input_dict: dict[str, Any]) -> Any:
    """Invoke a tool handler uniformly, regardless of sync/async type.

    Convention (before this fix):
      - Sync handlers:  handler(dict(block.input))           — positional dict
      - Async handlers: await handler(**dict(block.input))   — keyword unpack

    This asymmetry was a footgun for anyone adding new tools. This adapter
    provides a single call site for both cases:

      result = await call_handler(handler, dict(block.input))

    Async handlers receive keyword arguments (the long-standing contract for
    episodic memory tools). Sync handlers receive the full input dict (the
    long-standing contract for common document tools and submit_critique).
    """
    if asyncio.iscoroutinefunction(handler):
        return await handler(**input_dict)
    return handler(input_dict)
