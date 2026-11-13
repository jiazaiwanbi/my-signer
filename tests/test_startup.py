from contextlib import asynccontextmanager
import json
from types import SimpleNamespace as NS

import pytest
from pyrogram import raw

from my_signer.config import Settings, Account
from my_signer.runner import run
from my_signer.runinfo import RunStatus
from my_signer.telegram.pyrogram import Client


async def test_startup_identity_uses_basic_user_query():
    queries = []
    class Transport:
        async def invoke(self, query, **kwargs):
            queries.append(query)
            return [raw.types.User(id=9876543210, is_self=True, first_name="Example", phone="12345678900",
                                   usernames=[], restriction_reason=[])]
    me = await Client.get_me(Transport())
    assert me.id == 9876543210 and me.phone_number == "12345678900"
    assert len(queries) == 1 and isinstance(queries[0], raw.functions.users.GetUsers)
    assert isinstance(queries[0].id[0], raw.types.InputUserSelf)


async def test_empty_identity_stops_without_relogin():
    class Transport:
        async def invoke(self, query, **kwargs):
            return [raw.types.UserEmpty(id=123)]
    with pytest.raises(RuntimeError, match="基础资料"):
        await Client.get_me(Transport())


def make_account(name):
    return Account(name=name, phone="+12345678900", api_id=12345, api_hash="a" * 32)


async def test_startup_failure_replaces_stale_success(tmp_path, monkeypatch):
    report = tmp_path / "last-run.json"
    report.write_text(json.dumps({"time": "old success", "results": [{"status": "SUCCESS"}]}))
    @asynccontextmanager
    async def unavailable(*args):
        raise RuntimeError("Telegram startup failed")
        yield
    monkeypatch.setattr("my_signer.runner.check_unique_sessions", lambda *args: None)
    monkeypatch.setattr("my_signer.runner.connected", unavailable)
    settings = Settings(state_dir=tmp_path, sites=["sfcju", "saturday"])
    assert await run(settings, [make_account("main")]) == 1
    saved = json.loads(report.read_text())
    assert saved["time"] != "old success" and saved["status"] == "FAILED"
    assert {r["site"] for r in saved["results"]} == {"sfcju", "saturday"}
    assert all(r["status"] == "ERROR" for r in saved["results"])


async def test_missing_session_also_replaces_stale_success(tmp_path):
    report = tmp_path / "last-run.json"
    report.write_text('{"status":"SUCCESS"}')
    with pytest.raises(RuntimeError):
        await run(Settings(state_dir=tmp_path, sites=["sfcju"]), [make_account("main")])
    assert json.loads(report.read_text())["status"] == "ERROR"


async def test_one_failed_account_does_not_skip_the_next(tmp_path, monkeypatch):
    @asynccontextmanager
    async def connect(settings, account):
        if account.name == "bad":
            raise RuntimeError("Unable to connect")
        yield NS()
    class Checkin:
        name = "Example"
        def __init__(self, client, context, **kwargs):
            self.context = context
        async def _start(self):
            return self.context.finish(RunStatus.SUCCESS)
    monkeypatch.setattr("my_signer.runner.check_unique_sessions", lambda *args: None)
    monkeypatch.setattr("my_signer.runner.connected", connect)
    monkeypatch.setattr("my_signer.runner.load_site", lambda name: [Checkin])
    assert await run(Settings(state_dir=tmp_path, sites=["sfcju"]),
                     [make_account("bad"), make_account("good")]) == 1
    saved = json.loads((tmp_path / "last-run.json").read_text())
    assert [(r["account"], r["status"]) for r in saved["results"]] == [("bad", "ERROR"), ("good", "SUCCESS")]
