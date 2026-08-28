# Michi

A voice assistant that runs on your Windows PC. Say **"Hey Michi"**, ask for something,
and she answers out loud — using whichever LLM you point her at in `config.yaml`.

---

## Quick start

1. **Double-click `setup.bat`.** It makes a virtual environment and installs everything.
2. **Open `.env`** and paste in one API key:

   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```

3. **Run the self-test:** `run.bat --doctor`
   It checks packages, your microphone level, the speech model, a real call to your
   model provider, and the voice — and tells you exactly what to change if something
   is off. Fix anything it marks `FAIL`, then re-run it.
4. **Go live:** double-click `run.bat`, then say *"Hey Michi, what time is it?"*

Press `Ctrl+Alt+M` any time to talk without the wake word. `Ctrl+C` in the window quits.

---

## Choosing your model

One line in `config.yaml`:

```yaml
llm:
  active: claude      # claude | opencode | openai | groq | local
```

Providers are defined right below it. Adding a new one is three lines — anything that
speaks the OpenAI protocol works with `type: openai_compat`:

```yaml
    myprovider:
      type: openai_compat
      api_key: ${MY_API_KEY}
      base_url: https://api.example.com/v1
      model: some-model-name
```

API keys stay in `.env`; `config.yaml` only references them as `${NAME}`, so the config
is safe to share or commit.

Outage-proofing: set `llm.fallback: [opencode, local]` and Michi tries the next
provider automatically when the active one fails.

Try a provider without editing anything: `run.bat --provider local --text`

---

## Command reference

| Command | What it does |
|---|---|
| `run.bat` | Start listening |
| `run.bat --doctor` | Full self-test: packages, mic, speech, model, voice |
| `run.bat --text` | Keyboard chat — no mic, good for testing the model and tools |
| `run.bat --check` | Validate config, show which provider and key are active |
| `run.bat --tune-wake` | Live wake-word scores, for setting the threshold |
| `run.bat --devices` | List microphones with their index numbers |
| `run.bat --voices` | List available TTS voices |
| `run.bat --say "hello"` | Test the voice |
| `run.bat --provider groq` | Override `llm.active` for one run |
| `run.bat --tray` / `--no-tray` | Force the tray icon on or off |
| `run_tests.bat` | Offline test suite — no mic, no network, no API calls |

---

## Running her all the time

`install\install_autostart.bat` registers a logon task that starts Michi hidden, with a
tray icon. The icon changes colour with her state — blue waiting, green listening, amber
thinking, purple speaking, grey paused — and right-clicking it gives you **Pause
listening** and **Quit**.

`install\uninstall_autostart.bat` removes it. `install\michi_silent.vbs` also works as a
desktop shortcut if you'd rather start her by hand without a console window.

---

## Tuning

**She doesn't hear me.** Start with `run.bat --doctor` — it prints your live mic level and
suggests a threshold. Otherwise `run.bat --devices` and set `audio.input_device` to the
right index.

**She cuts me off mid-sentence.** Raise `audio.silence_duration` (try `1.3`).

**She wakes up at random / never wakes up.** `run.bat --tune-wake`, talk for a minute, and
it tells you what threshold would work. Then set `wake.stt_phrase.fuzzy_threshold`.

**Too slow.** Streaming is on by default, so she starts talking before the reply is
finished. Beyond that: drop `stt.faster_whisper.model` to `base.en`, or switch to a
faster model (`claude-haiku-4-5`, or Groq).

**The voice is robotic.** Switch `tts.engine` to `edge` — free neural voices, needs
internet. `en-US-AriaNeural` or `es-MX-DaliaNeural`.

**I want to interrupt her.** Set `audio.barge_in: true`. Use headphones, or she'll hear
her own voice and interrupt herself.

**She talks too much.** Edit `assistant.persona` in `config.yaml` — it's a plain-English
instruction, and it's the fastest lever you have on how she sounds.

---

## What she can do

Tool groups are toggled in `config.yaml` under `tools.enabled`:

- **basics** — time and date, timers (start/list/cancel, survive a restart), remember/recall/forget notes, "go to sleep"
- **system** — volume, media keys, lock screen, screenshot, CPU/battery status
- **apps** — open programs, list/focus/close windows, show desktop
- **web** — open a URL, search in the browser
- **clipboard** — read/write the clipboard, type dictated text into any window
- **shell** — run commands (**off by default**, and confirm-gated when on)

Anything in `tools.confirm_before` makes Michi ask out loud before acting.

### Adding your own tool

Drop a decorated function into any file under `michi/tools/`:

```python
from .registry import tool

@tool(group="basics",
      description="Open my current project folder in VS Code.",
      parameters={})
def open_project() -> str:
    import subprocess
    subprocess.Popen(["code", r"C:\\Users\\aroco\\Projects\\thing"])
    return "Opening your project."
```

Restart Michi and just ask for it — the model discovers tools automatically.

---

## Layout

```
config.yaml          everything you configure
.env                 API keys (never commit)
run.bat / setup.bat  Windows launchers
install/             autostart at logon, silent launcher
docs/                wake-word training guide
tests/               offline test suite (143 checks)
michi/
  config.py          YAML + ${ENV} loading
  runtime.py         shutdown / pause flags
  events.py          state bus the tray icon follows
  diagnostics.py     --doctor and --tune-wake
  audio/             microphone, VAD, cue tones
  wake/              stt_phrase (default) | hybrid | openwakeword | hotkey
  stt/               faster_whisper (local) | openai_api
  tts/               sapi | edge | piper | openai_api  + sentence-streaming speaker
  llm/               anthropic | openai_compat | fallback chain  <- the swappable brain
  tools/             capability groups exposed to the model
  agent/             brain (tool loop) + assistant (the main loop)
  ui/                system tray icon
```

See `PLAN.md` for the architecture rationale and what's left to build.
