from fastapi.testclient import TestClient


def test_control_health():
    import control
    assert TestClient(control.app).get("/health").json() == {"status": "ok"}


def test_main_health():
    import main
    assert TestClient(main.app).get("/health").json() == {"status": "ok"}
