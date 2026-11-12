from fastapi.testclient import TestClient
from main import app, db

client = TestClient(app)

def test_audit_report():
    # Add mock student so the API doesn't return 404
    db["770001"] = {"history": [], "plan": []}
    
    response = client.get("/api/v1/students/770001/audit-report")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    
def test_audit_report_strict():
    db["770001"] = {"history": [], "plan": []}
    response = client.get("/api/v1/students/770001/audit-report?strict=true")
    assert response.status_code == 200
