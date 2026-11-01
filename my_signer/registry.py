import importlib
import inspect
import json
from pathlib import Path
import re


def inventory():
    return json.loads(Path(__file__).with_name("sites.json").read_text(encoding="utf-8"))


def select_sites(names):
    items = {item["id"]: item for item in inventory()}
    selected = []
    for name in names:
        if name == "all":
            selected.extend(key for key, item in items.items() if item["include_in_all"])
        elif name == "sgk":
            selected.extend(key for key in items if key.endswith("sgk"))
        elif not name.startswith("-"):
            selected.append(name)
    excluded = {name[1:] for name in names if name.startswith("-")}
    return list(dict.fromkeys(name for name in selected if name not in excluded))


def load_site(name):
    match = re.fullmatch(r"templ_(a)<@?(\w+)>", name)
    if match:
        module = importlib.import_module(f"my_signer.telegram.checkiner._templ_{match[1]}")
        return [module.use(bot_username=match[2], name=f"@{match[2]}", templ_name=name)]
    if name not in {item["id"] for item in inventory()}:
        raise ValueError(f"未知签到器 {name!r}；执行 list-sites 查看。")
    module = importlib.import_module(f"my_signer.telegram.checkiner.{name}")
    expected = name.replace("_old", "").replace("_", "") + "checkin"
    for cn, cls in inspect.getmembers(module, inspect.isclass):
        if cn.lower() == expected.lower():
            children = [value for value in cls.__dict__.values() if inspect.isclass(value)]
            return children or [cls]
    raise ValueError(f"{name}: 未找到签到器实现")
