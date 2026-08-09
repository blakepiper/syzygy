"""Running the evaluation, and scoring it (M16.3b/c).

Deliberately *not* built on `LlamaCppProvider`. The provider hides exactly
what the harness needs to measure - whether the first reply was
schema-valid, whether the repair turn fired, how many tokens the server
generated and how fast. So this speaks the same HTTP the provider does,
using the same prompts and the same `structured_output` validation, and
records what happens at each step.

Scoring is two-layered, and the layers are not mixed:

* **Automatic checks** - schema validity, repair, truncation, latency,
  required facts present, forbidden strings absent, and how distinct the
  two registers are. These are reproducible and are what the release gate
  actually tests.
* **Manual rubric slots** - factual fidelity and usable prose, scored by a
  person on a 1-5 scale and recorded alongside. A number a program made up
  for "is this prose any good" would be worse than an empty field.

`ReleaseGate.passed` implements M16.3c: every schema validates, no
invented or altered card and astrology facts, no leaked chain-of-thought
or template control tokens, and latency and memory recorded on named
hardware.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from syzygy.domain.interpretation import InterpretationKind
from syzygy.interpretation.prompts import (
    RESPONSE_JSON_SCHEMA,
    SUMMARY_RESPONSE_JSON_SCHEMA,
    SUMMARY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_repair_prompt,
    build_summary_prompt,
    build_summary_repair_prompt,
    build_user_prompt,
)
from syzygy.interpretation.providers.structured_output import (
    ResponseValidationError,
    parse_and_validate,
    parse_summary,
)
from syzygy.local_models.evaluation.fixtures import EvaluationCase, evaluation_cases

#: Generous: a large model on a processor is slow, and a timeout here
#: would be recorded as a quality failure rather than a speed one.
EVALUATION_TIMEOUT_SECONDS = 1800.0

_WORD = re.compile(r"[a-z']+")


@dataclass
class CaseResult:
    """What one fixture did."""

    case_id: str
    schema_valid_first_pass: bool = False
    repaired: bool = False
    #: True when the reply stopped for length rather than completing.
    truncated: bool = False
    succeeded: bool = False
    seconds: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    #: Facts Syzygy supplied that the reply failed to carry.
    missing_facts: tuple[str, ...] = ()
    #: Forbidden strings that appeared.
    leaked: tuple[str, ...] = ()
    #: 0.0-1.0. How much vocabulary the two registers *do not* share; low
    #: values mean the model wrote the same paragraph twice.
    register_distinctness: float | None = None
    error: str | None = None

    @property
    def tokens_per_second(self) -> float | None:
        if not self.completion_tokens or self.seconds <= 0:
            return None
        return self.completion_tokens / self.seconds


@dataclass
class EvaluationRun:
    """One artifact, on one machine, at one moment."""

    artifact_id: str
    served_model_id: str
    runtime_version: str
    hardware: str
    context_tokens: int
    cases: list[CaseResult] = field(default_factory=list)
    #: Filled in by the maintainer after reading the output: 1-5.
    rubric_factual_fidelity: int | None = None
    rubric_usable_prose: int | None = None
    #: Peak RSS in bytes, if measured externally (`/usr/bin/time -v`,
    #: Activity Monitor). Not guessed.
    peak_memory_bytes: int | None = None
    notes: str = ""

    @property
    def schema_valid_rate(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for case in self.cases if case.schema_valid_first_pass) / len(self.cases)

    @property
    def repair_rate(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for case in self.cases if case.repaired) / len(self.cases)

    @property
    def success_rate(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for case in self.cases if case.succeeded) / len(self.cases)

    @property
    def median_tokens_per_second(self) -> float | None:
        rates = sorted(
            rate for rate in (case.tokens_per_second for case in self.cases) if rate
        )
        return rates[len(rates) // 2] if rates else None

    def to_json(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "served_model_id": self.served_model_id,
            "runtime_version": self.runtime_version,
            "hardware": self.hardware,
            "context_tokens": self.context_tokens,
            "schema_valid_rate": round(self.schema_valid_rate, 3),
            "repair_rate": round(self.repair_rate, 3),
            "success_rate": round(self.success_rate, 3),
            "median_tokens_per_second": self.median_tokens_per_second,
            "peak_memory_bytes": self.peak_memory_bytes,
            "rubric_factual_fidelity": self.rubric_factual_fidelity,
            "rubric_usable_prose": self.rubric_usable_prose,
            "notes": self.notes,
            "cases": [
                {
                    "case_id": case.case_id,
                    "succeeded": case.succeeded,
                    "schema_valid_first_pass": case.schema_valid_first_pass,
                    "repaired": case.repaired,
                    "truncated": case.truncated,
                    "seconds": round(case.seconds, 2),
                    "completion_tokens": case.completion_tokens,
                    "missing_facts": list(case.missing_facts),
                    "leaked": list(case.leaked),
                    "register_distinctness": case.register_distinctness,
                    "error": case.error,
                }
                for case in self.cases
            ],
        }


@dataclass(frozen=True)
class ReleaseGate:
    """M16.3c, as a checkable object."""

    every_schema_valid: bool
    no_invented_facts: bool
    no_leaked_control_tokens: bool
    latency_recorded: bool
    memory_recorded: bool
    license_reviewed: bool
    reasons: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return all(
            (
                self.every_schema_valid,
                self.no_invented_facts,
                self.no_leaked_control_tokens,
                self.latency_recorded,
                self.memory_recorded,
                self.license_reviewed,
            )
        )


def evaluate(
    *,
    base_url: str,
    served_model_id: str,
    artifact_id: str,
    runtime_version: str,
    hardware: str,
    context_tokens: int,
    cases: tuple[EvaluationCase, ...] | None = None,
    on_case=None,
) -> EvaluationRun:
    """Run every fixture against a live endpoint."""
    run = EvaluationRun(
        artifact_id=artifact_id,
        served_model_id=served_model_id,
        runtime_version=runtime_version,
        hardware=hardware,
        context_tokens=context_tokens,
    )
    with httpx.Client(timeout=EVALUATION_TIMEOUT_SECONDS) as client:
        for case in cases or evaluation_cases():
            result = _run_case(client, base_url, served_model_id, case)
            run.cases.append(result)
            if on_case is not None:
                on_case(result)
    return run


def _run_case(
    client: httpx.Client, base_url: str, model_id: str, case: EvaluationCase
) -> CaseResult:
    result = CaseResult(case_id=case.id)
    is_reading = case.context.kind is InterpretationKind.DAILY_READING
    system = SYSTEM_PROMPT if is_reading else SUMMARY_SYSTEM_PROMPT
    user = build_user_prompt(case.context) if is_reading else build_summary_prompt(case.context)
    schema = RESPONSE_JSON_SCHEMA if is_reading else SUMMARY_RESPONSE_JSON_SCHEMA
    name = "SyzygyDailyReading" if is_reading else "SyzygySummary"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    started = time.monotonic()
    try:
        raw, usage, finish = _complete(client, base_url, model_id, messages, schema, name)
        result.prompt_tokens = usage.get("prompt_tokens")
        result.completion_tokens = usage.get("completion_tokens")
        result.truncated = finish == "length"

        parsed = _validate(raw, case)
        if parsed is not None:
            result.schema_valid_first_pass = True
        else:
            result.repaired = True
            repair = (
                build_repair_prompt(raw, "did not validate")
                if is_reading
                else build_summary_repair_prompt(raw, "did not validate")
            )
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": repair},
            ]
            raw, usage, finish = _complete(client, base_url, model_id, messages, schema, name)
            result.completion_tokens = (result.completion_tokens or 0) + (
                usage.get("completion_tokens") or 0
            )
            result.truncated = result.truncated or finish == "length"
            parsed = _validate(raw, case)

        if parsed is None:
            result.error = "did not validate after one repair turn"
        else:
            result.succeeded = True
            _score(result, parsed, case)
    except httpx.HTTPError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.seconds = time.monotonic() - started
    return result


def _complete(
    client: httpx.Client,
    base_url: str,
    model_id: str,
    messages: list[dict[str, str]],
    schema: dict[str, object],
    schema_name: str,
) -> tuple[str, dict[str, Any], str | None]:
    response = client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        json={
            "model": model_id,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": True},
            },
        },
    )
    response.raise_for_status()
    payload = response.json()
    choice = payload["choices"][0]
    return (
        str(choice["message"]["content"]),
        payload.get("usage") or {},
        choice.get("finish_reason"),
    )


def _validate(raw: str, case: EvaluationCase):
    parse = (
        parse_and_validate
        if case.context.kind is InterpretationKind.DAILY_READING
        else parse_summary
    )
    try:
        return parse(raw, context=case.context, provider_id="evaluation", model_id="evaluation")
    except ResponseValidationError:
        return None


def _score(result: CaseResult, parsed, case: EvaluationCase) -> None:
    text = json.dumps(parsed.model_dump(), ensure_ascii=False).lower()
    result.missing_facts = tuple(
        fact for fact in case.required_mentions if fact.lower() not in text
    )
    result.leaked = tuple(token for token in case.forbidden if token.lower() in text)

    esoteric = getattr(parsed, "esoteric", None)
    conventional = getattr(parsed, "conventional", None)
    if esoteric is not None and conventional is not None:
        result.register_distinctness = _distinctness(esoteric.body, conventional.body)


def _distinctness(left: str, right: str) -> float:
    """1 - Jaccard similarity over content words.

    Crude, and honest about it: it catches the failure that matters (the
    two registers being the same paragraph with different adjectives) and
    makes no claim about anything subtler, which is what the manual rubric
    is for.
    """
    left_words = set(_WORD.findall(left.lower()))
    right_words = set(_WORD.findall(right.lower()))
    if not left_words or not right_words:
        return 0.0
    overlap = len(left_words & right_words)
    union = len(left_words | right_words)
    return round(1 - overlap / union, 3)


def release_gate(run: EvaluationRun, *, license_reviewed: bool) -> ReleaseGate:
    """M16.3c's gate, evaluated against a run."""
    reasons: list[str] = []

    every_schema_valid = all(case.succeeded for case in run.cases)
    if not every_schema_valid:
        failed = [case.case_id for case in run.cases if not case.succeeded]
        reasons.append(f"cases that never validated: {', '.join(failed)}")

    no_invented = all(not case.missing_facts for case in run.cases)
    if not no_invented:
        for case in run.cases:
            if case.missing_facts:
                reasons.append(f"{case.case_id} dropped: {', '.join(case.missing_facts)}")

    no_leaks = all(not case.leaked for case in run.cases)
    if not no_leaks:
        for case in run.cases:
            if case.leaked:
                reasons.append(f"{case.case_id} leaked: {', '.join(case.leaked)}")

    latency_recorded = run.median_tokens_per_second is not None
    if not latency_recorded:
        reasons.append("no token rate was recorded")

    memory_recorded = run.peak_memory_bytes is not None
    if not memory_recorded:
        reasons.append("peak memory was not measured")

    if not license_reviewed:
        reasons.append("licence/redistribution review not recorded")

    return ReleaseGate(
        every_schema_valid=every_schema_valid,
        no_invented_facts=no_invented,
        no_leaked_control_tokens=no_leaks,
        latency_recorded=latency_recorded,
        memory_recorded=memory_recorded,
        license_reviewed=license_reviewed,
        reasons=tuple(reasons),
    )
