# Student Management System

## Database configuration

The Flask app uses MySQL Connector/Python. Set these environment variables for
both local use and the Render web service:

- `MYSQL_HOST`: hostname supplied by the MySQL provider
- `MYSQL_PORT`: TCP port supplied by the MySQL provider
- `MYSQL_USER`: database username
- `MYSQL_PASSWORD`: database password
- `MYSQL_DATABASE`: database name
- `SECRET_KEY`: stable, randomly generated Flask session-signing key

Do not use a PostgreSQL `DATABASE_URL` with this MySQL application. The app
does not default to `localhost` or assume a database port. `.env.example`
lists the variable names without credentials.

For local development, copy `.env.example` to `.env` and fill in values from
your MySQL provider. Keep `.env` out of Git. On Render, configure the variables
under the web service's Environment settings. A Render Blueprint is described
in `render.yaml`; database credentials remain manual/sensitive variables.
The root `.env` is loaded explicitly by `config.py` before these settings are
read. Operating-system environment variables take precedence over `.env`.

Replace every example placeholder with the real value from your provider; the
example values are not usable connection details. A database password may be
empty only if your provider explicitly configures the account that way.

To generate a local Flask secret, run:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Keep the generated value private and set it as `SECRET_KEY` in `.env`. Render
can generate the key from the Blueprint; do not reuse the local `.env` file
there.

If the login POST reports missing `MYSQL_*` settings, the login form itself
still renders without a database connection; authentication needs the
provider's actual MySQL host, port, username, password, and database name.
Use the provider dashboard's MySQL connection details (not a local
`localhost` address or a PostgreSQL URL). If your provider does not offer
MySQL, this MySQL application cannot connect to it as configured.

To run locally after filling in `.env`:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m flask --app app run
```

Open `http://127.0.0.1:5000/student/login` or
`http://127.0.0.1:5000/admin/login`. A successful GET verifies only that the
login page renders; submit the form only after configuring a reachable database
and a valid account.

## Render commands

- Build: `pip install -r requirements.txt`
- Start: `gunicorn --bind 0.0.0.0:$PORT app:app`

Render supplies `PORT`. The start command binds Gunicorn to it; no Flask
development server is used in production.

## Existing database safety

`database.sql` describes the expected MySQL tables and columns. Do not rerun it
against an existing production database as a repair step: it also contains
sample statements and is not a versioned migration. No migration is performed
by the application. Compare the hosted schema to the expected schema and back
up the database before considering any data-changing SQL.

To inspect an existing MySQL schema without changing data, run these on the
database and share the output with credentials and row data omitted:

```sql
SHOW CREATE TABLE admins;
SHOW CREATE TABLE departments;
SHOW CREATE TABLE courses;
SHOW CREATE TABLE subjects;
SHOW CREATE TABLE students;
SHOW CREATE TABLE attendance;
SHOW CREATE TABLE marks;
```