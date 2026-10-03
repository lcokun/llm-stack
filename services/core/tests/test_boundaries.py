"""core must not know about HTTP. ADR 0001."""

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "src" / "llm_stack_core"
FORBIDDEN = {"fastapi", "starlette", "llm_stack_api"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_does_not_import_http_machinery() -> None:
    offenders = {
        str(path.relative_to(CORE)): sorted(_imported_roots(path) & FORBIDDEN)
        for path in CORE.rglob("*.py")
        if _imported_roots(path) & FORBIDDEN
    }
    assert not offenders, f"core imported HTTP machinery: {offenders}"
