import asyncio
from collections import OrderedDict
from io import BytesIO
from types import SimpleNamespace as NS

import pytest
from pyrogram import ContinuePropagation

from my_signer.runinfo import RunContext, RunStatus
from my_signer.telegram.checkiner._templ_a import TemplateACheckin, result_of, RetryCheckin
from my_signer.telegram.checkiner.sfcju import SFCJUCheckin


def message(text="", photo=None, buttons=None, click=None, reply=None, ident=10):
    return NS(id=ident, text=text, caption=None, photo=photo, edit_date=None,
              reply_markup=NS(inline_keyboard=buttons) if buttons else None,
              click=click, reply=reply,
              continue_propagation=lambda: (_ for _ in ()).throw(ContinuePropagation))


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.sent = []
        self.dispatcher = NS(groups=OrderedDict(), locks_list=[asyncio.Lock()])

    async def emit(self, msg):
        for handlers in list(self.dispatcher.groups.values()):
            try:
                await handlers[0].callback(self, msg)
            except ContinuePropagation:
                pass

    async def get_chat(self, username):
        return NS(id=123)

    async def get_users(self, username):
        return NS(is_bot=True)

    async def get_chat_history(self, chat, limit=1):
        yield message("old message")

    async def send_message(self, chat, text):
        self.sent.append((chat, text))
        for msg in self.responses:
            await self.emit(msg)

    async def download_media(self, msg, in_memory):
        return BytesIO(b"captcha-image")


def make_flow(client, cls=TemplateACheckin):
    return cls(client, context=RunContext.prepare(), retries=1, timeout=0.05,
               config={"action_interval": 0})


@pytest.mark.parametrize("text,status", [
    ("签到成功！本次获得 2 积分", RunStatus.SUCCESS),
    ("簽到成功", RunStatus.SUCCESS),
    ("您今日已经签到，明日再来", RunStatus.NONEED),
    ("请先加入群聊", RunStatus.FAIL),
    ("欢迎使用，登录成功", None),
])
def test_result_classification(text, status):
    assert result_of(text) == status


def test_captcha_error_is_retryable():
    with pytest.raises(RetryCheckin):
        result_of("验证码错误，请重试")


async def test_callback_answer_success_and_listener_cleanup():
    async def click(label):
        assert label == "签到"
        return NS(message="签到成功，获得 2 积分")
    panel = message("请选择功能", buttons=[[NS(text="签到", url=None)]], click=click)
    client = FakeClient([panel])
    result = await make_flow(client)._start()
    assert result.status == RunStatus.SUCCESS
    assert client.sent == [(123, "/start")]
    assert not client.dispatcher.groups


async def test_message_arrives_during_callback():
    client = FakeClient([])
    async def click(label):
        await client.emit(message("今日已签到", ident=11))
        return NS(message="Done")
    client.responses = [message("请选择功能", buttons=[[NS(text="签到", url=None)]], click=click)]
    assert (await make_flow(client)._start()).status == RunStatus.NONEED


async def test_local_captcha_roundtrip(monkeypatch):
    client = FakeClient([])
    replies = []
    async def reply(text):
        replies.append(text)
        await client.emit(message("签到成功", ident=12))
    async def recognize(data):
        assert data == b"captcha-image"
        return "AB12"
    monkeypatch.setattr("my_signer.telegram.checkiner._templ_a.recognize", recognize)
    client.responses = [message("请输入验证码", photo=True, reply=reply)]
    assert (await make_flow(client)._start()).status == RunStatus.SUCCESS
    assert replies == ["AB12"]


async def test_sfcju_does_not_ocr(monkeypatch):
    async def forbidden(*args):
        pytest.fail("sfcju must not run OCR")
    monkeypatch.setattr("my_signer.telegram.checkiner._templ_a.recognize", forbidden)
    client = FakeClient([message("欢迎", photo=True), message("签到成功", ident=11)])
    assert (await make_flow(client, SFCJUCheckin)._start()).status == RunStatus.SUCCESS


async def test_timeout_is_failure_and_removes_listener():
    client = FakeClient([])
    assert (await make_flow(client)._start()).status == RunStatus.FAIL
    assert not client.dispatcher.groups


async def test_real_history_is_used_even_if_count_api_would_return_zero():
    client = FakeClient([message("今日已签到")])
    async def incorrect_count(chat):
        return 0
    client.get_chat_history_count = incorrect_count
    assert (await make_flow(client)._start()).status == RunStatus.NONEED


async def test_no_history_does_not_start_unknown_bot():
    client = FakeClient([])
    async def empty_history(chat, limit=1):
        for msg in []:
            yield msg
    client.get_chat_history = empty_history
    assert (await make_flow(client)._start()).status == RunStatus.FAIL
    assert not client.sent


async def test_cancel_releases_listener():
    client = FakeClient([])
    flow = make_flow(client)
    flow.timeout = 10
    task = asyncio.create_task(flow._start())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not client.dispatcher.groups
