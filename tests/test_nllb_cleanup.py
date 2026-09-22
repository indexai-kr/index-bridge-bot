# -*- coding: utf-8 -*-
"""번역문 군더더기 제거 재발방지 시험.

지키려는 것.
  · 번역기가 앞에 붙인 '- ' 는 뗀다 — 사람이 한 말이 아니다.
  · 원문에 있던 글머리표는 남긴다 — 목록을 쓴 사람의 글을 망치지 않는다.

모델을 띄우지 않는다. `_strip_bullet` 은 순수 함수라 번역기 없이 시험된다
(모델이 있어야 도는 시험은 CI 에서 건너뛰어져 결국 아무도 안 본다).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nllb_local  # noqa: E402

strip = nllb_local._strip_bullet


# ── 번역기가 만든 군더더기는 뗀다 ───────────────────────────────────────

def test_removes_a_bullet_the_translator_invented():
    """실측된 결함이다: "안녕하세요" → "- Hi, how are you?"."""
    assert strip("안녕하세요", "- Hi, how are you?") == "Hi, how are you?"


@pytest.mark.parametrize("prefix", ["- ", "-", "– ", "— ", "* ", "• ", "  -  "])
def test_removes_every_bullet_shape_the_model_emits(prefix):
    assert strip("안녕하세요", f"{prefix}Hello") == "Hello"


def test_leaves_a_clean_translation_untouched():
    text = "Today's meeting starts at 3:00."
    assert strip("오늘 회의는 세 시에 시작합니다", text) == text


# ── 사람이 쓴 글머리표는 남긴다 ─────────────────────────────────────────

def test_keeps_the_bullet_when_the_speaker_wrote_one():
    """원문이 목록이면 번역도 목록이어야 한다.

    지우는 쪽으로만 기울면 목록을 쓴 사람의 글이 망가진다.
    """
    assert strip("- 첫째 항목", "- First item") == "- First item"


def test_keeps_the_bullet_even_with_leading_spaces_in_the_source():
    assert strip("   - 첫째", "   - First") == "   - First"


# ── 빼먹기 쉬운 경우 ────────────────────────────────────────────────────

def test_only_the_first_bullet_is_removed():
    """문장 안쪽의 붙임표는 글자다 — well-known 이 wellknown 이 되면 안 된다."""
    assert strip("잘 알려진 방법", "- well-known method") == "well-known method"


def test_empty_and_missing_values_do_not_explode():
    assert strip("", "") == ""
    assert strip(None, None) == ""
    assert strip("안녕", None) == ""


def test_a_translation_that_is_only_a_bullet_becomes_empty():
    """빈 문자열은 호출부에서 걸러진다 — 공백만 남은 조각을 이어붙이면
    문장 사이에 두 칸이 생긴다."""
    assert strip("안녕하세요", "- ") == ""
