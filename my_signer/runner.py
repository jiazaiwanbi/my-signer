import asyncio
from datetime import datetime
import json

from loguru import logger

from .locking import private_write
from .registry import load_site, select_sites
from .runinfo import RunContext, RunStatus
from .sessions import connected, check_unique_sessions


SUCCESS = {RunStatus.SUCCESS, RunStatus.NONEED}


def save_report(settings, results, status):
    private_write(settings.state_dir / "last-run.json", json.dumps(
        {"time": datetime.now().astimezone().isoformat(), "status": status, "results": results},
        ensure_ascii=False, indent=2) + "\n")


async def run_account(settings, account, names, results):
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
                results.append({"account": account.name, "site": name, "name": getattr(cls, "name", name),
                                "status": ctx.status.name, "detail": ctx.status_info})
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


async def run(settings, accounts, sites_override=None):
    results = []
    status = "ERROR"
    # Never leave a previous success looking like the latest run after a crash.
    save_report(settings, results, "RUNNING")
    try:
        check_unique_sessions(settings, accounts)
        for account in accounts:
            names = select_sites(sites_override if sites_override is not None else (account.sites or settings.sites))
            if not names:
                raise ValueError(f"{account.name}: 未选择签到器；请配置 sites。")
            try:
                await run_account(settings, account, names, results)
            except Exception as exc:
                logger.error("{}: 账号执行中断: {}: {}", account.name, type(exc).__name__, exc)
                recorded = {r["site"] for r in results if r["account"] == account.name}
                for name in names:
                    if name not in recorded:
                        results.append({"account": account.name, "site": name, "status": "ERROR",
                                        "detail": f"账号执行中断（{type(exc).__name__}）"})
        good = sum(item["status"] in {s.name for s in SUCCESS} for item in results)
        logger.info("本轮完成：{} 成功或已签到，{} 未完成。", good, len(results) - good)
        code = 0 if results and good == len(results) else 1
        status = "SUCCESS" if code == 0 else "FAILED"
        return code
    finally:
        save_report(settings, results, status)
