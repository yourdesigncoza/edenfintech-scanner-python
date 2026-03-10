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
    anthropic_api_key: str | None = None
    analyst_model: str = "claude-sonnet-4-5-20250514"

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


def _looks_like_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "assets" / "methodology" / "scan-report.schema.json").exists()


def discover_project_root(start: Path | None = None) -> Path | None:
    search_roots: list[Path] = []
    if start is not None:
        search_roots.append(start.resolve())
    search_roots.append(Path.cwd().resolve())
    search_roots.append(Path(__file__).resolve().parents[2])

    seen: set[Path] = set()
    for root in search_roots:
        for candidate in [root, *root.parents]:
            if candidate in seen:
                continue
            seen.add(candidate)
            if _looks_like_project_root(candidate):
                return candidate
    return None


def discover_dotenv_path(start: Path | None = None) -> Path | None:
    explicit = os.environ.get("EDENFINTECH_SCANNER_DOTENV")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.exists() else None

    project_root = discover_project_root(start)
    if project_root is None:
        return None

    dotenv_path = project_root / ".env"
    return dotenv_path if dotenv_path.exists() else None


def load_dotenv(dotenv_path: Path | None = None, *, override: bool = False) -> Path | None:
    path = dotenv_path or discover_dotenv_path()
    if path is None:
        return None
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
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        analyst_model=os.environ.get("ANALYST_MODEL", "claude-sonnet-4-5-20250514"),
    )
