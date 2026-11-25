from fastapi.testclient import TestClient


def authenticated_client(app, *, raise_server_exceptions: bool = True) -> TestClient:
    """Return a browser client authenticated through the real identity service."""
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    identity = app.state.identity
    state = identity.bootstrap_state()
    if state.completed and state.administrator_user_id:
        administrator = identity.get_user(state.administrator_user_id)
    else:
        administrator = identity.bootstrap("development", "Administrator").user
    credential = identity.issue_credential(
        administrator.user_id,
        "browser_session",
        "authenticated feature test",
        identity.browser_session_scopes(administrator.user_id),
    )
    client.cookies.set("json_codr_session", credential.token)
    bootstrap = client.get("/api/identity/bootstrap")
    if bootstrap.status_code != 200:
        client.close()
        raise RuntimeError("test client could not initialize browser identity")
    csrf = client.cookies.get("json_codr_csrf")
    if not csrf:
        client.close()
        raise RuntimeError("test client did not receive a CSRF token")
    client.headers.update({"X-CSRF-Token": csrf})
    return client
