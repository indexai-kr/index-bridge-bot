# -*- coding: utf-8 -*-
"""초대 페이지 재발방지 시험.

지키려는 것.
  · 가짜 초대 버튼을 만들지 않는다 — 남의 봇을 초대하는 페이지가 된다.
  · 구조화 데이터에 **실제로 하는 일만** 적는다. 없는 기능을 적으면
    그걸 보고 온 사람이 바로 나가고, 그건 우리가 한 거짓말이다.
  · 고객이 보는 글에 내부 용어를 쓰지 않는다(CLAUDE.md #12).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import site_build  # noqa: E402

APP_ID = "123456789012345678"
BASE = "https://example.com/bridge/"


# ── 가짜 링크를 만들지 않는다 ───────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", None, "   ", "내봇", "abc123", "12.34"])
def test_refuses_to_build_a_page_without_a_real_application_id(bad):
    """숫자가 아니면 페이지 자체를 안 만든다.

    기본값을 지어내면 그 버튼이 남의 봇을 초대한다.
    """
    with pytest.raises(ValueError):
        site_build.build_html(bad, BASE)


def test_refuses_a_relative_base_url(tmp_path):
    """상대경로면 sitemap·canonical 이 무효가 된다 — 조용히 통과시키지 않는다."""
    with pytest.raises(ValueError):
        site_build.build(APP_ID, "example.com", tmp_path)


def test_nothing_is_written_when_the_address_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        site_build.build(APP_ID, "example.com", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_the_button_points_at_our_own_invite_link():
    page = site_build.build_html(APP_ID, BASE)
    assert f"client_id={APP_ID}" in page


def test_the_button_asks_only_for_permissions_the_bot_uses():
    """권한을 넉넉히 받아두면 관리자가 초대창에서 보고 거절한다."""
    page = site_build.build_html(APP_ID, BASE)
    assert f"permissions={site_build.outreach.INVITE_PERMISSIONS}" in page
    assert "permissions=8" not in page, "관리자 권한을 달라고 하고 있다"


# ── 구조화 데이터 ───────────────────────────────────────────────────────

def _json_ld(page):
    return [json.loads(m) for m in re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        page, re.S)]

def test_structured_data_is_valid_json():
    """깨진 JSON-LD 는 없는 것만 못하다 — 검색엔진이 통째로 버린다."""
    blocks = _json_ld(site_build.build_html(APP_ID, BASE))
    assert len(blocks) == 2


def test_structured_data_describes_an_app_and_its_questions():
    blocks = {b["@type"]: b for b in _json_ld(site_build.build_html(APP_ID, BASE))}
    assert "SoftwareApplication" in blocks
    assert "FAQPage" in blocks
    assert blocks["SoftwareApplication"]["installUrl"].startswith(
        "https://discord.com/oauth2/authorize")


def test_every_question_on_the_page_is_also_in_the_structured_data():
    """눈에 보이는 답과 기계가 읽는 답이 갈리면 둘 중 하나는 거짓말이다."""
    page = site_build.build_html(APP_ID, BASE)
    blocks = {b["@type"]: b for b in _json_ld(page)}
    asked = {q["name"] for q in blocks["FAQPage"]["mainEntity"]}
    assert asked == {q for q, _ in site_build.FAQ}


def test_the_free_claim_matches_what_we_tell_people():
    blocks = {b["@type"]: b for b in _json_ld(site_build.build_html(APP_ID, BASE))}
    assert blocks["SoftwareApplication"]["offers"]["price"] == "0"
    answers = " ".join(a for _, a in site_build.FAQ)
    assert "무료" in answers


# ── 고객이 읽는 글 ──────────────────────────────────────────────────────

JARGON = ["STT", "TTS", "NLLB", "파이프라인", "폴백", "폴링", "Whisper",
          "sink", "Q1", "Q2", "Q3", "intent", "어댑터", "렌더러"]


def test_no_internal_words_reach_the_visitor():
    page = site_build.build_html(APP_ID, BASE)
    for w in JARGON:
        assert w not in page, f"내부 용어가 페이지에 새어나갔다: {w}"


def test_the_page_says_there_is_nothing_to_install():
    """전환에 제일 직결되는 문장이다 — 사라지면 안 된다."""
    page = site_build.build_html(APP_ID, BASE)
    assert "설치" in page and "가입" in page


def test_the_page_declares_its_language_as_korean():
    assert '<html lang="ko">' in site_build.build_html(APP_ID, BASE)


def test_no_raw_backticks_are_shown_to_the_visitor():
    """화면에 백틱이 그대로 찍히면 만들다 만 페이지로 보인다.

    눈으로 보기 전엔 안 보이던 결함이다 — 시험 전부 초록불인데
    스크린샷에서 `!join` 이 백틱째 찍혀 있었다(CLAUDE.md #12).
    """
    page = site_build.build_html(APP_ID, BASE)
    body = page.split("</style>", 1)[1]
    assert "`" not in body, "명령어가 명령어 모양으로 안 보이고 백틱이 찍힌다"


def test_commands_are_marked_up_as_commands():
    page = site_build.build_html(APP_ID, BASE)
    assert "<code>!join</code>" in page
    assert "<code>!flip</code>" in page


def test_machines_get_the_commands_without_markup_noise():
    """구조화 데이터에 백틱이 들어가면 AI 가 그걸 명령어 일부로 읽는다."""
    blocks = {b["@type"]: b for b in _json_ld(site_build.build_html(APP_ID, BASE))}
    for q in blocks["FAQPage"]["mainEntity"]:
        assert "`" not in q["name"]
        assert "`" not in q["acceptedAnswer"]["text"]


# ── sitemap / robots ────────────────────────────────────────────────────

def test_robots_points_to_the_sitemap():
    """ping 이 없어진 지금, 이게 살아 있는 유일한 자동 경로다."""
    robots = site_build.build_robots(BASE)
    assert "Sitemap: https://example.com/bridge/sitemap.xml" in robots


def test_robots_does_not_double_the_slash():
    assert "//sitemap.xml" not in site_build.build_robots("https://example.com/")


def test_robots_lets_crawlers_in():
    robots = site_build.build_robots(BASE)
    assert "Disallow: /" not in robots, "크롤러를 통째로 막고 있다"


def test_sitemap_is_valid_xml_with_our_address():
    import xml.etree.ElementTree as ET
    root = ET.fromstring(site_build.build_sitemap(BASE, today="2026-09-22"))
    locs = [e.text for e in root.iter(
        "{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert locs == [BASE]


# ── 실제로 파일이 나오는가 ──────────────────────────────────────────────

def test_build_writes_the_three_files(tmp_path):
    written = site_build.build(APP_ID, BASE, tmp_path)
    names = {p.name for p in written}
    assert names == {"index.html", "sitemap.xml", "robots.txt"}
    for p in written:
        assert p.stat().st_size > 0


def test_built_page_is_utf8_and_keeps_hangul(tmp_path):
    """cp949 로 쓰이면 브라우저에서 한글이 깨진다."""
    site_build.build(APP_ID, BASE, tmp_path)
    text = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "한국어" in text
    assert 'charset="utf-8"' in text
