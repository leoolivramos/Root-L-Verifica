"""Prompt-injection isolation (RNF-02): untrusted text is wrapped in strict <doc> delimiters."""

from __future__ import annotations

import re

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# bidi overrides / isolates / zero-width characters used to hide instructions
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
_DOC_TAG_RE = re.compile(r"<\s*/?\s*doc\b[^>]*>", re.IGNORECASE)


def clean_untrusted(text: str) -> str:
    text = _CONTROL_RE.sub("", text)
    text = _INVISIBLE_RE.sub("", text)
    # neutralise anything that looks like our delimiters so the doc cannot "close" itself
    text = _DOC_TAG_RE.sub(lambda m: "[" + m.group(0).strip("<>") + "]", text)
    return text


def wrap_untrusted(text: str) -> str:
    return f"<doc>\n{clean_untrusted(text)}\n</doc>"
