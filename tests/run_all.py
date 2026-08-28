"""Run every offline test module in one pass.

    python -m tests.run_all      (from the project root, or via run_tests.bat)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Keep the suite out of the user's real data files (timers, notes).
os.environ.setdefault("MICHI_TESTING", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import harness, test_assistant, test_core, test_streaming  # noqa: E402

MODULES = [
    ("core", [
        test_core.test_imports,
        test_core.test_config,
        test_core.test_wake_matching,
        test_core.test_tools,
        test_core.test_tool_safety,
        test_core.test_history_summary,
        test_core.test_fallback_chain,
        test_core.test_hybrid_wake,
        test_core.test_message_conversion,
        test_core.test_brain_tool_loop,
    ]),
    ("streaming & runtime", [
        test_streaming.test_sentence_splitting,
        test_streaming.test_speaker_queue,
        test_streaming.test_openai_streaming,
        test_streaming.test_anthropic_streaming,
        test_streaming.test_brain_streaming,
        test_streaming.test_runtime_and_events,
        test_streaming.test_new_config_keys,
    ]),
    ("assistant integration", [
        test_assistant.test_full_turn,
        test_assistant.test_wake_word_only_then_listen,
        test_assistant.test_confirmation_gate,
        test_assistant.test_paused_assistant_does_not_listen,
    ]),
]

if __name__ == "__main__":
    harness.reset()
    for group, functions in MODULES:
        print(f"\n{'#' * 62}\n#  {group}\n{'#' * 62}")
        for function in functions:
            function()
    sys.exit(harness.summary("Michi offline test suite"))
