import argparse
import asyncio
from pathlib import Path
import sys

from loguru import logger

from .config import Settings
from .locking import state_lock, AlreadyRunning
from .registry import inventory


def parser():
    root = argparse.ArgumentParser(description="Telegram 登录与单次签到；定时由青龙控制。")
    root.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "config.toml")
    sub = root.add_subparsers(dest="command")
    sub.add_parser("list-sites", help="列出内置签到器")
    run = sub.add_parser("run", help="签到一次后退出（默认）")
    run.add_argument("--sites", help="本次站点，逗号分隔；也支持 templ_a<bot_username>")
    run.add_argument("--account", help="只运行一个账号")
    status = sub.add_parser("status", help="只检查现有会话，不发送签到消息")
    status.add_argument("--account")
    login = sub.add_parser("login", help="使用 Telethon 交互式首次登录")
    login.add_argument("--account", required=True)
    login.add_argument("--replace", action="store_true", help="明确创建一个新会话并备份原会话")
    migration = sub.add_parser("migrate-embykeeper", help="在本机读取原配置和会话；先停用旧任务")
    migration.add_argument("--source", type=Path, required=True)
    return root


async def execute(args, settings, accounts):
    from .sessions import connected, login, check_unique_sessions
    if args.command == "login":
        await login(settings, accounts[0], args.replace)
        return 0
    if args.command == "status":
        check_unique_sessions(settings, accounts)
        for account in accounts:
            async with connected(settings, account):
                logger.info("{}: 现有 Telegram 会话有效。", account.name)
        return 0
    from .runner import run
    override = [s.strip() for s in args.sites.split(",") if s.strip()] if getattr(args, "sites", None) else None
    return await run(settings, accounts, override)


def main(argv=None):
    logger.remove()
    logger.add(sys.stdout, format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {message}", colorize=False)
    args = parser().parse_args(argv)
    try:
        if args.command == "list-sites":
            for item in inventory():
                print(item["id"])
            raise SystemExit(0)
        if args.command == "migrate-embykeeper":
            from .migrate import migrate
            count = migrate(args.source, args.config)
            logger.info("已迁移 {} 个账号的配置和会话；没有发起新登录。", count)
            raise SystemExit(0)
        settings = Settings.load(args.config)
        accounts = [a for a in settings.accounts if a.enabled and
                    (not getattr(args, "account", None) or a.name == args.account)]
        if not accounts:
            raise ValueError("没有匹配的启用账号。")
        with state_lock(settings.state_dir):
            code = asyncio.run(execute(args, settings, accounts))
        raise SystemExit(code)
    except AlreadyRunning as exc:
        logger.warning("{}", exc)
        raise SystemExit(75)
    except KeyboardInterrupt:
        logger.warning("任务被中断。")
        raise SystemExit(130)
    except Exception as exc:
        # No traceback locals, session strings, phone numbers or credentials in normal logs.
        logger.error("{}: {}", type(exc).__name__, exc)
        raise SystemExit(1)
