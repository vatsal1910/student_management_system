from __future__ import annotations

import unittest
from unittest.mock import patch
from typing import Any

import mysql.connector
from werkzeug.security import check_password_hash, generate_password_hash

from app import (
    DatabaseConfigurationError,
    DatabaseUnavailableError,
    app,
    get_db_connection,
    verify_stored_password,
)


class FakeCursor:
    def __init__(
        self,
        connection: FakeConnection,
        dictionary: bool = False
    ) -> None:
        self.connection = connection
        self.dictionary = dictionary
        self.rowcount = 1
        self.current_row: dict[str, Any] | None = None

    def execute(
        self,
        operation: str,
        params: tuple[Any, ...] | None = None
    ) -> None:
        self.connection.statements.append((operation, params))
        self.current_row = None
        if "FROM admins" in operation:
            self.current_row = self.connection.admin
        elif "FROM students" in operation and "WHERE username" in operation:
            self.current_row = self.connection.student

    def fetchone(self) -> dict[str, Any] | None:
        return self.current_row

    def fetchall(self) -> list[dict[str, Any]]:
        return []

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[Any, ...] | None]] = []
        self.admin: dict[str, Any] | None = None
        self.student: dict[str, Any] | None = None
        self.commits: int = 0

    def cursor(self, dictionary: bool = False) -> FakeCursor:
        return FakeCursor(self, dictionary)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass

    def is_connected(self) -> bool:
        return True


class DashboardCursor(FakeCursor):
    def __init__(
        self,
        connection: DashboardConnection,
        fail_on: str | None = None,
        dictionary: bool = True
    ) -> None:
        super().__init__(connection, dictionary=dictionary)
        self.fail_on = fail_on

    def execute(
        self,
        operation: str,
        params: tuple[Any, ...] | None = None
    ) -> None:
        super().execute(operation, params)
        if self.fail_on is not None and self.fail_on in operation:
            raise mysql.connector.Error("Unknown column in dashboard query")
        if "COUNT(*) AS total" in operation:
            self.current_row = {"total": 3}
        elif "AS average_attendance" in operation:
            self.current_row = {"average_attendance": 80.0}
        elif "AS average_marks" in operation:
            self.current_row = {"average_marks": 75.0}


class DashboardConnection(FakeConnection):
    def __init__(self, fail_on: str | None = None) -> None:
        super().__init__()
        self.fail_on = fail_on

    def cursor(self, dictionary: bool = False) -> DashboardCursor:
        return DashboardCursor(
            self,
            fail_on=self.fail_on,
            dictionary=dictionary
        )


class ApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-session-key"
        self.client = app.test_client()
        self.connection = FakeConnection()
        patcher = patch("app.get_db_connection", return_value=self.connection)
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_admin_session(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "admin"

    def test_legacy_password_is_verified_and_flagged_for_upgrade(self) -> None:
        matched, needs_upgrade = verify_stored_password("old-password", "old-password")
        self.assertTrue(matched)
        self.assertTrue(needs_upgrade)

        matched, needs_upgrade = verify_stored_password(
            generate_password_hash("current-password"),
            "current-password"
        )
        self.assertTrue(matched)
        self.assertFalse(needs_upgrade)

        self.assertEqual(
            verify_stored_password("scrypt:invalid", "anything"),
            (False, False)
        )

    def test_admin_legacy_password_is_upgraded_after_successful_login(self) -> None:
        self.connection.admin = {
            "id": 4,
            "username": "admin",
            "email": "admin@example.test",
            "password": "legacy-password",
        }

        response = self.client.post(
            "/admin/login",
            data={
                "username_or_email": "admin",
                "password": "legacy-password",
            },
        )

        self.assertEqual(response.status_code, 302)
        update = next(
            statement for statement in self.connection.statements
            if statement[0].startswith("UPDATE admins")
        )
        password_update = update[1]
        self.assertIsNotNone(password_update)
        assert password_update is not None
        self.assertTrue(
            check_password_hash(str(password_update[0]), "legacy-password")
        )
        with self.client.session_transaction() as browser_session:
            self.assertEqual(browser_session["admin_id"], 4)

    def test_student_hashed_password_login(self) -> None:
        self.connection.student = {
            "id": 7,
            "student_id": "STU007",
            "first_name": "Test",
            "last_name": "Student",
            "username": "student",
            "password": generate_password_hash("student-password"),
        }

        response = self.client.post(
            "/student/login",
            data={"username": "student", "password": "student-password"},
        )

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as browser_session:
            self.assertEqual(browser_session["student_id"], 7)
            self.assertEqual(browser_session["student_code"], "STU007")

    def test_department_and_subject_pages_use_schema_columns(self) -> None:
        self.set_admin_session()

        for path in ("/admin/departments", "/admin/subjects", "/admin/marks"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

        statements = "\n".join(
            query for query, _ in self.connection.statements
        ).lower()
        self.assertNotIn("department_code", statements)
        self.assertNotIn("subjects.max_marks", statements)
        self.assertNotIn("subject_code, max_marks", statements)

    def test_department_and_subject_creation_match_schema(self) -> None:
        self.set_admin_session()

        department_response = self.client.post(
            "/admin/departments/add",
            data={
                "department_name": "Physics",
                "description": "Physics department",
            },
        )
        self.assertEqual(department_response.status_code, 302)

        subject_response = self.client.post(
            "/admin/subjects/add",
            data={
                "subject_name": "Mechanics",
                "subject_code": "PHY101",
                "course_id": "2",
                "semester": "1",
            },
        )
        self.assertEqual(subject_response.status_code, 302)

        department_insert = next(
            query for query, _ in self.connection.statements
            if "INSERT INTO departments" in query
        )
        subject_insert = next(
            query for query, _ in self.connection.statements
            if "INSERT INTO subjects" in query
        )
        self.assertIn("department_name", department_insert)
        self.assertIn("description", department_insert)
        self.assertNotIn("department_code", department_insert)
        self.assertIn("subject_code", subject_insert)
        self.assertIn("semester", subject_insert)
        self.assertNotIn("max_marks", subject_insert)
        self.assertEqual(self.connection.commits, 2)

    def test_admin_dashboard_queries_match_live_marks_columns(self) -> None:
        self.set_admin_session()
        connection = DashboardConnection()
        with patch("app.get_db_connection", return_value=connection):
            response = self.client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Total Students", response.data)
        self.assertIn(b"Recent Examination Results", response.data)
        queries = "\n".join(query for query, _ in connection.statements)
        self.assertIn("SUM(marks_obtained)", queries)
        self.assertIn("SUM(max_marks)", queries)
        self.assertNotIn("SUM(marks)", queries)
        self.assertNotIn("SUM(total_marks)", queries)
        self.assertIn("m.exam_date", queries)
        self.assertNotIn("m.total_marks", queries)

    def test_dashboard_query_failure_logs_context_and_does_not_render_fake_stats(
        self
    ) -> None:
        self.set_admin_session()
        connection = DashboardConnection(fail_on="SUM(marks_obtained)")
        with patch("app.get_db_connection", return_value=connection):
            with self.assertLogs("app", level="ERROR") as captured_logs:
                response = self.client.get("/admin")

        self.assertEqual(response.status_code, 503)
        logs = "\n".join(captured_logs.output)
        self.assertIn("average marks", logs)
        self.assertIn("Unknown column in dashboard query", logs)
        self.assertNotIn(b'<section class="stats-grid">', response.data)
        self.assertNotIn(b'<section class="recent-section">', response.data)
        self.assertIn(b"Dashboard data could not be loaded.", response.data)

    def test_mysql_connection_does_not_fall_back_to_localhost(self) -> None:
        empty_settings = {
            "MYSQL_HOST": "",
            "MYSQL_PORT": "",
            "MYSQL_USER": "",
            "MYSQL_PASSWORD": "",
            "MYSQL_DATABASE": "",
        }
        with patch.dict(app.config, empty_settings):
            with patch("mysql.connector.connect") as connect:
                with self.assertRaisesRegex(RuntimeError, "MYSQL_HOST"):
                    get_db_connection()
                connect.assert_not_called()

    def test_mysql_connection_uses_configured_provider_port_and_settings(self) -> None:
        settings = {
            "MYSQL_HOST": "mysql.example.test",
            "MYSQL_PORT": "27243",
            "MYSQL_USER": "test-user",
            "MYSQL_PASSWORD": "test-password",
            "MYSQL_DATABASE": "test-database",
        }
        with patch.dict(app.config, settings):
            with patch("mysql.connector.connect", return_value=self.connection) as connect:
                result = get_db_connection()

        self.assertIs(result, self.connection)
        connect.assert_called_once_with(
            host="mysql.example.test",
            port=27243,
            user="test-user",
            password="test-password",
            database="test-database",
            use_pure=True,
            connection_timeout=10,
            ssl_disabled=False,
        )

    def test_mysql_connection_failures_are_wrapped_without_connector_details(
        self
    ) -> None:
        settings = {
            "MYSQL_HOST": "mysql.example.test",
            "MYSQL_PORT": "27243",
            "MYSQL_USER": "test-user",
            "MYSQL_PASSWORD": "private-test-password",
            "MYSQL_DATABASE": "test-database",
        }
        with patch.dict(app.config, settings):
            with patch(
                "mysql.connector.connect",
                side_effect=mysql.connector.Error(
                    "password=private-test-password"
                ),
            ):
                with self.assertLogs("app", level="ERROR") as captured_logs:
                    with self.assertRaises(DatabaseUnavailableError):
                        get_db_connection()

        self.assertNotIn("private-test-password", "\n".join(captured_logs.output))

    def test_login_posts_show_safe_configuration_errors(self) -> None:
        for path, form_data in (
            (
                "/admin/login",
                {"username_or_email": "admin", "password": "test-password"},
            ),
            (
                "/student/login",
                {"username": "student", "password": "test-password"},
            ),
        ):
            with self.subTest(path=path):
                with patch(
                    "app.get_db_connection",
                    side_effect=DatabaseConfigurationError(
                        "Missing required database environment variables: MYSQL_HOST"
                    ),
                ):
                    response = self.client.post(path, data=form_data)

                self.assertEqual(response.status_code, 503)
                self.assertIn(b"MYSQL_HOST", response.data)
                self.assertNotIn(b"Traceback", response.data)
                self.assertNotIn(b"test-password", response.data)

    def test_login_connection_errors_do_not_expose_connector_details(self) -> None:
        for path, form_data in (
            (
                "/admin/login",
                {"username_or_email": "admin", "password": "test-password"},
            ),
            (
                "/student/login",
                {"username": "student", "password": "test-password"},
            ),
        ):
            with self.subTest(path=path):
                with patch(
                    "app.get_db_connection",
                    side_effect=mysql.connector.Error(
                        "connection failed; password=test-password"
                    ),
                ):
                    response = self.client.post(path, data=form_data)

                self.assertEqual(response.status_code, 503)
                self.assertIn(b"Unable to access the database", response.data)
                self.assertNotIn(b"test-password", response.data)
                self.assertNotIn(b"connection failed", response.data)

    def test_all_templates_compile(self) -> None:
        with app.app_context():
            for template_name in app.jinja_env.list_templates():
                app.jinja_env.get_template(template_name)

    def test_public_pages_render_and_protected_pages_redirect(self) -> None:
        for path in ("/", "/admin/login", "/student/login", "/student/register"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

        protected_paths = (
            "/admin",
            "/admin/add-student",
            "/admin/students",
            "/admin/departments",
            "/admin/courses",
            "/admin/subjects",
            "/admin/student/1",
            "/admin/attendance",
            "/admin/marks",
            "/admin/results",
            "/student/dashboard",
            "/student/profile",
            "/student/attendance",
            "/student/results",
        )
        for path in protected_paths:
            self.assertEqual(self.client.get(path).status_code, 302, path)


if __name__ == "__main__":
    unittest.main()
