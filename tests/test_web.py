from pathlib import Path
import json
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from tushu.services.vision import VisionConfig, analyze, parse_result
from tushu.web.server import create_app


def client(tmp_path):
    app = create_app(tmp_path)
    return TestClient(app)


def token(client):
    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    return {"X-Tushu-Client": response.json()["client_token"]}


def finish(client):
    for _ in range(200):
        job = client.get("/api/bootstrap").json()["job"]
        if job["status"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("job timeout")


def test_project_import_edit_export_api(tmp_path):
    import io

    with client(tmp_path) as c:
        headers = token(c)
        assert c.post("/api/projects", json={"name": "Test"}).status_code == 403
        assert (
            c.post(
                "/api/projects", json={"name": "Test"}, headers={**headers, "Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert c.post("/api/projects", json={"name": "网页项目"}, headers=headers).status_code == 200
        assert c.post("/api/categories/template", json={}, headers=headers).status_code == 200
        files = []
        for index in range(3):
            stream = io.BytesIO()
            Image.new("RGB", (100 + index, 80), (index * 60, 20, 30)).save(stream, "PNG")
            files.append(("files", (f"中文{index}.png", stream.getvalue(), "image/png")))
        assert c.post("/api/import/upload", files=files, headers=headers).status_code == 200
        assert finish(c)["status"] == "success"
        state = c.get("/api/bootstrap").json()
        assert len(state["assets"]) == 3
        category = state["categories"][0]["id"]
        for index, asset in enumerate(state["assets"]):
            assert c.get(f"/api/assets/{asset['id']}/image").status_code == 200
            if index:
                box = {"id": f"box{index}", "category_id": category, "x1": 1, "y1": 2, "x2": 40, "y2": 50}
                response = c.put(
                    f"/api/assets/{asset['id']}/boxes", json={"revision": 0, "boxes": [box]}, headers=headers
                )
                assert response.status_code == 200
                assert (
                    c.put(
                        f"/api/assets/{asset['id']}/boxes", json={"revision": 0, "boxes": []}, headers=headers
                    ).status_code
                    == 409
                )
            response = c.post(
                f"/api/assets/{asset['id']}/review?negative_confirmed=true", json={}, headers=headers
            )
            assert response.status_code == 200
        assert c.post("/api/split", json={"train_ratio": 0.8, "seed": 42}, headers=headers).status_code == 200
        response = c.post(
            "/api/export", json={"format": "yolo", "acknowledge_warnings": True}, headers=headers
        )
        assert response.status_code == 200
        assert finish(c)["status"] == "success"
        record = c.get("/api/exports").json()[0]
        assert c.get(f"/api/exports/{record['id']}/download").status_code == 200
        assert "api_key" not in json.dumps(c.get("/api/bootstrap").json())
        assert c.post("/api/projects/open", json={"id": "../foo"}, headers=headers).status_code == 400


def test_vision_config_never_returned(tmp_path):
    with client(tmp_path) as c:
        headers = token(c)
        c.post("/api/projects", json={"name": "test"}, headers=headers)
        response = c.post(
            "/api/vision/config",
            json={"base_url": "https://example.com/v1", "model": "vision", "api_key": "TEST-SECRET-ONLY"},
            headers=headers,
        )
        assert response.status_code == 200
        assert "TEST-SECRET-ONLY" not in json.dumps(response.json())
        assert "TEST-SECRET-ONLY" not in json.dumps(c.get("/api/bootstrap").json())
        all_text = "".join(
            p.read_text(errors="ignore")
            for p in tmp_path.rglob("*")
            if p.is_file() and p.suffix != ".sqlite3"
        )
        assert "TEST-SECRET-ONLY" not in all_text


def test_vision_schema_and_redacted_errors():
    with pytest.raises(ValueError):
        parse_result('{"objects":[{"category_id":"bad","bbox":[0,0,100,100]}]}', {"ok"}, 200, 100)
    for values in ([0, 0, 0, 100], [0, 0, 1001, 100], [0, 0, 0.1, 0.1], [0, 0, float("nan"), 100]):
        with pytest.raises(ValueError):
            parse_result(json.dumps({"objects": [{"category_id": "ok", "bbox": values}]}), {"ok"}, 200, 100)
    result = parse_result(
        '```json\n{"summary":"一只猫","objects":[{"category_id":"ok","bbox":[100,200,500,600],"label":"猫"}]}\n```',
        {"ok"},
        200,
        100,
    )
    assert result["objects"][0]["bbox"] == [20, 20, 100, 60]
    transport = httpx.MockTransport(lambda request: httpx.Response(401, text="private SECRET"))
    config = VisionConfig("https://example.com/v1", "vision", "NEVER-ECHO-THIS")
    with httpx.Client(transport=transport) as c:
        with pytest.raises(ValueError) as error:
            analyze(
                Image.new("RGB", (20, 20)),
                [{"id": "ok", "enabled": 1, "display_name": "猫", "export_name": "cat"}],
                config,
                c,
            )
    assert "SECRET" not in str(error.value) and "NEVER-ECHO" not in str(error.value)


def test_launcher_reuses_existing_tushu(monkeypatch):
    import sys
    from tushu.web.launcher import main

    original = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"service": "tushu-web"}))
    monkeypatch.setattr(sys, "argv", ["tushu-web", "--port", "18766", "--no-browser"])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=transport))
    assert main() == 0
