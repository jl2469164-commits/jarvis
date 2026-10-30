"""Local CosyVoice synthesis, one utterance per sentence.

The browser still receives one complete audio blob per sentence and decodes
it with `AudioContext.decodeAudioData` (`frontend/src/voice.ts`). This module
returns 16-bit PCM WAV, which Chrome already plays. It does not call a
cloud TTS API.

CosyVoice (prefer CosyVoice2 when `cosyvoice2.yaml` is in the model dir) is
imported lazily, inside the inference thread, so the server and the test
suite boot without torch. Weights are not part of this repository.

CPU works. It is slow: a short sentence often takes several seconds, and a
long one longer. CUDA is what upstream targets when a GPU is present. MPS is
best-effort on Macs; if an op is missing, set COSYVOICE_DEVICE=cpu.
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import logging
import os
import sys
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("jarvis.tts")

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"

_DEVICES = ("cpu", "cuda", "mps")
_DEFAULT_TIMEOUT = 120.0
_engine_lock = threading.Lock()
_engine = None
_engine_key: Optional[tuple] = None


@dataclass
class SynthResult:
    audio: bytes
    first_byte_sec: float
    total_sec: float


@dataclass(frozen=True)
class CosyVoiceConfig:
    """Where the local model lives, and which voice to clone or select."""
    model_dir: str = ""
    prompt_wav: str = ""
    prompt_text: str = ""
    speaker: str = ""
    device: str = "cpu"
    repo: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> "CosyVoiceConfig":
        raw_timeout = os.environ.get("COSYVOICE_TIMEOUT", "").strip()
        try:
            timeout = float(raw_timeout) if raw_timeout else _DEFAULT_TIMEOUT
        except ValueError:
            timeout = _DEFAULT_TIMEOUT
        if timeout <= 0:
            timeout = _DEFAULT_TIMEOUT
        device = os.environ.get("COSYVOICE_DEVICE", "cpu").strip().lower() or "cpu"
        return cls(
            model_dir=os.environ.get("COSYVOICE_MODEL_DIR", "").strip(),
            prompt_wav=os.environ.get("COSYVOICE_PROMPT_WAV", "").strip(),
            prompt_text=os.environ.get("COSYVOICE_PROMPT_TEXT", "").strip(),
            speaker=os.environ.get("COSYVOICE_SPEAKER", "").strip(),
            device=device,
            repo=os.environ.get("COSYVOICE_REPO", "").strip(),
            timeout=timeout,
        )


@dataclass(frozen=True)
class Readiness:
    status: str
    message: str
    remedy: Optional[str] = None


def ensure_repo_on_path(repo: str = "") -> None:
    """Put a CosyVoice checkout and its Matcha-TTS third party on sys.path.

    The upstream project is a git tree, not a wheel. `COSYVOICE_REPO` is that
    checkout. Missing directories are ignored.
    """
    root = (repo or os.environ.get("COSYVOICE_REPO", "")).strip()
    if not root:
        return
    root_path = Path(root).expanduser()
    entries = [root_path, root_path / "third_party" / "Matcha-TTS"]
    for entry in entries:
        if not entry.is_dir():
            continue
        text = str(entry)
        if text not in sys.path:
            sys.path.insert(0, text)


def cosyvoice_importable(repo: str = "") -> bool:
    """True when `import cosyvoice` would resolve. Does not load the model."""
    ensure_repo_on_path(repo)
    try:
        return importlib.util.find_spec("cosyvoice") is not None
    except (ImportError, ValueError):
        return False


def _model_dir(config: CosyVoiceConfig) -> Path:
    return Path(config.model_dir).expanduser()


def looks_like_model_dir(path: Path) -> bool:
    """A downloaded CosyVoice / CosyVoice2 snapshot, not an empty folder."""
    if not path.is_dir():
        return False
    if (path / "cosyvoice2.yaml").is_file() or (path / "cosyvoice.yaml").is_file():
        return True
    return (path / "llm.pt").is_file()


def readiness(config: Optional[CosyVoiceConfig] = None) -> Readiness:
    """Whether a sentence can be synthesized. Never loads weights."""
    cfg = config or CosyVoiceConfig.from_env()
    if not cfg.model_dir:
        return Readiness(
            STATUS_FAIL,
            "COSYVOICE_MODEL_DIR is not set.",
            "Download CosyVoice2-0.5B and set COSYVOICE_MODEL_DIR. "
            "See docs/cosyvoice.md. CPU works and is slow.",
        )
    path = _model_dir(cfg)
    if not path.is_dir():
        return Readiness(
            STATUS_FAIL,
            f"COSYVOICE_MODEL_DIR is not a directory: {path}",
            "Point COSYVOICE_MODEL_DIR at the extracted CosyVoice2-0.5B folder.",
        )
    if not looks_like_model_dir(path):
        return Readiness(
            STATUS_FAIL,
            f"{path} has no cosyvoice2.yaml, cosyvoice.yaml, or llm.pt.",
            "Download the model weights into that directory. Do not commit them.",
        )
    if cfg.prompt_wav:
        prompt = Path(cfg.prompt_wav).expanduser()
        if not prompt.is_file():
            return Readiness(
                STATUS_FAIL,
                f"COSYVOICE_PROMPT_WAV is not a file: {prompt}",
                "Record a few seconds of the voice to clone and set COSYVOICE_PROMPT_WAV.",
            )
        if not cfg.prompt_text:
            return Readiness(
                STATUS_FAIL,
                "COSYVOICE_PROMPT_TEXT is empty.",
                "Set COSYVOICE_PROMPT_TEXT to the transcript of the prompt wav. "
                "Zero-shot CosyVoice2 needs both.",
            )
    elif not cfg.speaker:
        return Readiness(
            STATUS_FAIL,
            "No CosyVoice voice is configured.",
            "Set COSYVOICE_PROMPT_WAV and COSYVOICE_PROMPT_TEXT for zero-shot, "
            "or COSYVOICE_SPEAKER for an SFT speaker id baked into the model.",
        )
    if cfg.device not in _DEVICES:
        return Readiness(
            STATUS_FAIL,
            f"COSYVOICE_DEVICE must be cpu, cuda, or mps (got {cfg.device!r}).",
            "Use cpu on a Mac with no GPU. It is slow. mps is best-effort.",
        )
    if cfg.repo and not Path(cfg.repo).expanduser().is_dir():
        return Readiness(
            STATUS_FAIL,
            f"COSYVOICE_REPO is not a directory: {cfg.repo}",
            "Clone https://github.com/FunAudioLLM/CosyVoice and set COSYVOICE_REPO.",
        )
    if not cosyvoice_importable(cfg.repo):
        return Readiness(
            STATUS_FAIL,
            "The cosyvoice package is not importable.",
            "Clone FunAudioLLM/CosyVoice, install its requirements, and set "
            "COSYVOICE_REPO (see docs/cosyvoice.md). CPU inference is slow.",
        )
    message = f"CosyVoice model at {path} on {cfg.device}."
    if (path / "cosyvoice2.yaml").is_file():
        message = f"CosyVoice2 model at {path} on {cfg.device}."
    if cfg.device == "cpu":
        message += " CPU inference is slow (several seconds per sentence)."
    elif cfg.device == "mps":
        message += " MPS is best-effort; if synthesis errors, switch to cpu."
    return Readiness(STATUS_OK, message)


def pcm16_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """One complete WAV blob. Chrome's decodeAudioData accepts this."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buf.getvalue()


def _tensor_to_wav(audio, sample_rate: int) -> bytes:
    import torch
    flat = audio.detach().float().cpu().reshape(-1).clamp(-1, 1)
    pcm = (flat * 32767.0).to(torch.int16).contiguous().numpy().tobytes()
    return pcm16_wav(pcm, sample_rate)


def _apply_device_env(device: str) -> None:
    """Hide CUDA when the user asked for cpu or mps, before torch is imported.

    CosyVoice selects cuda whenever it is visible. Setting this after torch
    has already been imported does not unload that context.
    """
    if device in ("cpu", "mps"):
        os.environ["CUDA_VISIBLE_DEVICES"] = ""


def _load_prompt(path: str):
    from cosyvoice.utils.file_utils import load_wav
    return load_wav(str(Path(path).expanduser()), 16000)


def _load_model(config: CosyVoiceConfig):
    ensure_repo_on_path(config.repo)
    _apply_device_env(config.device)
    import torch
    model_dir = str(_model_dir(config))
    if (Path(model_dir) / "cosyvoice2.yaml").is_file():
        from cosyvoice.cli.cosyvoice import CosyVoice2
        model = CosyVoice2(model_dir, load_jit=False, load_trt=False, fp16=False)
    else:
        from cosyvoice.cli.cosyvoice import CosyVoice
        model = CosyVoice(model_dir)
    target = config.device
    if target == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("COSYVOICE_DEVICE=cuda but CUDA is not available")
    if target == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("COSYVOICE_DEVICE=mps but MPS is not available")
    if target == "cpu":
        device = torch.device("cpu")
    elif target == "mps":
        device = torch.device("mps")
    else:
        device = torch.device("cuda")
    inner = getattr(model, "model", None)
    if inner is not None and hasattr(inner, "to"):
        inner.to(device)
    if hasattr(model, "device"):
        model.device = device
    return model


def _engine_for(config: CosyVoiceConfig):
    global _engine, _engine_key
    key = (str(_model_dir(config)), config.device, config.repo)
    if _engine is not None and _engine_key == key:
        return _engine
    _engine = _load_model(config)
    _engine_key = key
    return _engine


def reset_engine() -> None:
    """Drop the cached model. Tests and a config change call this."""
    global _engine, _engine_key
    with _engine_lock:
        _engine = None
        _engine_key = None


def synthesize_sync(text: str, config: CosyVoiceConfig,
                    synthesizer: Optional[Callable[[str, CosyVoiceConfig], bytes]] = None) -> bytes:
    """Blocking synthesis. Holds one lock so two sentences cannot share the model."""
    if synthesizer is not None:
        return synthesizer(text, config)
    with _engine_lock:
        model = _engine_for(config)
        pieces = []
        if config.prompt_wav:
            prompt = _load_prompt(config.prompt_wav)
            outputs = model.inference_zero_shot(
                text, config.prompt_text, prompt, stream=False)
        else:
            outputs = model.inference_sft(text, config.speaker, stream=False)
        for out in outputs:
            speech = out["tts_speech"]
            pieces.append(speech)
        if not pieces:
            return b""
        import torch
        audio = torch.cat(pieces, dim=-1)
        rate = int(getattr(model, "sample_rate", 24000) or 24000)
        return _tensor_to_wav(audio, rate)


async def synthesize_chunk(text: str, *,
                           config: Optional[CosyVoiceConfig] = None,
                           synthesizer: Optional[Callable[[str, CosyVoiceConfig], bytes]] = None,
                           timeout: Optional[float] = None,
                           api_key: str = "",
                           voice_id: str = "",
                           client: object = None,
                           latency: str = "balanced") -> Optional[SynthResult]:
    """One sentence in, one complete WAV blob out.

    `api_key`, `voice_id`, `client`, and `latency` are accepted and ignored.
    Callers that still pass the old Fish Audio arguments keep working; the
    voice path no longer contacts that API.

    Local inference has no streaming first byte. `first_byte_sec` is the time
    until the whole chunk is ready, same as `total_sec`.
    """
    del api_key, voice_id, client, latency
    text = (text or "").strip()
    if not text:
        return None
    cfg = config or CosyVoiceConfig.from_env()
    if synthesizer is None:
        state = readiness(cfg)
        if state.status != STATUS_OK:
            log.warning("TTS skipped: CosyVoice is not ready (%s)", state.message)
            return None
    budget = cfg.timeout if timeout is None else timeout
    t0 = time.monotonic()
    try:
        audio = await asyncio.wait_for(
            asyncio.to_thread(synthesize_sync, text, cfg, synthesizer),
            timeout=budget,
        )
    except asyncio.TimeoutError:
        log.error("TTS timed out after %.1fs for %r", budget, text[:40])
        return None
    except Exception as e:
        log.error("TTS error: %s", e)
        return None
    if not audio:
        return None
    elapsed = time.monotonic() - t0
    return SynthResult(audio, elapsed, elapsed)
