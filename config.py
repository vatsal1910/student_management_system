# MySQL database configuration

import os
import secrets
from dotenv import load_dotenv


load_dotenv()


class Config:
    # Flask secret key
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get(
        "SESSION_COOKIE_SECURE",
        "false"
    ).lower() in {"1", "true", "yes"}

    # Select the local MySQL backend or a PostgreSQL deployment backend explicitly.
    DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "mysql").lower()
    DATABASE_URL = os.environ.get("DATABASE_URL")

    # Local MySQL configuration
    MYSQL_HOST = os.environ.get(
        "MYSQL_HOST",
        "localhost"
    )

    MYSQL_USER = os.environ.get(
        "MYSQL_USER",
        "root"
    )

    MYSQL_PASSWORD = os.environ.get(
        "MYSQL_PASSWORD",
        ""
    )

    MYSQL_DATABASE = os.environ.get(
        "MYSQL_DATABASE",
        "student_management_system"
    )
