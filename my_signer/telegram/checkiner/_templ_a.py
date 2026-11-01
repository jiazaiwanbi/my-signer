"""Common /start -> check-in button -> optional local OCR -> result flow.

Derived from Embykeeper's Template A behavior; no auth service or AI fallback.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import itertools
import re

from loguru import logger
from pyrogram import filters
from pyrogram.errors import MessageIdInvalid
from pyrogram.handlers import MessageHandler, EditedMessageHandler

from my_signer.ocr import recognize
from my_signer.runinfo import RunStatus

GROUPS = itertools.count(100)
CHECKED = ("已经签到", "今日已签到", "今天已签到", "今日已经", "重复签到", "明日再来", "明天再来", "距离上次签到未过", "已经簽到")
ACCOUNT_ERRORS = ("黑名单", "冻结", "未注册", "未找到用户", "无资格", "请先加入", "請先加入", "请先点击下面加入")
RETRY_ERRORS = ("验证码错误", "验证码不正确", "验证失败", "签到失败", "簽到失敗", "网络错误")
SUCCESS_PATTERN = r"(?:(?:签到|簽到).{0,12}(?:成功|完成)|(?:成功|完成).{0,12}(?:签到|簽到)|获得.{0,12}(?:积分|分数)|獲得.{0,12}積分)"


class RetryCheckin(Exception):
    pass


@dataclass
class FlowConfig:
    command: str = "/start"
    button_keywords: tuple = ("签到", "簽到")
    use_captcha: bool = True
    captcha_pattern: str | None = None
    success_pattern: str = SUCCESS_PATTERN
    action_interval: float = 1.5


def result_of(text, success_pattern=SUCCESS_PATTERN):
    if any(word in text for word in CHECKED):
        return RunStatus.NONEED
    if any(word in text for word in ACCOUNT_ERRORS):
        return RunStatus.FAIL
    if any(word in text for word in RETRY_ERRORS):
        raise RetryCheckin("站点返回失败信息")
    if re.search(success_pattern, text):
        return RunStatus.SUCCESS
    return None


def checkin_button(message, keywords):
    markup = getattr(message, "reply_markup", None)
    if not markup:
        return None
    for row in getattr(markup, "inline_keyboard", None) or getattr(markup, "keyboard", None) or []:
        for button in row:
            text = getattr(button, "text", str(button))
            if any(word in text for word in keywords):
                return button
    return None


class TemplateACheckin:
    name = "通用签到"
    bot_username = None
    bot_use_captcha = True

    def __init__(self, client, context, retries=4, timeout=240, config=None, **kwargs):
        self.client, self.ctx = client, context
        self.retries, self.timeout = retries, timeout
        options = dict(config or {})
        self.bot_username = options.pop("bot_username", self.bot_username)
        renames = {"bot_checkin_cmd": "command", "bot_checkin_button": "button_keywords",
                   "bot_use_captcha": "use_captcha", "bot_success_pat": "success_pattern"}
        options = {renames.get(k, k): v for k, v in options.items()}
        self.flow = FlowConfig(**{"use_captcha": self.bot_use_captcha, **options})
        if isinstance(self.flow.button_keywords, str):
            self.flow.button_keywords = (self.flow.button_keywords,)
        self.log = logger.bind(site=self.name)

    @asynccontextmanager
    async def handlers_lock(self):
        acquired = []
        try:
            for lock in self.client.dispatcher.locks_list:
                await lock.acquire()
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()

    @asynccontextmanager
    async def listener(self, chat_id):
        queue = asyncio.Queue(maxsize=64)

        async def receive(client, message):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(message)
            message.continue_propagation()

        handler_filter = filters.chat(chat_id) & ~filters.outgoing
        handlers = [MessageHandler(receive, handler_filter), EditedMessageHandler(receive, handler_filter)]
        group = next(GROUPS)
        # Hold all worker locks so the listener is ready before /start is sent.
        async with self.handlers_lock():
            self.client.dispatcher.groups[group] = handlers
        try:
            yield queue
        finally:
            async with self.handlers_lock():
                self.client.dispatcher.groups.pop(group, None)

    async def attempt(self, chat, queue):
        while not queue.empty():
            queue.get_nowait()
        seen = set()
        await self.client.send_message(chat.id, self.flow.command)
        deadline = asyncio.get_running_loop().time() + self.timeout
        while True:
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0:
                raise RetryCheckin("等待机器人响应超时")
            try:
                message = await asyncio.wait_for(queue.get(), left)
            except asyncio.TimeoutError as exc:
                raise RetryCheckin("等待机器人响应超时") from exc
            text = message.text or message.caption or ""
            fingerprint = (message.id, str(getattr(message, "edit_date", None)), text,
                           repr(getattr(message, "reply_markup", None)))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            result = result_of(text, self.flow.success_pattern)
            if result is not None:
                return result
            button = checkin_button(message, self.flow.button_keywords)
            if button is not None:
                if getattr(button, "url", None) or getattr(button, "web_app", None):
                    raise ValueError("该签到按钮需要网页操作，当前通用流程不支持")
                await asyncio.sleep(self.flow.action_interval)
                if getattr(message.reply_markup, "inline_keyboard", None):
                    try:
                        answer = await message.click(button.text)
                    except TimeoutError:
                        continue
                    except MessageIdInvalid as exc:
                        raise RetryCheckin("签到按钮已失效") from exc
                    result = result_of(getattr(answer, "message", "") or "", self.flow.success_pattern)
                    if result is not None:
                        return result
                else:
                    await self.client.send_message(chat.id, getattr(button, "text", str(button)))
            elif message.photo and self.flow.use_captcha:
                if self.flow.captcha_pattern and not re.search(self.flow.captcha_pattern, text):
                    continue
                self.log.info("{}: 收到图片验证码，使用本地 OCR。", self.name)
                image = await self.client.download_media(message, in_memory=True)
                captcha = await recognize(image.getvalue())
                if not captcha:
                    raise RetryCheckin("本地 OCR 返回空结果")
                await asyncio.sleep(self.flow.action_interval)
                await message.reply(captcha)

    async def _start(self):
        self.ctx.start(RunStatus.INITIALIZING)
        chat = await self.client.get_chat(self.bot_username)
        bot = await self.client.get_users(self.bot_username)
        if not bot.is_bot:
            return self.ctx.finish(RunStatus.ERROR, "配置的目标不是机器人")
        # Some API responses report count=0 even when history exists; inspect one message.
        has_history = False
        async for _ in self.client.get_chat_history(chat.id, limit=1):
            has_history = True
            break
        if not has_history:
            return self.ctx.finish(RunStatus.FAIL, "请先在 Telegram 中完成该站点的注册或绑定")
        self.ctx.start()
        async with self.listener(chat.id) as queue:
            for attempt in range(1, self.retries + 1):
                self.log.info("{}: 开始签到（{}/{}）。", self.name, attempt, self.retries)
                try:
                    status = await self.attempt(chat, queue)
                    detail = "签到成功" if status == RunStatus.SUCCESS else "今日已签到" if status == RunStatus.NONEED else "站点返回账号或权限错误"
                    return self.ctx.finish(status, detail)
                except RetryCheckin as exc:
                    self.log.warning("{}: {}", self.name, exc)
        return self.ctx.finish(RunStatus.FAIL, "签到重试次数已用完")


def use(**kwargs):
    return type("GenericCheckin", (TemplateACheckin,), kwargs)
