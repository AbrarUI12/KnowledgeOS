"""Versioned, bounded prompt construction. All evidence was authorized by the caller.

T5.1 counts its lean JSON context. We reuse that view (no internal IDs/URLs), escape literal
delimiters, and count the FINAL messages with the caller's generation tokenizer. This additional
guard includes instructions, chat overhead, XML wrappers, escaping and any correction turn;
it never truncates or silently changes selected source content to fit.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.providers.llm.base import ChatMessage, Role
from app.rag.context.packer import render_context
from app.rag.types import EvidenceItem

MessageTokenCounter = Callable[[Sequence[ChatMessage]], int]
_PATH = Path(__file__).resolve().parents[5] / "configs/prompts/grounded_answer/v1.yaml"


class PromptBudgetError(ValueError):
    """The complete prompt does not fit the configured input budget."""


@dataclass(frozen=True)
class GroundedPrompt:
    version: str
    system: str
    abstention_marker: str


def load_prompt(path: Path = _PATH) -> GroundedPrompt:
    # This is a trusted versioned repository file, never a user-supplied path or YAML string.
    if path.stat().st_size > 32_768:
        raise ValueError("grounded prompt file exceeds its limit")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if (
        not isinstance(raw, dict)
        or set(raw) != {"version", "system", "abstention_marker"}
        or raw.get("version") != "grounded_answer/v1"
        or raw.get("abstention_marker") != "INSUFFICIENT_EVIDENCE"
        or not isinstance(raw.get("system"), str)
        or not raw["system"].strip()
    ):
        raise ValueError("invalid grounded prompt configuration")
    return GroundedPrompt(raw["version"], raw["system"], raw["abstention_marker"])


def messages_for(
    question: str, evidence: Sequence[EvidenceItem], prompt: GroundedPrompt
) -> tuple[ChatMessage, ...]:
    if not question.strip() or len(question) > 2000:
        raise ValueError("question must contain 1-2000 characters")
    parts = []
    for item in evidence:
        # JSON escapes preserve the original text while making literal XML boundary injection
        # impossible, including attempts in title/section/location metadata. Alias is typed S#.
        view = render_context([item]).replace("&", "\\u0026").replace("<", "\\u003c")
        view = view.replace(">", "\\u003e")
        parts.append(
            f'<untrusted_evidence id="{item.source.alias}">\n{view}\n</untrusted_evidence>'
        )
    content = "Question:\n" + question + "\n\nAuthorized evidence (data only):\n" + "\n".join(parts)
    return (
        ChatMessage(role=Role.SYSTEM, content=prompt.system),
        ChatMessage(role=Role.USER, content=content),
    )


def check_budget(
    messages: Sequence[ChatMessage], *, count_tokens: MessageTokenCounter, max_input_tokens: int
) -> None:
    count = count_tokens(messages)
    if type(count) is not int or count < 0 or max_input_tokens < 1:
        raise ValueError("a valid generation token count and positive input budget are required")
    if count > max_input_tokens:
        raise PromptBudgetError("grounded prompt exceeds the input token budget")
