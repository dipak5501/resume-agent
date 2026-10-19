"""T11 — profile + résumé library (SQLite persistence): init/seed, storage
round-trip, profile & résumé endpoints, and POST /jobs from library or ad-hoc."""

from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.core import config
from app.main import app
from app.models import Profile, Resume
from app.schemas.ats import AtsScore
from app.schemas.pipeline import PipelineResult, Report
from app.services import jobs, storage


def _client():
    return TestClient(app)


# --- init_db / seed --------------------------------------------------------


def test_init_db_seeds_default_profile_idempotently():
    db.init_db()  # second call (conftest already ran it) must not error/duplicate
    with db.SessionLocal() as s:
        assert s.get(Profile, "default") is not None
        assert s.query(Profile).count() == 1


# --- storage round-trip (seam) --------------------------------------------


def test_storage_roundtrip_and_delete():
    rel = storage.save_resume_file("default", "abc", "source.tex", b"\\documentclass{article}")
    assert not Path(rel).is_absolute()  # relative path (portable)
    assert "default" in rel  # namespaced by profile_id
    assert storage.open_resume_file("default", "abc", "source.tex") == b"\\documentclass{article}"
    storage.delete_resume_dir("default", "abc")
    assert not (config.DATA_DIR / "profiles" / "default" / "resumes" / "abc").exists()


# --- profile endpoints -----------------------------------------------------


def test_get_and_update_profile():
    c = _client()
    assert c.get("/profile").json()["id"] == "default"
    up = c.put("/profile", json={"name": "Ada", "email": "ada@x.io", "links": {"github": "gh/ada"}}).json()
    assert up["name"] == "Ada"
    assert up["links"]["github"] == "gh/ada"
    assert c.get("/profile").json()["name"] == "Ada"  # persisted


# --- résumé library endpoints ---------------------------------------------


def _upload(c, name="a.tex", body=b"\\documentclass{article}", label=None):
    data = {"label": label} if label else {}
    return c.post("/resumes", data=data, files={"file": (name, body, "text/plain")})


def test_first_upload_is_default_and_bytes_on_disk():
    c = _client()
    meta = _upload(c, "a.tex", b"TEXA").json()
    assert meta["is_default"] is True
    assert meta["filename"] == "a.tex"
    assert storage.open_resume_file("default", meta["id"], "source.tex") == b"TEXA"


def test_second_upload_not_default_and_rows_carry_profile_id():
    c = _client()
    _upload(c, "a.tex")
    assert _upload(c, "b.tex").json()["is_default"] is False
    with db.SessionLocal() as s:
        rows = s.query(Resume).all()
        assert len(rows) == 2 and all(r.profile_id == "default" for r in rows)


def test_list_resumes():
    c = _client()
    _upload(c, "a.tex")
    _upload(c, "b.tex")
    assert {m["filename"] for m in c.get("/resumes").json()} == {"a.tex", "b.tex"}


def test_set_default_moves_flag_exactly_one():
    c = _client()
    id1 = _upload(c, "a.tex").json()["id"]
    id2 = _upload(c, "b.tex").json()["id"]
    assert c.put(f"/resumes/{id2}/default").status_code == 200
    flags = {m["id"]: m["is_default"] for m in c.get("/resumes").json()}
    assert flags[id2] is True and flags[id1] is False and sum(flags.values()) == 1


def test_delete_removes_row_and_files():
    c = _client()
    mid = _upload(c, "a.tex", b"TEXA").json()["id"]
    assert c.delete(f"/resumes/{mid}").status_code == 200
    assert c.get("/resumes").json() == []
    assert not (config.DATA_DIR / "profiles" / "default" / "resumes" / mid).exists()


def test_delete_default_promotes_another():
    c = _client()
    id1 = _upload(c, "a.tex").json()["id"]  # default
    id2 = _upload(c, "b.tex").json()["id"]
    c.delete(f"/resumes/{id1}")
    remaining = c.get("/resumes").json()
    assert len(remaining) == 1 and remaining[0]["id"] == id2
    assert remaining[0]["is_default"] is True  # promoted so a default always exists


def test_delete_and_default_missing_404():
    c = _client()
    assert c.delete("/resumes/nope").status_code == 404
    assert c.put("/resumes/nope/default").status_code == 404


# --- POST /jobs: library resume_ids OR ad-hoc files ------------------------


def _stub_pipeline(monkeypatch):
    captured = {}

    def fake(jd, resumes, **k):
        captured["jd"], captured["resumes"] = jd, resumes
        a = AtsScore(overall=80, keyword_coverage=1.0, llm_fit=80,
                     required_keywords=[], matched=[], missing=[], rationale="r")
        return PipelineResult(pdf_path="/tmp/x.pdf", tex="TEX", report=Report(ats_before=a, ats_after=a))

    monkeypatch.setattr(jobs, "run_pipeline", fake)
    jobs.store._recs.clear()
    return captured


def test_jobs_from_library_resume_ids(monkeypatch):
    captured = _stub_pipeline(monkeypatch)
    c = _client()
    mid = _upload(c, "mine.tex", b"MYTEX", label="Backend").json()["id"]
    assert c.post("/jobs", data={"jd": "a job", "resume_ids": [mid]}).status_code == 200
    assert len(captured["resumes"]) == 1 and captured["resumes"][0].tex == "MYTEX"


def test_jobs_adhoc_files_still_work(monkeypatch):
    captured = _stub_pipeline(monkeypatch)
    c = _client()
    r = c.post("/jobs", data={"jd": "a job"}, files={"files": ("x.tex", b"ADHOC", "text/plain")})
    assert r.status_code == 200 and captured["resumes"][0].tex == "ADHOC"


def test_jobs_requires_some_resume(monkeypatch):
    _stub_pipeline(monkeypatch)
    assert _client().post("/jobs", data={"jd": "a job"}).status_code == 400


def test_jobs_unknown_resume_id_404(monkeypatch):
    _stub_pipeline(monkeypatch)
    assert _client().post("/jobs", data={"jd": "a job", "resume_ids": ["nope"]}).status_code == 404
