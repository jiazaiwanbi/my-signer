from pathlib import Path
from types import SimpleNamespace
import tomllib

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Proxy(StrictModel):
    scheme: str = "socks5"
    hostname: str
    port: int = Field(gt=0, le=65535)
    username: str | None = None
    password: str | None = None

    @field_validator("scheme")
    @classmethod
    def valid_scheme(cls, value):
        if value not in {"socks5", "http"}:
            raise ValueError("proxy.scheme must be socks5 or http")
        return value

    def pyrogram(self):
        return self.model_dump(exclude_none=True)

    def url(self):
        from urllib.parse import quote
        auth = ""
        if self.username:
            auth = quote(self.username, safe="") + ":" + quote(self.password or "", safe="") + "@"
        return f"{self.scheme}://{auth}{self.hostname}:{self.port}"


class Account(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    phone: str = Field(pattern=r"^\+\d{7,15}$")
    api_id: int = Field(gt=0)
    api_hash: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    enabled: bool = True
    sites: list[str] | None = None
    # Keep the identity used when creating/importing the authorization.
    device_model: str = "A320MH"
    system_version: str = "4.16.30-vxEmby"
    app_version: str = "7.6.1"


class Checkiner(BaseModel):
    model_config = ConfigDict(extra="allow")
    timeout: int = Field(default=240, ge=10, le=3600)
    retries: int = Field(default=4, ge=1, le=10)
    concurrency: int = Field(default=1, ge=1, le=8)
    max_duration: int = Field(default=900, ge=30, le=7200)

    def get_site_config(self, name):
        return self.model_extra.get(name, {})


class Settings(StrictModel):
    state_dir: Path = Path("data")
    sites: list[str] = Field(default_factory=list)
    accounts: list[Account] = Field(default_factory=list)
    checkiner: Checkiner = Field(default_factory=Checkiner)
    proxy: Proxy | None = None

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        obj = cls.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
        if not obj.state_dir.is_absolute():
            obj.state_dir = path.parent / obj.state_dir
        names = [a.name for a in obj.accounts]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate account names")
        config.basedir = obj.state_dir
        config.checkiner = obj.checkiner
        config.proxy = obj.proxy
        return obj


# Small runtime settings object used by extracted adapters; no scheduler or watchers.
config = SimpleNamespace(
    basedir=Path("data"), checkiner=Checkiner(), proxy=None,
    nofail=True,
)
