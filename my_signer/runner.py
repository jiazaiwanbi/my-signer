import asyncio
from datetime import datetime
import json

from loguru import logger

from .locking import private_write
from .registry import load_site, select_sites
from .runinfo import RunContext, RunStatus
from .sessions import connected, check_unique_sessions


SUCCESS = {RunStatus.SUCCESS, RunStatus.NONEED}


async def run(settings, accounts, sites_override=None):
    check_unique_sessions(settings, accounts)
    results = []
    for account in accounts:
        names = select_sites(sites_override if sites_override is not None else (account.sites or settings.sites))
        if not names:
            raise ValueError(f"{account.name}: 未选择签到器；请配置 sites。")
        async with connected(settings, account) as client:
            logger.info("{}: Telegram 会话已连接，执行 {} 个签到器。", account.name, len(names))
            # One Telegram connection per account; adapters share it.
            semaphore = asyncio.Semaphore(settings.checkiner.concurrency)

            async def one(name, cls):
                async with semaphore:
                    ctx = RunContext.prepare(name)
                    try:
                        bot = cls(client, context=ctx, retries=settings.checkiner.retries,
                                  timeout=settings.checkiner.timeout,
                                  config=settings.checkiner.get_site_config(name), instant=True)
                        result = await asyncio.wait_for(bot._start(), settings.checkiner.max_duration)
                        if result is None:
                            ctx.finish(RunStatus.ERROR, "签到器未返回结果")
                    except asyncio.TimeoutError:
                        ctx.finish(RunStatus.ERROR, "达到单站最长执行时间")
                    except Exception as exc:
                        logger.error("{}: {}: {}", name, type(exc).__name__, exc)
                        ctx.finish(RunStatus.ERROR, type(exc).__name__)
                    if ctx.status == RunStatus.RESCHEDULE:
                        logger.warning("{}: 站点要求稍后重试 {}，本次退出，由青龙控制重跑。", name, ctx.next_time)
                    results.append({"account": account.name, "site": name, "name": getattr(cls, "name", name),
                                    "status": ctx.status.name, "detail": ctx.status_info,
                                    "next_time": str(ctx.next_time) if ctx.next_time else None})
                    logger.info("{} / {}: {} {}", account.name, name, ctx.status.name, ctx.status_info)

            jobs = []
            for name in names:
                try:
                    for cls in load_site(name):
                        jobs.append(one(name, cls))
                except Exception as exc:
                    logger.error("{}: 加载失败: {}", name, exc)
                    results.append({"account": account.name, "site": name, "status": "ERROR", "detail": str(exc)})
            await asyncio.gather(*jobs)
    private_write(settings.state_dir / "last-run.json", json.dumps(
        {"time": datetime.now().astimezone().isoformat(), "results": results}, ensure_ascii=False, indent=2) + "\n")
    good = sum(item["status"] in {s.name for s in SUCCESS} for item in results)
    logger.info("本轮完成：{} 成功或已签到，{} 未完成。", good, len(results) - good)
    return 0 if results and good == len(results) else 1
