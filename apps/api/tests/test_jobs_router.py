"""jobs router 端到端测试：TestClient + 假 supabase + dependency override（不碰真实网络/JWT）。

FastAPI 的 TestClient 在返回响应前会跑完 BackgroundTasks，所以创建任务后立刻
GET 就能看到 runner 已经执行完的最终状态。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.deps import CurrentUser, get_current_user, get_supabase
from app.main import app
from app.tasks import runner


def _override_user():
    return CurrentUser(id="user-1", email="a@b.com", role="sales")


def test_create_job_runs_in_background_and_reaches_done(fake_supabase):
    ran_with = []
    saved_handlers = dict(runner.HANDLERS)  # HANDLERS 现在有真实注册（quote_generate），测完还原
    runner.HANDLERS["quote_generate"] = lambda ctx: (ran_with.append(ctx.job_id), {"done": True})[1]

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase] = lambda: fake_supabase
    try:
        client = TestClient(app)
        created = client.post("/api/jobs", json={"feature": "quote_generate", "params": {"x": 1}})
        assert created.status_code == 201
        job_id = created.json()["id"]

        fetched = client.get(f"/api/jobs/{job_id}")
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["status"] == "done"
        assert body["progress"] == 100
        assert ran_with == [job_id]
    finally:
        app.dependency_overrides.clear()
        runner.HANDLERS.clear()
        runner.HANDLERS.update(saved_handlers)


def test_create_job_rejects_unknown_feature(fake_supabase):
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase] = lambda: fake_supabase
    try:
        client = TestClient(app)
        resp = client.post("/api/jobs", json={"feature": "not_a_real_feature"})
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_cancel_job_sets_cancelled_and_guards(fake_supabase):
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_supabase] = lambda: fake_supabase
    try:
        client = TestClient(app)
        # running 任务 → 取消置 cancelled
        fake_supabase.table("jobs").insert(
            {"id": "j-run", "user_id": "user-1", "feature": "quote_generate", "status": "running"}
        ).execute()
        r = client.post("/api/jobs/j-run/cancel")
        assert r.status_code == 200 and r.json()["status"] == "cancelled"

        # 已完成任务 → 取消是 no-op（不改 done）
        fake_supabase.table("jobs").insert(
            {"id": "j-done", "user_id": "user-1", "feature": "quote_generate", "status": "done"}
        ).execute()
        assert client.post("/api/jobs/j-done/cancel").json()["status"] == "done"

        # 别人的任务 → 404（不泄露、不可取消）
        fake_supabase.table("jobs").insert(
            {"id": "j-other", "user_id": "user-2", "feature": "quote_generate", "status": "running"}
        ).execute()
        assert client.post("/api/jobs/j-other/cancel").status_code == 404
    finally:
        app.dependency_overrides.clear()
