import pyrogram


class Client(pyrogram.Client):
    async def authorize(self):
        # A cron job must never request another code or silently create a new device.
        raise RuntimeError("Telegram 会话失效，请手动执行 login；定时任务不会重新登录。")
