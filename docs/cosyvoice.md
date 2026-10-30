# Local CosyVoice (JARVIS voice)

JARVIS speaks with a local [CosyVoice](https://github.com/FunAudioLLM/CosyVoice)
model. `tts.py` returns one 16-bit WAV per sentence. The browser plays that
blob with the player it already has. There is no cloud voice API and no API
key for speech.

Use **CosyVoice2-0.5B**. The download is about 2 GB. Do not put it inside
this git repository and do not commit it.

The first time a sentence is spoken, the weights load. On CPU that first
sentence is the slow one. Later sentences are still several seconds each.
That is normal.

## Mac: download and place the model

Do this on Apple Silicon or Intel. Use the same Python environment you use
to run `python server.py`.

1. Confirm the machine and make two folders outside the JARVIS repo.

```bash
uname -m
mkdir -p "$HOME/src" "$HOME/models"
```

`arm64` is Apple Silicon. `x86_64` is an Intel Mac.

2. Clone CosyVoice (the code, not the weights). `--recursive` is required.

```bash
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git "$HOME/src/CosyVoice"
cd "$HOME/src/CosyVoice"
python3 -m pip install -r requirements.txt
```

If that environment does not already have torch, from the JARVIS repo:

```bash
python3 -m pip install -r requirements-cosyvoice.txt
```

Do not install an NVIDIA CUDA build of torch on a Mac. The Mac pip install
is CPU, and on Apple Silicon it can also see MPS.

3. Download CosyVoice2-0.5B (about 2 GB) into `$HOME/models`. This model is
public. You do not need a Hugging Face token.

```bash
python3 -m pip install -U huggingface_hub
huggingface-cli download FunAudioLLM/CosyVoice2-0.5B \
  --local-dir "$HOME/models/CosyVoice2-0.5B"
```

If Hugging Face is slow or blocked, use ModelScope instead. The snapshot
is the same set of files (`iic/CosyVoice2-0.5B`):

```bash
python3 -m pip install -U modelscope
modelscope download --model iic/CosyVoice2-0.5B \
  --local_dir "$HOME/models/CosyVoice2-0.5B"
```

4. Check the folder. This file must exist:

```bash
ls "$HOME/models/CosyVoice2-0.5B/cosyvoice2.yaml"
```

If that `ls` fails, the download did not finish. Do not point JARVIS at the
folder until `cosyvoice2.yaml` is there. You should also see large weight
files (`llm.pt` and others) in the same directory.

## Mac: reference voice

Zero-shot CosyVoice2 needs a short recording and the exact words in it.

- One speaker, quiet room.
- About 3 to 10 seconds.
- The transcript must match the audio, word for word.

Record with QuickTime Player: File → New Audio Recording → stop → File →
Save. That writes an `.m4a` (often on the Desktop).

Turn it into 16 kHz mono WAV with `afconvert`, which is already on macOS:

```bash
afconvert "$HOME/Desktop/prompt.m4a" "$HOME/models/jarvis-prompt.wav" \
  -f WAVE -d LEI16@16000 -c 1
```

Write the transcript in a note. You will paste it into `.env` as one line.
Example, only if this is really what you said: `Good evening. All systems are nominal.`

## Mac: tell JARVIS where the files are

In the JARVIS repo:

```bash
cp .env.example .env
```

Edit `.env`. Use absolute paths. Replace `you` with your home folder name.

```bash
COSYVOICE_REPO=/Users/you/src/CosyVoice
COSYVOICE_MODEL_DIR=/Users/you/models/CosyVoice2-0.5B
COSYVOICE_PROMPT_WAV=/Users/you/models/jarvis-prompt.wav
COSYVOICE_PROMPT_TEXT=Good evening. All systems are nominal.
COSYVOICE_DEVICE=cpu
```

Or open Settings → Voice (CosyVoice) in the browser and fill the same
fields, then Save voice.

### CPU, Apple Silicon, and Intel

| Mac | Set this | What to expect |
| --- | --- | --- |
| Apple Silicon (`arm64`) | `COSYVOICE_DEVICE=cpu` | Works. Several seconds per sentence. Start here. |
| Apple Silicon, after cpu works | `COSYVOICE_DEVICE=mps` | Best-effort. Restart the server. If the first sentence errors, set `cpu` again and restart. |
| Intel (`x86_64`) | `COSYVOICE_DEVICE=cpu` | The only option. Slower than Apple Silicon. There is no MPS. |

`cuda` is for an NVIDIA GPU. A Mac does not use it.

Changing `COSYVOICE_DEVICE` needs a server restart. The first sentence after
a restart loads the 2 GB weights, so it is slower than the ones after it.

## Check

Restart:

```bash
python server.py --host 127.0.0.1
```

Startup preflight includes a check named `cosyvoice`. It fails if the model
directory is missing, `cosyvoice2.yaml` is not there, the prompt wav or its
transcript is missing, or `import cosyvoice` fails. It does not load the
weights.

Settings → Test CosyVoice runs that same check. A green dot means the files
and the install are in place. It does not mean the first sentence will be
fast.

An SFT checkpoint that already has named speakers can set `COSYVOICE_SPEAKER`
instead of the prompt wav and transcript. CosyVoice2-0.5B as downloaded
above uses the prompt wav.

Each sentence still arrives on the existing voice WebSocket as one WAV.
