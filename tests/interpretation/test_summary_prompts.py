"""The two M13.2 summary contracts stay narrow and schema-validated."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syzygy.domain.interpretation import InterpretationKind
from syzygy.interpretation.prompts import build_summary_prompt
from syzygy.interpretation.providers.structured_output import parse_summary


def _summary_context(sample_context, kind: InterpretationKind):
    return sample_context.model_copy(
        update={"kind": kind, "card": None, "prompt_version": f"{kind.value}-v1"}
    )


@pytest.mark.parametrize(
    "kind,heading",
    [
        (InterpretationKind.NATAL_SUMMARY, "NATAL CHART"),
        (InterpretationKind.COSMOS_SUMMARY, "TODAY'S SKY"),
    ],
)
def test_summary_prompt_kinds_are_explicit(sample_context, kind, heading):
    context = _summary_context(sample_context, kind)
    prompt = build_summary_prompt(context)
    assert heading in prompt
    assert context.profile_display_name in prompt
    assert "CARD DRAWN" not in prompt


def test_summary_output_is_schema_validated_and_provenance_stamped(sample_context):
    context = _summary_context(sample_context, InterpretationKind.NATAL_SUMMARY)
    result = parse_summary(
        '{"headline":"A fixed sky","body":"A concise synthesis."}',
        context=context,
        provider_id="fixture",
        model_id="fixture-v1",
    )
    assert result.prompt_version == context.prompt_version
    with pytest.raises(ValidationError):
        parse_summary(
            '{"headline":"Missing body"}',
            context=context,
            provider_id="fixture",
            model_id="fixture-v1",
        )
