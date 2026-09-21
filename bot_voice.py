# -*- coding: utf-8 -*-
"""
INDEX Bridge Bot (Voice) — 디스코드 이중언어 봇
타이핑 한 줄을 두 갈래로 내보낸다:
  · 텍스트 채널 : TEXT_LANG 로 번역해 답장
  · 음성 채널   : VOICE_LANG 로 번역해 TTS(소리)로 읽어줌
                 (글쓴 사람이 들어가 있는 음성채널로 봇이 들어가 재생)
기본: 음성=한국어(ko) / 텍스트=영어(en).   채팅창에 !flip 치면 서로 뒤집힘.
필요: PyNaCl(음성) · ffmpeg(시스템) · edge-tts(무료 TTS) · deep-translator.
동작은 읽기·번역 답장·음성 재생만. 삭제·다른 행동 없음.
"""
import os
import uuid
import asyncio
import tempfile

import discord
import edge_tts
import google.generativeai as genai
from dotenv import load_dotenv

import botlists
import outreach

load_dotenv()  # .env 파일이 있으면 환경변수로 읽음 (없으면 무시)

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "").strip())
_gem = genai.GenerativeModel(
    os.environ.get("GEMINI_MODEL", "gemini-3.6-flash").strip()
    or "gemini-3.6-flash")   # 2026-09 실측 동작 확인 모델. 바뀌면 GEMINI_MODEL로 지정
_LANG = {"ko": "Korean", "en": "English", "ja": "Japanese", "zh-CN": "Chinese"}

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
VOICE_LANG = os.environ.get("VOICE_LANG", "ko").strip().lower()   # 음성으로 나갈 언어
TEXT_LANG = os.environ.get("TEXT_LANG", "en").strip().lower()     # 채팅으로 나갈 언어
CHANNEL_NAME = os.environ.get("TRANSLATE_CHANNEL", "").strip()    # 비우면 모든 텍스트채널

# 언어코드 → edge-tts 목소리
VOICES = {
    "ko": "ko-KR-SunHiNeural",
    "en": "en-US-AriaNeural",
    "ja": "ja-JP-NanamiNeural",
    "zh-CN": "zh-CN-XiaoxiaoNeural",
}

intents = discord.Intents.default()
intents.message_content = True   # 개발자 포털에서 Message Content Intent 켜야 함
intents.voice_states = True

client = discord.Client(intents=intents)
_play_lock = asyncio.Lock()      # 음성 재생 겹침 방지

# output stage + 세션 계측 상태 (STT 이후 출력 배선용)
_VOICE_CHANNEL = None            # 현재 접속 음성채널 (TEXT_SEND 대상)
_VOICE_SESSION = {"connect_count": 0, "disconnect_count": 0,
                  "last_close_code": None, "reconnect_count": 0,
                  "last_channel_id": None}
_LAST_TTS_TEXT = {"text": None}  # 같은 문장 TTS 중복 생성 방지

# 사용 집계 + 마스터 통지 (MSG-P1/P2)
_USAGE = outreach.Usage()
_OWNER_ID = os.environ.get("BRIDGE_OWNER_ID", "").strip()
_DAILY_TASK_STARTED = {"v": False}


async def notify_owner(text: str) -> bool:
    """마스터에게 개인 메시지. 보낼 곳을 모르면 **조용히 넘어가지 않고** 말한다.

    통지가 안 가는 것과 아무 일도 없는 것은 다른 상태다. 구분 못 하면
    "아무도 안 쓰네"와 "통지가 고장났네"를 영영 못 가른다.
    """
    uid = _OWNER_ID
    if not uid:
        try:                                   # 앱 소유자로 대체 시도
            app = await client.application_info()
            uid = str(app.owner.id)
        except Exception as e:
            print(f"NOTIFY status=OFF reason=owner_unknown({e}) "
                  f"hint=BRIDGE_OWNER_ID 환경변수에 디스코드 사용자 ID를 넣으세요")
            return False
    try:
        user = client.get_user(int(uid)) or await client.fetch_user(int(uid))
        await user.send(text)
        print(f"NOTIFY status=OK to={uid}")
        return True
    except Exception as e:
        print(f"NOTIFY status=FAIL to={uid} reason={e}")
        return False


async def count_translation(kind: str, guild=None):
    """번역 한 건을 세고, 통틀어 첫 건이면 마스터에게 알린다 (MSG-P2)."""
    try:
        first = _USAGE.record_translation()
    except Exception as e:
        print(f"COUNT status=FAIL reason={e}")
        return
    print(f"COUNT kind={kind} today={_USAGE.count_for()}")
    if first:
        where = getattr(guild, "name", None)
        await notify_owner(
            "🎊 **첫 번역이 나왔습니다**\n"
            f"경로: {kind}" + (f"\n서버: {where}" if where else ""))


async def push_botlist_stats():
    """봇 목록 사이트에 현재 서버 수를 올린다 (MSG-P3). 꺼져 있으면 그냥 넘어간다."""
    if not botlists.enabled_providers():
        return
    bot_id = getattr(client.user, "id", None)
    if bot_id is None:
        print("BOTLIST post=SKIP reason=아직 로그인 전")
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as sess:
            await botlists.post_stats(sess, bot_id, len(client.guilds))
    except Exception as e:
        print(f"BOTLIST post=FAIL reason={e}")


async def _botlist_loop():
    """30분마다 서버 수를 올린다. 사이트 쪽 통계가 멈춰 보이면 여기부터 본다."""
    await client.wait_until_ready()
    while not client.is_closed():
        await push_botlist_stats()
        try:
            await asyncio.sleep(1800)
        except asyncio.CancelledError:
            raise


async def _daily_report_loop():
    """KST 자정이 지나면 전날 집계를 한 번 보낸다."""
    await client.wait_until_ready()
    last_sent = outreach.today_kst()
    while not client.is_closed():
        try:
            await asyncio.sleep(300)           # 5분마다 날짜만 확인
            today = outreach.today_kst()
            if today != last_sent:
                await notify_owner(outreach.daily_report_text(
                    last_sent, _USAGE.count_for(last_sent), len(client.guilds)))
                last_sent = today
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"DAILY status=FAIL reason={e}")


def _first_sendable_channel(guild):
    """인사를 보낼 수 있는 첫 채널. 없으면 None (지어내지 않는다)."""
    me = guild.me
    candidates = []
    if guild.system_channel:
        candidates.append(guild.system_channel)
    candidates.extend(guild.text_channels)
    for ch in candidates:
        try:
            if ch.permissions_for(me).send_messages:
                return ch
        except Exception:
            continue
    return None


def voice_diag():
    """시작 시 음성 transport 전제조건을 로그로 남긴다 (VOICE_DIAG)."""
    import sys
    print("VOICE_DIAG")
    print(f"python_executable={sys.executable}")
    print(f"discord_version={discord.__version__}")
    for mod in ("nacl", "davey", "edge_tts"):
        try:
            __import__(mod)
            print(f"{mod}=OK")
        except Exception:
            print(f"{mod}=FAIL")
    print("voice_connect=PENDING (첫 음성채널 접속 시 OK/FAIL 기록)")


def translate(text: str, target: str) -> str:
    """로컬 NLLB 우선(할당량 없음·오프라인), 실패 시에만 Gemini 폴백."""
    try:
        from nllb_local import translate_local
        out = translate_local(text, target, source="auto")
        if out:
            return out
    except Exception as e:
        print("[Bridge] 로컬 번역 실패, Gemini 폴백:", e)
    try:
        lang = _LANG.get(target, target)
        r = _gem.generate_content(
            f"Translate into {lang}. Output ONLY the translation:\n\n{text}")
        return (r.text or "").strip()
    except Exception as e:
        print("[Bridge] 번역 오류:", e)
        return ""


async def tts_to_file(text: str, lang: str) -> str:
    voice = VOICES.get(lang, VOICES["en"])
    path = os.path.join(tempfile.gettempdir(), f"bridge_tts_{uuid.uuid4().hex}.mp3")
    await edge_tts.Communicate(text, voice).save(path)
    return path


async def _ensure_voice(voice_channel):
    """음성채널 접속 보장. 성공 시 vc, 실패 시 None (+ 로그)."""
    vc = discord.utils.get(client.voice_clients, guild=voice_channel.guild)
    try:
        if vc and vc.is_connected():
            if vc.channel.id != voice_channel.id:
                await vc.move_to(voice_channel)
        else:
            try:
                from discord.ext.voice_recv import VoiceRecvClient
                vc = await voice_channel.connect(cls=VoiceRecvClient)
            except Exception as e_cls:
                print(f"[Bridge] VoiceRecvClient 접속 실패, 일반 접속 폴백: {e_cls}")
                vc = await voice_channel.connect()
    except Exception as e:
        print("[Bridge] 음성채널 연결 오류:", e)
        print("voice_connect=FAIL")
        return None
    print("voice_connect=OK")
    print("VOICE_RUNTIME")
    print(f"vc_type={type(vc).__module__}.{type(vc).__name__}")
    try:
        from discord.ext.voice_recv import VoiceRecvClient as _VRC
        print(f"voice_recv_client={isinstance(vc, _VRC)}")
    except Exception:
        print("voice_recv_client=UNKNOWN(voice_recv import 실패)")
    _VOICE_SESSION["connect_count"] += 1
    _VOICE_SESSION["last_channel_id"] = getattr(voice_channel, "id", None)
    global _VOICE_CHANNEL
    _VOICE_CHANNEL = voice_channel
    _start_listen(vc)
    return vc


async def speak_in_channel(voice_channel, text: str, lang: str):
    """글쓴 사람이 있는 음성채널에 봇이 들어가 TTS 재생."""
    async with _play_lock:
        vc = await _ensure_voice(voice_channel)
        if vc is None:
            return
        mp3 = None
        try:
            mp3 = await tts_to_file(text, lang)
            done = asyncio.Event()

            def _after(err):
                if err:
                    print("[Bridge] 재생 오류:", err)
                client.loop.call_soon_threadsafe(done.set)

            vc.play(discord.FFmpegPCMAudio(mp3), after=_after)
            await done.wait()
        except Exception as e:
            print("[Bridge] TTS/재생 오류:", e)
        finally:
            if mp3:
                try:
                    os.remove(mp3)
                except Exception:
                    pass


async def voice_output(uid, text):
    """STT 출력 스테이지: 번역 → 음성방 채팅 → TTS → playback."""
    loop = asyncio.get_running_loop()
    translated = await loop.run_in_executor(None, translate, text, "en")
    print(f"VOICE_TRANSLATE source_lang=ko target_lang=en "
          f'source="{text}" translated="{translated}"')
    if not translated.strip():
        return
    channel = _VOICE_CHANNEL
    outreach.append_turn(text, translated, "ko", "en", "음성")
    await count_translation("음성", getattr(channel, "guild", None))
    if channel is not None:
        try:
            await channel.send(f"[en] {translated}")
            print(f"VOICE_TEXT_SEND channel_id={getattr(channel, 'id', '?')} "
                  f"status=OK")
        except Exception as e:
            print(f"VOICE_TEXT_SEND status=FAIL({e})")
    if translated.strip() == (_LAST_TTS_TEXT["text"] or ""):
        print("VOICE_TTS status=SKIP(duplicate)")
        return
    try:
        mp3 = await tts_to_file(translated, "en")
        print(f"VOICE_TTS engine=edge-tts lang=en file={mp3} status=OK")
    except Exception as e:
        print(f"VOICE_TTS status=FAIL({e})")
        return
    _LAST_TTS_TEXT["text"] = translated.strip()
    try:
        vc = None
        guild = getattr(channel, "guild", None)
        if guild is not None:
            vc = discord.utils.get(client.voice_clients, guild=guild)
        if vc is None or not vc.is_connected():
            print("VOICE_PLAY status=SKIP(not connected)")
            return
        async with _play_lock:
            done = asyncio.Event()
            running = asyncio.get_running_loop()

            def _after(err):
                if err:
                    print("[Bridge] 재생 오류:", err)
                running.call_soon_threadsafe(done.set)

            vc.play(discord.FFmpegPCMAudio(mp3), after=_after)
            print(f"VOICE_PLAY voice_client={type(vc).__module__}."
                  f"{type(vc).__name__} playing={vc.is_playing()} status=OK")
            await done.wait()
    except Exception as e:
        print(f"VOICE_PLAY status=FAIL({e})")
    finally:
        try:
            os.remove(mp3)
        except Exception:
            pass


def _start_listen(vc):
    """수신 시작 (1회만). voice_recv 없으면 조용히 스킵."""
    if getattr(vc, "_bridge_listening", False):
        return
    try:
        from discord.ext.voice_recv import VoiceRecvClient
    except Exception as e:
        print(f"[Bridge] voice_recv 없음, 수신 스킵: {e}")
        return
    if not isinstance(vc, VoiceRecvClient):
        print("[Bridge] VoiceRecvClient 아님, 수신 스킵")
        return
    import asyncio
    import traceback
    from voice_in import ReceiveSink
    me = client.user.id if client.user else None
    print("[VOICE] listen BEFORE")
    try:
        sink = ReceiveSink(asyncio.get_running_loop(), bot_user_id=me,
                           on_utterance=voice_output)
        print(f"VOICE_SINK sink_type={type(sink).__module__}.{type(sink).__name__} sink_created=OK")
        vc.listen(sink)
    except Exception:
        print("[VOICE] listen FAIL")
        traceback.print_exc()
        return
    print("[VOICE] listen AFTER")
    try:
        print(f"is_listening={vc.is_listening()} sink_set={vc.sink is not None}")
    except Exception as e:
        print(f"is_listening=UNKNOWN({e})")
    vc._bridge_listening = True
    print("[Bridge] 음성 수신 시작 (listen)")


@client.event
async def on_ready():
    print(f"[INDEX Bridge · Voice] 로그인됨: {client.user}")
    print(f"  음성={VOICE_LANG} / 텍스트={TEXT_LANG}   (채팅에 !flip 치면 뒤집힘, !leave 로 음성 나감)")
    print(f"  서버 {len(client.guilds)}곳 · 오늘 번역 {_USAGE.count_for()}건")
    try:
        print(f"  초대링크: {outreach.invite_url(getattr(client.user, 'id', None))}")
    except ValueError as e:
        print(f"  초대링크 생성 실패: {e}")
    print(f"  {botlists.describe_status()}")
    if not _DAILY_TASK_STARTED["v"]:        # on_ready 는 재접속마다 다시 불린다
        _DAILY_TASK_STARTED["v"] = True
        client.loop.create_task(_daily_report_loop())
        client.loop.create_task(_botlist_loop())


@client.event
async def on_guild_join(guild):
    """새 서버에 초대됨 — 인사 한 번 + 마스터 통지 (MSG-P1/P2)."""
    print(f"GUILD_JOIN id={guild.id} name={guild.name} "
          f"members={getattr(guild, 'member_count', '?')}")
    ch = _first_sendable_channel(guild)
    if ch is None:
        print("GUILD_JOIN intro=SKIP(보낼 수 있는 채널 없음)")
    else:
        try:
            await ch.send(outreach.intro_text())
            print(f"GUILD_JOIN intro=OK channel={ch.name}")
        except Exception as e:
            print(f"GUILD_JOIN intro=FAIL({e})")
    await notify_owner(
        f"🎉 새 서버에 초대됐습니다\n"
        f"**{guild.name}** · 멤버 {getattr(guild, 'member_count', '?')}명\n"
        f"이제 서버 {len(client.guilds)}곳입니다.")
    await push_botlist_stats()      # 서버 수가 바뀌었으니 목록 사이트도 갱신


@client.event
async def on_guild_remove(guild):
    """서버에서 빠짐 — 서버 수가 줄었으니 목록도 줄여야 맞다."""
    print(f"GUILD_REMOVE id={guild.id} name={guild.name} "
          f"remaining={len(client.guilds)}")
    await push_botlist_stats()


@client.event
async def on_voice_state_update(member, before, after):
    """봇 자신의 음성 상태 변화만 세션 계측 (4006 관찰용)."""
    if client.user is None or member.id != client.user.id:
        return
    if before.channel != after.channel:
        if after.channel is None:
            _VOICE_SESSION["disconnect_count"] += 1
        else:
            _VOICE_SESSION["reconnect_count"] += 1
        print(f"VOICE_SESSION connect_count={_VOICE_SESSION['connect_count']} "
              f"disconnect_count={_VOICE_SESSION['disconnect_count']} "
              f"last_close_code={_VOICE_SESSION['last_close_code']} "
              f"reconnect_count={_VOICE_SESSION['reconnect_count']}")


@client.event
async def on_message(message: discord.Message):
    global VOICE_LANG, TEXT_LANG
    if message.author.bot:
        return
    content = (message.content or "").strip()
    if not content:
        return

    low = content.lower()
    if low in ("!help", "!도움", "!도움말"):
        await message.channel.send(outreach.help_text())
        return
    if low in ("!invite", "!초대"):
        try:
            # getattr 로 받는다 — 로그인 전이면 user 가 None 이고,
            # client.user.id 는 ValueError 가 아니라 AttributeError 를 내서
            # 아래 그물을 그냥 빠져나간다(사용자는 아무 답도 못 받는다).
            await message.channel.send(
                f"이 링크로 다른 서버에 데려갈 수 있습니다:\n"
                f"{outreach.invite_url(getattr(client.user, 'id', None))}")
        except ValueError as e:
            print(f"INVITE status=FAIL({e})")
            await message.channel.send(
                "초대링크를 지금 만들지 못했습니다. 잠시 후 다시 시도해주세요.")
        return
    if low == "!flip":
        VOICE_LANG, TEXT_LANG = TEXT_LANG, VOICE_LANG
        await message.channel.send(f"🔁 이제  음성={VOICE_LANG} / 텍스트={TEXT_LANG}")
        return
    if low == "!leave":
        vc = discord.utils.get(client.voice_clients, guild=message.guild)
        if vc:
            await vc.disconnect()
        return
    if low == "!join":
        author_voice = getattr(message.author, "voice", None)
        if not (author_voice and author_voice.channel):
            await message.channel.send("음성채널에 먼저 들어가주세요.")
            return
        ch = author_voice.channel
        vc = await _ensure_voice(ch)
        if vc is None:
            await message.channel.send("voice_connect=FAIL")
            return
        print("VOICE_CONNECT")
        print(f"channel_id={ch.id}")
        print(f"channel_name={ch.name}")
        print("voice_connect=OK")
        print(f"recv_listening={'OK' if getattr(vc, '_bridge_listening', False) else 'SKIP'}")
        # 처음 불러본 사람에게만 쓰는 법을 개인 메시지로 한 번 (MSG-P1).
        # DM이 닫혀 있으면 실패하는데, 그건 사용자 설정이지 고장이 아니다.
        if _USAGE.needs_onboarding(message.author.id):
            try:
                await message.author.send(outreach.onboarding_text())
                print(f"ONBOARD status=OK user={message.author.id}")
            except Exception as e:
                print(f"ONBOARD status=FAIL user={message.author.id} reason={e}")
            finally:
                _USAGE.mark_onboarded(message.author.id)
        return
    if low.startswith("!"):
        return  # 그 외 명령은 무시

    if CHANNEL_NAME and getattr(message.channel, "name", "") != CHANNEL_NAME:
        return

    loop = asyncio.get_running_loop()

    # 1) 텍스트 채널 → TEXT_LANG
    text_out = await loop.run_in_executor(None, translate, content, TEXT_LANG)
    if text_out.strip() and text_out.strip().lower() != content.lower():
        await message.reply(f"[{TEXT_LANG}] {text_out}", mention_author=False)
        outreach.append_turn(content, text_out, "auto", TEXT_LANG, "텍스트")
        await count_translation("텍스트", message.guild)

    # 2) 음성 채널 → VOICE_LANG (글쓴 사람이 음성채널에 있을 때만)
    author_voice = getattr(message.author, "voice", None)
    if author_voice and author_voice.channel:
        voice_out = await loop.run_in_executor(None, translate, content, VOICE_LANG)
        if voice_out.strip():
            await speak_in_channel(author_voice.channel, voice_out, VOICE_LANG)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("환경변수 DISCORD_BOT_TOKEN 에 봇 토큰을 넣고 실행하세요.")
    voice_diag()
    client.run(TOKEN)
