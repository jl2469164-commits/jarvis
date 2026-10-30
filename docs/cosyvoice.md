# Local CosyVoice (JARVIS voice)

JARVIS speaks with a local [CosyVoice](https://github.com/FunAudioLLM/CosyVoice)
model. `tts.py` returns one 16-bit WAV per sentence. The browser plays it
with the audio player it already has (`AudioContext.decodeAudioData`). No
Fish Audio key is required.

Weights are large (about 2 GB for CosyVoice2-0.5B). Do not commit them.

CPU works on a Mac and on a machine with no GPU. It is slow: several seconds
for one short sentence is normal. CUDA is faster when you have an NVIDIA GPU.
`COSYVOICE_DEVICE=mps` is best-effort; if synthesis throws, use `cpu`.

## Install

```bash
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git
cd CosyVoice
pip install -r requirements.txt
```

Optional, from this JARVIS checkout, if that install did not pull torch:

```bash
pip install -r requirements-cosyvoice.txt
```

Download CosyVoice2-0.5B (preferred) into a folder outside git. Hugging Face:

```bash
pip install -U huggingface_hub
huggingface-cli download FunAudioLLM/CosyVoice2-0.5B \
  --local-dir "$HOME/models/CosyVoice2-0.5B"
```

ModelScope is the other official source (`iic/CosyVoice2-0.5B`). Either
snapshot is fine if it contains `cosyvoice2.yaml`.

Record a few seconds of the voice you want (16 kHz mono WAV is ideal) and
write down exactly what was said.

## Wire it

In `.env` (copy from `.env.example`; placeholders only, no real secrets):

```bash
COSYVOICE_REPO=/absolute/path/to/CosyVoice
COSYVOICE_MODEL_DIR=/absolute/path/to/CosyVoice2-0.5B
COSYVOICE_PROMPT_WAV=/absolute/path/to/prompt.wav
COSYVOICE_PROMPT_TEXT=The words spoken in that wav file.
COSYVOICE_DEVICE=cpu
```

`cpu`, `cuda`, or `mps`. On a Mac without a working MPS run, leave `cpu`.

An SFT checkpoint that already has named speakers can use
`COSYVOICE_SPEAKER` instead of the prompt wav and transcript.

Restart the server. Preflight check `cosyvoice` fails until the directory,
the voice, and `import cosyvoice` all succeed. Each sentence still goes out
on the existing voice WebSocket as one audio frame.

`FISH_API_KEY` is ignored by `tts.py`. The settings panel in the browser
still has the old Fish fields; leave them blank.
