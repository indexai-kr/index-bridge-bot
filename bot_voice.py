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
