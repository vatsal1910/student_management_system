# MySQL database configuration

import os
import secrets
from pathlib import Path
from dotenv import load_dotenv


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

RUNNING_ON_RENDER = os.environ.get("RENDER", "").lower() == "true"
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY and RUNNING_ON_RENDER:
    raise RuntimeError("SECRET_KEY must be configured in the Render environment.")


class Config:
    SECRET_KEY = SECRET_KEY or secrets.token_hex(32)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get(
        "SESSION_COOKIE_SECURE",
        "true" if RUNNING_ON_RENDER else "false"
    ).lower() in {"1", "true", "yes"}

    MYSQL_HOST = os.environ.get("MYSQL_HOST", "")
    MYSQL_PORT = os.environ.get("MYSQL_PORT", "")
    MYSQL_USER = os.environ.get("MYSQL_USER", "")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "")
