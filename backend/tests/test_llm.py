from app.services import llm


def test_chat_closes_its_client(monkeypatch):
    """Every call used to leave its HTTPS connection open (ResourceWarning per call)."""
    events = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            events.append("closed")

        def chat(self, **kw):
            events.append("chat")
            return {"message": {"content": '{"ok": true}'}}

    monkeypatch.setattr(llm, "_client", FakeClient)
    assert llm.chat([{"role": "user", "content": "hi"}], format={"type": "object"}) == {"ok": True}
    assert events == ["chat", "closed"]
