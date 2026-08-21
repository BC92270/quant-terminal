"""Environment-backed operational settings with safe workspace defaults."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    data_dir: Path = Path(".quant_data")
    cache_dir: Path = Path(".quant_cache/fixed_income_credit")
    audit_dir: Path = Path(".quant_audit")
    max_background_workers: int = 2
    max_background_jobs: int = 100
    require_real_sec_user_agent: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("QT_FI_ENVIRONMENT", "development").strip().lower()
        if environment not in {"development", "validation", "production"}:
            raise ValueError("QT_FI_ENVIRONMENT must be development, validation or production")
        workers = int(os.getenv("QT_FI_MAX_WORKERS", "2"))
        jobs = int(os.getenv("QT_FI_MAX_JOBS", "100"))
        if workers < 1 or jobs < 1:
            raise ValueError("background capacity must be positive")
        return cls(
            environment=environment,
            data_dir=Path(os.getenv("QT_FI_DATA_DIR", ".quant_data")),
            cache_dir=Path(os.getenv("QT_FI_CACHE_DIR", ".quant_cache/fixed_income_credit")),
            audit_dir=Path(os.getenv("QT_FI_AUDIT_DIR", ".quant_audit")),
            max_background_workers=workers,
            max_background_jobs=jobs,
            require_real_sec_user_agent=environment in {"validation", "production"},
        )

    def prepare_directories(self) -> None:
        for path in (self.data_dir, self.cache_dir, self.audit_dir):
            path.mkdir(parents=True, exist_ok=True)

    def validate_production(self, sec_user_agent: str = "") -> list[str]:
        issues: list[str] = []
        if self.environment == "production":
            if not self.require_real_sec_user_agent:
                issues.append("production must require an identified SEC user agent")
            if "contact@example.com" in sec_user_agent or "@" not in sec_user_agent:
                issues.append("SEC_USER_AGENT must contain a monitored contact address")
            for path in (self.data_dir, self.audit_dir):
                if not path.is_absolute():
                    issues.append(f"production path must be absolute: {path}")
        return issues
