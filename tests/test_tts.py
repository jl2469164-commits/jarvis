"""Local CosyVoice synthesis. No network, no weights, no torch."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent


def _config():
    import tts
    return tts.CosyVoiceConfig(
        model_dir="/models/CosyVoice2-0.5B",
        prompt_wav="/voices/prompt.wav",
        prompt_text="Good evening.",
        device="cpu",
    )


@pytest.mark.asyncio
async def test_fake_synthesizer_returns_one_complete_wav():
    import speech
    import tts
    seen = {}

    def fake(text, config):
        seen["text"] = text
        seen["device"] = config.device
        return tts.pcm16_wav(b"\x01\x00" * 2400, 24000)

    result = await tts.synthesize_chunk(
        "Good evening, sir.", config=_config(), synthesizer=fake)
    assert seen == {"text": "Good evening, sir.", "device": "cpu"}
    assert result is not None
    assert result.audio.startswith(b"RIFF")
    assert result.total_sec >= result.first_byte_sec >= 0
    assert abs(speech.wav_seconds(result.audio) - 0.1) < 0.01


@pytest.mark.asyncio
async def test_empty_text_does_not_call_the_synthesizer():
    import tts
    calls = []

    def fake(text, config):
        calls.append(text)
        return b"RIFF"

    assert await tts.synthesize_chunk("   ", config=_config(), synthesizer=fake) is None
    assert calls == []


@pytest.mark.asyncio
async def test_unready_config_returns_none_without_loading_a_model(monkeypatch):
    import tts
    monkeypatch.delenv("COSYVOICE_MODEL_DIR", raising=False)
    assert await tts.synthesize_chunk("hello") is None


@pytest.mark.asyncio
async def test_synthesizer_error_returns_none():
    import tts

    def boom(text, config):
        raise RuntimeError("weights missing")

    assert await tts.synthesize_chunk("hello", config=_config(), synthesizer=boom) is None


@pytest.mark.asyncio
async def test_timeout_returns_none():
    import tts

    def slow(text, config):
        time.sleep(0.4)
        return tts.pcm16_wav(b"\x00\x00" * 8, 8000)

    assert await tts.synthesize_chunk(
        "hello", config=_config(), synthesizer=slow, timeout=0.05) is None


def test_old_fish_arguments_are_ignored():
    import asyncio
    import tts

    def fake(text, config):
        return tts.pcm16_wav(b"\x00\x00" * 8, 8000)

    result = asyncio.run(tts.synthesize_chunk(
        "hello", config=_config(), synthesizer=fake,
        api_key="should-not-be-sent", voice_id="fish", client=object(),
        latency="balanced"))
    assert result is not None and result.audio.startswith(b"RIFF")


def test_voice_modules_do_not_call_fish_audio():
    for name in ("tts.py", "server.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "api.fish.audio" not in text, name
        assert "FISH_API_URL" not in text, name


def test_pcm16_wav_is_mono_16bit():
    import tts
    blob = tts.pcm16_wav(b"\x00\x01" * 4, 16000)
    assert blob[8:12] == b"WAVE"
    assert b"data" in blob
