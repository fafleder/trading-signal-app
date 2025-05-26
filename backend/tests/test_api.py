import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_market_data():
    response = client.get("/market-data?asset=XAUUSD&timeframe=1h")
    assert response.status_code == 200
    assert isinstance(response.json(), list) 