import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.config import settings


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "auth_secret", "integration-test-secret-that-is-at-least-32-characters")
    monkeypatch.setattr(settings, "admin_api_token", "integration-admin-token-at-least-32-characters")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def register(client, email):
    response = client.post("/api/auth/register", json={"email": email, "password": "long-test-password-123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_research_chat_uses_post_json_contract(client):
    response = client.post("/api/research/chat", json={"question": "Explain RSI"})
    assert response.status_code == 200
    assert response.json()["assistant_type"] == "grounded_rule_based"


def test_watchlists_are_isolated_between_users(client):
    token_a = register(client, "user-a@example.test")
    token_b = register(client, "user-b@example.test")
    added = client.post("/api/watchlist", json={"symbol": "OGDC"}, headers={"Authorization": f"Bearer {token_a}"})
    assert added.status_code == 200
    a_items = client.get("/api/watchlist", headers={"Authorization": f"Bearer {token_a}"}).json()["items"]
    b_items = client.get("/api/watchlist", headers={"Authorization": f"Bearer {token_b}"}).json()["items"]
    assert [x["symbol"] for x in a_items] == ["OGDC"]
    assert b_items == []


def test_paper_portfolio_rejects_overselling(client):
    token = register(client, "trader@example.test")
    headers = {"Authorization": f"Bearer {token}"}
    buy = client.post("/api/portfolio/simulated-trade", json={"symbol":"OGDC","side":"buy","quantity":2,"price":100}, headers=headers)
    assert buy.status_code == 200
    sell = client.post("/api/portfolio/simulated-trade", json={"symbol":"OGDC","side":"sell","quantity":3,"price":105}, headers=headers)
    assert sell.status_code == 400


def test_admin_csv_import_requires_admin_token_and_marks_training_eligibility(client):
    csv = b"symbol,timestamp,open,high,low,close,volume\nOGDC,2026-01-01,100,105,99,103,10000\n"
    denied = client.post("/api/admin/import-csv", files={"file":("bars.csv",csv,"text/csv")}, data={"source":"Licensed test","training_eligible":"true"})
    assert denied.status_code == 401
    headers = {"Authorization": "Bearer integration-admin-token-at-least-32-characters"}
    imported = client.post("/api/admin/import-csv?source=Licensed%20test&interval=1d&simulated=true&training_eligible=true", headers=headers,
        files={"file":("bars.csv",csv,"text/csv")})
    assert imported.status_code == 200, imported.text
    assert imported.json()["training_eligible"] is False
    overview = client.get("/api/market/overview").json()
    assert overview["simulated"] is True


def test_health_has_security_headers_and_pdf_endpoint(client):
    health = client.get('/api/health')
    assert health.status_code == 200
    assert health.headers.get('x-content-type-options') == 'nosniff'
    pdf = client.get('/api/reports/daily')
    assert pdf.status_code == 200
    assert pdf.headers['content-type'].startswith('application/pdf')
    assert pdf.content.startswith(b'%PDF')
