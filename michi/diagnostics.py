"""`michi --doctor` — check every layer end to end before you trust the voice loop.

Each check prints a verdict and, when something is wrong, the specific thing to do
about it. Runs top to bottom and keeps going after failures so you see the whole
picture in one pass.
"""

from __future__ import annotations

import sys
import time

OK, WARN, FAIL = "ok", "warn", "FAIL"

_ICONS = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, title: str, hint: str = "") -> None:
        self.rows.append((status, title, hint))
        print(f"{_ICONS[status]}  {title}")
        if hint and status != OK:
            print(f"          -> {hint}")

    @property
    def failures(self) -> int:
        return sum(1 for status, _, _ in self.rows if status == FAIL)

    @property
    def warnings(self) -> int:
        return sum(1 for status, _, _ in self.rows if status == WARN)


# ---------------------------------------------------------------------------
def _check_python(report: Report) -> None:
    version = sys.version_info
    pretty = f"{version.major}.{version.minor}.{version.micro}"
    if version >= (3, 10):
        report.add(OK, f"Python {pretty}")
    else:
        report.add(FAIL, f"Python {pretty} is too old",
                   "Install Python 3.10 or newer from python.org and re-run setup.bat.")


def _check_packages(report: Report) -> None:
    required = {
        "yaml": "PyYAML",
        "numpy": "numpy",
        "sounddevice": "sounddevice",
        "soundfile": "soundfile",
    }
    optional = {
        "faster_whisper": "faster-whisper (local speech-to-text)",
        "pyttsx3": "pyttsx3 (Windows voice)",
        "pyautogui": "pyautogui (system + app control)",
        "pyperclip": "pyperclip (clipboard tools)",
        "pygetwindow": "pygetwindow (window control)",
        "keyboard": "keyboard (push-to-talk)",
        "psutil": "psutil (system status tool)",
        "pystray": "pystray (tray icon)",
        "PIL": "Pillow (tray icon)",
        "openwakeword": "openwakeword (low-CPU wake engine)",
    }

    missing = [name for module, name in required.items() if not _importable(module)]
    if missing:
        report.add(FAIL, f"Core packages missing: {', '.join(missing)}",
                   "Run setup.bat, or: pip install -r requirements.txt")
    else:
        report.add(OK, "Core packages installed")

    absent = [name for module, name in optional.items() if not _importable(module)]
    if absent:
        report.add(WARN, f"{len(absent)} optional package(s) missing",
                   "Not fatal — affected features degrade. Missing: " + "; ".join(absent))
    else:
        report.add(OK, "Optional packages installed")


def _importable(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _check_config(report: Report, cfg) -> None:
    try:
        name, settings = cfg.active_provider()
    except Exception as exc:
        report.add(FAIL, "Model provider not usable", str(exc))
        return
    report.add(OK, f"Provider '{name}' -> {settings.get('type')} / {settings.get('model')}")


def _check_audio_devices(report: Report, cfg) -> tuple[bool, bool]:
    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception as exc:
        report.add(FAIL, "Audio system unreachable", f"{exc}. Check your sound drivers.")
        return False, False

    inputs = [d for d in devices if d["max_input_channels"] > 0]
    outputs = [d for d in devices if d["max_output_channels"] > 0]

    if inputs:
        report.add(OK, f"{len(inputs)} microphone(s) detected")
    else:
        report.add(FAIL, "No microphone detected",
                   "Plug one in, then check Windows Settings > Privacy > Microphone.")
    if outputs:
        report.add(OK, f"{len(outputs)} output device(s) detected")
    else:
        report.add(FAIL, "No speakers detected", "Check your default playback device.")

    requested = cfg.get("audio.input_device")
    if requested not in (None, ""):
        from .audio.mic import _resolve_device

        if _resolve_device(requested) is None:
            report.add(WARN, f"audio.input_device '{requested}' didn't match anything",
                       "Run: run.bat --devices, then use the index number shown.")
    return bool(inputs), bool(outputs)


def _check_microphone(report: Report, cfg, seconds: float = 3.0):
    import numpy as np

    from .audio import Microphone

    print(f"\n  Say something for {seconds:.0f} seconds...")
    mic = Microphone(cfg)
    try:
        mic.start()
        time.sleep(0.3)
        mic.flush()
        audio = mic.read_seconds(seconds)
    except Exception as exc:
        report.add(FAIL, "Couldn't open the microphone",
                   f"{exc}. Check Windows microphone permissions for Python.")
        return None
    finally:
        try:
            mic.stop()
        except Exception:
            pass

    if len(audio) == 0:
        report.add(FAIL, "Microphone returned no audio", "Try a different input device.")
        return None

    peak = float(np.max(np.abs(audio)))
    level = float(np.sqrt(np.mean(np.square(audio))))
    threshold = mic.silence_threshold
    bar = "#" * min(40, int(level * 400))
    print(f"  level: {level:.4f}  peak: {peak:.3f}  |{bar}")

    if level < threshold * 0.5:
        report.add(WARN, f"Microphone is very quiet (RMS {level:.4f})",
                   f"Either you stayed silent, or lower audio.silence_threshold "
                   f"(currently {threshold}) to about {max(level * 1.5, 0.002):.4f}.")
    elif level > threshold * 25:
        report.add(WARN, f"Microphone is very loud (RMS {level:.4f})",
                   "Consider raising audio.silence_threshold so background noise "
                   "doesn't count as speech.")
    else:
        report.add(OK, f"Microphone level healthy (RMS {level:.4f})")
    return audio


def _check_stt(report: Report, cfg, audio) -> None:
    if audio is None:
        report.add(WARN, "Skipped speech-to-text (no audio captured)")
        return
    try:
        from .stt import create_stt

        print("  Loading the speech model (first run downloads it)...")
        started = time.monotonic()
        stt = create_stt(cfg)
        loaded = time.monotonic() - started

        started = time.monotonic()
        text = stt.transcribe(audio, cfg.get("audio.sample_rate", 16000))
        elapsed = time.monotonic() - started
    except Exception as exc:
        report.add(FAIL, "Speech-to-text failed", str(exc))
        return

    if text:
        report.add(OK, f"Heard: \"{text}\"  (load {loaded:.1f}s, transcribe {elapsed:.1f}s)")
        if elapsed > 3.0:
            report.add(WARN, "Transcription is slow",
                       "Drop stt.faster_whisper.model to base.en or tiny.en.")
    else:
        report.add(WARN, "Nothing was transcribed",
                   "Normal if you stayed quiet. Otherwise check the mic level above.")


def _check_llm(report: Report, cfg) -> None:
    try:
        from .llm import create_provider

        provider = create_provider(cfg)
    except Exception as exc:
        report.add(FAIL, "Couldn't create the model provider", str(exc))
        return

    try:
        started = time.monotonic()
        reply = provider.chat(
            messages=[{"role": "user", "content": "Reply with exactly: ready"}],
            system="You are a test harness. Reply with one word.",
        )
        elapsed = time.monotonic() - started
    except Exception as exc:
        report.add(FAIL, f"Model call failed ({type(exc).__name__})",
                   f"{exc}\n             Check the API key in .env and your internet connection.")
        return

    report.add(OK, f"Model replied in {elapsed:.1f}s: \"{reply.text[:40]}\"")
    if not provider.supports_streaming:
        report.add(WARN, "This provider doesn't stream",
                   "Replies will only start speaking once fully generated.")
    if elapsed > 6.0:
        report.add(WARN, "The model is slow to respond",
                   "Try a faster model (claude-haiku-4-5, or a Groq model).")


def _check_tts(report: Report, cfg) -> None:
    try:
        from .tts import create_tts

        engine = create_tts(cfg)
        print("  Playing a test phrase...")
        started = time.monotonic()
        engine.speak("Michi is working.")
        elapsed = time.monotonic() - started
    except Exception as exc:
        report.add(FAIL, "Text-to-speech failed",
                   f"{exc}. Try setting tts.engine to 'sapi' in config.yaml.")
        return

    report.add(OK, f"Spoke a test phrase via '{engine.name}' in {elapsed:.1f}s")
    if elapsed < 0.15:
        report.add(WARN, "That returned suspiciously fast",
                   "If you heard nothing, check your default playback device.")


def _check_tools(report: Report, cfg) -> None:
    try:
        from .tools import build_registry

        registry = build_registry(cfg)
    except Exception as exc:
        report.add(FAIL, "Tool registry failed to build", str(exc))
        return

    enabled = cfg.get("tools.enabled", []) or []
    names = registry.names()
    if not names:
        report.add(WARN, "No tools loaded", "Check tools.enabled in config.yaml.")
        return
    report.add(OK, f"{len(names)} tool(s) from {len(enabled)} group(s) ready")

    if "shell" in enabled:
        report.add(WARN, "The 'shell' tool group is enabled",
                   "Michi can run arbitrary commands. Keep it confirm-gated.")


# ---------------------------------------------------------------------------
def run_doctor(cfg, skip_audio: bool = False) -> int:
    print("\n" + "=" * 62)
    print("  Michi self-test")
    print("=" * 62 + "\n")

    report = Report()

    print("-- environment")
    _check_python(report)
    _check_packages(report)
    _check_config(report, cfg)

    print("\n-- tools")
    _check_tools(report, cfg)

    print("\n-- model")
    _check_llm(report, cfg)

    audio = None
    if skip_audio:
        report.add(WARN, "Audio checks skipped (--no-audio)")
    else:
        print("\n-- audio devices")
        has_input, has_output = _check_audio_devices(report, cfg)

        if has_input:
            print("\n-- microphone")
            audio = _check_microphone(report, cfg)
            print("\n-- speech to text")
            _check_stt(report, cfg, audio)
        if has_output:
            print("\n-- voice")
            _check_tts(report, cfg)

    print("\n" + "=" * 62)
    if report.failures:
        print(f"  {report.failures} failure(s), {report.warnings} warning(s) — "
              "fix the failures above, then re-run.")
    elif report.warnings:
        print(f"  No failures, {report.warnings} warning(s). "
              "Michi should run; review the notes above.")
    else:
        print("  Everything passed. Run  run.bat  and say the wake word.")
    print("=" * 62 + "\n")
    return 1 if report.failures else 0


# ---------------------------------------------------------------------------
def tune_wake(cfg) -> int:
    """Live view of what the wake engine hears and how closely it matches."""
    from .audio import Microphone
    from .stt import create_stt
    from .wake.stt_phrase import _normalise, _similarity

    phrases = [str(p) for p in cfg.get("wake.stt_phrase.phrases", ["hey michi"])]
    threshold = float(cfg.get("wake.stt_phrase.fuzzy_threshold", 0.75))
    chunk = float(cfg.get("wake.stt_phrase.chunk_seconds", 2.0))

    print("\n  Wake-word tuning. Say the wake phrase a few times, and also talk")
    print("  normally to see whether anything false-triggers. Ctrl+C to stop.\n")
    print(f"  phrases   : {', '.join(phrases)}")
    print(f"  threshold : {threshold}\n")

    stt = create_stt(cfg, model_override=cfg.get("stt.faster_whisper.wake_model", "tiny.en"))
    mic = Microphone(cfg)
    best_hits: list[float] = []
    best_misses: list[float] = []

    try:
        with mic:
            while True:
                audio = mic.read_seconds(chunk)
                text = stt.transcribe(audio, mic.sample_rate)
                if not text:
                    continue

                words = _normalise(text).split()
                best, best_phrase = 0.0, ""
                for phrase in phrases:
                    target = _normalise(phrase)
                    span = len(target.split())
                    for start in range(0, max(1, len(words) - span + 1)):
                        score = _similarity(" ".join(words[start : start + span]), target)
                        if score > best:
                            best, best_phrase = score, phrase

                verdict = "WAKE " if best >= threshold else "     "
                (best_hits if best >= threshold else best_misses).append(best)
                print(f"  {verdict} {best:.2f}  [{best_phrase or '-'}]  {text}")
    except KeyboardInterrupt:
        pass

    print("\n  ---")
    if best_hits:
        print(f"  triggered {len(best_hits)}x, scores {min(best_hits):.2f}-{max(best_hits):.2f}")
    if best_misses:
        top = max(best_misses)
        print(f"  ignored {len(best_misses)}x, highest non-trigger score {top:.2f}")
        print(f"  A threshold just above {top:.2f} would keep ignoring those.")
    print()
    return 0
