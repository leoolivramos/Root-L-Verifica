"""RNF-03: the verification engine is LLM-free (enforced by import scanning)."""

from __future__ import annotations

import ast
from pathlib import Path

VERIFICATION = Path(__file__).parent.parent / "src" / "reliability" / "verification"
FORBIDDEN = ("openai", "instructor", "reliability.claims", "reliability.search", "reliability.demo", "httpx")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


def test_verification_package_has_no_llm_imports():
    files = list(VERIFICATION.glob("*.py"))
    assert len(files) >= 4
    for f in files:
        for mod in _imports(f):
            assert not mod.startswith(FORBIDDEN), f"{f.name} imports forbidden module {mod}"
