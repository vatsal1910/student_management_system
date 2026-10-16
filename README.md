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