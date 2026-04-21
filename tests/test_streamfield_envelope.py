"""Tests for the StreamField envelope contract.

Full walk tests land with the PageQueryToolset in the next task. This
suite locks the shape of the envelope and the error vocabulary so those
implementations can be built against a fixed contract.
"""

from __future__ import annotations

import pytest

from wagtail_mcp_server.serializers.streamfield import (
    StreamFieldError,
    StreamFieldValidationError,
    is_envelope,
    make_envelope,
)


def test_envelope_shape():
    env = make_envelope("paragraph", "abc-123", "<p>Hello</p>")
    assert env == {"type": "paragraph", "id": "abc-123", "value": "<p>Hello</p>"}


def test_envelope_default_id_empty_string():
    env = make_envelope("heading", None, "Title")
    assert env["id"] == ""


def test_is_envelope_accepts_canonical_shape():
    assert is_envelope({"type": "x", "id": "y", "value": 1})


def test_is_envelope_rejects_missing_keys():
    assert is_envelope({"type": "x"}) is False
    assert is_envelope({"value": 1}) is False
    assert is_envelope({"type": 42, "value": 1}) is False
    assert is_envelope([1, 2, 3]) is False


def test_validation_error_carries_structured_errors():
    errs = [
        StreamFieldError(
            code="unknown_block_type",
            path="body[3]",
            expected="one of [paragraph, heading, image]",
            got="banana",
        )
    ]
    exc = StreamFieldValidationError(errs)
    assert exc.errors == errs
    assert "unknown_block_type" in str(exc)
    assert "body[3]" in str(exc)


@pytest.mark.parametrize(
    "code",
    [
        "unknown_block_type",
        "unknown_child",
        "missing_required",
        "type_mismatch",
        "invalid_chooser_ref",
        "invalid_richtext",
        "envelope_shape",
    ],
)
def test_closed_vocabulary_codes_all_constructible(code):
    """Every documented error code must be constructible."""
    err = StreamFieldError(code=code, path="$", expected="", got="")
    assert err.code == code
