"""Streaming, speech chunking and run-state checks — still no audio, no network."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import check, summary  # noqa: E402


# ---------------------------------------------------------------------------
def test_sentence_splitting() -> None:
    print("\nsentence splitting")
    from michi.tts.speaker import split_sentences

    cases = [
        ("Hello there. How are you?", ["Hello there.", "How are you?"]),
        ("One sentence only", ["One sentence only"]),
        ("", []),
        # A short fragment gets merged forward rather than spoken alone.
        ("Sure. I opened Spotify for you.", ["Sure. I opened Spotify for you."]),
        # Decimals must not split.
        ("The CPU is at 3.5 percent right now.", ["The CPU is at 3.5 percent right now."]),
        # Titles must not split.
        ("Dr. Smith called you back.", ["Dr. Smith called you back."]),
        # Newlines are boundaries.
        ("The first line of text\nThe second line of text",
         ["The first line of text", "The second line of text"]),
        # Fragments below min_chars merge forward rather than being spoken alone.
        ("Yes. Ok.", ["Yes. Ok."]),
    ]
    for text, expected in cases:
        got = split_sentences(text)
        check(f"split {text!r}", got == expected, f"got {got}")

    long_text = "This is the first sentence. This is the second one! And a third?"
    check("three sentences found", len(split_sentences(long_text)) == 3)
    check("min_chars is honoured",
          len(split_sentences("Ab. Cd. Ef.", min_chars=1)) == 3,
          f"{split_sentences('Ab. Cd. Ef.', min_chars=1)}")


# ---------------------------------------------------------------------------
def test_speaker_queue() -> None:
    print("\nspeech queue")
    from michi.tts.speaker import Speaker

    class FakeEngine:
        name = "fake"

        def __init__(self):
            self.spoken: list[str] = []
            self.stopped = 0

        def speak(self, text):
            self.spoken.append(text)

        def stop(self):
            self.stopped += 1

    engine = FakeEngine()
    speaker = Speaker(engine, bus=None)

    speaker.begin()
    # Feed a reply the way a stream would deliver it.
    for delta in ["Sure thing, ", "I can do that. ", "Opening Spotify now."]:
        speaker.feed(delta)
    speaker.flush()
    speaker.wait()

    check("all text was spoken", len(engine.spoken) >= 1, f"got {engine.spoken}")
    joined = " ".join(engine.spoken)
    check("first sentence queued before the rest", "Sure thing" in engine.spoken[0])
    check("nothing was dropped", "Opening Spotify now." in joined, joined)

    # Interruption
    engine2 = FakeEngine()
    speaker2 = Speaker(engine2, bus=None)
    speaker2.begin()
    speaker2.say("One. Two. Three. Four. Five.")
    speaker2.interrupt()
    speaker2.wait(timeout=1.0)
    check("interrupt calls engine.stop", engine2.stopped >= 1)
    check("interrupt drops queued sentences", len(engine2.spoken) < 5, f"{engine2.spoken}")

    speaker.shutdown()
    speaker2.shutdown()


# ---------------------------------------------------------------------------
def _openai_chunk(content=None, tool_fragments=None):
    tool_calls = None
    if tool_fragments:
        tool_calls = [
            SimpleNamespace(
                index=fragment.get("index", 0),
                id=fragment.get("id"),
                function=SimpleNamespace(
                    name=fragment.get("name"), arguments=fragment.get("arguments")
                ),
            )
            for fragment in tool_fragments
        ]
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def test_openai_streaming() -> None:
    print("\nopenai-compatible streaming")
    from michi.llm.openai_compat import OpenAICompatProvider

    provider = object.__new__(OpenAICompatProvider)
    provider.model = "test"
    provider.max_tokens = 100
    provider.temperature = 0.5

    # -- plain text stream
    chunks = [_openai_chunk("Hel"), _openai_chunk("lo the"), _openai_chunk("re.")]
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: iter(chunks)))
    )
    deltas, final = [], None
    for chunk in provider.chat_stream([{"role": "user", "content": "hi"}]):
        (deltas.append(chunk.text) if not chunk.is_final else None)
        if chunk.is_final:
            final = chunk.reply
    check("text deltas streamed", deltas == ["Hel", "lo the", "re."], f"{deltas}")
    check("final text assembled", final.text == "Hello there.", final.text)
    check("no phantom tool calls", final.tool_calls == [])

    # -- tool call fragmented across chunks (the part that actually breaks)
    tool_chunks = [
        _openai_chunk(tool_fragments=[{"index": 0, "id": "call_9", "name": "set_volume"}]),
        _openai_chunk(tool_fragments=[{"index": 0, "arguments": '{"direct'}]),
        _openai_chunk(tool_fragments=[{"index": 0, "arguments": 'ion": "up"}'}]),
    ]
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: iter(tool_chunks)))
    )
    final = None
    for chunk in provider.chat_stream([{"role": "user", "content": "louder"}]):
        if chunk.is_final:
            final = chunk.reply
    check("tool call reassembled", len(final.tool_calls) == 1, f"{final.tool_calls}")
    check("tool name preserved", final.tool_calls[0].name == "set_volume")
    check("fragmented JSON parsed", final.tool_calls[0].arguments == {"direction": "up"},
          f"{final.tool_calls[0].arguments}")
    check("tool id preserved", final.tool_calls[0].id == "call_9")

    # -- malformed arguments must not crash the loop
    bad = [_openai_chunk(tool_fragments=[{"index": 0, "id": "c", "name": "t",
                                          "arguments": "{not json"}])]
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: iter(bad)))
    )
    final = [c.reply for c in provider.chat_stream([]) if c.is_final][0]
    check("bad JSON degrades to empty args", final.tool_calls[0].arguments == {})


# ---------------------------------------------------------------------------
def test_anthropic_streaming() -> None:
    print("\nanthropic streaming")
    from michi.llm.anthropic_provider import AnthropicProvider

    provider = object.__new__(AnthropicProvider)
    provider.model = "test"
    provider.max_tokens = 100
    provider.temperature = 0.5

    events = [
        SimpleNamespace(type="content_block_start"),
        SimpleNamespace(type="content_block_delta",
                        delta=SimpleNamespace(type="text_delta", text="It's ")),
        SimpleNamespace(type="content_block_delta",
                        delta=SimpleNamespace(type="text_delta", text="two o'clock.")),
        # A non-text delta must be ignored, not spoken.
        SimpleNamespace(type="content_block_delta",
                        delta=SimpleNamespace(type="input_json_delta", partial_json='{"a":1}')),
    ]
    final_message = SimpleNamespace(content=[
        SimpleNamespace(type="text", text="It's two o'clock."),
        SimpleNamespace(type="tool_use", id="tu_1", name="get_time", input={"tz": "local"}),
    ])

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            return iter(events)

        def get_final_message(self):
            return final_message

    provider.client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: FakeStream()))

    deltas, final = [], None
    for chunk in provider.chat_stream([{"role": "user", "content": "time?"}]):
        if chunk.is_final:
            final = chunk.reply
        elif chunk.text:
            deltas.append(chunk.text)

    check("text deltas streamed", deltas == ["It's ", "two o'clock."], f"{deltas}")
    check("json deltas not streamed as text", "".join(deltas).count("{") == 0)
    check("final text assembled", final.text == "It's two o'clock.")
    check("tool call captured from final message", final.tool_calls[0].name == "get_time")
    check("tool args captured", final.tool_calls[0].arguments == {"tz": "local"})


# ---------------------------------------------------------------------------
def test_brain_streaming() -> None:
    print("\nbrain streaming path")
    from michi.agent.brain import Brain
    from michi.config import load_config
    from michi.llm.base import LLMProvider, Reply, StreamChunk, ToolCall
    from michi.tools import build_registry

    class StreamingProvider(LLMProvider):
        supports_streaming = True

        def __init__(self, scripts):
            self.scripts = list(scripts)
            self.model = "stream-test"

        def chat(self, messages, system="", tools=None):
            raise AssertionError("chat() should not be used when streaming")

        def chat_stream(self, messages, system="", tools=None):
            for chunk in self.scripts.pop(0):
                yield chunk

    cfg = load_config()
    registry = build_registry(cfg)

    provider = StreamingProvider([
        # Round 1: a bit of text, then a tool call. The pre-tool text must not
        # be spoken — the model hasn't done anything yet.
        [StreamChunk(text="One sec. "),
         StreamChunk(reply=Reply(text="One sec.",
                                 tool_calls=[ToolCall(id="c1", name="get_time")]))],
        # Round 2: the real answer, streamed.
        [StreamChunk(text="It's "), StreamChunk(text="late."),
         StreamChunk(reply=Reply(text="It's late."))],
    ])

    brain = Brain(cfg, provider, registry)
    spoken: list[str] = []
    answer = brain.respond("what time is it", on_delta=spoken.append)

    check("pre-tool text suppressed", spoken == ["It's late."], f"{spoken}")
    check("final answer returned", answer == "It's late.", answer)
    check("tool result recorded", any(m["role"] == "tool" for m in brain.history.messages))

    # Multi-sentence answers still stream: the first sentence is spoken while
    # the rest is generating, only the trailing sentence waits for the end.
    provider2 = StreamingProvider([
        [StreamChunk(text="First sentence. "), StreamChunk(text="Second sentence."),
         StreamChunk(reply=Reply(text="First sentence. Second sentence."))],
    ])
    spoken2: list[str] = []
    brain2 = Brain(cfg, provider2, registry)
    brain2.respond("hello", on_delta=spoken2.append)
    check("complete sentences stream early",
          spoken2 == ["First sentence.", "Second sentence."], f"{spoken2}")

    # A round that ends in tools must not leak its trailing sentence either.
    provider3 = StreamingProvider([
        [StreamChunk(text="Let me look. "), StreamChunk(text="Doing it now."),
         StreamChunk(reply=Reply(text="Let me look. Doing it now.",
                                 tool_calls=[ToolCall(id="c2", name="get_time")]))],
        [StreamChunk(reply=Reply(text="Done."))],
    ])
    spoken3: list[str] = []
    brain3 = Brain(cfg, provider3, registry)
    answer3 = brain3.respond("again", on_delta=spoken3.append)
    check("trailing sentence before a tool call is dropped",
          spoken3 == ["Let me look."] and answer3 == "Done.", f"{spoken3} / {answer3}")

    # Non-streaming providers still work through the same call path.
    class PlainProvider(LLMProvider):
        supports_streaming = False

        def __init__(self):
            self.model = "plain"

        def chat(self, messages, system="", tools=None):
            return Reply(text="Plain answer.")

    plain = Brain(cfg, PlainProvider(), registry)
    collected: list[str] = []
    check("non-streaming provider still answers",
          plain.respond("hi", on_delta=collected.append) == "Plain answer.")
    check("no deltas emitted for non-streaming provider", collected == [])

    # The default chat_stream wrapper on a provider that only implements chat()
    wrapped = list(PlainProvider().chat_stream([{"role": "user", "content": "hi"}]))
    check("base chat_stream yields one final chunk",
          len(wrapped) == 1 and wrapped[0].is_final)


# ---------------------------------------------------------------------------
def test_runtime_and_events() -> None:
    print("\nrun state and events")
    from michi import runtime
    from michi.events import BUS, EventBus, State

    runtime.reset()
    check("starts running", runtime.should_run())
    check("starts unpaused", not runtime.is_paused())

    check("toggle pauses", runtime.toggle_pause() is True)
    check("is_paused reflects it", runtime.is_paused())
    check("paused is still running", runtime.should_run())
    check("toggle resumes", runtime.toggle_pause() is False)

    runtime.pause()
    runtime.resume()
    check("explicit resume works", not runtime.is_paused())

    runtime.request_shutdown()
    check("shutdown stops the loop", not runtime.should_run())
    runtime.reset()
    check("reset restores", runtime.should_run())

    seen: list[tuple] = []
    bus = EventBus()
    bus.subscribe(lambda state, detail: seen.append((state, detail)))
    check("subscriber gets current state immediately", len(seen) == 1)
    bus.set_state(State.LISTENING)
    bus.set_state(State.LISTENING)  # duplicate must not re-fire
    bus.set_state(State.THINKING, "tool")
    check("duplicate states are collapsed", len(seen) == 3, f"{seen}")
    check("detail carried", seen[-1] == (State.THINKING, "tool"))
    check("states have labels", bool(State.IDLE.label) and bool(BUS.state.label))

    # A misbehaving listener must not break the bus.
    bus.subscribe(lambda s, d: 1 / 0)
    bus.set_state(State.IDLE)
    check("listener exceptions are contained", bus.state == State.IDLE)


# ---------------------------------------------------------------------------
def test_new_config_keys() -> None:
    print("\nnew config keys")
    from michi.config import load_config

    cfg = load_config()
    check("assistant.streaming present", cfg.get("assistant.streaming") is True)
    check("audio.barge_in defaults off", cfg.get("audio.barge_in") is False)
    check("audio.chime.enabled present", cfg.get("audio.chime.enabled") is True)
    check("ui.tray present", isinstance(cfg.get("ui.tray"), bool))
    check("tts.min_chunk_chars present", isinstance(cfg.get("tts.min_chunk_chars"), int))

    # config.example.yaml must stay in step with config.yaml.
    import yaml

    from michi.config import PROJECT_ROOT

    with open(PROJECT_ROOT / "config.example.yaml", encoding="utf-8") as fh:
        example = yaml.safe_load(fh)

    def keys(node, prefix=""):
        found = set()
        if isinstance(node, dict):
            for key, value in node.items():
                path = f"{prefix}.{key}" if prefix else key
                found.add(path)
                found |= keys(value, path)
        return found

    with open(PROJECT_ROOT / "config.yaml", encoding="utf-8") as fh:
        live = yaml.safe_load(fh)

    missing = keys(live) - keys(example)
    check("example config covers every key", not missing, f"missing: {sorted(missing)}")


if __name__ == "__main__":
    test_sentence_splitting()
    test_speaker_queue()
    test_openai_streaming()
    test_anthropic_streaming()
    test_brain_streaming()
    test_runtime_and_events()
    test_new_config_keys()
    sys.exit(summary())
