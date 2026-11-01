import json
import os
from pathlib import Path
import pickle
from types import SimpleNamespace as NS

import pytest

from my_signer.config import Settings, Account
from my_signer.locking import AlreadyRunning, state_lock, private_write
from my_signer.migrate import migrate, source_api_hash
from my_signer.registry import inventory, load_site
from my_signer.sessions import pack_session, unpack_session, connected, check_unique_sessions


def account(name="main"):
    return Account(name=name, phone="+12345678900", api_id=12345, api_hash="a" * 32)


def session():
    return pack_session(2, 12345, False, b"x" * 256, 9876543210)


def test_session_conversion_preserves_key_and_64_bit_id():
    dc, api, test, key, user, bot = unpack_session(session())
    assert (dc, api, test, key, user, bot) == (2, 12345, False, b"x" * 256, 9876543210, False)
    with pytest.raises(ValueError):
        pack_session(2, 12345, False, b"short", 1)


def test_kernel_lock_rejects_overlapping_runs_and_releases(tmp_path):
    with state_lock(tmp_path):
        with pytest.raises(AlreadyRunning):
            with state_lock(tmp_path):
                pass
    with state_lock(tmp_path):
        pass


def test_duplicate_sessions_rejected_before_connect(tmp_path):
    settings = Settings(state_dir=tmp_path)
    for name in ["first", "second"]:
        private_write(tmp_path / "sessions" / f"{name}.json", json.dumps({"session": session(), "user_id": 9876543210}))
    with pytest.raises(ValueError, match="同一个会话"):
        check_unique_sessions(settings, [account("first"), account("second")])


async def test_failed_connection_never_relogs_or_deletes_session(tmp_path, monkeypatch):
    path = tmp_path / "sessions/main.json"
    private_write(path, json.dumps({"session": session(), "user_id": 9876543210}))
    original = path.read_bytes()
    starts = []
    class Revoked:
        is_connected = False
        def __init__(self, **kwargs):
            assert kwargs["in_memory"] is True
        async def start(self):
            starts.append(1)
            raise RuntimeError("SESSION_REVOKED")
    monkeypatch.setattr("my_signer.sessions.Client", Revoked)
    with pytest.raises(RuntimeError, match="SESSION_REVOKED"):
        async with connected(Settings(state_dir=tmp_path), account()):
            pytest.fail("Should not connect")
    assert starts == [1] and path.read_bytes() == original


def test_registry_is_only_three_sites_plus_generic_template():
    assert {x["id"] for x in inventory()} == {"jingzhe", "sfcju", "saturday"}
    for item in inventory():
        assert load_site(item["id"])
    assert load_site("sfcju")[0].bot_username == "fyemby_bot"
    assert load_site("templ_a<ExampleBot>")[0].bot_username == "ExampleBot"
    with pytest.raises(ValueError):
        load_site("../../bad")


def test_migration_is_local_and_preserves_original(tmp_path):
    source = tmp_path / "old"
    (source / "data").mkdir(parents=True)
    (source / "embykeeper/telegram").mkdir(parents=True)
    config = '[[telegram]]\nphone = "+12345678900"\n'
    (source / "config.toml").write_text(config)
    blob = pickle.dumps(list(map(ord, "a" * 32)), protocol=4)
    (source / "embykeeper/telegram/session.py").write_text("_hash = " + repr(blob))
    cache = {"telegram": {"session_str": {"+12345678900": session()}}}
    (source / "data/cache.json").write_text(json.dumps(cache))
    target = tmp_path / "new/config.toml"
    target.parent.mkdir()
    assert migrate(source, target) == 1
    loaded = Settings.load(target)
    assert loaded.accounts[0].api_hash == "a" * 32
    assert (source / "config.toml").read_text() == config
    assert (source / "data/cache.json").read_text() == json.dumps(cache)
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="已存在"):
        migrate(source, target)


def test_migration_never_executes_pickle_code(tmp_path):
    path = tmp_path / "embykeeper/telegram"
    path.mkdir(parents=True)
    (path / "session.py").write_text("_hash = b'cos\\nsystem\\n.'")
    with pytest.raises(ValueError):
        source_api_hash(tmp_path)
