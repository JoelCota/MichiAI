"""Offline sanity checks — no microphone, no API calls, no audio hardware.

    python -m tests.test_core        (from the project root)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Keep timers/notes out of the user's real data files during tests.
os.environ.setdefault("MICHI_TESTING", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import check, summary  # noqa: E402


# --------------------------------------------------------------------------
def test_config() -> None:
    print("\nconfig")
    import os

    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-key")
    os.environ.setdefault("OPENCODE_API_KEY", "sk-test-key")
    os.environ.setdefault("OPENAI_API_KEY", "sk-test-key")
    from michi.config import _expand, load_config

    # Expansion tested against a variable we own, so a real key in .env can't
    # change the result.
    os.environ["MICHI_TEST_VAR"] = "expanded-value"
    check("${VAR} expands", _expand("${MICHI_TEST_VAR}") == "expanded-value")
    check("${VAR:-default} falls back", _expand("${MICHI_UNSET_VAR:-fallback}") == "fallback")
    check("unset var is marked missing",
          _expand("${MICHI_UNSET_VAR}") == "<<MISSING:MICHI_UNSET_VAR>>")
    check("expansion recurses into dicts",
          _expand({"a": ["${MICHI_TEST_VAR}"]}) == {"a": ["expanded-value"]})

    cfg = load_config()
    check("config.yaml parses", cfg.get("assistant.name") == "Michi")
    active = cfg.get("llm.active")
    check("dotted lookup resolves the active provider's model",
          isinstance(cfg.get(f"llm.providers.{active}.model"), str) if active else False)
    check("missing key returns default", cfg.get("nope.nope", "fallback") == "fallback")

    name, settings = cfg.active_provider()
    check("active provider resolves", name == active and "type" in settings,
          f"active={active} got={name} type={settings.get('type')}")
    check("provider api_key resolved from env",
          bool(settings["api_key"]) and not str(settings["api_key"]).startswith("<<MISSING"),
          str(settings["api_key"])[:12])

    cfg.data["llm"]["active"] = "does-not-exist"
    try:
        cfg.active_provider()
        check("unknown provider raises", False)
    except Exception as exc:
        check("unknown provider raises a clear error", "no such provider" in str(exc))
    cfg.data["llm"]["active"] = active

    # A provider whose env var is unset must fail loudly, not silently.
    cfg.data["llm"]["active"] = "groq"
    cfg.data["llm"]["providers"]["groq"]["api_key"] = "<<MISSING:GROQ_API_KEY>>"
    try:
        cfg.active_provider()
        check("missing API key raises", False)
    except Exception as exc:
        check("missing API key names the variable", "GROQ_API_KEY" in str(exc))


# --------------------------------------------------------------------------
def test_wake_matching() -> None:
    print("\nwake phrase matching")
    from michi.wake.stt_phrase import find_wake_phrase

    phrases = ["hey michi", "hey mishi", "hey michy", "hola michi", "oye michi"]

    for heard, expect_remainder in [
        ("Hey Michi, what time is it?", "what time is it"),
        ("hey mishi open spotify", "open spotify"),
        ("Hey, Michy!", ""),
        ("hola michi que hora es", "que hora es"),
    ]:
        matched, remainder = find_wake_phrase(heard, phrases, 0.75)
        check(f"wakes on {heard!r}", matched)
        check(f"  remainder {remainder!r}", remainder == expect_remainder, f"expected {expect_remainder!r}")

    for heard in ["the weather is nice today", "let me check my email", ""]:
        matched, _ = find_wake_phrase(heard, phrases, 0.75)
        check(f"ignores {heard!r}", not matched)


# --------------------------------------------------------------------------
def test_tools() -> None:
    print("\ntool registry")
    from michi.config import load_config
    from michi.tools import build_registry

    cfg = load_config()
    registry = build_registry(cfg)

    check("basics group loaded", "get_time" in registry.names())
    check("shell stays disabled", "shell_run" not in registry.names())

    specs = registry.specs()
    check("specs generated", len(specs) > 0)
    spec = next(s for s in specs if s.name == "start_timer")
    check("schema is a JSON-Schema object", spec.parameters["type"] == "object")
    check("required propagates", spec.parameters["required"] == ["minutes"])
    check("schema is JSON serialisable", bool(json.dumps(spec.parameters)))

    result = registry.call("get_time", {})
    check("tool executes", isinstance(result, str) and len(result) > 5, result)

    check("unknown tool is handled", "no tool named" in registry.call("nope", {}))
    check("bad args are handled", isinstance(registry.call("get_time", {"junk": 1}), str))

    registry.call("remember", {"key": "test note", "value": "42"})
    check("remember/recall round-trips", registry.call("recall", {"key": "test note"}) == "42")

    registry.call("remember", {"key": "forget me key", "value": "temp"})
    check("forget deletes", "Forgot" in registry.call("forget", {"key": "forget me key"}))
    check("recall after forget fails",
          "Nothing saved" in registry.call("recall", {"key": "forget me key"}))
    check("forgetting unknown key is handled",
          isinstance(registry.call("forget", {"key": "never saved"}), str))

    # Confirmation gate
    from michi.tools.registry import ToolRegistry

    denied = ToolRegistry(cfg, confirm_callback=lambda name: False)
    denied.load_groups(["basics"])
    denied.tools["get_time"].meta.confirm = True
    check("declining a confirm blocks the tool", "declined" in denied.call("get_time", {}))


# --------------------------------------------------------------------------
def test_tool_safety() -> None:
    print("\ntool safety: truncation, rate limits, timers")
    from michi.config import load_config
    from michi.tools import basics
    from michi.tools.registry import RegisteredTool, ToolMeta, ToolRegistry

    cfg = load_config()

    # -- huge results are truncated before they reach the model
    big = ToolRegistry(cfg)
    big.tools["blab"] = RegisteredTool(
        meta=ToolMeta(group="basics", description="test"), func=lambda: "x" * 5000
    )
    result = big.call("blab", {})
    check("long results are truncated", "truncated" in result, str(len(result)))
    check("truncated result is short", len(result) <= 2100, str(len(result)))
    check("short results pass through", big.tools["blab"].func()[:10] == "x" * 10)

    # -- per-tool rate limits
    limited = ToolRegistry(cfg)
    limited.rate_limits["ping"] = {"per_minute": 2}
    limited.tools["ping"] = RegisteredTool(
        meta=ToolMeta(group="basics", description="test"), func=lambda: "pong"
    )
    check("first calls pass", limited.call("ping", {}) == "pong"
          and limited.call("ping", {}) == "pong")
    check("third call is rate-limited", "per minute" in limited.call("ping", {}))

    # -- persistent timers: start, list, cancel
    basics._timers.clear()
    check("timer starts", "Timer set" in basics.start_timer(10, label="safety test timer"))
    listing = basics.list_timers()
    check("timer listed", "safety test timer" in listing, listing)
    check("timer file written", basics.TIMERS_FILE.exists())
    check("cancel removes it", "Cancelled" in basics.cancel_timer("safety test timer"))
    check("timer gone after cancel", "No timers" in basics.list_timers())
    check("cancel unknown label handled", isinstance(basics.cancel_timer("nope"), str))
    check("cancel with none running handled", "No timers" in basics.cancel_timer())

    # Unlabeled timers must not overwrite each other.
    basics.start_timer(5)
    basics.start_timer(5)
    check("two unlabeled timers coexist", basics.list_timers().count("unnamed") == 2)
    basics.cancel_timer()
    basics.cancel_timer()
    check("everything cancelled", "No timers" in basics.list_timers())
    basics._save_timers()

    # -- unknown arguments are dropped with a warning, not an error
    from michi.tools import build_registry

    registry = build_registry(cfg)
    check("unknown args handled without crash",
          isinstance(registry.call("get_time", {"junk": 1}), str))


# --------------------------------------------------------------------------
def test_history_summary() -> None:
    print("\nrolling history summary")
    from michi.agent.brain import Brain
    from michi.agent.history import History
    from michi.config import load_config
    from michi.llm.base import LLMProvider, Reply
    from michi.tools import build_registry

    history = History(max_turns=2)
    for i in range(5):
        history.add_user(f"msg {i}")
        history.add_assistant(f"reply {i}")
    dropped = history.trim()
    check("trim returns dropped turns", len(dropped) == 6, f"{len(dropped)}")
    check("trim keeps max_turns", len(history) == 4, f"{len(history)}")
    check("trim with nothing to drop returns empty", History(max_turns=9).trim() == [])

    class Summarizer(LLMProvider):
        def __init__(self):
            self.model = "sum"
            self.prompts: list[str] = []

        def chat(self, messages, system="", tools=None):
            self.prompts.append(messages[-1]["content"])
            return Reply(text="The user asked several test questions.")

    cfg = load_config()
    provider = Summarizer()
    brain = Brain(cfg, provider, build_registry(cfg))
    summary = brain._summarize(dropped)
    check("summary produced", bool(summary), summary)
    check("summary prompt contains the dropped text", "msg 2" in provider.prompts[0],
          provider.prompts[0][:80])
    brain.history.set_summary(summary)
    check("system prompt includes summary", "test questions" in brain.system_prompt())


# --------------------------------------------------------------------------
def test_fallback_chain() -> None:
    print("\nfallback chain")
    from michi.llm.base import LLMProvider, Reply, StreamChunk
    from michi.llm.fallback import FallbackProvider

    class Dead(LLMProvider):
        def __init__(self, name="dead"):
            self.name = name
            self.model = "dead"
            self.settings = {"model": "dead"}

        def chat(self, messages, system="", tools=None):
            raise ConnectionError("boom")

    class Live(LLMProvider):
        def __init__(self):
            self.name = "live"
            self.model = "live"
            self.settings = {"model": "live"}

        def chat(self, messages, system="", tools=None):
            return Reply(text="All good.")

    chain = FallbackProvider([Dead(), Live()])
    check("falls through to the healthy provider", chain.chat([]).text == "All good.")
    check("describe shows the chain",
          "dead" in chain.describe() and "live" in chain.describe(), chain.describe())

    all_dead = FallbackProvider([Dead("a"), Dead("b")])
    try:
        all_dead.chat([])
        check("all-dead raises", False)
    except Exception as exc:
        check("all-dead raises a clear error", "All providers failed" in str(exc), str(exc))

    # Streaming: a mid-stream failure switches to the next provider.
    class StreamDead(LLMProvider):
        supports_streaming = True

        def __init__(self):
            self.name = "sd"
            self.model = "s1"
            self.settings = {"model": "s1"}

        def chat(self, messages, system="", tools=None):
            raise AssertionError("should stream")

        def chat_stream(self, messages, system="", tools=None):
            yield StreamChunk(text="parti")
            raise ConnectionError("mid-stream")

    class StreamLive(LLMProvider):
        supports_streaming = True

        def __init__(self):
            self.name = "sl"
            self.model = "s2"
            self.settings = {"model": "s2"}

        def chat(self, messages, system="", tools=None):
            raise AssertionError("should stream")

        def chat_stream(self, messages, system="", tools=None):
            yield StreamChunk(text="full ")
            yield StreamChunk(reply=Reply(text="full answer"))

    streamed = list(FallbackProvider([StreamDead(), StreamLive()]).chat_stream([]))
    check("stream ends with a final chunk",
          streamed[-1].is_final and streamed[-1].reply.text == "full answer",
          f"{streamed[-1].reply.text if streamed[-1].is_final else 'no final'}")
    check("next provider text arrives", any(c.text == "full " for c in streamed))


# --------------------------------------------------------------------------
def test_hybrid_wake() -> None:
    print("\nhybrid wake phrases")
    from michi.config import load_config
    from michi.wake.hybrid import hybrid_phrases

    cfg = load_config()
    phrases = hybrid_phrases(cfg, gate_label="hey_jarvis")
    check("gate word accepted first", phrases[0] == "hey jarvis", f"{phrases}")
    configured = [str(p) for p in cfg.section("wake.stt_phrase").get("phrases", [])]
    missing = [p for p in configured if p not in phrases]
    check("configured wake phrases still present", not missing, f"missing: {missing}")
    check("no duplicates", len(phrases) == len(set(phrases)))

    custom = hybrid_phrases(cfg, gate_label="michi_wake_word")
    check("custom model label becomes a phrase", "michi wake word" in custom, f"{custom}")

    defaulted = hybrid_phrases(cfg)
    check("defaults to the configured gate model", defaulted[0] == "hey jarvis", f"{defaulted}")


# --------------------------------------------------------------------------
def test_message_conversion() -> None:
    print("\nprovider message conversion")
    from michi.llm.anthropic_provider import AnthropicProvider
    from michi.llm.base import ToolCall, ToolSpec
    from michi.llm.openai_compat import OpenAICompatProvider

    call = ToolCall(id="call_1", name="set_volume", arguments={"direction": "up"})
    conversation = [
        {"role": "user", "content": "turn it up"},
        {"role": "assistant", "content": "", "tool_calls": [call]},
        {"role": "tool", "tool_call_id": "call_1", "name": "set_volume", "content": "Volume up."},
        {"role": "user", "content": "thanks"},
    ]

    # --- Anthropic shape
    anthropic_messages = AnthropicProvider._to_anthropic(conversation)
    check("anthropic: assistant emits tool_use", any(
        m["role"] == "assistant" and isinstance(m["content"], list)
        and m["content"][0]["type"] == "tool_use" for m in anthropic_messages))
    check("anthropic: result becomes user tool_result", any(
        m["role"] == "user" and isinstance(m["content"], list)
        and m["content"][0]["type"] == "tool_result" for m in anthropic_messages))
    check("anthropic: roles alternate correctly",
          [m["role"] for m in anthropic_messages] == ["user", "assistant", "user", "user"])

    spec = ToolSpec(name="t", description="d", parameters={"type": "object", "properties": {}})
    check("anthropic: tools use input_schema",
          "input_schema" in AnthropicProvider._tools([spec])[0])

    # -- extra_body pass-through (e.g. thinking: disabled for reasoning models)
    from michi.llm.openai_compat import OpenAICompatProvider as _OAI

    provider = object.__new__(_OAI)
    provider.model = "test"
    provider.max_tokens = 100
    provider.temperature = 0.5
    provider.settings = {"extra_body": {"thinking": {"type": "disabled"}}}
    kwargs = provider._request_kwargs([{"role": "user", "content": "hi"}], "", None)
    check("extra_body passed through",
          kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}, f"{kwargs}")
    provider.settings = {}
    check("no extra_body when unset",
          "extra_body" not in provider._request_kwargs(
              [{"role": "user", "content": "hi"}], "", None))

    # --- OpenAI shape
    openai_messages = OpenAICompatProvider._to_openai(conversation, "you are michi")
    check("openai: system goes first", openai_messages[0]["role"] == "system")
    assistant = next(m for m in openai_messages if m["role"] == "assistant")
    check("openai: tool_calls serialised", assistant["tool_calls"][0]["function"]["name"] == "set_volume")
    check("openai: arguments are a JSON string",
          json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"direction": "up"})
    check("openai: tool role preserved",
          any(m["role"] == "tool" and m["tool_call_id"] == "call_1" for m in openai_messages))
    check("openai: tools wrapped in function envelope",
          OpenAICompatProvider._tools([spec])[0]["type"] == "function")


# --------------------------------------------------------------------------
def test_brain_tool_loop() -> None:
    print("\nagent loop (mocked provider)")
    from michi.agent.brain import Brain
    from michi.config import load_config
    from michi.llm.base import LLMProvider, Reply, ToolCall
    from michi.tools import build_registry

    class ScriptedProvider(LLMProvider):
        def __init__(self, replies):
            self.replies = list(replies)
            self.seen: list[list[dict]] = []
            self.model = "scripted"

        def chat(self, messages, system="", tools=None):
            self.seen.append(list(messages))
            return self.replies.pop(0)

    cfg = load_config()
    registry = build_registry(cfg)

    provider = ScriptedProvider([
        Reply(text="", tool_calls=[ToolCall(id="c1", name="get_time", arguments={})]),
        Reply(text="It's just after two."),
    ])
    brain = Brain(cfg, provider, registry)
    answer = brain.respond("what time is it")

    check("final answer returned", answer == "It's just after two.")
    check("tool round-trip happened", len(provider.seen) == 2)
    check("tool result fed back", any(m["role"] == "tool" for m in provider.seen[1]))
    check("history keeps the exchange", len(brain.history) == 4)

    # A failing provider must not take the assistant down.
    class BrokenProvider(LLMProvider):
        def __init__(self):
            self.model = "broken"

        def chat(self, messages, system="", tools=None):
            raise ConnectionError("no network")

    broken = Brain(cfg, BrokenProvider(), registry)
    reply = broken.respond("hello")
    check("provider failure degrades gracefully", "couldn't reach" in reply.lower(), reply)
    check("failed turn not left in history", len(broken.history) == 0)

    # History trimming
    brain.history.max_turns = 2
    for i in range(6):
        brain.history.add_user(f"msg {i}")
        brain.history.add_assistant("ok")
    brain.history.trim()
    users = [m for m in brain.history.messages if m["role"] == "user"]
    check("history trims to max_turns", len(users) == 2, f"got {len(users)}")


# --------------------------------------------------------------------------
def test_imports() -> None:
    print("\nmodule imports")
    for module in [
        "michi.config", "michi.runtime", "michi.logging_setup", "michi.events",
        "michi.diagnostics", "michi.llm", "michi.llm.base", "michi.llm.fallback",
        "michi.llm.anthropic_provider", "michi.llm.openai_compat",
        "michi.tools", "michi.tools.registry", "michi.tools.basics",
        "michi.tools.system", "michi.tools.apps", "michi.tools.web",
        "michi.tools.clipboard", "michi.tools.shell",
        "michi.agent.brain", "michi.agent.history",
        "michi.wake.stt_phrase", "michi.wake.base", "michi.wake.hotkey",
        "michi.wake.hybrid", "michi.wake.openwakeword_engine",
        "michi.tts.speaker", "michi.tts.base", "michi.__main__",
    ]:
        try:
            __import__(module)
            check(f"import {module}", True)
        except Exception as exc:
            check(f"import {module}", False, str(exc))


if __name__ == "__main__":
    test_imports()
    test_config()
    test_wake_matching()
    test_tools()
    test_message_conversion()
    test_brain_tool_loop()
    sys.exit(summary("core"))
