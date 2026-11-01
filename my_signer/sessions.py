"""Telethon first login -> Pyrogram session, matching upstream's workaround."""
import asyncio
import base64
from contextlib import asynccontextmanager
import getpass
import json
from pathlib import Path
import struct
import sys

from loguru import logger
from pyrogram.storage import Storage
from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from .locking import private_write
from .telegram.pyrogram import Client


class LoginRequired(RuntimeError):
    pass


def pack_session(dc_id, api_id, test_mode, auth_key, user_id, is_bot=False):
    if len(auth_key) != 256:
        raise ValueError("Invalid Telegram authorization key length")
    return base64.urlsafe_b64encode(struct.pack(
        Storage.SESSION_STRING_FORMAT,
        dc_id, api_id, test_mode, auth_key, user_id, is_bot,
    )).decode().rstrip("=")


def unpack_session(value):
    data = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    fields = struct.unpack(Storage.SESSION_STRING_FORMAT, data)
    if fields[2] or fields[5]:
        raise ValueError("Only production user sessions are supported")
    return fields


def session_path(settings, account):
    return settings.state_dir / "sessions" / f"{account.name}.json"


def read_session(settings, account):
    path = session_path(settings, account)
    if not path.is_file():
        raise LoginRequired(f"{account.name}: 请先执行 login --account {account.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    fields = unpack_session(data["session"])
    if fields[1] != account.api_id or fields[4] != data["user_id"]:
        raise LoginRequired(f"{account.name}: 配置与会话不匹配，已停止连接。")
    return data


async def login(settings, account, replace=False):
    if not sys.stdin.isatty():
        raise LoginRequired("首次登录需要交互式终端；使用 docker exec -it 后执行 login。")
    path = session_path(settings, account)
    if path.exists() and not replace:
        raise LoginRequired("已有会话。请执行 status 检查；确需重新登录时显式添加 --replace。")
    # Telethon is used only for first login and is disconnected before Pyrogram starts.
    proxy = None
    if settings.proxy:
        proxy = settings.proxy.pyrogram()
        proxy["proxy_type"] = proxy.pop("scheme")
        proxy["addr"] = proxy.pop("hostname")
    client = TelegramClient(
        StringSession(), account.api_id, account.api_hash,
        proxy=proxy, device_model=account.device_model,
        system_version=account.system_version, app_version=account.app_version,
        connection_retries=2, request_retries=1, flood_sleep_threshold=0,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=40)
        sent = await client.send_code_request(account.phone)
        me = None
        for _ in range(3):
            code = getpass.getpass("Telegram 登录验证码（隐藏输入）: ").strip()
            try:
                me = await client.sign_in(account.phone, code, phone_code_hash=sent.phone_code_hash)
                break
            except errors.PhoneCodeInvalidError:
                logger.warning("验证码错误，请重试。")
            except errors.SessionPasswordNeededError:
                password = getpass.getpass("Telegram 两步验证密码（隐藏输入）: ")
                me = await client.sign_in(password=password)
                break
        if me is None:
            raise LoginRequired("验证码尝试次数已用完；本次登录停止。")
        session = pack_session(
            client.session.dc_id, account.api_id, False,
            client.session.auth_key.key, me.id, me.bot,
        )
        if path.exists():
            private_write(path.with_suffix(".previous.json"), path.read_text(encoding="utf-8"))
        private_write(path, json.dumps({"session": session, "user_id": me.id}) + "\n")
        logger.info("{}: 登录完成，会话已保存。", account.name)
    finally:
        await client.disconnect()  # Never log_out or terminate any other device.


@asynccontextmanager
async def connected(settings, account):
    data = read_session(settings, account)
    client = Client(
        name=account.name, api_id=account.api_id, api_hash=account.api_hash,
        session_string=data["session"], in_memory=True,
        device_model=account.device_model, system_version=account.system_version,
        app_version=account.app_version,
        proxy=settings.proxy.pyrogram() if settings.proxy else None,
        workers=4, sleep_threshold=0,
    )
    try:
        await asyncio.wait_for(client.start(), timeout=45)
        if client.me.id != data["user_id"] or "+" + client.me.phone_number != account.phone:
            raise LoginRequired(f"{account.name}: 登录账号与配置不同，已停止。")
        yield client
    finally:
        if client.is_connected:
            if client.is_initialized:
                await client.stop()
            else:
                await client.disconnect()


def check_unique_sessions(settings, accounts):
    """Reject two config entries containing the same authorization key."""
    keys = set()
    for account in accounts:
        key = unpack_session(read_session(settings, account)["session"])[3]
        if key in keys:
            raise ValueError("两个账号配置复用了同一个会话；禁止并行或重复使用。")
        keys.add(key)
