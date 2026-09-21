# -*- coding: utf-8 -*-
"""봇 목록 사이트에 서버 수를 올린다 (MSG-P3).

봇 목록(Top.gg 같은 디렉터리)은 **최초 등록만 사람이** 한다. 계정을 만들고
봇을 등록하고 토큰을 받는 건 사람 손이 필요하고, 그건 여기서 할 수 없다.
등록이 끝난 뒤의 '서버 수 갱신'만 이 파일이 자동으로 한다.

세 가지를 지킨다.
  · 토큰이 없으면 **끈다**. 조용히 실패하지 않고 왜 꺼졌는지 한 줄 남긴다.
  · 2xx가 아니면 실패다. 응답 본문을 그대로 남긴다 — 올리기는 올렸는데
    사이트가 안 받은 경우를 "올렸다"로 적으면 서버 수가 영영 안 맞는다.
  · 토큰은 어떤 경로로도 찍지 않는다(로그·예외 메시지 포함).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    """봇 목록 한 곳. 새 사이트를 붙이는 건 코드가 아니라 이 표에 한 줄."""
    key: str            # 사람이 부르는 이름
    env: str            # 토큰을 읽을 환경변수
    url: str            # {bot_id} 가 들어간 주소
    field: str          # 서버 수를 담을 키 이름 (사이트마다 다르다)
    auth_prefix: str = ""   # Authorization 값 앞에 붙는 것 (없으면 토큰만)


# 여기 적힌 주소·필드명은 **미검증**이다. 실제로 한 번 올려보기 전까지는
# 맞다고 적지 않는다(CLAUDE.md #4). 첫 실행 로그의 status/본문이 정답이다.
PROVIDERS = (
    Provider("top.gg", "TOPGG_TOKEN",
             "https://top.gg/api/bots/{bot_id}/stats", "server_count"),
    Provider("discord.bots.gg", "BOTSGG_TOKEN",
             "https://discord.bots.gg/api/v1/bots/{bot_id}/stats", "guildCount"),
)


def enabled_providers(env=None):
    """토큰이 실제로 들어있는 곳만. 없으면 빈 목록(예외 아님)."""
    src = env if env is not None else os.environ
    out = []
    for p in PROVIDERS:
        if str(src.get(p.env, "") or "").strip():
            out.append(p)
    return out


def describe_status(env=None) -> str:
    """지금 어디에 올라가는지 한 줄. 토큰 값은 절대 넣지 않는다."""
    on = enabled_providers(env)
    if not on:
        names = ", ".join(p.env for p in PROVIDERS)
        return (f"BOTLIST status=OFF reason=토큰 없음 "
                f"hint={names} 중 하나를 환경변수에 넣으면 켜집니다 "
                f"(사이트 등록은 사람이 먼저 해야 합니다)")
    return f"BOTLIST status=ON providers={','.join(p.key for p in on)}"


async def post_one(session, provider: Provider, bot_id, guild_count: int,
                   token: str) -> dict:
    """한 곳에 올린다. 결과를 사실대로 돌려준다(성공을 가정하지 않는다)."""
    url = provider.url.format(bot_id=bot_id)
    headers = {"Authorization": f"{provider.auth_prefix}{token}".strip(),
               "Content-Type": "application/json"}
    payload = {provider.field: int(guild_count)}
    try:
        async with session.post(url, json=payload, headers=headers,
                                timeout=15) as resp:
            body = (await resp.text())[:300]
            ok = 200 <= resp.status < 300
            return {"provider": provider.key, "ok": ok,
                    "status": resp.status, "body": body}
    except Exception as e:
        # 토큰이 예외 메시지에 섞여 나올 여지를 없앤다
        msg = str(e).replace(token, "<토큰>") if token else str(e)
        return {"provider": provider.key, "ok": False,
                "status": None, "body": f"요청 실패: {msg}"}


async def post_stats(session, bot_id, guild_count: int, env=None) -> list:
    """켜져 있는 모든 곳에 올리고 결과 목록을 돌려준다."""
    src = env if env is not None else os.environ
    results = []
    for p in enabled_providers(src):
        token = str(src.get(p.env, "")).strip()
        r = await post_one(session, p, bot_id, guild_count, token)
        results.append(r)
        if r["ok"]:
            print(f"BOTLIST post={p.key} servers={guild_count} status=OK")
        else:
            print(f"BOTLIST post={p.key} servers={guild_count} "
                  f"status=FAIL http={r['status']} body={r['body']}")
    return results
