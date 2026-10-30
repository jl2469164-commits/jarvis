"""The settings voice panel talks about CosyVoice, not a cloud voice key."""
import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def test_settings_panel_has_no_fish_labels():
    text = (ROOT / "frontend" / "src" / "settings.ts").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "fish" not in lowered
    assert "CosyVoice" in text
    assert "Test CosyVoice" in text
    assert "/api/settings/test-cosyvoice" in text
    assert "COSYVOICE_MODEL_DIR" in text


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JARVIS_BRAIN_AUTOSTART", "0")
    for key in list(os.environ):
        if key.startswith("COSYVOICE_"):
            monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "COSYVOICE_MODEL_DIR=/Users/you/models/CosyVoice2-0.5B\n"
        "COSYVOICE_DEVICE=cpu\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_ENV_FILE", str(env_file))
    import data_paths
    importlib.reload(data_paths)
    import run_store
    importlib.reload(run_store)
    import server
    importlib.reload(server)
    run_store.init_db()
    monkeypatch.setattr(server, "_env_file_path", lambda: env_file)
    with TestClient(server.app, headers={"Origin": "http://localhost:5173"}) as c:
        yield c


def test_status_json_names_cosyvoice_and_not_fish(client):
    body = client.get("/api/settings/status").json()
    assert body["env_keys_set"]["cosyvoice"] is False
    assert body["voice"]["model_dir"] == "/Users/you/models/CosyVoice2-0.5B"
    assert body["voice"]["device"] == "cpu"
    blob = str(body).lower()
    assert "fish" not in blob


def test_test_cosyvoice_route_reports_the_missing_voice(client):
    r = client.post("/api/settings/test-cosyvoice", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert "fish" not in str(body).lower()
