# -*- coding: utf-8 -*-
"""초대 페이지 만들기 (MSG-P5).

한 장짜리 페이지 + 검색·AI가 읽을 구조화 데이터 + sitemap/robots 를 만든다.

전제 정정 — "sitemap 자동 제출"은 지금 불가능하다:
구글은 sitemap ping 엔드포인트(`google.com/ping?sitemap=`)를 2023년에 없앴고
지금은 404를 돌려준다. 빙도 같이 접었다. 그러니 "자동 제출" 코드를 짜 두면
매번 404를 받고도 성공한 줄 아는 물건이 된다(CLAUDE.md #4).
**지금 살아 있는 자동 경로는 robots.txt 에 sitemap 위치를 적어 두는 것**이고,
그건 이 파일이 해 준다. 서치콘솔 등록만 사람이 한 번 하면 된다.

application id 는 **받아서** 쓴다. 없으면 만들지 않는다 — 기본값을 지어내면
그 페이지의 버튼이 남의 봇을 초대한다(outreach.invite_url 과 같은 이유).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import re
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import outreach

NAME = "INDEX Bridge"
TAGLINE = "한국어 ↔ 영어를 이어주는 디스코드 봇"

# 검색창과 AI 비서가 실제로 받는 질문들. 내부 용어를 쓰지 않는다(CLAUDE.md #12).
FAQ = [
    ("설치할 게 있나요?",
     "없습니다. 초대 링크를 누르고 서버를 고르면 바로 씁니다. "
     "가입도, 내려받을 것도 없습니다."),
    ("무료인가요?",
     "네, 무료로 쓸 수 있습니다."),
    ("음성도 번역되나요?",
     "됩니다. 음성 채널에서 `!join` 이라고 치면 들어가서, "
     "말한 내용을 옮겨서 읽어줍니다. 옮긴 글은 채팅에도 남습니다."),
    ("어떤 언어를 지원하나요?",
     "한국어와 영어 사이를 옮깁니다. `!flip` 으로 방향을 뒤집을 수 있습니다."),
    ("번역한 내용이 저장되나요?",
     "서버 관리자가 따로 켜지 않는 한, 옮긴 글은 채팅에 남는 것 말고는 "
     "바깥으로 나가지 않습니다."),
    ("어떻게 부르나요?",
     "채팅에 `!help` 를 치면 쓰는 법이 나옵니다."),
]

STEPS = [
    ("초대하기", "아래 버튼을 눌러 서버를 고릅니다."),
    ("그냥 쓰기", "채팅에 한국어를 쓰면 영어로 답합니다. 반대도 됩니다."),
    ("음성방에서", "`!join` 으로 부르면 말한 것을 옮겨 읽어줍니다."),
]


_CODE = re.compile(r"`([^`]+)`")


def _inline(text: str) -> str:
    """사람이 보는 HTML. `!join` 처럼 감싼 것은 명령어 모양으로 보여준다.

    이걸 안 하면 화면에 백틱이 그대로 찍힌다 — 눈으로 보기 전엔 안 보이는
    결함이라 시험만으로는 못 잡는다(CLAUDE.md #12, 스크린샷 실측).
    """
    return _CODE.sub(r"<code>\1</code>", html.escape(text))


def _plain(text: str) -> str:
    """기계가 읽는 쪽. 백틱은 글자가 아니라 표시용이라 빼고 준다."""
    return _CODE.sub(r"\1", text)


def _structured_data(base_url: str, invite: str) -> str:
    """검색엔진·AI 비서가 읽는 부분. 사람 눈에는 안 보인다.

    실제로 하는 일만 적는다 — 없는 기능을 적으면 그걸 보고 온 사람이
    바로 나간다(그리고 그건 우리가 한 거짓말이다).
    """
    app = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": NAME,
        "description": (
            f"{TAGLINE}. 디스코드 채팅과 음성 채널에서 한국어와 영어를 "
            "서로 옮겨줍니다. 설치나 가입 없이 초대만 하면 씁니다."),
        "applicationCategory": "CommunicationApplication",
        "operatingSystem": "Discord",
        "url": base_url,
        "installUrl": invite,
        "inLanguage": ["ko", "en"],
        "offers": {
            "@type": "Offer",
            "price": "0",
            "priceCurrency": "KRW",
        },
    }
    faq = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": _plain(q),
                "acceptedAnswer": {"@type": "Answer", "text": _plain(a)},
            }
            for q, a in FAQ
        ],
    }
    blocks = []
    for obj in (app, faq):
        blocks.append(
            '<script type="application/ld+json">\n'
            + json.dumps(obj, ensure_ascii=False, indent=2)
            + "\n</script>")
    return "\n".join(blocks)


def build_html(application_id, base_url: str) -> str:
    invite = outreach.invite_url(application_id)   # 숫자가 아니면 여기서 멈춘다
    e = html.escape
    steps = "\n".join(
        f"      <li><strong>{_inline(t)}</strong><span>{_inline(d)}</span></li>"
        for t, d in STEPS)
    faqs = "\n".join(
        f"      <details>\n"
        f"        <summary>{_inline(q)}</summary>\n"
        f"        <p>{_inline(a)}</p>\n"
        f"      </details>"
        for q, a in FAQ)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(NAME)} — {e(TAGLINE)}</title>
<meta name="description" content="{e(TAGLINE)}. 설치도 가입도 없이 초대만 하면 채팅과 음성방에서 한국어와 영어를 옮겨줍니다.">
<link rel="canonical" href="{e(base_url)}">
<meta property="og:title" content="{e(NAME)} — {e(TAGLINE)}">
<meta property="og:description" content="설치도 가입도 없습니다. 초대하면 바로 씁니다.">
<meta property="og:type" content="website">
<meta property="og:url" content="{e(base_url)}">
<meta name="twitter:card" content="summary">
{_structured_data(base_url, invite)}
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0 20px 64px;
    background: #101418; color: #e9edf2;
    font-family: "Malgun Gothic", "Apple SD Gothic Neo", system-ui, sans-serif;
    line-height: 1.7;
  }}
  main {{ max-width: 680px; margin: 0 auto; }}
  h1 {{ font-size: 2.2rem; margin: 64px 0 8px; letter-spacing: -.02em; }}
  .tagline {{ font-size: 1.15rem; color: #9fb0c0; margin: 0 0 8px; }}
  .sub {{ color: #7d8b99; margin: 0 0 32px; }}
  .cta {{
    display: inline-block; padding: 16px 32px; border-radius: 10px;
    background: #5865f2; color: #fff; font-weight: 700; font-size: 1.05rem;
    text-decoration: none;
  }}
  .cta:hover {{ background: #4752c4; }}
  .note {{ font-size: .9rem; color: #7d8b99; margin-top: 12px; }}
  h2 {{ font-size: 1.25rem; margin: 56px 0 16px; }}
  ol {{ padding-left: 0; list-style: none; counter-reset: s; }}
  ol li {{
    counter-increment: s; position: relative;
    padding: 0 0 18px 44px;
  }}
  ol li::before {{
    content: counter(s); position: absolute; left: 0; top: 2px;
    width: 28px; height: 28px; border-radius: 50%;
    background: #1d2733; color: #9fb0c0;
    display: grid; place-items: center; font-size: .85rem; font-weight: 700;
  }}
  ol li strong {{ display: block; }}
  ol li span {{ color: #9fb0c0; }}
  details {{
    border-top: 1px solid #1d2733; padding: 14px 0;
  }}
  details summary {{ cursor: pointer; font-weight: 600; }}
  details p {{ color: #9fb0c0; margin: 10px 0 0; }}
  code {{
    background: #1d2733; padding: 2px 7px; border-radius: 5px;
    font-size: .9em;
  }}
  footer {{
    margin-top: 64px; padding-top: 24px; border-top: 1px solid #1d2733;
    color: #61707e; font-size: .88rem;
  }}
</style>
</head>
<body>
  <main>
    <h1>{e(NAME)}</h1>
    <p class="tagline">{e(TAGLINE)}</p>
    <p class="sub">설치할 것도, 가입할 것도 없습니다. 초대하면 바로 씁니다.</p>

    <a class="cta" href="{e(invite)}" rel="noopener">디스코드에 추가하기</a>
    <p class="note">서버에 봇을 추가할 권한이 있어야 합니다.</p>

    <h2>쓰는 법</h2>
    <ol>
{steps}
    </ol>

    <h2>자주 묻는 것</h2>
{faqs}

    <footer>
      <p>채팅에 <code>!help</code> 를 치면 쓰는 법이 나옵니다.</p>
    </footer>
  </main>
</body>
</html>
"""


def build_sitemap(base_url: str, today: str | None = None) -> str:
    day = today or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url>\n"
        f"    <loc>{html.escape(base_url)}</loc>\n"
        f"    <lastmod>{day}</lastmod>\n"
        "  </url>\n"
        "</urlset>\n"
    )


def build_robots(base_url: str) -> str:
    """sitemap 위치를 여기 적는 것이 **지금 살아 있는 자동 경로**다.

    ping 엔드포인트는 2023년에 없어져서 404를 돌려준다.
    """
    root = base_url.rstrip("/")
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {root}/sitemap.xml\n"
    )


def build(application_id, base_url: str, out_dir: Path) -> list:
    """세 파일을 만든다. 만들어진 경로 목록을 돌려준다."""
    if not str(base_url or "").startswith(("http://", "https://")):
        raise ValueError(
            "주소는 http:// 또는 https:// 로 시작해야 합니다. "
            f"받은 값={base_url!r} (sitemap·canonical 이 상대경로면 무효입니다)")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in (
        ("index.html", build_html(application_id, base_url)),
        ("sitemap.xml", build_sitemap(base_url)),
        ("robots.txt", build_robots(base_url)),
    ):
        p = out_dir / name
        p.write_text(text, encoding="utf-8")
        written.append(p)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="초대 페이지 만들기")
    ap.add_argument("--application-id", required=True,
                    help="디스코드 개발자 포털의 Application ID (숫자)")
    ap.add_argument("--base-url", required=True,
                    help="이 페이지가 올라갈 주소 (예: https://example.github.io/bridge/)")
    ap.add_argument("--out", type=Path, default=Path("site"))
    args = ap.parse_args(argv)

    written = build(args.application_id, args.base_url, args.out)
    for p in written:
        print(f"  {p}  ({p.stat().st_size:,} 바이트)")
    print(f"\n{len(written)}개를 만들었습니다.")
    print("서치콘솔 등록은 사람이 한 번 해야 합니다 — "
          "ping 자동 제출은 2023년에 없어졌습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
