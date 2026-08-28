# Michi — Build Plan

A voice assistant that lives on your Windows PC, wakes on **"Hey Michi"**, and routes its
thinking to whatever LLM provider you put in `config.yaml` (Claude API, OpenCode Zen,
OpenAI, a local Ollama model — your choice, swappable without touching code).

---

## 1. Design principles

| Principle | What it means in practice |
|---|---|
| **Provider-agnostic** | The assistant's brain is behind one interface. Anthropic, any OpenAI-compatible endpoint (OpenCode Zen, OpenAI, Groq, OpenRouter, LM Studio), and Ollama all plug in via config. Switching model = editing one line. |
| **Everything in one config file** | `config.yaml` controls provider, model, keys, wake word, mic, voice, personality, and which tools Michi may use. No code edits for normal changes. |
| **Keys never live in the config** | `config.yaml` holds `${ANTHROPIC_API_KEY}`-style references; the real values sit in `.env` or Windows environment variables. Safe to share or commit the config. |
| **Swappable at every layer** | Wake word, speech-to-text, and voice are each an interface with multiple backends. Start local and free; move any single layer to a cloud API later. |
| **Explicit capability grants** | Computer control is opt-in per tool group in config. Anything destructive requires spoken confirmation. |

---

## 2. Architecture

```
     mic ──▶ [ WAKE ] ──▶ [ VAD capture ] ──▶ [ STT ] ──▶ text
                                                            │
                                                            ▼
                                                     [ AGENT LOOP ]
                                                    history + system
                                                            │
                                          ┌─────────────────┴──────────────┐
                                          ▼                                ▼
                                   [ LLM PROVIDER ]  ◀── tool results ── [ TOOLS ]
                                  anthropic / openai_compat / ollama    volume, apps,
                                          │                             media, windows,
                                          ▼                             clipboard, web
                                       reply text
                                          │
                                          ▼
                                       [ TTS ] ──▶ speakers
```

Six replaceable layers. Each one is a small Python interface with a `create()` factory that
reads its section of `config.yaml`.

### Layer choices (and why)

**Wake word** — `openwakeword`, running fully offline on CPU (~few % of one core).
Picovoice/Porcupine was the other obvious option, but Picovoice **discontinued free-tier
AccessKeys on June 30, 2026**, so existing free keys no longer initialise — openWakeWord is
now the sensible default for a personal build.

openWakeWord ships pretrained models for `alexa`, `hey_jarvis`, `hey_mycroft`, `hey_rhasspy`
— but **not "hey michi"**, which has to be trained. So the scaffold gives you three engines:

| Engine | Works day one? | Detects literally "Hey Michi"? | Notes |
|---|---|---|---|
| `stt_phrase` *(default)* | ✅ yes | ✅ yes | VAD + tiny Whisper on short clips, fuzzy-matches the phrase. Zero setup, slightly more CPU. |
| `openwakeword` | ✅ yes (with `hey_jarvis`) | only after you train a model | Lowest CPU. Drop a custom `hey_michi.onnx` in `models/` when trained. |
| `hotkey` | ✅ yes | n/a | Push-to-talk on `Ctrl+Alt+M`. Always-reliable fallback for noisy rooms and screen shares. |

**Speech-to-text** — `faster-whisper` locally (free, private, no per-minute cost, `small.en`
is comfortably real-time on CPU), with an OpenAI-compatible transcription API backend as the
alternative if you'd rather trade cost for speed.

**Voice** — Windows SAPI via `pyttsx3` as the always-works default (zero install, robotic),
`edge-tts` for free high-quality neural voices including Spanish (needs internet), Piper for
offline neural quality, or a cloud TTS API.

**Brain** — see next section.

---

## 3. The config file (the core of what you asked for)

Every model decision is data, not code:

```yaml
llm:
  active: claude          # ← the only line you change to switch brains

  providers:
    claude:
      type: anthropic
      api_key: ${ANTHROPIC_API_KEY}
      model: claude-sonnet-5

    opencode:
      type: openai_compat
      api_key: ${OPENCODE_API_KEY}
      base_url: https://opencode.ai/zen/v1
      model: kimi-k3

    local:
      type: openai_compat
      base_url: http://localhost:11434/v1
      api_key: ollama
      model: qwen3:8b
```

`type: openai_compat` is deliberately doing a lot of work — OpenCode Zen, OpenAI, Groq,
OpenRouter, Together, LM Studio and Ollama all speak that protocol, so **one adapter covers
nearly every provider you'll ever want**, and adding a new one is three lines of YAML.
`type: anthropic` exists separately because the Claude API uses its own message and
tool-calling shape.

Both adapters normalise to the same internal message/tool format, so the agent loop, the
tools, and the conversation history don't know or care which provider answered.

The same pattern repeats for `wake:`, `stt:`, `tts:`, `assistant:` (name, language,
personality, conversation memory) and `tools:` (which capability groups are enabled).

---

## 4. What Michi can do

**Conversation** — wake, listen, answer, speak. Follow-up window stays open ~8s after a reply
so you can keep talking without re-saying the wake word. History trims to a configurable turn
limit.

**Computer control** — exposed to the model as tools it calls when relevant:

- *system*: volume up/down/mute/set, media play-pause/next/previous, lock screen, screenshot
- *apps*: launch by name or path, focus/minimise windows, close by title, list open windows
- *web*: open a URL, run a search in the default browser
- *clipboard*: read, write, type text into the focused window

Each group is toggled in config. `shell` (arbitrary commands) is included but **disabled by
default** and gated behind spoken confirmation — worth keeping off until you trust it.

---

## 5. Phased roadmap

| Phase | Goal | Status |
|---|---|---|
| **0 — Scaffold** | Project layout, config system, provider registry, tool registry, agent loop, all layers wired | ✅ built |
| **1 — First voice** | `setup.bat`, pick a provider, `run.bat --doctor`, then say "Hey Michi" | ⬜ **you, ~20 min** |
| **2 — Tune the ears** | Mic device + VAD thresholds (`--doctor`), wake threshold (`--tune-wake`), Whisper size vs. latency, pick a voice | ⬜ you |
| **3 — Real wake word** | Train `hey_michi.onnx` and switch engine to `openwakeword` — see `docs/TRAINING_WAKE_WORD.md` | ⬜ optional |
| **4 — Your tools** | Add the tools that are about *your* workflow — open your projects, control your specific apps, read your notes | ⬜ ongoing |
| **5 — Always on** | Tray icon with pause/quit, hidden autostart at logon, rotating logs | ✅ built |
| **6 — Latency & polish** | Streaming replies (speak sentence 1 while the rest generates), wake chime, barge-in, `--doctor` self-test | ✅ built |
| **7 — Later** | Long-term memory across sessions, Spanish/English auto-switching, per-app context | ⬜ |

---

## 6. Known trade-offs

- **Latency budget.** Local Whisper `small.en` ≈ 0.6–1.2s + model ≈ 1–3s + voice ≈ 0.3s.
  Streaming hides most of the model time: Michi starts speaking the first sentence while
  the rest is still generating, so the felt delay is closer to the Whisper pass alone.
  Still too slow? Drop to `base.en`, or use `claude-haiku-4-5` / Groq.
- **`stt_phrase` wake engine costs CPU** because it transcribes constantly — though it
  skips the transcription entirely while the room is quiet. Train the real wake word
  (phase 3) if you run this on battery.
- **Barge-in is off by default.** Without headphones the mic hears Michi's own voice and
  she interrupts herself. Turn on `audio.barge_in` once you've tested your setup.
- **Tool-calling quality varies by provider.** Claude and GPT-class models handle the tool
  loop reliably; smaller local models often need the tool list trimmed to stay coherent.
- **Whisper mishears "Michi"** as *mishi / michy / meechee*, which is exactly why the default
  wake engine fuzzy-matches rather than string-compares. `--tune-wake` shows you the scores.
- **Streaming was verified against mocked SDK wire shapes**, not live API calls — the
  sandbox this was built in has no package index. `run.bat --doctor` is the real check,
  and it exercises the provider, mic, Whisper and voice for real on your machine.

---

## 7. Sources

- [openWakeWord (dscripka)](https://github.com/dscripka/openWakeWord) — pretrained models, Windows uses onnxruntime only
- [Picovoice free-tier AccessKeys discontinued June 30, 2026](https://community.home-assistant.io/t/fyi-picovoice-confirmed-free-tier-accesskeys-will-stop-working-after-june-30-2026/1012744)
- [OpenCode Zen docs](https://opencode.ai/docs/zen/) — OpenAI-compatible base URL and model list
- [Claude models overview](https://platform.claude.com/docs/en/about-claude/models/overview) — current model IDs
- [RealtimeSTT / faster-whisper](https://github.com/KoljaB/RealtimeSTT) — local streaming STT reference
