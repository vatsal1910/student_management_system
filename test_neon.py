
import os
from urllib.parse import parse_qs, urlsplit

import psycopg
from dotenv import load_dotenv

load_dotenv()

database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError("DATABASE_URL is missing from the environment.")

try:
    parsed_url = urlsplit(database_url)
except ValueError as error:
    raise RuntimeError("DATABASE_URL is not a valid PostgreSQL URL.") from error

if (
    parsed_url.scheme not in {"postgres", "postgresql"}
    or not parsed_url.hostname
    or parsed_url.hostname.upper() in {"HOST", "YOUR_HOST", "HOSTNAME"}
    or not parsed_url.username
    or not parsed_url.password
    or not parsed_url.path.strip("/")
):
    raise RuntimeError(
        "DATABASE_URL is incomplete or still contains placeholder values."
    )

sslmode = parse_qs(parsed_url.query).get("sslmode", [""])[0].lower()
if sslmode not in {"require", "verify-ca", "verify-full"}:
    raise RuntimeError(
        "DATABASE_URL must specify sslmode=require or a certificate-verifying SSL mode."
    )

try:
    with psycopg.connect(database_url, connect_timeout=8) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version()")
            result = cursor.fetchone()
            if result is None:
                raise RuntimeError("PostgreSQL returned no version information.")
    print("Neon PostgreSQL connection successful.")
except psycopg.Error as error:
    detail = str(error).lower()
    if "resolve" in detail or "getaddrinfo" in detail:
        message = "Could not resolve the database host; verify the Neon endpoint and network."
    elif "password authentication failed" in detail:
        message = "PostgreSQL rejected the credentials; verify the Neon username and password."
    elif "does not exist" in detail and "database" in detail:
        message = "The requested PostgreSQL database was not found; verify its name."
    else:
        message = "PostgreSQL connection failed; verify the Neon URL, credentials, and endpoint status."
    raise RuntimeError(message) from None
