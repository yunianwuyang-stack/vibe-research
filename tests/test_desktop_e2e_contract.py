from pathlib import Path


def test_desktop_automation_is_loopback_token_gated_and_accessible():
    root = Path(__file__).resolve().parents[1]
    main = (root / "main.js").read_text(encoding="utf-8")
    ui = (root / "frontend/src/main.tsx").read_text(encoding="utf-8")
    css = (root / "frontend/src/styles.css").read_text(encoding="utf-8")
    assert "VIBE_AUTOMATION_PORT" in main and "x-vibe-automation-token" in main and "127.0.0.1" in main
    assert "skip-link" in ui and 'aria-current={page===item' in ui and 'role="status"' in ui
    assert ".skip-link:focus" in css and "input:focus-visible" in css and ".sr-only" in css
