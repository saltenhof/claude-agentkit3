"""Regression matrix for exact explicit HTML-anchor semantics."""

from __future__ import annotations

import pytest
from concept_toolchain.docmodel import anchor_slugs


@pytest.mark.parametrize(
    ("markup", "expected"),
    (
        ('<a id="lower"></a>', frozenset({"lower"})),
        ("<A ID='upper'></A>", frozenset({"upper"})),
        ('<a class="x" id="ordered" title="y"></a>', frozenset({"ordered"})),
        ('<a title="y" ID=\'reverse\' class="x"></a>', frozenset({"reverse"})),
        (
            '<a id="first"></a> text <A class="x" id="second"></A>',
            frozenset({"first", "second"}),
        ),
    ),
)
def test_exact_a_id_attributes_are_resolvable(
    markup: str,
    expected: frozenset[str],
) -> None:
    assert anchor_slugs(markup) == expected


@pytest.mark.parametrize(
    "markup",
    (
        '<aside data-id="ghost"></aside>',
        '<abbr id="abbr"></abbr>',
        '<a data-id="wrong"></a>',
        '<article aria-id="wrong"></article>',
        '<anchor id="prefix"></anchor>',
        '<a identity="wrong"></a>',
        '<a id=""></a>',
    ),
)
def test_non_a_tags_and_non_id_attributes_never_create_anchors(
    markup: str,
) -> None:
    assert anchor_slugs(markup) == frozenset()
