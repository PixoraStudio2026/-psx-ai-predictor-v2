from app.auth import hash_password, verify_password, create_access_token, read_access_token
from app.config import settings

def test_password_hash_and_verify():
    encoded=hash_password("a-very-long-test-password")
    assert verify_password("a-very-long-test-password", encoded)
    assert not verify_password("wrong-password", encoded)

def test_signed_session_round_trip(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret-that-is-at-least-32-chars-long")
    token=create_access_token(123)
    assert read_access_token(token)==123
    assert read_access_token(token+"x") is None
