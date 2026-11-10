"""Content safety: duplicate keys, prompt-injection screening, conflict heuristics.

Memory is a classic prompt-injection channel: anything written today is replayed into a model's
context in every future session. recall-kit therefore (1) screens content on write and
quarantines anything that reads like instructions to an agent, and (2) always returns memory
inside a data envelope that tells the client the text is user data, not instructions.
"""

from __future__ import annotations

import hashlib
import re

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "override-instructions",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|all|earlier|system)\b.{0,20}\b(instructions?|rules?|prompts?|messages?)",
            re.I,
        ),
    ),
    (
        "role-hijack",
        re.compile(r"\b(you are now|act as|from now on you (are|will)|new instructions?:)", re.I),
    ),
    (
        "fake-role-tag",
        re.compile(r"(^|\n)\s*(system|assistant|developer)\s*:|<\s*/?\s*(system|instructions?)\s*>", re.I),
    ),
    (
        "tool-coercion",
        re.compile(
            r"\b(call|invoke|run|use)\b.{0,20}\b(the\s+)?(forget|delete|export|backup|shell|bash|tool)\b.{0,40}\b(all|every|now|immediately)\b",
            re.I,
        ),
    ),
    (
        "exfiltration",
        re.compile(
            r"\b(send|post|upload|exfiltrate|forward)\b.{0,60}\b(https?://|webhook|api key|token|password|secret)",
            re.I,
        ),
    ),
    (
        "secret-material",
        re.compile(
            r"\b(sk-ant-[a-z0-9-]{8,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})", re.I
        ),
    ),
]

_NUM = re.compile(r"(?<!\w)\d+(?:[.,:/-]\d+)*")
_NEG = re.compile(r"\b(not|never|no longer|isn't|doesn't|don't|won't|cannot|can't|stopped)\b", re.I)
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def screen(text: str) -> str | None:
    """Return a reason string if the text looks like an injection attempt or a secret."""
    for name, pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            return name
    return None


def normalize(text: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", text.lower())).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode()).hexdigest()


def numbers(text: str) -> set[str]:
    return set(_NUM.findall(text))


def negated(text: str) -> bool:
    return bool(_NEG.search(text))


def disagrees(a: str, b: str) -> bool:
    """Cheap contradiction signal for two texts already known to be about the same thing."""
    if normalize(a) == normalize(b):
        return False
    na, nb = numbers(a), numbers(b)
    if na and nb and na != nb:
        return True
    return negated(a) != negated(b)
