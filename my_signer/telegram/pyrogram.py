import pyrogram
from pyrogram import raw, types


class Client(pyrogram.Client):
    async def get_me(self):
        # Full profiles are unnecessary for check-ins and can fail independently
        # of an otherwise valid authorization (Telegram RPC_CALL_FAIL).
        users = await self.invoke(
            raw.functions.users.GetUsers(id=[raw.types.InputUserSelf()]),
            retries=3, timeout=10,
        )
        if len(users) != 1 or not isinstance(users[0], raw.types.User):
            raise RuntimeError("无法读取当前 Telegram 账号的基础资料。")
        return types.User._parse(self, users[0])

    async def authorize(self):
        # A cron job must never request another code or silently create a new device.
        raise RuntimeError("Telegram 会话失效，请手动执行 login；定时任务不会重新登录。")
