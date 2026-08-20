from fixed_income.config import Settings
from fixed_income.services.observability import HealthMonitor


def test_validation_settings_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("QT_FI_ENVIRONMENT", "validation")
    monkeypatch.setenv("QT_FI_MAX_WORKERS", "3")
    settings = Settings.from_env()
    assert settings.environment == "validation"
    assert settings.max_background_workers == 3
    assert settings.require_real_sec_user_agent


def test_production_settings_require_real_contact(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_FI_ENVIRONMENT", "production")
    monkeypatch.setenv("QT_FI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("QT_FI_AUDIT_DIR", str(tmp_path / "audit"))
    settings = Settings.from_env()
    issues = settings.validate_production("contact@example.com")
    assert issues
    assert not settings.validate_production("Quant Terminal ops@example.org")


def test_health_monitor_reports_success_and_failure() -> None:
    monitor = HealthMonitor()
    monitor.register("healthy", lambda: "ok")

    def fail() -> None:
        raise RuntimeError("down")

    monitor.register("failing", fail)
    report = monitor.check()
    assert not report["ok"]
    assert len(report["checks"]) == 2
    assert report["checks"][0]["ok"]
    assert not report["checks"][1]["ok"]
