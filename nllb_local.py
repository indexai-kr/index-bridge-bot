# -*- coding: utf-8 -*-
"""로컬 NLLB 번역 (TMP-P1 재사용, CT2 int8, CPU).

모델: C:\\Projects\\tmp-voice-log\\models\\nllb-200-distilled-600M-ct2
토크나이저: 같은 폴더의 nllb-200-distilled-600M-hf (로컬 경로, 오프라인).
환경변수 NLLB_CT2_DIR / NLLB_HF_DIR 로 경로 변경 가능.
"""
import os
import re

_BASE = r"C:\Projects\tmp-voice-log\models"
CT2_DIR = os.environ.get("NLLB_CT2_DIR",
                         os.path.join(_BASE, "nllb-200-distilled-600M-ct2"))
HF_DIR = os.environ.get("NLLB_HF_DIR",
                        os.path.join(_BASE, "nllb-200-distilled-600M-hf"))

NLLB_CODE = {"en": "eng_Latn", "ko": "kor_Hang",
             "ja": "jpn_Jpan", "zh-CN": "zho_Hans"}

_CLAUSE_SPLIT = re.compile(r"[,，、.!?。！？]+")
_HANGUL = re.compile(r"[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]")

_translator = None
_tokenizer = None


def detect_source(text):
    """텍스트봇과 같은 규칙: 한글 포함이면 ko, 아니면 en."""
    return "ko" if _HANGUL.search(text or "") else "en"


def _load():
    global _translator, _tokenizer
    if _translator is not None:
        return
    import ctranslate2
    from transformers import AutoTokenizer
    _translator = ctranslate2.Translator(CT2_DIR, device="cpu",
                                         compute_type="int8")
    _tokenizer = AutoTokenizer.from_pretrained(HF_DIR, local_files_only=True)


def translate_local(text, target, source="auto"):
    """translate(text, target) -> str. 실패하면 예외를 던진다(호출자가 폴백)."""
    if source == "auto":
        source = detect_source(text)
    src_code, tgt_code = NLLB_CODE.get(source), NLLB_CODE.get(target)
    if not src_code or not tgt_code:
        raise ValueError(f"unsupported pair: {source}->{target}")
    _load()
    _tokenizer.src_lang = src_code
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(text) if c.strip()]
    if not clauses:
        return ""
    batch = [_tokenizer.convert_ids_to_tokens(_tokenizer.encode(c))
             for c in clauses]
    results = _translator.translate_batch(
        batch, target_prefix=[[tgt_code]] * len(batch),
        beam_size=1, length_penalty=1.5,
        no_repeat_ngram_size=3, max_decoding_length=256)
    outs = []
    for r in results:
        hyp = r.hypotheses[0]
        if hyp and hyp[0] == tgt_code:
            hyp = hyp[1:]
        outs.append(_tokenizer.decode(
            _tokenizer.convert_tokens_to_ids(hyp)))
    return " ".join(outs).strip()
