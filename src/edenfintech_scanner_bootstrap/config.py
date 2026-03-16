from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    # --- API keys (secrets — load from .env.age) ---
    fmp_api_key: str | None
    gemini_api_key: str | None
    openai_api_key: str | None
    anthropic_api_key: str | None = None
    # --- Model configuration (defaults here, override via env if needed) ---
    codex_judge_model: str = "gpt-4o-mini"
    analyst_model: str = "claude-haiku-4-5-20251001"
    analyst_fundamentals_model: str = "claude-haiku-4-5-20251001"
    analyst_qualitative_model: str = "claude-haiku-4-5-20251001"
    analyst_synthesis_model: str = "claude-sonnet-4-20250514"
    llm_provider: str = "anthropic"
    llm_model: str = "claude-haiku-4-5-20251001"
    # --- Timeouts ---
    llm_timeout: int = 360
    llm_synthesis_timeout: int = 600
    # --- Sampling (tiered by agent role) ---
    analyst_temperature: float = 0.0
    adversarial_temperature: float = 0.6
    reviewer_temperature: float = 0.2
    # --- Other ---
    sector_staleness_days: int = 7

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


def _default_age_identity() -> Path:
    """Return the default age identity file path."""
    explicit = os.environ.get("AGE_IDENTITY")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".config" / "sops" / "age" / "keys.txt"


def _decrypt_age_file(age_path: Path) -> str:
    """Decrypt an age-encrypted file to string. Requires ``age`` on PATH."""
    identity = _default_age_identity()
    cmd = ["age", "--decrypt", "--identity", str(identity), str(age_path)]
    result = subprocess.run(
        cmd,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"age decrypt failed for {age_path}: {stderr}")
    return result.stdout.decode()


def _load_dotenv_text(text: str, *, override: bool = False) -> None:
    """Parse dotenv-formatted text and inject into ``os.environ``."""
    for line in text.splitlines():
        parsed = _parse_dotenv_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value


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


def discover_age_path(start: Path | None = None) -> Path | None:
    """Find ``.env.age`` in the project root."""
    project_root = discover_project_root(start)
    if project_root is None:
        return None
    age_path = project_root / ".env.age"
    return age_path if age_path.exists() else None


def load_dotenv(dotenv_path: Path | None = None, *, override: bool = False) -> Path | None:
    path = dotenv_path or discover_dotenv_path()
    if path is None:
        return None
    if not path.exists():
        return None

    _load_dotenv_text(path.read_text(), override=override)
    return path


def load_secrets(dotenv_path: Path | None = None, *, override: bool = False) -> Path | None:
    """Load secrets with priority: env already set > .env.age > .env.

    Returns the path that was loaded, or None if secrets were already
    present or no source was found.
    """
    # If key env vars are already set (e.g. Railway, CI), nothing to do.
    if os.environ.get("FMP_API_KEY"):
        return None

    # Prefer encrypted .env.age when age is available.
    age_path = discover_age_path()
    if age_path is not None and shutil.which("age"):
        text = _decrypt_age_file(age_path)
        _load_dotenv_text(text, override=override)
        return age_path

    # Fall back to plaintext .env (legacy / CI without age).
    return load_dotenv(dotenv_path, override=override)


def load_config(dotenv_path: Path | None = None) -> AppConfig:
    load_secrets(dotenv_path)

    def _env(key: str, default: str | None = None) -> str | None:
        return os.environ.get(key, default) or default

    return AppConfig(
        # Secrets (from .env.age or environment)
        fmp_api_key=os.environ.get("FMP_API_KEY") or None,
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        # Config overrides (defaults in AppConfig are the source of truth;
        # env vars only needed for deployment-specific overrides)
        **{k: v for k, v in {
            "codex_judge_model": _env("CODEX_JUDGE_MODEL"),
            "analyst_model": _env("ANALYST_MODEL"),
            "analyst_fundamentals_model": _env("ANALYST_FUNDAMENTALS_MODEL"),
            "analyst_qualitative_model": _env("ANALYST_QUALITATIVE_MODEL"),
            "analyst_synthesis_model": _env("ANALYST_SYNTHESIS_MODEL"),
            "llm_provider": _env("LLM_PROVIDER"),
            "llm_model": _env("LLM_MODEL"),
        }.items() if v is not None},
        **{k: v for k, v in {
            "llm_timeout": int(os.environ["LLM_TIMEOUT"]) if "LLM_TIMEOUT" in os.environ else None,
            "llm_synthesis_timeout": int(os.environ["LLM_SYNTHESIS_TIMEOUT"]) if "LLM_SYNTHESIS_TIMEOUT" in os.environ else None,
            "sector_staleness_days": int(os.environ["SECTOR_STALENESS_DAYS"]) if "SECTOR_STALENESS_DAYS" in os.environ else None,
            "analyst_temperature": float(os.environ["ANALYST_TEMPERATURE"]) if "ANALYST_TEMPERATURE" in os.environ else None,
            "adversarial_temperature": float(os.environ["ADVERSARIAL_TEMPERATURE"]) if "ADVERSARIAL_TEMPERATURE" in os.environ else None,
            "reviewer_temperature": float(os.environ["REVIEWER_TEMPERATURE"]) if "REVIEWER_TEMPERATURE" in os.environ else None,
        }.items() if v is not None},
    )
