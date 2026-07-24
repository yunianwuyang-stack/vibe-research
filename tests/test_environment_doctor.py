from pathlib import Path

def test_environment_doctor_reports_version_and_login_action(monkeypatch):
    from services.environment_doctor import EnvironmentDoctor
    monkeypatch.setattr("services.environment_doctor.shutil.which", lambda name: "C:/tools/" + name if name in {"git", "node", "codex"} else None)
    monkeypatch.setattr("services.environment_doctor._version", lambda exe: "v-test" if exe else None)
    report = EnvironmentDoctor(project_root=Path(".")).report()
    tools = {item["id"]: item for item in report["tools"]}
    assert tools["git"]["status"] == "available" and tools["git"]["version"] == "v-test"
    assert tools["pandoc"]["status"] == "unavailable"
    assert tools["claude"]["action"]["kind"] == "official_login"
    assert "openai.com" in tools["codex"]["action"]["url"]

def test_environment_doctor_never_fabricates_authentication(monkeypatch):
    from services.environment_doctor import EnvironmentDoctor
    monkeypatch.setattr("services.environment_doctor.shutil.which", lambda name: "C:/tools/" + name if name == "codex" else None)
    monkeypatch.setattr("services.environment_doctor._version", lambda exe: "v-test")
    codex = next(x for x in EnvironmentDoctor(project_root=Path(".")).report()["tools"] if x["id"] == "codex")
    assert codex["auth_status"] == "unknown"
    assert codex["status"] == "available"


def test_environment_doctor_endpoint_is_registered():
    from main import app
    assert any(getattr(route, "path", None) == "/api/environment/doctor" for route in app.routes)
