"""Cookie-based browser session tests (dual-track auth).

Existing tests all authenticate via the Authorization header and must keep
passing unchanged; these cover the HttpOnly cookie track added on top.
"""

LOGIN_BODY = {"email": "admin@demo.voyageos", "password": "Demo1234!", "tenant_code": "demo"}


def _login(client):
    r = client.post("/api/v1/auth/login", json=LOGIN_BODY)
    assert r.status_code == 200, r.text
    return r


def test_login_sets_httponly_session_cookie(client):
    r = _login(client)
    # JSON token kept for backward compatibility
    assert r.json()["access_token"]
    set_cookie = r.headers.get("set-cookie", "")
    assert "voyageos_token=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    assert "path=/" in set_cookie.lower()
    assert "max-age=" in set_cookie.lower()


def test_cookie_only_request_authenticates(client):
    _login(client)  # TestClient jar now holds the session cookie
    r = client.get("/api/v1/me")  # no Authorization header
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "admin@demo.voyageos"


def test_tampered_cookie_rejected(client):
    _login(client)
    client.cookies.set("voyageos_token", "tampered.token.value")
    assert client.get("/api/v1/me").status_code == 401


def test_no_credentials_rejected(client):
    assert client.get("/api/v1/me").status_code == 401


def test_logout_clears_cookie(client):
    _login(client)
    assert client.get("/api/v1/me").status_code == 200
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "voyageos_token=" in set_cookie
    assert "max-age=0" in set_cookie
    # Cookie jar must be empty now — cookie-only access fails
    assert client.get("/api/v1/me").status_code == 401


def test_authorization_header_flow_regression(client, auth_headers):
    # Header track unchanged by the cookie work
    assert client.get("/api/v1/me", headers=auth_headers).status_code == 200


def test_invalid_header_wins_over_valid_cookie(client, auth_headers):
    # Dual-track resolution order: a present-but-invalid Authorization header
    # fails immediately; the valid cookie is not used as a fallback.
    _login(client)
    r = client.get("/api/v1/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_cookie_revoked_after_password_change(client):
    # pwv revocation applies to the cookie track exactly like the header track
    _login(client)
    h = {"Authorization": f"Bearer {client.cookies.get('voyageos_token')}"}
    chg = client.post(
        "/api/v1/me/security/password",
        headers=h,
        json={"current_password": "Demo1234!", "new_password": "NewPass123!"},
    )
    assert chg.status_code == 200, chg.text
    try:
        assert client.get("/api/v1/me").status_code == 401
    finally:
        # restore demo password for other tests sharing the seeded db
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@demo.voyageos", "password": "NewPass123!", "tenant_code": "demo"},
        )
        assert r.status_code == 200, r.text
        h2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
        client.post(
            "/api/v1/me/security/password",
            headers=h2,
            json={"current_password": "NewPass123!", "new_password": "Demo1234!"},
        )
