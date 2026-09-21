# -*- coding: utf-8 -*-
"""Discord 음성 수신 → PCM → STT (최소구현).

경로: VoiceRecvClient.listen(sink) → RecvLogSink.write(user, data)
      → data.pcm 누적 → faster-whisper(small/CPU) → VOICE_PIPELINE 로그.

- 봇 자신의 user_id 패킷은 receive 단계에서 제외 (TTS 재입력 방지).
- 이 단계에서는 로그만 남긴다. NLLB/TTS/채팅 출력은 다음 단계.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor

from discord.ext.voice_recv import AudioSink
LISTEN_PCM_RATE = 48000   # voice_recv sink PCM (discord voice 표준)
LISTEN_CHANNELS = 2
CHUNK_SEC = 8.0           # 최대 발화 길이
SILENCE_SEC = 0.6
MIN_SPEECH_SEC = 0.3

_listen_model = None


def _get_model():
    global _listen_model
    if _listen_model is None:
        from faster_whisper import WhisperModel
        _listen_model = WhisperModel("small", device="cpu",
                                     compute_type="int8")
    return _listen_model


def _to_16k_mono(pcm_bytes):
    """48k stereo int16 → 16k mono float32 (whisper 입력)."""
    import numpy as np
    raw = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    raw = raw.reshape(-1, LISTEN_CHANNELS).mean(axis=1) / 32768.0
    idx = (np.arange(int(len(raw) * 16000 / LISTEN_PCM_RATE))
           * LISTEN_PCM_RATE / 16000).astype(int)
    return raw[idx[idx < len(raw)]]


class ReceiveSink(AudioSink):
    """AudioSink 상속 (vc.listen 타입 검사 통과). wants_opus=False → PCM 수신."""

    def __init__(self, loop, bot_user_id=None, on_utterance=None):
        super().__init__()
        self.loop = loop
        self.bot_user_id = bot_user_id
        self.on_utterance = on_utterance  # async callable (uid, text)
        self._buf = {}
        self.rx_count = 0
        self._timers = {}
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-stt")

    def wants_opus(self):
        return False

    def write(self, user, data):
        print(f"VOICE_RX_RAW user={getattr(user, 'id', None)} "
              f"ssrc={getattr(getattr(data, 'packet', None), 'ssrc', None)} "
              f"pcm={len(getattr(data, 'pcm', None) or b'')}", flush=True)
        uid = getattr(user, "id", None)
        if uid is not None and uid == self.bot_user_id:
            return  # 봇 자신의 TTS 재입력 차단
        pcm = getattr(data, "pcm", b"") or b""
        packet = getattr(data, "packet", None)
        ssrc = getattr(packet, "ssrc", "?")
        self.rx_count += 1
        print(f"VOICE_RX user_id={uid} ssrc={ssrc} "
              f"packet_received=true audio_bytes={len(pcm)}")
        if not pcm:
            return
        print(f"VOICE_DECODE user_id={uid} pcm_bytes={len(pcm)} "
              f"decode=OK")
        # Audio reader runs on another thread; own buffers/timers on asyncio loop.
        if not self._closed and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._append_pcm, uid, bytes(pcm))

    def _append_pcm(self, uid, pcm):
        if self._closed:
            return
        timer = self._timers.pop(uid, None)
        if timer is not None:
            timer.cancel()
        buf = self._buf.setdefault(uid, bytearray())
        buf.extend(pcm)
        duration_ms = len(buf) * 1000 / (LISTEN_PCM_RATE * LISTEN_CHANNELS * 2)
        print(f"VOICE_BUFFER user_id={uid} pcm_bytes={len(buf)} "
              f"duration_ms={duration_ms:.0f}", flush=True)
        if duration_ms >= CHUNK_SEC * 1000:
            self._flush(uid, "duration")
        else:
            self._timers[uid] = self.loop.call_later(
                SILENCE_SEC, self._flush, uid, "silence")

    def _flush(self, uid, reason):
        timer = self._timers.pop(uid, None)
        if timer is not None:
            timer.cancel()
        buf = bytes(self._buf.pop(uid, b""))
        if self._closed or not buf:
            return
        duration_ms = len(buf) * 1000 / (LISTEN_PCM_RATE * LISTEN_CHANNELS * 2)
        print(f"VOICE_ENDPOINT user_id={uid} reason={reason} "
              f"duration_ms={duration_ms:.0f}", flush=True)
        if duration_ms < MIN_SPEECH_SEC * 1000:
            print(f"VOICE_STT_SKIP user_id={uid} reason=too_short", flush=True)
            return
        print(f"VOICE_STT_CALL user_id={uid} pcm_bytes={len(buf)} "
              f"duration_ms={duration_ms:.0f}", flush=True)
        self.loop.run_in_executor(self._executor, self._stt, uid, buf)

    def _stt(self, uid, buf):
        try:
            audio = _to_16k_mono(buf)
            segs, info = _get_model().transcribe(
                audio, language="ko", beam_size=1,
                condition_on_previous_text=False,
                no_speech_threshold=0.6)
            text = " ".join(s.text.strip() for s in segs
                            if s.text.strip())
            if text:
                print(f'VOICE_PIPELINE RX=OK DECODE=OK STT="{text}" '
                      f"TRANSLATE=- TEXT_SEND=- TTS=-")
                print(f'VOICE_STT user_id={uid} text="{text}"')
                if self.on_utterance is not None:
                    cb = self.on_utterance
                    self.loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(cb(uid, text)))
        except Exception as e:
            print(f"VOICE_PIPELINE RX=OK DECODE=OK STT=FAIL({e}) "
                  f"TRANSLATE=- TEXT_SEND=- TTS=-")

    def cleanup(self):
        self._closed = True
        if not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._cleanup_loop)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _cleanup_loop(self):
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
        self._buf.clear()
