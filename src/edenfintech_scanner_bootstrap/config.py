from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    fmp_api_key: str | None
    gemini_api_key: str | None
    openai_api_key: str | None
    codex_judge_model: str

    def require(self, *fields: str) -> None:
        missing = [field for field in fields if not getattr(self, field)]
        if missing:
            raise ValueError(f"missing required configuration: {', '.join(missing)}")


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if value and ((value[0] == value[-1]) and value[0] in {"'", '"'}):
        value = value[1:-1]
    return key, value


def load_dotenv(dotenv_path: Path | None = None, *, override: bool = False) -> Path | None:
    path = dotenv_path or Path.cwd() / ".env"
    if not path.exists():
        return None

    for line in path.read_text().splitlines():
        parsed = _parse_dotenv_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value

    return path


def load_config(dotenv_path: Path | None = None) -> AppConfig:
    load_dotenv(dotenv_path)
    return AppConfig(
        fmp_api_key=os.environ.get("FMP_API_KEY") or None,
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        codex_judge_model=os.environ.get("CODEX_JUDGE_MODEL", "gpt-5-codex"),
    )
