from fastapi.testclient import TestClient
import services.api.main as api

def test_health_and_project_creation(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"manager",api.ProjectManager(tmp_path))
    client=TestClient(api.app)
    assert client.get("/health").json()["model_free"] is True
    response=client.post("/api/projects",json={"name":"API World","seed":55})
    assert response.status_code==201
    assert response.json()["project"]["name"]=="API World"
