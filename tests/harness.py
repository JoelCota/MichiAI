"""Minimal shared assertion helpers — no pytest dependency needed to run these."""

from __future__ import annotations

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    ok = bool(condition)
    (PASSED if ok else FAILED).append(f"{name}{' — ' + detail if detail else ''}")
    suffix = f"  {detail}" if detail and not ok else ""
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{suffix}")
    return ok


def summary(title: str = "") -> int:
    print(f"\n{'=' * 62}")
    if title:
        print(f"  {title}")
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    for item in FAILED:
        print(f"    FAILED: {item}")
    print(f"{'=' * 62}\n")
    return 1 if FAILED else 0


def reset() -> None:
    PASSED.clear()
    FAILED.clear()
