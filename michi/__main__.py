"""Entry point:  python -m michi  [options]"""

from __future__ import annotations

import argparse
import sys

from .config import ConfigError, check_config, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="michi",
        description="Michi — a local voice assistant with a swappable model backend.",
    )
    parser.add_argument("-c", "--config", help="path to config.yaml")

    checks = parser.add_argument_group("checks")
    checks.add_argument("--check", action="store_true", help="validate config and exit")
    checks.add_argument("--doctor", action="store_true",
                        help="full self-test: audio, speech, model, voice")
    checks.add_argument("--no-audio", action="store_true",
                        help="with --doctor, skip the microphone and speaker tests")
    checks.add_argument("--devices", action="store_true", help="list audio devices and exit")
    checks.add_argument("--voices", action="store_true", help="list TTS voices and exit")
    checks.add_argument("--say", metavar="TEXT", help="speak TEXT and exit (tests the voice)")
    checks.add_argument("--tune-wake", action="store_true",
                        help="live wake-word scores, for setting the threshold")

    run = parser.add_argument_group("running")
    run.add_argument("--text", action="store_true", help="keyboard chat, no microphone")
    run.add_argument("--tray", action="store_true", help="show the system tray icon")
    run.add_argument("--no-tray", action="store_true", help="force the tray icon off")
    run.add_argument("--provider", metavar="NAME", help="override llm.active for this run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.check:
        return check_config(args.config)

    if args.devices:
        from .audio import list_devices

        print("Audio devices:\n" + list_devices())
        return 0

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return 1

    if args.provider:
        cfg.data.setdefault("llm", {})["active"] = args.provider

    if args.doctor:
        from .diagnostics import run_doctor
        from .logging_setup import setup_logging

        setup_logging(cfg)
        return run_doctor(cfg, skip_audio=args.no_audio)

    if args.tune_wake:
        from .diagnostics import tune_wake
        from .logging_setup import setup_logging

        setup_logging(cfg)
        return tune_wake(cfg)

    if args.voices:
        engine = str(cfg.get("tts.engine", "sapi")).lower()
        if engine == "edge":
            from .tts.edge import EdgeTTS

            print(EdgeTTS.list_voices(str(cfg.get("assistant.language", "en"))))
        else:
            from .tts.sapi import SapiTTS

            print(SapiTTS.list_voices())
        return 0

    if args.say:
        from .logging_setup import setup_logging
        from .tts import create_tts

        setup_logging(cfg)
        create_tts(cfg).speak(args.say)
        return 0

    from .agent import Assistant

    try:
        assistant = Assistant(cfg)
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return 1
    except RuntimeError as exc:
        print(f"Startup failed: {exc}")
        return 1

    with_tray = None
    if args.tray:
        with_tray = True
    elif args.no_tray:
        with_tray = False

    try:
        if args.text:
            assistant.run_text_mode()
        else:
            assistant.run(with_tray=with_tray)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        assistant.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
