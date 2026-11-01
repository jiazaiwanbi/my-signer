"""Local OCR, loaded only if a selected bot actually sends a captcha."""
import asyncio
import re

_model = None
_lock = None


def _recognize(data):
    global _model
    try:
        from ddddocr import DdddOcr
    except ImportError as exc:
        raise RuntimeError("图片验证码需要 OCR 依赖：pip install -e '.[ocr]'") from exc
    if _model is None:
        _model = DdddOcr(beta=True, show_ad=False)
    text = _model.classification(data)
    return re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", text)


async def recognize(data):
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        return await asyncio.to_thread(_recognize, data)
