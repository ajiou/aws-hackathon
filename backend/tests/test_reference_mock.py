"""Integration with the shared repository's bundled mock and launch paths."""

import runpy
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import uvicorn
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings

MOCK = Path(__file__).resolve().parents[2] / "frontend" / "mock"


def test_repository_defaults_are_independent_of_working_directory(monkeypatch, tmp_path):
    for name in ("SERVING_DIR", "DATA_BUCKET", "CORS_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[2]
    expected = root / "out" / "serving"
    if not expected.exists():
        expected = MOCK
    assert Settings.from_env().serving_dir == expected


def test_legacy_script_launcher(monkeypatch, tmp_path):
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    root = Path(__file__).resolve().parents[2]
    runpy.run_path(str(root / "backend" / "local_server.py"), run_name="__main__")
    run.assert_called_once_with("backend.app:app", host="127.0.0.1", port=8000)
    assert sys.path[0] == str(root)


@pytest.mark.skipif(not MOCK.exists(), reason="Reference checkout is not present")
def test_full_reference_mock():
    with TestClient(create_app(Settings(serving_dir=MOCK))) as client:
        meta = client.get("/api/v1/meta").json()
        parks = client.get("/api/v1/parks").json()
        assert parks["total"] == meta["population"]
        assert parks["total"] > len(parks["items"])
        park_id = parks["items"][0]["park_id"]
        for path in [
            f"parks/{park_id}",
            f"parks/{park_id}/brief",
            "risk/top?k=200",
            "districts",
            "map?town=板橋區",
            "curve",
            "worklist?k=200",
        ]:
            response = client.get("/api/v1/" + path)
            assert response.status_code == 200, (path, response.text)
        sheet = client.get("/api/v1/worklist?k=200").json()
        assert len(sheet["items"]) == 200
        assert all(len(row["reasons"]) == 3 for row in sheet["items"])
        inactive = next(p for p in client.app.state.store.parks().values() if not p.is_active)
        assert client.get(f"/api/v1/parks/{inactive.park_id}").json()["risk"]["rank"] is None
