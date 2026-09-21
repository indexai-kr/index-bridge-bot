# -*- coding: utf-8 -*-
"""봇이 바깥으로 내보내는 말과 숫자 — 안내문 · 초대링크 · 사용 집계.

여기엔 discord를 import하지 않는다. 그래야 봇을 띄우지 않고 시험할 수 있고,
문구·숫자가 틀렸을 때 디스코드 탓인지 우리 탓인지 헷갈리지 않는다.

두 가지를 특히 조심한다.
  · 초대링크의 application id는 **받아서** 쓴다. 기본값을 지어내면 그 링크는
    남의 봇을 초대하는 링크가 된다(CLAUDE.md #4: 실측값만).
  · 집계는 **센 것만** 말한다. 추정·반올림·"약 N건" 금지. 못 세었으면 0이 아니라
    못 세었다고 말한다.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlencode

# ── 초대 권한 ───────────────────────────────────────────────────────────
# 이 봇이 실제로 하는 일에 필요한 것만. 권한을 넉넉히 받아두면 편하지만,
# 서버 관리자가 초대창에서 그 목록을 보고 거절한다(전환에 직결).
_PERMISSIONS = {
    "view_channel":        1 << 10,   # 채널을 본다
    "send_messages":       1 << 11,   # 번역을 답장한다
    "read_message_history": 1 << 16,  # 답장 대상 원문을 읽는다
    "connect":             1 << 20,   # 음성방에 들어간다
    "speak":               1 << 21,   # 음성방에서 읽어준다
}
INVITE_PERMISSIONS = 0
for _bit in _PERMISSIONS.values():
    INVITE_PERMISSIONS |= _bit


def invite_url(application_id) -> str:
    """이 봇의 초대링크. application_id는 반드시 넘겨야 한다.

    비었거나 숫자가 아니면 예외 — 빈 링크·기본 링크를 돌려주면 사람이
    그걸 그대로 복사해 붙이고, 어디로도 안 가거나 남의 봇을 초대한다.
    """
    aid = str(application_id or "").strip()
    if not aid.isdigit():
        raise ValueError(
            "초대링크를 만들 수 없습니다: application id가 숫자가 아닙니다. "
            f"받은 값={application_id!r}")
    q = urlencode({
        "client_id": aid,
        "permissions": str(INVITE_PERMISSIONS),
        "scope": "bot",
    })
    return f"https://discord.com/oauth2/authorize?{q}"


# ── 사람에게 보이는 글 ──────────────────────────────────────────────────
# 내부 용어를 쓰지 않는다(CLAUDE.md #12). STT·TTS·파이프라인·폴백은
# 우리끼리 쓰는 말이고, 처음 온 사람은 그 말을 보면 창을 닫는다.

def help_text() -> str:
    return (
        "**INDEX Bridge — 한국어 ↔ 영어 다리**\n"
        "채팅에 쓰면 번역해서 답해주고, 음성방에서 말하면 옮겨서 읽어줍니다.\n"
        "\n"
        "`!join` 지금 들어가 있는 음성방으로 부릅니다\n"
        "`!leave` 음성방에서 내보냅니다\n"
        "`!flip` 번역 방향을 뒤집습니다\n"
        "`!invite` 다른 서버에 데려가는 링크\n"
        "`!help` 이 안내\n"
        "\n"
        "설치할 것도, 가입할 것도 없습니다. 그냥 쓰면 됩니다."
    )


def intro_text() -> str:
    """서버에 막 들어갔을 때 한 번 하는 인사."""
    return (
        "안녕하세요, **INDEX Bridge**입니다. 한국어와 영어 사이를 이어드립니다.\n"
        "· 채팅에 한국어를 쓰면 영어로 답합니다 (반대도 됩니다)\n"
        "· 음성방에서 `!join`으로 부르면, 말하는 걸 옮겨서 읽어줍니다\n"
        "\n"
        "`!help` 를 치면 쓰는 법이 나옵니다."
    )


def onboarding_text() -> str:
    """처음 !join 을 쓴 사람에게 한 번만 보내는 개인 메시지."""
    return (
        "음성방에 들어갔습니다 👋\n"
        "\n"
        "**이것만 알면 됩니다**\n"
        "1. 그냥 평소처럼 말하세요. 잠깐 멈추면 그 대목을 옮겨서 읽어줍니다.\n"
        "2. 옮긴 글은 채팅에도 같이 남으니 나중에 다시 볼 수 있습니다.\n"
        "3. 방향을 바꾸려면 `!flip`, 내보내려면 `!leave`.\n"
        "\n"
        "잘 안 들리거나 엉뚱하게 옮기면 말씀해주세요 — 그게 제일 도움이 됩니다."
    )


# ── 사용 집계 ───────────────────────────────────────────────────────────

def _default_state_path() -> Path:
    """상태 파일 위치. 환경변수로 덮어쓸 수 있고, 기본은 리포 안이 아니다.

    리포 안에 두면 PUBLIC 리포에 사용 기록이 따라 올라간다
    (2026-09-17 교훈: 산출물을 어디에 쓸지는 쓰기 전에 정한다).
    """
    env = os.environ.get("BRIDGE_STATE_FILE", "").strip()
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / "index_bridge_state.json"


def today_kst(now: _dt.datetime | None = None) -> str:
    """집계 기준일(KST). 한국에서 쓰는 봇이라 UTC 자정에 끊으면 밤 9시에 끊긴다."""
    kst = _dt.timezone(_dt.timedelta(hours=9))
    n = now.astimezone(kst) if now else _dt.datetime.now(kst)
    return n.strftime("%Y-%m-%d")


class Usage:
    """번역 건수·첫 사용·온보딩 이력을 센다.

    디스크에 남긴다 — 봇을 재시작하면 '오늘 몇 건'이 0으로 돌아가는데,
    그건 0건이 아니라 '못 세었다'이고 그 둘을 섞으면 숫자가 거짓말이 된다.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else _default_state_path()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("최상위가 객체가 아님")
        except FileNotFoundError:
            data = {}
        except Exception as e:
            # 깨진 파일을 조용히 비우면 어제 숫자가 소리 없이 사라진다.
            print(f"[outreach] 상태 파일을 읽지 못했습니다({e}). "
                  f"이번 실행의 집계는 0부터 세며, 기존 파일은 건드리지 않습니다.")
            data = {"_unreadable": True}
        data.setdefault("days", {})
        data.setdefault("onboarded", [])
        data.setdefault("first_translation_done", False)
        return data

    def save(self) -> None:
        if self._data.get("_unreadable"):
            return  # 못 읽은 파일 위에 덮어쓰지 않는다
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)   # 중간에 죽어도 반쪽 파일이 남지 않게
        except Exception as e:
            print(f"[outreach] 상태 저장 실패: {e}")

    # -- 번역 --
    def record_translation(self, day: str | None = None) -> bool:
        """한 건 세고, 이게 통틀어 첫 번역이면 True."""
        d = day or today_kst()
        self._data["days"][d] = int(self._data["days"].get(d, 0)) + 1
        first = not self._data.get("first_translation_done")
        if first:
            self._data["first_translation_done"] = True
        self.save()
        return first

    def count_for(self, day: str | None = None) -> int:
        return int(self._data["days"].get(day or today_kst(), 0))

    # -- 온보딩 --
    def needs_onboarding(self, user_id) -> bool:
        return str(user_id) not in self._data["onboarded"]

    def mark_onboarded(self, user_id) -> None:
        uid = str(user_id)
        if uid not in self._data["onboarded"]:
            self._data["onboarded"].append(uid)
            self.save()


# ── 번역 기록 ───────────────────────────────────────────────────────────
# 데모 영상(MSG-P4)은 '실제로 번역한 것'을 보여줘야 의미가 있다. 그런데 봇은
# 콘솔에만 찍고 아무 데도 남기지 않아서, 창을 닫으면 그날 번역이 사라진다.
# 여기서 한 줄씩 남겨둬야 나중에 진짜 대화로 영상을 만들 수 있다.

def transcript_path() -> Path:
    env = os.environ.get("BRIDGE_TRANSCRIPT_FILE", "").strip()
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / "index_bridge_transcript.jsonl"


def append_turn(source: str, translated: str, source_lang: str,
                target_lang: str, kind: str, when=None,
                path: Path | None = None) -> bool:
    """번역 한 건을 기록. 실패해도 예외를 밖으로 내지 않는다(본업이 우선).

    본문을 그대로 남기므로 **PUBLIC 리포 안에 두지 않는다**
    (2026-09-17 교훈). 기본 위치가 임시 폴더인 이유가 이것이다.
    """
    p = Path(path) if path else transcript_path()
    rec = {
        "at": (when or _dt.datetime.now(_dt.timezone.utc)).isoformat(),
        "kind": kind,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "source": source,
        "translated": translated,
    }
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        print(f"[outreach] 기록 실패: {e}")
        return False


def read_turns(path: Path | None = None) -> list:
    """기록을 읽는다. 깨진 줄은 **건너뛰되 몇 줄 버렸는지 말한다**.

    조용히 건너뛰면 영상에 문장이 빠져도 아무도 모른다.
    """
    p = Path(path) if path else transcript_path()
    turns, broken = [], 0
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if isinstance(rec, dict) and rec.get("translated"):
                turns.append(rec)
            else:
                broken += 1
        except Exception:
            broken += 1
    if broken:
        print(f"[outreach] 읽지 못한 기록 {broken}줄은 건너뜁니다.")
    return turns


def daily_report_text(day: str, count: int, guild_count: int) -> str:
    """마스터에게 가는 하루 요약. 0건이면 0건이라고 쓴다(빈 보고 금지)."""
    head = f"📊 **{day}** (KST)"
    if count == 0:
        body = "번역 0건. 아무도 쓰지 않았습니다."
    else:
        body = f"번역 **{count}건**."
    return f"{head}\n{body}\n서버 {guild_count}곳에 들어가 있습니다."
