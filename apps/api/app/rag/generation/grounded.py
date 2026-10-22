"""DB-free grounded answer driver: pre/post abstention and at most one citation correction.

Authorization and calibrated thresholds belong to the caller/profile. A valid alias is NOT a
proof of semantic support. Invalid answers are never returned, even partially, to the client.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.providers.llm.base import ChatMessage, GenerationParams, LLMProvider, Role
from app.rag.citations.validator import validate_citations
from app.rag.generation.prompt import (
    GroundedPrompt,
    MessageTokenCounter,
    PromptBudgetError,
    check_budget,
    load_prompt,
    messages_for,
)
from app.rag.types import EvidenceItem, SourceAlias, Usage

ABSTENTION = "I don't have enough authorized evidence to answer this question."


@dataclass(frozen=True)
class GroundedAnswer:
    text: str
    citations: tuple[SourceAlias, ...] = ()
    abstained: bool = False
    abstain_reason: str | None = None
    closest_sources: tuple[SourceAlias, ...] = ()
    usage: Usage = field(default_factory=Usage)
    model: str | None = None
    provider: str | None = None
    correction_attempted: bool = False


def evidence_insufficient(
    evidence: Sequence[EvidenceItem], *, minimum_rerank_score: float | None
) -> str | None:
    if minimum_rerank_score is not None and not math.isfinite(minimum_rerank_score):
        raise ValueError("rerank threshold must be finite")
    scores = [item.rerank_score for item in evidence if item.rerank_score is not None]
    if any(not math.isfinite(score) for score in scores):
        raise ValueError("rerank scores must be finite")
    if not evidence:
        return "no_evidence"
    if minimum_rerank_score is not None and (not scores or max(scores) < minimum_rerank_score):
        return "insufficient_rerank_score"
    return None


def _sum_usage(first: Usage, second: Usage) -> Usage:
    if any(
        type(value) is not int or value < 0
        for value in (
            first.input_tokens,
            first.output_tokens,
            second.input_tokens,
            second.output_tokens,
        )
    ):
        raise ValueError("invalid generation accounting")
    return Usage(
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        estimated=first.estimated or second.estimated,
    )


async def generate_grounded(
    question: str,
    evidence: Sequence[EvidenceItem],
    *,
    provider: LLMProvider,
    count_tokens: MessageTokenCounter,
    max_input_tokens: int,
    minimum_rerank_score: float | None,
    params: GenerationParams | None = None,
    prompt: GroundedPrompt | None = None,
) -> GroundedAnswer:
    # Detach mutable EvidenceItem instances before any await; prompt and returned citations must
    # refer to exactly the same authorized source view, even if caller-owned inputs change.
    selected = tuple(item.model_copy(deep=True) for item in evidence)
    registry = validate_citations("", selected, abstained=True)
    if not registry.valid:
        raise ValueError("invalid selected evidence registry")
    closest = tuple(item.source for item in selected)
    reason = evidence_insufficient(selected, minimum_rerank_score=minimum_rerank_score)
    if reason is not None:
        return GroundedAnswer(
            text=ABSTENTION, abstained=True, abstain_reason=reason, closest_sources=closest
        )
    template = prompt or load_prompt()
    messages = messages_for(question, selected, template)
    check_budget(messages, count_tokens=count_tokens, max_input_tokens=max_input_tokens)
    usage = Usage()
    model = provider_id = None
    corrected = False
    for attempt in range(2):
        result = await provider.generate(messages, params)
        usage = _sum_usage(usage, result.usage)
        model, provider_id = result.model, result.provider
        reason = None
        if result.finish_reason == "length":
            reason = "generation_truncated"
        elif result.text.strip().startswith(template.abstention_marker):
            reason = "model_insufficient_evidence"
        else:
            validation = validate_citations(result.text, selected)
            if validation.valid:
                return GroundedAnswer(
                    text=result.text,
                    citations=validation.citations,
                    usage=usage,
                    model=model,
                    provider=provider_id,
                    correction_attempted=corrected,
                )
            reason = "invalid_citations"
        if reason != "invalid_citations" or attempt == 1:
            break
        messages = (
            *messages,
            ChatMessage(role=Role.ASSISTANT, content=result.text),
            ChatMessage(
                role=Role.USER,
                content=(
                    "Regenerate the answer from the same authorized evidence. Your previous answer "
                    "failed citation validation. Use only these exact source aliases: "
                    + ", ".join(item.source.alias for item in selected)
                    + ". Cite each factual paragraph with [S#] or [S#, S#]. Never invent metadata. "
                    "Do not include links, images, URLs, or raw HTML. "
                    "If unsupported, output exactly " + template.abstention_marker + "."
                ),
            ),
        )
        try:
            check_budget(messages, count_tokens=count_tokens, max_input_tokens=max_input_tokens)
        except PromptBudgetError:
            reason = "correction_budget_exceeded"
            break
        corrected = True
    return GroundedAnswer(
        text=ABSTENTION,
        abstained=True,
        abstain_reason=reason,
        closest_sources=closest,
        usage=usage,
        model=model,
        provider=provider_id,
        correction_attempted=corrected,
    )
