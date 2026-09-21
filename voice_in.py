# -*- coding: utf-8 -*-
"""Discord 음성 수신 → PCM → STT (최소구현).

경로: VoiceRecvClient.listen(sink) → RecvLogSink.write(user, data)
      → data.pcm 누적 → faster-whisper(small/CPU) → VOICE_PIPELINE 로그.

- 봇 자신의 user_id 패킷은 receive 단계에서 제외 (TTS 재입력 방지).
- 이 단계에서는 로그만 남긴다. NLLB/TTS/채팅 출력은 다음 단계.
"""
import asyncio
import time

LISTEN_PCM_RATE = 48000   # voice_recv sink PCM (discord voice 표준)
LISTEN_CHANNELS = 2
CHUNK_SEC = 4.0           # 이만큼 모이면 1회 STT

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
    idx = (np.arange(int(len(raw) * 16000 / LISTEN_PCM_RATE))).astype(int)
    return raw[idx[idx < len(raw)]]


class RecvLogSink:
    """AudioSink 프로토콜: write(user, data). listen()에 직접 전달."""

    def __init__(self, loop, bot_user_id=None):
        try:
            from discord.ext.voice_recv import AudioSink
            AudioSink.__init__(self)
        except Exception:
            import traceback
            print("[Bridge] sink init 실패:")
            traceback.print_exc()
        self.loop = loop
        self.bot_user_id = bot_user_id
        self._buf = {}
        self.rx_count = 0

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
        buf = self._buf.setdefault(uid, b"") + pcm
        need = int(LISTEN_PCM_RATE * LISTEN_CHANNELS * 2 * CHUNK_SEC)
        if len(buf) >= need:
            self._buf[uid] = b""
            self.loop.run_in_executor(None, self._stt, uid, buf)

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
        except Exception as e:
            print(f"VOICE_PIPELINE RX=OK DECODE=OK STT=FAIL({e}) "
                  f"TRANSLATE=- TEXT_SEND=- TTS=-")

    def cleanup(self):
        pass
