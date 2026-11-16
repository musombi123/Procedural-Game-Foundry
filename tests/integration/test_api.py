from fastapi.testclient import TestClient
import services.api.main as api

def test_health_and_project_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "manager", api.ProjectManager(tmp_path))
    client = TestClient(api.app)
    assert client.get("/health").json()["model_free"] is True
    response = client.post("/api/projects", json={"name": "API World", "seed": 55})
    assert response.status_code == 201
    assert response.json()["project"]["name"] == "API World"
    project_id = response.json()["id"]
    saved = client.put(f"/api/projects/{project_id}/world", json={
        "seed": 55,
        "world": {"width": 112, "depth": 96, "resolution": 64, "amplitude": 12, "frequency": 0.06},
        "objects": [{
            "id": "obj-beacon1", "name": "Signal beacon", "kind": "beacon",
            "x": 8, "y": 0, "z": -5, "rotation": 35, "scale": 1.2, "color": "#5b8da8"
        }],
        "sun_angle": 35, "fog": False, "water_level": -2
    })
    assert saved.status_code == 200
    assert saved.json()["objects"] == 1
    restored = client.get(f"/api/projects/{project_id}/world")
    assert restored.status_code == 200
    assert restored.json()["world"]["width"] == 112
    assert restored.json()["objects"][0]["name"] == "Signal beacon"
