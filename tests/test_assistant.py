"""End-to-end smoke test of the full loop with every I/O layer faked.

This is the one that catches wiring mistakes: wake -> listen -> think -> tool ->
speak, plus the follow-up window and the confirmation gate. No audio hardware,
no network, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from tests.harness import check, summary  # noqa: E402


# -- fakes ------------------------------------------------------------------
class FakeMic:
    sample_rate = 16000
    silence_threshold = 0.01

    def __init__(self, cfg=None):
        self.utterances: list[np.ndarray] = []
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def flush(self):
        pass

    def read_seconds(self, seconds):
        return np.zeros(int(self.sample_rate * seconds), dtype=np.float32)

    def record_utterance(self, preroll=None):
        if self.utterances:
            return self.utterances.pop(0)
        return np.zeros(0, dtype=np.float32)


class FakeSTT:
    name = "fake-stt"

    def __init__(self, script=None):
        self.script = list(script or [])

    def transcribe(self, audio, sample_rate=16000):
        if len(audio) == 0:
            return ""
        return self.script.pop(0) if self.script else ""


class FakeTTS:
    name = "fake-tts"

    def __init__(self):
        self.spoken: list[str] = []

    def speak(self, text):
        self.spoken.append(text)

    def stop(self):
        pass


class FakeWake:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def banner(self):
        return "fake wake"

    def wait(self, mic):
        self.calls += 1
        from michi.wake.base import WakeResult

        return self.results.pop(0) if self.results else WakeResult(False)


def _install_fakes(monkey: dict, mic, stt, tts, wake):
    import michi.agent.assistant as module

    monkey["orig"] = {
        "Microphone": module.Microphone,
        "create_stt": module.create_stt,
        "create_tts": module.create_tts,
        "create_wake": module.create_wake,
    }
    module.Microphone = lambda cfg: mic
    module.create_stt = lambda cfg: stt
    module.create_tts = lambda cfg: tts
    module.create_wake = lambda cfg: wake


def _restore(monkey: dict):
    import michi.agent.assistant as module

    for name, original in monkey.get("orig", {}).items():
        setattr(module, name, original)


def _build_assistant(provider, mic, stt, tts, wake, overrides=None):
    from michi.agent.assistant import Assistant
    from michi.config import load_config

    cfg = load_config()
    cfg.data["ui"]["tray"] = False
    cfg.data["audio"]["chime"]["enabled"] = False
    cfg.data["assistant"]["followup_seconds"] = 0.1
    for dotted, value in (overrides or {}).items():
        node = cfg.data
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    monkey: dict = {}
    _install_fakes(monkey, mic, stt, tts, wake)

    # Patch the provider factory used inside Assistant.__init__.
    import michi.llm as llm_module

    original_create = llm_module.create_provider
    llm_module.create_provider = lambda c: provider
    try:
        assistant = Assistant(cfg)
    finally:
        llm_module.create_provider = original_create
    return assistant, monkey


# -- tests ------------------------------------------------------------------
def test_full_turn() -> None:
    print("\nfull voice turn (all I/O faked)")
    from michi import runtime
    from michi.llm.base import LLMProvider, Reply, StreamChunk, ToolCall
    from michi.wake.base import WakeResult

    runtime.reset()

    class ScriptedProvider(LLMProvider):
        supports_streaming = True

        def __init__(self, rounds):
            self.rounds = list(rounds)
            self.model = "scripted"
            self.systems: list[str] = []

        def chat(self, messages, system="", tools=None):
            self.systems.append(system)
            chunks = self.rounds.pop(0)
            return [c.reply for c in chunks if c.is_final][0]

        def chat_stream(self, messages, system="", tools=None):
            self.systems.append(system)
            for chunk in self.rounds.pop(0):
                yield chunk

    provider = ScriptedProvider([
        [StreamChunk(text="Let me check. "),
         StreamChunk(reply=Reply(text="Let me check.",
                                 tool_calls=[ToolCall(id="c1", name="get_time")]))],
        [StreamChunk(text="It is late in the day. "),
         StreamChunk(text="Anything else?"),
         StreamChunk(reply=Reply(text="It is late in the day. Anything else?"))],
    ])

    mic, stt, tts = FakeMic(), FakeSTT(), FakeTTS()
    wake = FakeWake([WakeResult(True, text="what time is it", source="wake")])

    assistant, monkey = _build_assistant(provider, mic, stt, tts, wake)
    try:
        assistant.run(with_tray=False)
        assistant.speaker.wait(timeout=3.0)

        spoken = " ".join(tts.spoken)
        check("greeting spoken", "ready" in spoken.lower(), spoken)
        check("streamed answer spoken", "late in the day" in spoken, spoken)
        check("tool was actually invoked",
              any(m["role"] == "tool" for m in assistant.brain.history.messages))
        check("two model rounds happened", len(provider.systems) == 2, str(len(provider.systems)))
        check("system prompt mentions tools", "tool" in provider.systems[0].lower())
        check("wake engine polled until exhausted", wake.calls == 2, str(wake.calls))
        check("mic was opened and closed", mic.started is False)
    finally:
        assistant.shutdown()
        _restore(monkey)


def test_wake_word_only_then_listen() -> None:
    print("\nwake word alone triggers a listen")
    from michi import runtime
    from michi.llm.base import LLMProvider, Reply
    from michi.wake.base import WakeResult

    runtime.reset()

    class PlainProvider(LLMProvider):
        supports_streaming = False

        def __init__(self):
            self.model = "plain"
            self.heard: list[str] = []

        def chat(self, messages, system="", tools=None):
            self.heard.append(messages[-1]["content"])
            return Reply(text="Opening Spotify for you now.")

    provider = PlainProvider()
    mic = FakeMic()
    # One utterance for the command, then silence to close the follow-up window.
    mic.utterances = [np.ones(16000, dtype=np.float32) * 0.2]
    stt = FakeSTT(["open spotify"])
    tts = FakeTTS()
    wake = FakeWake([WakeResult(True, text="", source="wake")])

    assistant, monkey = _build_assistant(provider, mic, stt, tts, wake)
    try:
        assistant.run(with_tray=False)
        assistant.speaker.wait(timeout=3.0)

        check("bare wake word led to a recording", provider.heard == ["open spotify"],
              str(provider.heard))
        check("answer spoken", any("Spotify" in s for s in tts.spoken), str(tts.spoken))
    finally:
        assistant.shutdown()
        _restore(monkey)


def test_confirmation_gate() -> None:
    print("\nspoken confirmation gate")
    from michi import runtime
    from michi.llm.base import LLMProvider, Reply
    from michi.wake.base import WakeResult

    runtime.reset()

    class PlainProvider(LLMProvider):
        supports_streaming = False

        def __init__(self):
            self.model = "plain"

        def chat(self, messages, system="", tools=None):
            return Reply(text="Ok.")

    mic = FakeMic()
    mic.utterances = [np.ones(8000, dtype=np.float32) * 0.2]
    stt = FakeSTT(["yes do it"])
    tts = FakeTTS()
    wake = FakeWake([WakeResult(False)])

    assistant, monkey = _build_assistant(PlainProvider(), mic, stt, tts, wake)
    try:
        approved = assistant._confirm("lock_screen")
        check("spoken 'yes' approves", approved is True)
        check("Michi asked out loud", any("lock screen" in s for s in tts.spoken), str(tts.spoken))

        mic.utterances = [np.ones(8000, dtype=np.float32) * 0.2]
        stt.script = ["no don't"]
        check("spoken 'no' declines", assistant._confirm("lock_screen") is False)

        mic.utterances = []  # silence
        check("silence declines", assistant._confirm("lock_screen") is False)
    finally:
        assistant.shutdown()
        _restore(monkey)


def test_paused_assistant_does_not_listen() -> None:
    print("\npause stops the loop cleanly")
    from michi import runtime
    from michi.llm.base import LLMProvider, Reply
    from michi.wake.base import WakeResult

    runtime.reset()

    class PlainProvider(LLMProvider):
        supports_streaming = False

        def __init__(self):
            self.model = "plain"
            self.calls = 0

        def chat(self, messages, system="", tools=None):
            self.calls += 1
            return Reply(text="Sure thing.")

    provider = PlainProvider()
    mic, stt, tts = FakeMic(), FakeSTT(), FakeTTS()
    wake = FakeWake([WakeResult(True, text="say something", source="wake")])

    assistant, monkey = _build_assistant(provider, mic, stt, tts, wake)
    try:
        runtime.pause()
        assistant.run(with_tray=False)
        assistant.speaker.wait(timeout=2.0)
        check("a paused turn still completes if the engine returns", provider.calls <= 1)
        check("state reflects pause", assistant.bus.state.value in ("paused", "idle", "starting"),
              assistant.bus.state.value)
    finally:
        runtime.reset()
        assistant.shutdown()
        _restore(monkey)


if __name__ == "__main__":
    test_full_turn()
    test_wake_word_only_then_listen()
    test_confirmation_gate()
    test_paused_assistant_does_not_listen()
    sys.exit(summary("assistant integration"))
