"""A minimal tool-calling model client.

Injected rather than imported so the policy is unit-testable with a scripted
fake. A test suite that needs a live model is slow, costs money, and turns a
network failure into a red build -- and none of that would be testing the
policy.

Reads its key at call time. An import-time environment read would be cached into
the pre-warmed pool workers and leak between cases, which the purity lint
forbids for exactly this reason.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol


class ModelUnavailable(Exception):
    """The model could not be reached or refused the request.

    Raised, never degraded into "the agent decided not to act" -- a network
    failure that reads as a policy decision would silently turn an inconclusive
    run into a clean one.
    """


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ModelReply:
    tool_calls: tuple[ToolCall, ...]
    text: str | None


class Model(Protocol):
    def reply(self, messages: list[dict], tools: list[dict]) -> ModelReply: ...


@dataclass(frozen=True)
class DeepSeek:
    """DeepSeek via its OpenAI-compatible endpoint.

    temperature=0 for reproducibility as far as the provider offers it. That is
    not determinism and is not claimed as such -- which is why the LLM arms run
    in Mode B, where frequency is the measurement, rather than in the scripted
    Mode A schedules.
    """

    model: str = "deepseek-chat"
    temperature: float = 0.0
    base_url: str = "https://api.deepseek.com"
    max_tokens: int = 512

    def reply(self, messages: list[dict], tools: list[dict]) -> ModelReply:
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise ModelUnavailable("DEEPSEEK_API_KEY is not set")

        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=self.base_url)
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except Exception as exc:
            raise ModelUnavailable(f"{type(exc).__name__}: {exc}") from exc

        message = response.choices[0].message
        calls = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                # Malformed arguments are a real model failure mode. Surfaced,
                # not coerced into an empty dict, which would silently become a
                # call with default arguments.
                raise ModelUnavailable(
                    f"model emitted invalid tool arguments: {call.function.arguments!r}"
                ) from exc
            calls.append(
                ToolCall(id=call.id, name=call.function.name, arguments=arguments)
            )
        return ModelReply(tool_calls=tuple(calls), text=message.content)
