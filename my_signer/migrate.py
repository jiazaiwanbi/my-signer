"""Read existing Embykeeper credentials locally; never contact Telegram here."""
import ast
import json
from pathlib import Path
import pickletools
import tomllib

from .config import Settings
from .locking import private_write, state_lock
from .sessions import unpack_session


def source_api_hash(source):
    tree = ast.parse((source / "embykeeper/telegram/session.py").read_text(encoding="utf-8"))
    blob = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_hash" for t in node.targets):
            blob = ast.literal_eval(node.value)
    if blob is None:
        raise ValueError("无法读取原项目 API hash，请在新配置中填写自己的 API 凭据。")
    # Inspect the integer-only literal; do not unpickle or import the old project.
    numbers = []
    for opcode, arg, _ in pickletools.genops(blob):
        if opcode.name in {"BININT1", "BININT2", "BININT", "INT"}:
            numbers.append(arg)
        elif opcode.name not in {"PROTO", "FRAME", "EMPTY_LIST", "MEMOIZE", "MARK", "APPENDS", "STOP"}:
            raise ValueError("原项目 API hash 不是预期的整数列表。")
    return "".join(map(chr, numbers))


def migrate(source, config_path):
    source, target = Path(source).resolve(), Path(config_path).resolve()
    if target.exists():
        raise ValueError("目标配置已存在，迁移不会覆盖现有配置。")
    old = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    telegram = old.get("telegram", [])
    if isinstance(telegram, dict):
        telegram = telegram.get("account", [])
    cache = json.loads((source / "data/cache.json").read_text(encoding="utf-8"))
    sessions = cache.get("telegram", {}).get("session_str", {})
    if not telegram:
        raise ValueError("原配置中没有 Telegram 账号。")
    lines = ['state_dir = "data"', 'sites = ["jingzhe", "sfcju", "saturday"]', "", "[checkiner]", "timeout = 240", "retries = 4", "concurrency = 1", ""]
    records = []
    for index, account in enumerate(telegram):
        phone = account["phone"]
        candidates = [v for k, v in sessions.items() if phone in k]
        value = account.get("session")
        if not value:
            if len(candidates) != 1:
                raise ValueError(f"账号 {index + 1} 的原会话不存在或不唯一，迁移停止。")
            value = candidates[0]
        fields = unpack_session(value)
        api_hash = account.get("api_hash") or source_api_hash(source)
        name = "main" if index == 0 else f"account{index + 1}"
        lines += ["[[accounts]]", f"name = {json.dumps(name)}", f"phone = {json.dumps(phone)}", f"api_id = {fields[1]}", f"api_hash = {json.dumps(api_hash)}", ""]
        records.append((name, {"session": value, "user_id": fields[4]}))
    if old.get("proxy"):
        lines += ["[proxy]"]
        for key in ("scheme", "hostname", "port", "username", "password"):
            if key in old["proxy"]:
                lines.append(f"{key} = {json.dumps(old['proxy'][key], ensure_ascii=False)}")
    text = "\n".join(lines) + "\n"
    Settings.model_validate(tomllib.loads(text))
    with state_lock(target.parent / "data"):
        for name, record in records:
            path = target.parent / "data/sessions" / f"{name}.json"
            if path.exists():
                raise ValueError("目标会话已存在，迁移停止。")
        for name, record in records:
            private_write(target.parent / "data/sessions" / f"{name}.json", json.dumps(record) + "\n")
        private_write(target, text)
    return len(records)
