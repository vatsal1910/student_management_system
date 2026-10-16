from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

import mysql.connector
from collections.abc import Mapping, Sequence
from datetime import date
import hmac
import math
from mysql.connector.abstracts import MySQLConnectionAbstract
from mysql.connector.pooling import PooledMySQLConnection
from typing import Any, Protocol, cast
from werkzeug.security import check_password_hash, generate_password_hash
from config import Config


# CREATE FLASK APPLICATION

app = Flask(__name__)
app.config.from_object(Config)


DatabaseConnection = MySQLConnectionAbstract | PooledMySQLConnection


class DatabaseConfigurationError(RuntimeError):
    pass


class DatabaseUnavailableError(DatabaseConfigurationError):
    pass


class DictionaryCursor(Protocol):
    def execute(
        self,
        operation: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None
    ) -> Any: ...

    def fetchone(self) -> dict[str, Any] | None: ...

    def fetchall(self) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


class TupleCursor(Protocol):
    rowcount: int

    def execute(
        self,
        operation: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None
    ) -> Any: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...

    def fetchall(self) -> list[tuple[Any, ...]]: ...

    def close(self) -> None: ...


# MYSQL CONNECTION


def get_db_connection() -> DatabaseConnection:
    database_config = cast(dict[str, object], app.config)
    required_settings = (
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DATABASE",
    )
    missing_settings: list[str] = []
    for name in required_settings:
        value = database_config.get(name)
        if not isinstance(value, str) or not value.strip():
            missing_settings.append(name)

    if missing_settings:
        raise DatabaseConfigurationError(
            "Missing required database environment variables: "
            + ", ".join(missing_settings)
        )

    port_value = database_config["MYSQL_PORT"]
    if not isinstance(port_value, str):
        raise DatabaseConfigurationError(
            "MYSQL_PORT must be a valid TCP port number."
        )

    try:
        mysql_port = int(port_value)
    except (TypeError, ValueError) as error:
        raise DatabaseConfigurationError(
            "MYSQL_PORT must be a valid TCP port number."
        ) from error

    if not 1 <= mysql_port <= 65535:
        raise DatabaseConfigurationError(
            "MYSQL_PORT must be between 1 and 65535."
        )

    try:
        return mysql.connector.connect(
            host=cast(str, database_config["MYSQL_HOST"]).strip(),
            port=mysql_port,
            user=cast(str, database_config["MYSQL_USER"]).strip(),
            password=cast(str, database_config["MYSQL_PASSWORD"]),
            database=cast(str, database_config["MYSQL_DATABASE"]).strip(),
            use_pure=True,
            connection_timeout=10,
            ssl_disabled=False
        )
    except mysql.connector.Error as error:
        app.logger.error(
            "MySQL connection failed (errno=%s, sqlstate=%s)",
            error.errno,
            error.sqlstate
        )
        raise DatabaseUnavailableError(
            "The database connection failed. Verify the provider settings "
            "and database availability."
        ) from None


@app.errorhandler(DatabaseConfigurationError)
def handle_database_configuration_error(
    error: DatabaseConfigurationError
):
    app.logger.error("Database configuration error: %s", error)
    return (
        render_template(
            "database_unavailable.html",
            message=(
                "The database is not configured. Set the required MySQL "
                "environment variables and try again."
            )
        ),
        503,
    )


def get_dictionary_cursor(
    connection: DatabaseConnection
) -> DictionaryCursor:
    return cast(
        DictionaryCursor,
        connection.cursor(dictionary=True)
    )


def get_tuple_cursor(connection: DatabaseConnection) -> TupleCursor:
    return cast(TupleCursor, connection.cursor())


def fetch_required_dict(cursor: DictionaryCursor) -> dict[str, Any]:
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("The database query returned no row.")
    return row


def fetch_required_tuple(cursor: TupleCursor) -> tuple[Any, ...]:
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("The database query returned no row.")
    return row


def verify_stored_password(
    stored_password: Any,
    candidate_password: str
) -> tuple[bool, bool]:
    if not isinstance(stored_password, str):
        return False, False

    if stored_password.startswith(("scrypt:", "pbkdf2:")):
        try:
            return check_password_hash(stored_password, candidate_password), False
        except (TypeError, ValueError):
            return False, False

    return hmac.compare_digest(stored_password, candidate_password), True


# HOME

@app.route("/")
def home():
    return render_template("index.html")


# MYSQL TEST

@app.route("/db-test")
def db_test():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_tuple_cursor(connection)

        cursor.execute("SELECT DATABASE()")

        result = fetch_required_tuple(cursor)
        if result[0] is None:
            raise RuntimeError("MySQL did not report the connected database.")
        database_name = str(result[0])

        return f"""
        <h1>MySQL Connection Successful! ✅</h1>

        <p>
            Connected Database:
            <strong>{database_name}</strong>
        </p>

        <p>
            <a href="/admin/login">
                Go to Admin Login
            </a>
        </p>
        """

    except mysql.connector.Error:

        return f"""
        <h1>MySQL Connection Failed ❌</h1>

        <p>The database request failed. Verify the database provider settings
        and availability.</p>
        """, 503

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ADMIN LOGIN

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    if "admin_id" in session:
        return redirect(url_for("admin_home"))

    if request.method == "POST":

        username_or_email = request.form.get(
            "username_or_email",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if not username_or_email or not password:

            flash(
                "Username/email and password are required.",
                "danger"
            )

            return render_template("admin_login.html")

        connection = None
        cursor = None

        try:

            connection = get_db_connection()

            cursor = get_dictionary_cursor(connection)

            query = """
                SELECT
                    id,
                    username,
                    email,
                    password
                FROM admins
                WHERE username = %s
                   OR email = %s
                LIMIT 1
            """

            cursor.execute(
                query,
                (
                    username_or_email,
                    username_or_email
                )
            )

            admin = cursor.fetchone()

            password_matches, legacy_password = verify_stored_password(
                admin.get("password") if admin else None,
                password
            )

            if admin is not None and password_matches:
                if legacy_password:
                    cursor.execute(
                        "UPDATE admins SET password = %s WHERE id = %s",
                        (generate_password_hash(password), admin["id"])
                    )
                    connection.commit()

                session.clear()

                session["admin_id"] = admin["id"]

                session["admin_username"] = (
                    admin["username"]
                )

                flash(
                    "Login successful!",
                    "success"
                )

                return redirect(
                    url_for("admin_home")
                )

            else:

                flash(
                    "Invalid username/email or password.",
                    "danger"
                )

        except DatabaseConfigurationError as error:
            flash(str(error), "danger")
            return render_template("admin_login.html"), 503

        except mysql.connector.Error as error:
            app.logger.error(
                "Admin login database request failed (errno=%s, sqlstate=%s)",
                error.errno,
                error.sqlstate
            )
            flash(
                "Unable to access the database. Verify its configuration and availability.",
                "danger"
            )
            return render_template("admin_login.html"), 503

        finally:

            if cursor is not None:
                cursor.close()

            if connection is not None and connection.is_connected():
                connection.close()

    return render_template("admin_login.html")


@app.route("/student/register")
def student_registration():
    return render_template("register.html")



# ADMIN DASHBOARD

@app.route("/admin")
def admin_home():

    # Protect dashboard: admin must be logged in
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    connection = None
    cursor = None

    dashboard_data_available = True
    total_students = None
    total_courses = None
    total_departments = None
    average_attendance = None
    average_marks = None
    recent_students = None
    recent_results = None
    query_context = "database connection"

    try:
        connection = get_db_connection()
        cursor = get_dictionary_cursor(connection)

        # 1. Total Students
        query_context = "total students"
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM students
        """)
        total_students = int(fetch_required_dict(cursor)["total"])

        # 2. Total Courses
        query_context = "total courses"
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM courses
        """)
        total_courses = int(fetch_required_dict(cursor)["total"])

        # 3. Total Departments
        query_context = "total departments"
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM departments
        """)
        total_departments = int(fetch_required_dict(cursor)["total"])

        # 4. Average Attendance Percentage
        query_context = "average attendance"
        cursor.execute("""
            SELECT
                COALESCE(
                    ROUND(
                        100.0 * SUM(
                            CASE
                                WHEN status = 'Present' THEN 1
                                ELSE 0
                            END
                        ) / NULLIF(COUNT(*), 0),
                        2
                    ),
                    0
                ) AS average_attendance
            FROM attendance
        """)
        average_attendance = float(
            fetch_required_dict(cursor)["average_attendance"]
        )

        # 5. Average Marks Percentage
        query_context = "average marks"
        cursor.execute("""
            SELECT
                COALESCE(
                    ROUND(
                        100.0 * SUM(marks_obtained) /
                        NULLIF(SUM(max_marks), 0),
                        2
                    ),
                    0
                ) AS average_marks
            FROM marks
        """)
        average_marks = float(
            fetch_required_dict(cursor)["average_marks"]
        )

        # 6. Recent Students (latest 5 records)
        query_context = "recent students"
        cursor.execute("""
            SELECT
                student_id,
                first_name,
                last_name,
                email
            FROM students
            ORDER BY id DESC
            LIMIT 5
        """)
        recent_students = cursor.fetchall()

        # 7. Recent Examination Results (latest 5 records)
        query_context = "recent results"
        cursor.execute("""
            SELECT
                s.first_name,
                s.last_name,
                sub.subject_name,
                m.exam_name,
                m.marks_obtained,
                m.max_marks,
                m.exam_date
            FROM marks AS m
            INNER JOIN students AS s
                ON m.student_id = s.id
            INNER JOIN subjects AS sub
                ON m.subject_id = sub.id
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT 5
        """)
        recent_results = cursor.fetchall()


    except mysql.connector.Error as error:
        dashboard_data_available = False
        app.logger.exception(
            "Admin dashboard query '%s' failed (errno=%s, sqlstate=%s)",
            query_context,
            error.errno,
            error.sqlstate
        )

        flash(
            "Dashboard data could not be loaded. "
            "The failed query has been logged for the administrator.",
            "danger"
        )

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    # Send all dashboard data to dashboard.html
    return render_template(
        "dashboard.html",
        username=session.get("admin_username", "Admin"),
        total_students=total_students,
        total_courses=total_courses,
        total_departments=total_departments,
        average_attendance=average_attendance,
        average_marks=average_marks,
        recent_students=recent_students,
        recent_results=recent_results,
        dashboard_data_available=dashboard_data_available
    ), 200 if dashboard_data_available else 503


# ADD STUDENT

@app.route(
    "/admin/add-student",
    methods=["GET", "POST"]
)
def add_student():

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    connection = None
    cursor = None

    departments = []
    courses = []

    try:

        # =================================================
        # GET DEPARTMENTS
        # =================================================

        connection = get_db_connection()

        cursor = get_dictionary_cursor(connection)

        cursor.execute("""
            SELECT
                id,
                department_name
            FROM departments
            ORDER BY department_name
        """)

        departments = cursor.fetchall()


        # =================================================
        # GET COURSES
        # =================================================

        cursor.execute("""
            SELECT
                id,
                course_name,
                department_id
            FROM courses
            ORDER BY course_name
        """)

        courses = cursor.fetchall()


        cursor.close()
        connection.close()

        cursor = None
        connection = None


        # =================================================
        # POST
        # =================================================

        if request.method == "POST":

            student_id = request.form.get(
                "student_id",
                ""
            ).strip()

            first_name = request.form.get(
                "first_name",
                ""
            ).strip()

            last_name = request.form.get(
                "last_name",
                ""
            ).strip()

            email = request.form.get(
                "email",
                ""
            ).strip()

            phone = request.form.get(
                "phone",
                ""
            ).strip()

            date_of_birth = request.form.get(
                "date_of_birth",
                ""
            ).strip()

            gender = request.form.get(
                "gender",
                ""
            ).strip()

            address = request.form.get(
                "address",
                ""
            ).strip()

            city = request.form.get(
                "city",
                ""
            ).strip()

            department_id = request.form.get(
                "department_id",
                ""
            ).strip()

            course_id = request.form.get(
                "course_id",
                ""
            ).strip()

            semester = request.form.get(
                "semester",
                ""
            ).strip()

            admission_date = request.form.get(
                "admission_date",
                ""
            ).strip()

            username = request.form.get(
                "username",
                ""
            ).strip()

            password = request.form.get(
                "password",
                ""
            )


            if date_of_birth == "":
                date_of_birth = None

            if admission_date == "":
                admission_date = None


            # =================================================
            # VALIDATION
            # =================================================

            if not student_id:

                flash(
                    "Student ID is required.",
                    "danger"
                )

                return render_template(
                    "add_student.html",
                    departments=departments,
                    courses=courses
                )


            if not first_name:

                flash(
                    "First Name is required.",
                    "danger"
                )

                return render_template(
                    "add_student.html",
                    departments=departments,
                    courses=courses
                )


            if not last_name:

                flash(
                    "Last Name is required.",
                    "danger"
                )

                return render_template(
                    "add_student.html",
                    departments=departments,
                    courses=courses
                )

            if not email:
                flash("Email address is required.", "danger")
                return render_template(
                    "add_student.html",
                    departments=departments,
                    courses=courses
                )

            if not phone:
                flash("Phone number is required.", "danger")
                return render_template(
                    "add_student.html",
                    departments=departments,
                    courses=courses
                )

            if not admission_date:
                flash("Admission date is required.", "danger")
                return render_template(
                    "add_student.html",
                    departments=departments,
                    courses=courses
                )

            if not username:
                flash("Student username is required.", "danger")
                return render_template("add_student.html", departments=departments, courses=courses)

            if not password:
                flash("Student password is required.", "danger")
                return render_template("add_student.html", departments=departments, courses=courses)

            if not department_id:

                flash(
                    "Please select a department.",
                    "danger"
                )

                return render_template(
                    "add_student.html",
                    departments=departments,
                    courses=courses
                )


            if not course_id:

                flash(
                    "Please select a course.",
                    "danger"
                )

                return render_template(
                    "add_student.html",
                    departments=departments,
                    courses=courses
                )


            if not semester:

                flash(
                    "Please select a semester.",
                    "danger"
                )

                return render_template(
                    "add_student.html",
                    departments=departments,
                    courses=courses
                )


            # =================================================
            # INSERT STUDENT
            # =================================================

            connection = get_db_connection()

            cursor = get_tuple_cursor(connection)

            query = """
                INSERT INTO students
                (
                    student_id,
                    first_name,
                    last_name,
                    email,
                    phone,
                    date_of_birth,
                    gender,
                    address,
                    city,
                    department_id,
                    course_id,
                    semester,
                    admission_date,
                    username,
                    password
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
            """

            values = (
                student_id,
                first_name,
                last_name,
                email,
                phone,
                date_of_birth,
                gender if gender else None,
                address if address else None,
                city if city else None,
                int(department_id),
                int(course_id),
                int(semester),
                admission_date,
                username,
                generate_password_hash(password)
            )

            cursor.execute(
                query,
                values
            )

            connection.commit()

            flash(
                "Student added successfully!",
                "success"
            )

            return redirect(
                url_for("students")
            )


    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )


    except (TypeError, ValueError):

        if connection is not None:
            connection.rollback()

        flash(
            "Please enter valid department, course, and semester values.",
            "danger"
        )


    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


    return render_template(
        "add_student.html",
        departments=departments,
        courses=courses
    )


# STUDENT LIST + SEARCH

@app.route("/admin/students")
def students():

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    search = request.args.get(
        "search",
        ""
    ).strip()

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_dictionary_cursor(connection)

        query = """
            SELECT
                s.id,
                s.student_id,
                s.first_name,
                s.last_name,
                s.email,
                s.phone,
                s.gender,
                s.date_of_birth,
                s.address,
                s.city,
                s.semester,
                s.admission_date,
                s.username,
                d.department_name,
                c.course_name
            FROM students s
            LEFT JOIN departments d
                ON s.department_id = d.id
            LEFT JOIN courses c
                ON s.course_id = c.id
        """

        if search:

            query += """
                WHERE
                    s.student_id LIKE %s
                    OR s.first_name LIKE %s
                    OR s.last_name LIKE %s
                    OR s.email LIKE %s
                    OR s.phone LIKE %s
            """

            search_value = f"%{search}%"

            cursor.execute(
                query + " ORDER BY s.id DESC",
                (
                    search_value,
                    search_value,
                    search_value,
                    search_value,
                    search_value
                )
            )

        else:

            cursor.execute(
                query + " ORDER BY s.id DESC"
            )

        students_data = cursor.fetchall()

        return render_template(
            "students.html",
            students=students_data,
            search=search
        )

    except mysql.connector.Error as error:
        app.logger.error(
            "Student list database request failed (errno=%s, sqlstate=%s)",
            error.errno,
            error.sqlstate
        )
        flash(
            "Unable to load students. Verify database availability and try again.",
            "danger"
        )
        return render_template(
            "students.html",
            students=[],
            search=search
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# =========================================================
# EDIT / UPDATE STUDENT
# =========================================================

# IMPORTANT:
# This route accepts the visible student_id such as:
# STU001
#
# This prevents the BuildError when students.html
# sends student.student_id to url_for().
# =========================================================

@app.route(
    "/admin/student/<student_id>/edit",
    methods=["GET", "POST"]
)
def edit_student(student_id: str):

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_dictionary_cursor(connection)


        # =================================================
        # GET STUDENT
        # =================================================

        cursor.execute("""
            SELECT
                id,
                student_id,
                first_name,
                last_name,
                email,
                phone,
                date_of_birth,
                gender,
                address,
                city,
                department_id,
                course_id,
                semester,
                admission_date,
                username,
                password
            FROM students
            WHERE student_id = %s
        """, (student_id,))

        student = cursor.fetchone()


        # =================================================
        # STUDENT NOT FOUND
        # =================================================

        if student is None:

            flash(
                "Student not found.",
                "danger"
            )

            return redirect(
                url_for("students")
            )


        # =================================================
        # GET DEPARTMENTS
        # =================================================

        cursor.execute("""
            SELECT
                id,
                department_name,
                description
            FROM departments
            ORDER BY department_name
        """)

        departments = cursor.fetchall()


        # =================================================
        # GET COURSES
        # =================================================

        cursor.execute("""
            SELECT
                id,
                course_name,
                department_id
            FROM courses
            ORDER BY course_name
        """)

        courses = cursor.fetchall()


        # =================================================
        # UPDATE STUDENT
        # =================================================

        if request.method == "POST":

            first_name = request.form.get(
                "first_name",
                ""
            ).strip()

            last_name = request.form.get(
                "last_name",
                ""
            ).strip()

            email = request.form.get(
                "email",
                ""
            ).strip()

            phone = request.form.get(
                "phone",
                ""
            ).strip()

            date_of_birth = request.form.get(
                "date_of_birth",
                ""
            ).strip()

            gender = request.form.get(
                "gender",
                ""
            ).strip()

            address = request.form.get(
                "address",
                ""
            ).strip()

            city = request.form.get(
                "city",
                ""
            ).strip()

            department_id = request.form.get(
                "department_id",
                ""
            ).strip()

            course_id = request.form.get(
                "course_id",
                ""
            ).strip()

            semester = request.form.get(
                "semester",
                ""
            ).strip()

            admission_date = request.form.get(
                "admission_date",
                ""
            ).strip()

            username = request.form.get(
                "username",
                ""
            ).strip()

            password = request.form.get(
                "password",
                ""
            )


            # =================================================
            # EMPTY DATES
            # =================================================

            if date_of_birth == "":
                date_of_birth = None

            if admission_date == "":
                admission_date = None


            # =================================================
            # VALIDATION
            # =================================================

            if not first_name:

                flash(
                    "First Name is required.",
                    "danger"
                )

                return render_template(
                    "edit_student.html",
                    student=student,
                    departments=departments,
                    courses=courses
                )


            if not last_name:

                flash(
                    "Last Name is required.",
                    "danger"
                )

                return render_template(
                    "edit_student.html",
                    student=student,
                    departments=departments,
                    courses=courses
                )


            if not email:
                flash("Email address is required.", "danger")
                return render_template(
                    "edit_student.html",
                    student=student,
                    departments=departments,
                    courses=courses
                )


            if not phone:
                flash("Phone number is required.", "danger")
                return render_template(
                    "edit_student.html",
                    student=student,
                    departments=departments,
                    courses=courses
                )


            if not admission_date:
                flash("Admission date is required.", "danger")
                return render_template(
                    "edit_student.html",
                    student=student,
                    departments=departments,
                    courses=courses
                )


            if not username:
                flash("Student username is required.", "danger")
                return render_template(
                    "edit_student.html",
                    student=student,
                    departments=departments,
                    courses=courses
                )


            if not department_id:

                flash(
                    "Please select a department.",
                    "danger"
                )

                return render_template(
                    "edit_student.html",
                    student=student,
                    departments=departments,
                    courses=courses
                )


            if not course_id:

                flash(
                    "Please select a course.",
                    "danger"
                )

                return render_template(
                    "edit_student.html",
                    student=student,
                    departments=departments,
                    courses=courses
                )


            if not semester:

                flash(
                    "Please select a semester.",
                    "danger"
                )

                return render_template(
                    "edit_student.html",
                    student=student,
                    departments=departments,
                    courses=courses
                )


            # =================================================
            # UPDATE WITHOUT PASSWORD
            # =================================================

            if password == "":

                cursor.execute("""
                    UPDATE students
                    SET
                        first_name = %s,
                        last_name = %s,
                        email = %s,
                        phone = %s,
                        date_of_birth = %s,
                        gender = %s,
                        address = %s,
                        city = %s,
                        department_id = %s,
                        course_id = %s,
                        semester = %s,
                        admission_date = %s,
                        username = %s
                    WHERE student_id = %s
                """, (
                    first_name,
                    last_name,
                    email,
                    phone,
                    date_of_birth,
                    gender if gender else None,
                    address if address else None,
                    city if city else None,
                    int(department_id),
                    int(course_id),
                    int(semester),
                    admission_date,
                    username,
                    student_id
                ))


            # =================================================
            # UPDATE WITH PASSWORD
            # =================================================

            else:

                cursor.execute("""
                    UPDATE students
                    SET
                        first_name = %s,
                        last_name = %s,
                        email = %s,
                        phone = %s,
                        date_of_birth = %s,
                        gender = %s,
                        address = %s,
                        city = %s,
                        department_id = %s,
                        course_id = %s,
                        semester = %s,
                        admission_date = %s,
                        username = %s,
                        password = %s
                    WHERE student_id = %s
                """, (
                    first_name,
                    last_name,
                    email,
                    phone,
                    date_of_birth,
                    gender if gender else None,
                    address if address else None,
                    city if city else None,
                    int(department_id),
                    int(course_id),
                    int(semester),
                    admission_date,
                    username,
                    generate_password_hash(password),
                    student_id
                ))


            connection.commit()


            flash(
                "Student updated successfully.",
                "success"
            )

            return redirect(
                url_for("students")
            )


        # =================================================
        # EDIT PAGE
        # =================================================

        return render_template(
            "edit_student.html",
            student=student,
            departments=departments,
            courses=courses
        )


    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

        return redirect(
            url_for("students")
        )


    except Exception as e:

        if connection is not None:
            connection.rollback()

        print(
            "GENERAL ERROR:",
            e,
            flush=True
        )

        flash(
            f"Error: {e}",
            "danger"
        )

        return redirect(
            url_for("students")
        )


    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# =========================================================
# DELETE STUDENT
# =========================================================

@app.route(
    "/admin/student/<int:student_id>/delete",
    methods=["POST"]
)
def delete_student(student_id: int):

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_tuple_cursor(connection)


        cursor.execute("""
            DELETE FROM students
            WHERE id = %s
        """, (student_id,))


        connection.commit()


        if cursor.rowcount == 0:

            flash(
                "Student not found.",
                "danger"
            )

        else:

            flash(
                "Student deleted successfully.",
                "success"
            )


    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            "Student cannot be deleted because related records may exist.",
            "danger"
        )


    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


    return redirect(
        url_for("students")
    )


# =========================================================
# DEPARTMENT MANAGEMENT
# =========================================================

@app.route("/admin/departments")
def departments():

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_dictionary_cursor(connection)

        cursor.execute("""
            SELECT
                id,
                department_name
            FROM departments
            ORDER BY department_name
        """)

        departments_data = cursor.fetchall()

        return render_template(
            "departments.html",
            departments=departments_data
        )

    except mysql.connector.Error as error:
        app.logger.error(
            "Department list database request failed (errno=%s, sqlstate=%s)",
            error.errno,
            error.sqlstate
        )
        flash(
            "Unable to load departments. Verify database availability and try again.",
            "danger"
        )
        return render_template(
            "departments.html",
            departments=[]
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ADD DEPARTMENT

@app.route(
    "/admin/departments/add",
    methods=["POST"]
)
def add_department():

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    department_name = request.form.get(
        "department_name",
        ""
    ).strip()
    description = request.form.get("description", "").strip() or None

    if not department_name or len(department_name) > 100:
        flash(
            "Department name is required and must be 100 characters or fewer.",
            "danger"
        )
        return redirect(
            url_for("departments")
        )

    if description is not None and len(description) > 255:
        flash("Department description must be 255 characters or fewer.", "danger")
        return redirect(url_for("departments"))

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_tuple_cursor(connection)

        cursor.execute("""
            INSERT INTO departments
            (
                department_name,
                description
            )
            VALUES
            (
                %s,
                %s
            )
        """, (
            department_name,
            description
        ))

        connection.commit()

        flash(
            "Department added successfully.",
            "success"
        )

    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return redirect(
        url_for("departments")
    )


# EDIT / UPDATE DEPARTMENT

@app.route(
    "/admin/departments/<int:department_id>/edit",
    methods=["GET", "POST"]
)
def edit_department(department_id: int):

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_dictionary_cursor(connection)


        cursor.execute("""
            SELECT
                id,
                department_name,
                description
            FROM departments
            WHERE id = %s
        """, (department_id,))

        department = cursor.fetchone()


        if department is None:

            flash(
                "Department not found.",
                "danger"
            )

            return redirect(
                url_for("departments")
            )


        if request.method == "POST":

            department_name = request.form.get(
                "department_name",
                ""
            ).strip()
            description = request.form.get("description", "").strip() or None

            if not department_name or len(department_name) > 100:
                flash(
                    "Department name is required and must be 100 characters or fewer.",
                    "danger"
                )
                return render_template(
                    "edit_department.html",
                    department=department
                )

            if description is not None and len(description) > 255:
                flash("Department description must be 255 characters or fewer.", "danger")
                return render_template(
                    "edit_department.html",
                    department=department
                )

            cursor.execute("""
                UPDATE departments
                SET
                    department_name = %s,
                    description = %s
                WHERE id = %s
            """, (
                department_name,
                description,
                department_id
            ))

            connection.commit()


            flash(
                "Department updated successfully.",
                "success"
            )

            return redirect(
                url_for("departments")
            )


        return render_template(
            "edit_department.html",
            department=department
        )


    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

        return redirect(
            url_for("departments")
        )


    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# DELETE DEPARTMENT

@app.route(
    "/admin/departments/<int:department_id>/delete",
    methods=["POST"]
)
def delete_department(department_id: int):

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_tuple_cursor(connection)


        cursor.execute("""
            DELETE FROM departments
            WHERE id = %s
        """, (department_id,))


        connection.commit()


        if cursor.rowcount == 0:

            flash(
                "Department not found.",
                "danger"
            )

        else:

            flash(
                "Department deleted successfully.",
                "success"
            )


    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            "Department cannot be deleted because it may be used by courses or students.",
            "danger"
        )


    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


    return redirect(
        url_for("departments")
    )


# COURSE MANAGEMENT

@app.route("/admin/courses")
def courses():

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_dictionary_cursor(connection)


        # =================================================
        # GET COURSES
        # =================================================

        cursor.execute("""
            SELECT
                c.id,
                c.course_name,
                c.department_id,
                d.department_name
            FROM courses c
            LEFT JOIN departments d
                ON c.department_id = d.id
            ORDER BY c.course_name
        """)

        courses_data = cursor.fetchall()


        # =================================================
        # GET DEPARTMENTS
        # =================================================

        cursor.execute("""
            SELECT
                id,
                department_name
            FROM departments
            ORDER BY department_name
        """)

        departments_data = cursor.fetchall()


        return render_template(
            "courses.html",
            courses=courses_data,
            departments=departments_data
        )


    except mysql.connector.Error as e:

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

        return render_template(
            "courses.html",
            courses=[],
            departments=[]
        )


    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ADD COURSE

@app.route(
    "/admin/courses/add",
    methods=["POST"]
)
def add_course():

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    course_name = request.form.get(
        "course_name",
        ""
    ).strip()

    course_code = request.form.get(
        "course_code",
        ""
    ).strip().upper()

    duration_years_value = request.form.get(
        "duration_years",
        ""
    ).strip()

    department_id = request.form.get(
        "department_id",
        ""
    ).strip()


    if not course_name:

        flash(
            "Course name is required.",
            "danger"
        )

        return redirect(
            url_for("courses")
        )


    if not course_code:
        flash("Course code is required.", "danger")
        return redirect(url_for("courses"))

    if len(course_code) > 20:
        flash("Course code cannot exceed 20 characters.", "danger")
        return redirect(url_for("courses"))

    try:
        duration_years = int(duration_years_value)
    except ValueError:
        flash("Duration must be a whole number of years.", "danger")
        return redirect(url_for("courses"))

    if duration_years < 1:
        flash("Duration must be at least one year.", "danger")
        return redirect(url_for("courses"))


    if not department_id:

        flash(
            "Please select a department.",
            "danger"
        )

        return redirect(
            url_for("courses")
        )

    try:
        department_pk = int(department_id)
    except ValueError:
        flash("Please select a valid department.", "danger")
        return redirect(url_for("courses"))


    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_tuple_cursor(connection)

        cursor.execute("""
            INSERT INTO courses
            (
                course_name,
                course_code,
                department_id,
                duration_years
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s
            )
        """, (
            course_name,
            course_code,
            department_pk,
            duration_years
        ))

        connection.commit()

        flash(
            "Course added successfully.",
            "success"
        )


    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )


    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


    return redirect(
        url_for("courses")
    )


# EDIT / UPDATE COURSE

@app.route(
    "/admin/courses/<int:course_id>/edit",
    methods=["GET", "POST"]
)
def edit_course(course_id: int):

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_dictionary_cursor(connection)


        cursor.execute("""
            SELECT
                id,
                course_name,
                course_code,
                duration_years,
                department_id
            FROM courses
            WHERE id = %s
        """, (course_id,))

        course = cursor.fetchone()


        if course is None:

            flash(
                "Course not found.",
                "danger"
            )

            return redirect(
                url_for("courses")
            )


        cursor.execute("""
            SELECT
                id,
                department_name
            FROM departments
            ORDER BY department_name
        """)

        departments = cursor.fetchall()


        if request.method == "POST":

            course_name = request.form.get(
                "course_name",
                ""
            ).strip()

            course_code = request.form.get(
                "course_code",
                ""
            ).strip().upper()

            duration_years_value = request.form.get(
                "duration_years",
                ""
            ).strip()

            department_id = request.form.get(
                "department_id",
                ""
            ).strip()


            if not course_name:

                flash(
                    "Course name is required.",
                    "danger"
                )

                return render_template(
                    "edit_course.html",
                    course=course,
                    departments=departments
                )


            if not course_code or len(course_code) > 20:
                flash(
                    "Enter a course code of 1 to 20 characters.",
                    "danger"
                )
                return render_template(
                    "edit_course.html",
                    course=course,
                    departments=departments
                )


            try:
                duration_years = int(duration_years_value)
            except ValueError:
                flash("Duration must be a whole number of years.", "danger")
                return render_template(
                    "edit_course.html",
                    course=course,
                    departments=departments
                )

            if duration_years < 1:
                flash("Duration must be at least one year.", "danger")
                return render_template(
                    "edit_course.html",
                    course=course,
                    departments=departments
                )


            if not department_id:

                flash(
                    "Please select a department.",
                    "danger"
                )

                return render_template(
                    "edit_course.html",
                    course=course,
                    departments=departments
                )

            try:
                department_pk = int(department_id)
            except ValueError:
                flash("Please select a valid department.", "danger")
                return render_template(
                    "edit_course.html",
                    course=course,
                    departments=departments
                )


            cursor.execute("""
                UPDATE courses
                SET
                    course_name = %s,
                    course_code = %s,
                    department_id = %s,
                    duration_years = %s
                WHERE id = %s
            """, (
                course_name,
                course_code,
                department_pk,
                duration_years,
                course_id
            ))

            connection.commit()


            flash(
                "Course updated successfully.",
                "success"
            )

            return redirect(
                url_for("courses")
            )


        return render_template(
            "edit_course.html",
            course=course,
            departments=departments
        )


    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

        return redirect(
            url_for("courses")
        )


    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# DELETE COURSE

@app.route(
    "/admin/courses/<int:course_id>/delete",
    methods=["POST"]
)
def delete_course(course_id: int):

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_tuple_cursor(connection)


        cursor.execute("""
            DELETE FROM courses
            WHERE id = %s
        """, (course_id,))


        connection.commit()


        if cursor.rowcount == 0:

            flash(
                "Course not found.",
                "danger"
            )

        else:

            flash(
                "Course deleted successfully.",
                "success"
            )


    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            "Course cannot be deleted because it may be assigned to a student.",
            "danger"
        )


    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


    return redirect(
        url_for("courses")
    )


# SUBJECT MANAGEMENT

@app.route("/admin/subjects")
def subjects():

    if "admin_id" not in session:
        flash("Please login as admin first.", "warning")
        return redirect(url_for("admin_login"))

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = get_dictionary_cursor(connection)

        # Get subjects with course name
        cursor.execute("""
            SELECT
                s.id,
                s.subject_name,
                s.subject_code,
                s.course_id,
                s.semester,
                c.course_name
            FROM subjects s
            LEFT JOIN courses c
                ON s.course_id = c.id
            ORDER BY s.subject_name
        """)

        subjects_data = cursor.fetchall()

        # Get courses for Add Subject form
        cursor.execute("""
            SELECT
                id,
                course_name
            FROM courses
            ORDER BY course_name
        """)

        courses_data = cursor.fetchall()

        return render_template(
            "subjects.html",
            subjects=subjects_data,
            courses=courses_data
        )

    except mysql.connector.Error as e:

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

        return render_template(
            "subjects.html",
            subjects=[],
            courses=[]
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ADD SUBJECT

@app.route(
    "/admin/subjects/add",
    methods=["POST"]
)
def add_subject():

    if "admin_id" not in session:
        flash("Please login as admin first.", "warning")
        return redirect(url_for("admin_login"))

    subject_name = request.form.get(
        "subject_name",
        ""
    ).strip()

    subject_code = request.form.get(
        "subject_code",
        ""
    ).strip().upper()

    course_id = request.form.get(
        "course_id",
        ""
    ).strip()

    semester = request.form.get(
        "semester",
        ""
    ).strip()

    # Validation

    if not subject_name:
        flash(
            "Subject name is required.",
            "danger"
        )
        return redirect(url_for("subjects"))

    if not subject_code:
        flash(
            "Subject code is required.",
            "danger"
        )
        return redirect(url_for("subjects"))

    if not course_id or not semester:
        flash("Please select a course and semester.", "danger")
        return redirect(url_for("subjects"))

    try:
        course_pk = int(course_id)
        semester_number = int(semester)
    except ValueError:
        flash("Please select a valid course and semester.", "danger")
        return redirect(url_for("subjects"))

    if course_pk < 1 or semester_number < 1:
        flash("Please select a valid course and semester.", "danger")
        return redirect(url_for("subjects"))

    if len(subject_name) > 100 or len(subject_code) > 50:
        flash("Subject name or code exceeds the allowed length.", "danger")
        return redirect(url_for("subjects"))

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = get_tuple_cursor(connection)

        cursor.execute("""
            INSERT INTO subjects
            (
                subject_name,
                subject_code,
                course_id,
                semester
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s
            )
        """, (
            subject_name,
            subject_code,
            course_pk,
            semester_number
        ))

        connection.commit()

        flash(
            "Subject added successfully.",
            "success"
        )

    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return redirect(
        url_for("subjects")
    )


# STUDENT DETAILS

@app.route(
    "/admin/student/<int:student_id>"
)
def student_details(student_id: int):

    if "admin_id" not in session:

        flash(
            "Please login as admin first.",
            "warning"
        )

        return redirect(
            url_for("admin_login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_dictionary_cursor(connection)

        query = """
            SELECT
                s.*,
                d.department_name,
                c.course_name
            FROM students s
            LEFT JOIN departments d
                ON s.department_id = d.id
            LEFT JOIN courses c
                ON s.course_id = c.id
            WHERE s.id = %s
        """

        cursor.execute(
            query,
            (student_id,)
        )

        student = cursor.fetchone()


        if student is None:

            flash(
                "Student not found.",
                "danger"
            )

            return redirect(
                url_for("students")
            )


        return render_template(
            "student_details.html",
            student=student
        )


    except mysql.connector.Error as e:

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

        return redirect(
            url_for("students")
        )


    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ADMIN LOGOUT

@app.route("/admin/logout")
def admin_logout():

    session.clear()

    flash(
        "You have been logged out successfully.",
        "success"
    )

    return redirect(
        url_for("admin_login")
    )


# STUDENT PROFILE

@app.route("/student/profile")
def student_profile():

    # Check student login
    if "student_id" not in session:

        flash(
            "Please login as student first.",
            "warning"
        )

        return redirect(
            url_for("student_login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = get_dictionary_cursor(connection)

        cursor.execute("""
            SELECT
                s.id,
                s.student_id,
                s.first_name,
                s.last_name,
                s.email,
                s.phone,
                s.date_of_birth,
                s.gender,
                s.address,
                s.city,
                s.semester,
                s.admission_date,
                s.username,
                d.department_name,
                c.course_name
            FROM students s

            LEFT JOIN departments d
                ON s.department_id = d.id

            LEFT JOIN courses c
                ON s.course_id = c.id

            WHERE s.id = %s
        """, (
            session["student_id"],
        ))

        student = cursor.fetchone()

        if student is None:

            session.clear()

            flash(
                "Student account not found.",
                "danger"
            )

            return redirect(
                url_for("student_login")
            )

        return render_template(
            "student_profile.html",
            student=student
        )

    except mysql.connector.Error as e:

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

        return redirect(
            url_for("student_dashboard")
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# STUDENT LOGOUT

@app.route("/student/logout")
def student_logout():

    session.pop("student_id", None)
    session.pop("student_username", None)
    session.pop("student_code", None)

    flash(
        "You have been logged out successfully.",
        "success"
    )

    return redirect(
        url_for("student_login")
    )


# ADMIN ATTENDANCE

@app.route("/admin/attendance")
def attendance():

    if "admin_id" not in session:
        flash("Please login as admin first.", "warning")
        return redirect(url_for("admin_login"))

    connection = None
    cursor = None

    # Default values
    attendance_records = []
    students_data = []
    subjects_data = []
    attendance_summary = []

    try:
        connection = get_db_connection()
        cursor = get_dictionary_cursor(connection)

        # 1. Get attendance records
        cursor.execute("""
            SELECT
                a.id,
                s.student_id,
                s.first_name,
                s.last_name,
                a.subject_id,
                sub.subject_name,
                sub.subject_code,
                a.attendance_date,
                a.status
            FROM attendance a
            INNER JOIN students s
                ON a.student_id = s.id
            INNER JOIN subjects sub
                ON a.subject_id = sub.id
            ORDER BY a.attendance_date DESC, a.id DESC
        """)

        attendance_records = cursor.fetchall()

        # 2. Get students for dropdown
        cursor.execute("""
            SELECT
                id,
                student_id,
                first_name,
                last_name
            FROM students
            ORDER BY first_name, last_name
        """)

        students_data = cursor.fetchall()

        # 3. Get subjects for dropdown
        cursor.execute("""
            SELECT
                id,
                subject_name,
                subject_code,
                semester
            FROM subjects
            ORDER BY subject_name
        """)

        subjects_data = cursor.fetchall()

        # 4. Calculate attendance percentage per student and subject
        cursor.execute("""
            SELECT
                s.id AS student_db_id,
                s.student_id,
                s.first_name,
                s.last_name,
                sub.subject_name,
                sub.subject_code,
                COUNT(a.id) AS total_classes,
                SUM(
                    CASE
                        WHEN a.status = 'Present' THEN 1
                        ELSE 0
                    END
                ) AS present_classes,
                SUM(
                    CASE
                        WHEN a.status = 'Absent' THEN 1
                        ELSE 0
                    END
                ) AS absent_classes,
                ROUND(
                    100.0 * SUM(
                        CASE
                            WHEN a.status = 'Present' THEN 1
                            ELSE 0
                        END
                    ) / NULLIF(COUNT(a.id), 0),
                    2
                ) AS attendance_percentage
            FROM attendance a
            INNER JOIN students s
                ON a.student_id = s.id
            INNER JOIN subjects sub
                ON a.subject_id = sub.id
            GROUP BY
                s.id,
                s.student_id,
                s.first_name,
                s.last_name,
                sub.id,
                sub.subject_name,
                sub.subject_code
            ORDER BY s.student_id, sub.subject_name
        """)

        attendance_summary = cursor.fetchall()

    except mysql.connector.Error as e:
        print("ATTENDANCE DATABASE ERROR:", e, flush=True)
        flash("Unable to load attendance data. Please check the server console.", "danger")

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    # 5. Send all data to attendance.html
    return render_template(
        "attendance.html",
        attendance_records=attendance_records,
        students=students_data,
        subjects=subjects_data,
        attendance_summary=attendance_summary
    )


# ADD ATTENDANCE

@app.route("/admin/attendance/add", methods=["POST"])
def add_attendance():

    if "admin_id" not in session:
        flash("Please login as admin first.", "warning")
        return redirect(url_for("admin_login"))

    student_id = request.form.get("student_id", "").strip()
    subject_id = request.form.get("subject_id", "").strip()
    attendance_date = request.form.get("attendance_date", "").strip()
    status = request.form.get("status", "").strip()

    # Validation
    if not student_id:
        flash("Please select a student.", "danger")
        return redirect(url_for("attendance"))

    if not subject_id:
        flash("Please select a subject.", "danger")
        return redirect(url_for("attendance"))

    if not attendance_date:
        flash("Please select an attendance date.", "danger")
        return redirect(url_for("attendance"))

    if status not in ["Present", "Absent"]:
        flash("Please select a valid attendance status.", "danger")
        return redirect(url_for("attendance"))

    try:
        student_pk = int(student_id)
        subject_pk = int(subject_id)
        date.fromisoformat(attendance_date)
    except ValueError:
        flash("Enter a valid student, subject, and attendance date.", "danger")
        return redirect(url_for("attendance"))

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = get_tuple_cursor(connection)

        # Check whether attendance already exists
        cursor.execute("""
            SELECT id
            FROM attendance
            WHERE student_id = %s
              AND subject_id = %s
              AND attendance_date = %s
        """, (
            student_pk,
            subject_pk,
            attendance_date
        ))

        existing_record = cursor.fetchone()

        if existing_record:
            flash(
                "Attendance for this student, subject and date already exists.",
                "warning"
            )

            return redirect(url_for("attendance"))

        # Insert attendance
        cursor.execute("""
            INSERT INTO attendance
            (
                student_id,
                subject_id,
                attendance_date,
                status
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s
            )
        """, (
            student_pk,
            subject_pk,
            attendance_date,
            status
        ))

        connection.commit()

        flash(
            "Attendance added successfully.",
            "success"
        )

    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

    except ValueError:

        if connection is not None:
            connection.rollback()

        flash(
            "Invalid student or subject selected.",
            "danger"
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return redirect(url_for("attendance"))


# EDIT ATTENDANCE

@app.route("/admin/attendance/<int:attendance_id>/edit", methods=["GET", "POST"])
def edit_attendance(attendance_id: int):

    if "admin_id" not in session:
        flash("Please login as admin first.", "warning")
        return redirect(url_for("admin_login"))

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = get_dictionary_cursor(connection)

        # Get attendance record
        cursor.execute("""
            SELECT
                id,
                student_id,
                subject_id,
                attendance_date,
                status
            FROM attendance
            WHERE id = %s
        """, (attendance_id,))

        attendance_record = cursor.fetchone()

        if attendance_record is None:
            flash("Attendance record not found.", "danger")
            return redirect(url_for("attendance"))

        # POST = update attendance
        if request.method == "POST":

            student_id = request.form.get("student_id", "").strip()
            subject_id = request.form.get("subject_id", "").strip()
            attendance_date = request.form.get("attendance_date", "").strip()
            status = request.form.get("status", "").strip()

            if not student_id:
                flash("Please select a student.", "danger")
                return redirect(
                    url_for(
                        "edit_attendance",
                        attendance_id=attendance_id
                    )
                )

            if not subject_id:
                flash("Please select a subject.", "danger")
                return redirect(
                    url_for(
                        "edit_attendance",
                        attendance_id=attendance_id
                    )
                )

            if not attendance_date:
                flash("Please select an attendance date.", "danger")
                return redirect(
                    url_for(
                        "edit_attendance",
                        attendance_id=attendance_id
                    )
                )

            if status not in ["Present", "Absent"]:
                flash("Please select a valid attendance status.", "danger")
                return redirect(
                    url_for(
                        "edit_attendance",
                        attendance_id=attendance_id
                    )
                )

            student_pk = int(student_id)
            subject_pk = int(subject_id)
            date.fromisoformat(attendance_date)

            # Check duplicate record
            cursor.execute("""
                SELECT id
                FROM attendance
                WHERE student_id = %s
                  AND subject_id = %s
                  AND attendance_date = %s
                  AND id != %s
            """, (
                student_pk,
                subject_pk,
                attendance_date,
                attendance_id
            ))

            existing_record = cursor.fetchone()

            if existing_record:
                flash(
                    "Attendance for this student, subject and date already exists.",
                    "warning"
                )

                return redirect(
                    url_for(
                        "edit_attendance",
                        attendance_id=attendance_id
                    )
                )

            # Update attendance
            cursor.execute("""
                UPDATE attendance
                SET
                    student_id = %s,
                    subject_id = %s,
                    attendance_date = %s,
                    status = %s
                WHERE id = %s
            """, (
                student_pk,
                subject_pk,
                attendance_date,
                status,
                attendance_id
            ))

            connection.commit()

            flash(
                "Attendance updated successfully.",
                "success"
            )

            return redirect(url_for("attendance"))

        # Get students
        cursor.execute("""
            SELECT
                id,
                student_id,
                first_name,
                last_name
            FROM students
            ORDER BY first_name, last_name
        """)

        students_data = cursor.fetchall()

        # Get subjects
        cursor.execute("""
            SELECT
                id,
                subject_name,
                subject_code,
                semester
            FROM subjects
            ORDER BY subject_name
        """)

        subjects_data = cursor.fetchall()

        return render_template(
            "edit_attendance.html",
            attendance=attendance_record,
            students=students_data,
            subjects=subjects_data
        )

    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

        return redirect(url_for("attendance"))

    except ValueError:

        if connection is not None:
            connection.rollback()

        flash(
            "Invalid student or subject selected.",
            "danger"
        )

        return redirect(url_for("attendance"))

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# DELETE ATTENDANCE

@app.route("/admin/attendance/<int:attendance_id>/delete", methods=["POST"])
def delete_attendance(attendance_id: int):

    if "admin_id" not in session:
        flash("Please login as admin first.", "warning")
        return redirect(url_for("admin_login"))

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = get_tuple_cursor(connection)

        cursor.execute("""
            DELETE FROM attendance
            WHERE id = %s
        """, (attendance_id,))

        connection.commit()

        if cursor.rowcount == 0:
            flash(
                "Attendance record not found.",
                "warning"
            )
        else:
            flash(
                "Attendance deleted successfully.",
                "success"
            )

    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print(
            "DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            f"Database Error: {e}",
            "danger"
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return redirect(url_for("attendance"))


# STUDENT ATTENDANCE

@app.route("/student/attendance")
def student_attendance():

    if "student_id" not in session:
        flash("Please login as student first.", "warning")
        return redirect(url_for("student_login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = get_dictionary_cursor(connection)

        cursor.execute("""
            SELECT
                a.id,
                a.attendance_date,
                a.status,
                sub.subject_name,
                sub.subject_code
            FROM attendance a
            INNER JOIN subjects sub
                ON a.subject_id = sub.id
            WHERE a.student_id = %s
            ORDER BY a.attendance_date DESC, a.id DESC
        """, (session["student_id"],))

        attendance_records = cursor.fetchall()

        total_classes = len(attendance_records)
        present_count = sum(
            1 for record in attendance_records
            if record["status"] == "Present"
        )
        absent_count = sum(
            1 for record in attendance_records
            if record["status"] == "Absent"
        )

        attendance_percentage = (
            round((present_count / total_classes) * 100, 2)
            if total_classes > 0 else 0
        )

        return render_template(
            "student_attendance.html",
            attendance_records=attendance_records,
            total_classes=total_classes,
            present_count=present_count,
            absent_count=absent_count,
            attendance_percentage=attendance_percentage
        )

    except mysql.connector.Error as e:
        print("DATABASE ERROR:", e, flush=True)
        flash("Unable to load attendance records.", "danger")
        return redirect(url_for("student_dashboard"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# STUDENT RESULTS

@app.route("/student/results")
def student_results():

    if "student_id" not in session:
        flash("Please login as student first.", "warning")
        return redirect(url_for("student_login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = get_dictionary_cursor(connection)

        cursor.execute("""
            SELECT
                m.id,
                m.exam_name,
                m.marks AS marks_obtained,
                m.total_marks AS max_marks,
                m.created_at AS exam_date,
                sub.subject_name,
                sub.subject_code
            FROM marks AS m
            INNER JOIN subjects AS sub
                ON m.subject_id = sub.id
            WHERE m.student_id = %s
            ORDER BY m.created_at DESC, m.id DESC
        """, (session["student_id"],))

        results = cursor.fetchall()

        total_obtained = 0
        total_maximum = 0

        for result in results:
            obtained = float(result["marks_obtained"] or 0)
            maximum = float(result["max_marks"] or 0)

            percentage = (
                round((obtained / maximum) * 100, 2)
                if maximum > 0 else 0
            )

            if percentage >= 90:
                grade = "A+"
            elif percentage >= 80:
                grade = "A"
            elif percentage >= 70:
                grade = "B"
            elif percentage >= 60:
                grade = "C"
            elif percentage >= 50:
                grade = "D"
            elif percentage >= 35:
                grade = "Pass"
            else:
                grade = "Fail"

            result["percentage"] = percentage
            result["grade"] = grade

            total_obtained += obtained
            total_maximum += maximum

        overall_percentage = (
            round((total_obtained / total_maximum) * 100, 2)
            if total_maximum > 0 else 0
        )

        return render_template(
            "student_results.html",
            results=results,
            total_obtained=round(total_obtained, 2),
            total_maximum=round(total_maximum, 2),
            overall_percentage=overall_percentage,
            total_exams=len(results)
        )

    except mysql.connector.Error as e:
        print("STUDENT RESULTS DATABASE ERROR:", e, flush=True)
        flash("Unable to load your results.", "danger")
        return redirect(url_for("student_dashboard"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

# ADMIN RESULTS - VIEW ALL STUDENT RESULTS

@app.route("/admin/results")
def admin_results():

    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = get_dictionary_cursor(connection)

        cursor.execute("""
            SELECT
                m.id,
                s.student_id AS student_code,
                s.first_name,
                s.last_name,
                sub.subject_name,
                sub.subject_code,
                m.exam_name,
                m.marks AS marks_obtained,
                m.total_marks AS max_marks,
                m.created_at AS exam_date
            FROM marks AS m
            INNER JOIN students AS s
                ON m.student_id = s.id
            INNER JOIN subjects AS sub
                ON m.subject_id = sub.id
            ORDER BY m.created_at DESC, m.id DESC
        """)

        results = cursor.fetchall()

        total_obtained = 0
        total_maximum = 0

        for result in results:
            obtained = float(result["marks_obtained"] or 0)
            maximum = float(result["max_marks"] or 0)

            percentage = (
                round((obtained / maximum) * 100, 2)
                if maximum > 0 else 0
            )

            result["percentage"] = percentage
            result["status"] = "Pass" if percentage >= 35 else "Fail"

            total_obtained += obtained
            total_maximum += maximum

        overall_percentage = (
            round((total_obtained / total_maximum) * 100, 2)
            if total_maximum > 0 else 0
        )

        return render_template(
            "admin_results.html",
            results=results,
            total_results=len(results),
            total_obtained=round(total_obtained, 2),
            total_maximum=round(total_maximum, 2),
            overall_percentage=overall_percentage
        )

    except mysql.connector.Error as error:
        print("ADMIN RESULTS DATABASE ERROR:", error, flush=True)
        flash("Unable to load student results.", "danger")
        return redirect(url_for("admin_home"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ADMIN MARKS MANAGEMENT

@app.route("/admin/marks")
def marks():

    if "admin_id" not in session:
        flash("Please login as admin first.", "warning")
        return redirect(url_for("admin_login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = get_dictionary_cursor(connection)

        cursor.execute("""
            SELECT
                m.id,
                m.student_id,
                m.subject_id,
                m.exam_name,
                m.marks AS marks_obtained,
                m.total_marks AS max_marks,
                m.created_at AS exam_date,
                s.student_id AS student_code,
                s.first_name,
                s.last_name,
                sub.subject_name,
                sub.subject_code
            FROM marks AS m
            INNER JOIN students AS s ON m.student_id = s.id
            INNER JOIN subjects AS sub ON m.subject_id = sub.id
            ORDER BY m.created_at DESC, m.id DESC
        """)
        marks_records = cursor.fetchall()

        cursor.execute("""
            SELECT id, student_id, first_name, last_name
            FROM students
            ORDER BY first_name, last_name
        """)
        students_data = cursor.fetchall()

        cursor.execute("""
            SELECT id, subject_name, subject_code
            FROM subjects
            ORDER BY subject_name
        """)
        subjects_data = cursor.fetchall()

        return render_template(
            "marks.html",
            marks_records=marks_records,
            students=students_data,
            subjects=subjects_data
        )

    except mysql.connector.Error as e:
        print("MARKS DATABASE ERROR:", e, flush=True)
        flash(f"Database Error: {e}", "danger")
        return render_template(
            "marks.html",
            marks_records=[],
            students=[],
            subjects=[]
        )

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

# ADD MARKS

@app.route("/admin/marks/add", methods=["POST"])
def add_marks():

    if "admin_id" not in session:
        flash("Please login as admin first.", "warning")
        return redirect(url_for("admin_login"))

    student_id = request.form.get("student_id", "").strip()
    subject_id = request.form.get("subject_id", "").strip()
    exam_name = request.form.get("exam_name", "").strip()
    marks_obtained = request.form.get("marks_obtained", "").strip()
    max_marks = request.form.get("max_marks", "").strip()
    exam_date = request.form.get("exam_date", "").strip() or None

    if not all([student_id, subject_id, exam_name, marks_obtained, max_marks]):
        flash("Please fill in all required marks fields.", "danger")
        return redirect(url_for("marks"))

    if len(exam_name) > 100:
        flash("Exam name cannot exceed 100 characters.", "danger")
        return redirect(url_for("marks"))

    try:
        obtained = float(marks_obtained)
        maximum = float(max_marks)
        student_pk = int(student_id)
        subject_pk = int(subject_id)
    except ValueError:
        flash("Please enter valid student, subject, and marks values.", "danger")
        return redirect(url_for("marks"))

    if (
        not math.isfinite(obtained)
        or not math.isfinite(maximum)
        or maximum <= 0
        or maximum > 999.99
        or obtained < 0
        or obtained > maximum
    ):
        flash("Enter marks between 0 and the maximum marks.", "danger")
        return redirect(url_for("marks"))

    if exam_date:
        try:
            date.fromisoformat(exam_date)
        except ValueError:
            flash("Enter a valid exam date.", "danger")
            return redirect(url_for("marks"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = get_tuple_cursor(connection)

        cursor.execute(
            "SELECT id FROM students WHERE id = %s",
            (student_pk,)
        )
        if cursor.fetchone() is None:
            flash("Selected student was not found.", "danger")
            return redirect(url_for("marks"))

        cursor.execute(
            "SELECT id FROM subjects WHERE id = %s",
            (subject_pk,)
        )
        if cursor.fetchone() is None:
            flash("Selected subject was not found.", "danger")
            return redirect(url_for("marks"))

        cursor.execute("""
            SELECT id
            FROM marks
            WHERE student_id = %s
              AND subject_id = %s
              AND exam_name = %s
        """, (student_pk, subject_pk, exam_name))

        if cursor.fetchone():
            flash(
                "Marks for this student, subject, and exam already exist.",
                "warning"
            )
            return redirect(url_for("marks"))

        
        cursor.execute("""
            INSERT INTO marks
                (student_id, subject_id, exam_name,
                 marks, total_marks, created_at)
            VALUES (%s, %s, %s, %s, %s,
                    COALESCE(%s, CURRENT_TIMESTAMP))
        """, (
            student_pk,
            subject_pk,
            exam_name,
            obtained,
            maximum,
            exam_date
        ))


        connection.commit()
        flash("Marks added successfully.", "success")

    except mysql.connector.Error as e:
        if connection is not None:
            connection.rollback()

        print("ADD MARKS DATABASE ERROR:", e, flush=True)
        flash(f"Database Error: {e}", "danger")

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return redirect(url_for("marks"))




# EDIT MARKS

@app.route("/admin/marks/edit/<int:mark_id>", methods=["GET", "POST"])
def edit_marks(mark_id: int):

    if "admin_id" not in session:
        flash("Please login as admin first.", "warning")
        return redirect(url_for("admin_login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = get_dictionary_cursor(connection)

        # Get the existing marks record
        cursor.execute("""
            SELECT
                id,
                student_id,
                subject_id,
                exam_name,
                marks,
                total_marks,
                created_at
            FROM marks
            WHERE id = %s
        """, (mark_id,))

        mark = cursor.fetchone()

        if mark is None:
            flash("Marks record not found.", "danger")
            return redirect(url_for("marks"))

        # Update marks
        if request.method == "POST":

            exam_name = request.form.get(
                "exam_name", ""
            ).strip()

            marks_obtained = request.form.get(
                "marks_obtained", ""
            ).strip()

            max_marks = request.form.get(
                "max_marks", ""
            ).strip()

            exam_date = request.form.get(
                "exam_date", ""
            ).strip() or None

            if not exam_name:
                flash("Exam name is required.", "danger")
                return render_template(
                    "edit_marks.html",
                    mark=mark
                )

            if len(exam_name) > 100:
                flash("Exam name cannot exceed 100 characters.", "danger")
                return render_template(
                    "edit_marks.html",
                    mark=mark
                )

            try:
                obtained = float(marks_obtained)
                maximum = float(max_marks)
            except (ValueError, TypeError):
                flash("Marks must be valid numbers.", "danger")
                return render_template(
                    "edit_marks.html",
                    mark=mark
                )

            if (
                not math.isfinite(obtained)
                or not math.isfinite(maximum)
                or maximum <= 0
                or maximum > 999.99
                or obtained < 0
                or obtained > maximum
            ):
                flash(
                    "Obtained marks must be between 0 and maximum marks.",
                    "danger"
                )
                return render_template(
                    "edit_marks.html",
                    mark=mark
                )

            if exam_date:
                try:
                    date.fromisoformat(exam_date)
                except ValueError:
                    flash("Enter a valid exam date.", "danger")
                    return render_template(
                        "edit_marks.html",
                        mark=mark
                    )

            # IMPORTANT:
            # Use the actual database column names:
            # marks, total_marks, and created_at.
            cursor.execute("""
                UPDATE marks
                SET
                    exam_name = %s,
                    marks = %s,
                    total_marks = %s,
                    created_at = COALESCE(%s, created_at)
                WHERE id = %s
            """, (
                exam_name,
                obtained,
                maximum,
                exam_date,
                mark_id
            ))

            connection.commit()

            flash("Marks updated successfully.", "success")
            return redirect(url_for("marks"))

        return render_template(
            "edit_marks.html",
            mark=mark
        )

    except mysql.connector.Error as e:

        if connection is not None:
            connection.rollback()

        print("EDIT MARKS DATABASE ERROR:", e, flush=True)

        flash(
            "Unable to update marks. Please check the database structure.",
            "danger"
        )

        return redirect(url_for("marks"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()




@app.route("/admin/marks/delete/<int:mark_id>", methods=["POST"])
def delete_marks(mark_id: int):
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = get_tuple_cursor(connection)

        cursor.execute("DELETE FROM marks WHERE id = %s", (mark_id,))
        connection.commit()

        if cursor.rowcount:
            flash("Marks deleted successfully.", "success")
        else:
            flash("Marks record not found.", "warning")

    except mysql.connector.Error as e:
        print("DATABASE ERROR:", e, flush=True)
        flash("Unable to delete marks.", "danger")

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()

    return redirect(url_for("marks"))


# STUDENT LOGIN

@app.route("/student/login", methods=["GET", "POST"])
def student_login():

    # If student is already logged in
    if "student_id" in session:
        return redirect(url_for("student_dashboard"))

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        # Validation
        if not username or not password:

            flash(
                "Username and password are required.",
                "danger"
            )

            return render_template(
                "student_login.html"
            )

        connection = None
        cursor = None

        try:

            connection = get_db_connection()

            cursor = get_dictionary_cursor(connection)

            cursor.execute("""
                SELECT
                    id,
                    student_id,
                    first_name,
                    last_name,
                    username,
                    password
                FROM students
                WHERE username = %s
                LIMIT 1
            """, (username,))

            student = cursor.fetchone()

            password_matches, legacy_password = verify_stored_password(
                student.get("password") if student else None,
                password
            )
            if student is not None and password_matches and legacy_password:
                cursor.execute(
                    "UPDATE students SET password = %s WHERE id = %s",
                    (generate_password_hash(password), student["id"])
                )
                connection.commit()

            if student is not None and password_matches:
                session.clear()
                session["student_id"] = student["id"]
                session["student_username"] = student["username"]
                session["student_code"] = student["student_id"]

                flash("Student login successful!", "success")
                return redirect(url_for("student_dashboard"))

            flash("Invalid username or password.", "danger")

        except DatabaseConfigurationError as error:
            flash(str(error), "danger")
            return render_template("student_login.html"), 503

        except mysql.connector.Error as error:
            app.logger.error(
                "Student login database request failed (errno=%s, sqlstate=%s)",
                error.errno,
                error.sqlstate
            )
            flash(
                "Unable to access the database. Verify its configuration and availability.",
                "danger"
            )
            return render_template("student_login.html"), 503

        finally:

            if cursor is not None:
                cursor.close()

            if connection is not None and connection.is_connected():
                connection.close()

    return render_template(
        "student_login.html"
    )


# STUDENT DASHBOARD

@app.route("/student/dashboard")
def student_dashboard():

    # Check student login
    if "student_id" not in session:
        flash(
            "Please login as student first.",
            "warning"
        )
        return redirect(url_for("student_login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = get_dictionary_cursor(connection)

        # -------------------------------------------------
        # 1. Get logged-in student's profile
        # -------------------------------------------------
        cursor.execute("""
            SELECT
                s.id,
                s.student_id,
                s.first_name,
                s.last_name,
                s.email,
                s.phone,
                s.gender,
                s.date_of_birth,
                s.address,
                s.city,
                s.semester,
                s.admission_date,
                s.username,
                d.department_name,
                c.course_name
            FROM students s
            LEFT JOIN departments d
                ON s.department_id = d.id
            LEFT JOIN courses c
                ON s.course_id = c.id
            WHERE s.id = %s
        """, (session["student_id"],))

        student = cursor.fetchone()

        if student is None:
            session.clear()
            flash(
                "Student account not found.",
                "danger"
            )
            return redirect(url_for("student_login"))

        # -------------------------------------------------
        # 2. Get attendance summary for this student
        # -------------------------------------------------
        cursor.execute("""
            SELECT
                sub.id AS subject_id,
                sub.subject_name,
                sub.subject_code,

                COUNT(a.id) AS total_classes,

                COALESCE(
                    SUM(
                        CASE
                            WHEN a.status = 'Present'
                            THEN 1
                            ELSE 0
                        END
                    ), 0
                ) AS present_classes,

                COALESCE(
                    SUM(
                        CASE
                            WHEN a.status = 'Absent'
                            THEN 1
                            ELSE 0
                        END
                    ), 0
                ) AS absent_classes,

                ROUND(
                    100.0 * SUM(
                        CASE
                            WHEN a.status = 'Present'
                            THEN 1
                            ELSE 0
                        END
                    ) / NULLIF(COUNT(a.id), 0),
                    2
                ) AS attendance_percentage

            FROM subjects sub

            LEFT JOIN attendance a
                ON a.subject_id = sub.id
                AND a.student_id = %s

            WHERE sub.course_id = (
                SELECT course_id
                FROM students
                WHERE id = %s
            )

            GROUP BY
                sub.id,
                sub.subject_name,
                sub.subject_code

            ORDER BY sub.subject_name
        """, (
            session["student_id"],
            session["student_id"]
        ))

        attendance_summary = cursor.fetchall()

        # -------------------------------------------------
        # 3. Calculate overall attendance percentage
        # -------------------------------------------------
        total_classes = sum(
            int(item["total_classes"] or 0)
            for item in attendance_summary
        )

        present_classes = sum(
            int(item["present_classes"] or 0)
            for item in attendance_summary
        )

        absent_classes = sum(
            int(item["absent_classes"] or 0)
            for item in attendance_summary
        )

        if total_classes > 0:
            overall_attendance = round(
                (present_classes / total_classes) * 100,
                2
            )
        else:
            overall_attendance = 0

        # -------------------------------------------------
        # 4. Display student dashboard
        # -------------------------------------------------
        return render_template(
            "student_dashboard.html",
            student=student,
            attendance_summary=attendance_summary,
            total_classes=total_classes,
            present_classes=present_classes,
            absent_classes=absent_classes,
            overall_attendance=overall_attendance
        )

    except mysql.connector.Error as e:
        print(
            "STUDENT DASHBOARD DATABASE ERROR:",
            e,
            flush=True
        )

        flash(
            "Unable to load dashboard data. Please try again.",
            "danger"
        )

        return redirect(url_for("student_login"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":

    print(
        "Starting Student Management System...",
        flush=True
    )

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=False
    )