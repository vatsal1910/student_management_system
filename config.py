# MySQL database configuration

import os
import secrets


class Config:
    # Flask secret key
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get(
        "SESSION_COOKIE_SECURE",
        "false"
    ).lower() in {"1", "true", "yes"}

    # MySQL configuration
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
        "Vatsal@1008"
    )

    MYSQL_DATABASE = os.environ.get(
        "MYSQL_DATABASE",
        "student_management_system"
    )
