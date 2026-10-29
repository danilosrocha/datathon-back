from functools import cache
from pathlib import Path

AGENTS_DIR = Path(__file__).parent


@cache
def load_prompt(agent: str, name: str) -> str:
    return (AGENTS_DIR / agent / "prompts" / f"{name}.md").read_text(encoding="utf-8")
