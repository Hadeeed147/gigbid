"""GigSim behaviour: idempotency, dry_run, Connects, policy v2, hidden fields stay hidden."""
import os

os.environ["GIGSIM_ERROR_RATE"] = "0"
os.environ["GIGSIM_DB"] = os.path.join(os.path.dirname(__file__), "_gigsim_test.sqlite")

from fastapi.testclient import TestClient  # noqa: E402

from gigsim import server  # noqa: E402

H = {"Authorization": "Bearer gs_ai_ml"}
A = {"X-Admin-Key": "gigsim-admin"}


def client():
    server.init_db(reset=True)
    c = TestClient(server.app)
    c.post("/admin/clock", json={"advance_minutes": 60 * 24 * 8}, headers=A)
    return c


def first_job(c):
    return c.get("/jobs?limit=1", headers=H).json()["jobs"][0]


def test_hidden_fields_not_exposed():
    c = client()
    j = first_job(c)
    assert "gold" not in j and "_hidden" not in j
    cl = c.get(f"/clients/{j['client_id']}", headers=H).json()
    assert "hidden_prefs" not in cl and "is_scam" not in cl


def test_dry_run_and_idempotent_submit_spends_once():
    c = client()
    j = first_job(c)
    body = {"job_id": j["id"], "cover_letter": "x " * 100, "bid_amount": 40}
    dry = c.post("/proposals", json={**body, "dry_run": True}, headers=H).json()
    assert dry["dry_run"] and dry["would_create"]["connects_cost_on_submit"] > 0
    p1 = c.post("/proposals", json=body, headers={**H, "Idempotency-Key": "k1"}).json()
    p2 = c.post("/proposals", json=body, headers={**H, "Idempotency-Key": "k1"}).json()
    assert p1["id"] == p2["id"]
    before = c.get("/me/connects", headers=H).json()["balance"]
    s1 = c.post(f"/proposals/{p1['id']}/submit", json={}, headers={**H, "Idempotency-Key": "s1"}).json()
    s2 = c.post(f"/proposals/{p1['id']}/submit", json={}, headers={**H, "Idempotency-Key": "s1"}).json()
    s3 = c.post(f"/proposals/{p1['id']}/submit", json={}, headers={**H, "Idempotency-Key": "s2"}).json()
    after = c.get("/me/connects", headers=H).json()["balance"]
    assert s1 == s2 and s3["note"] == "already submitted"
    assert before - after == s1["connects_spent"]


def test_policy_v2_requires_ai_disclosure():
    c = client()
    c.post("/admin/policy", json={"version": 2}, headers=A)
    j = first_job(c)
    p = c.post("/proposals", json={"job_id": j["id"], "cover_letter": "hello " * 90, "bid_amount": 30}, headers=H).json()
    r = c.post(f"/proposals/{p['id']}/submit", json={}, headers=H)
    assert r.status_code == 422
    r = c.post(f"/proposals/{p['id']}/submit", json={"ai_assisted": True}, headers=H)
    assert r.status_code == 200


def test_rate_limit():
    c = client()
    server._rate.clear()
    codes = [c.get("/me", headers=H).status_code for _ in range(server.RATE_LIMIT + 2)]
    assert 429 in codes
