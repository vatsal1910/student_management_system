-- 1. Create Database
CREATE DATABASE IF NOT EXISTS student_management_system;


-- 2. Select Database
USE student_management_system;


-- 3. ADMINS TABLE
CREATE TABLE IF NOT EXISTS admins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- 4. DEPARTMENTS TABLE
CREATE TABLE IF NOT EXISTS departments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    department_name VARCHAR(100) NOT NULL UNIQUE,
    description VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- 5. COURSES TABLE
CREATE TABLE IF NOT EXISTS courses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    course_name VARCHAR(100) NOT NULL,
    course_code VARCHAR(50) NOT NULL UNIQUE,
    department_id INT NOT NULL,
    duration_years INT NOT NULL DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_course_department
        FOREIGN KEY (department_id)
        REFERENCES departments(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);


-- 6. SUBJECTS TABLE
CREATE TABLE IF NOT EXISTS subjects (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject_name VARCHAR(100) NOT NULL,
    subject_code VARCHAR(50) NOT NULL UNIQUE,
    course_id INT NOT NULL,
    semester INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_subject_course
        FOREIGN KEY (course_id)
        REFERENCES courses(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);


-- 7. STUDENTS TABLE
CREATE TABLE IF NOT EXISTS students (
    id INT AUTO_INCREMENT PRIMARY KEY,

    student_id VARCHAR(50) NOT NULL UNIQUE,

    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,

    email VARCHAR(100) NOT NULL UNIQUE,
    phone VARCHAR(20) UNIQUE,

    date_of_birth DATE,
    gender ENUM('Male', 'Female', 'Other'),

    address VARCHAR(255),
    city VARCHAR(100),

    department_id INT NOT NULL,
    course_id INT NOT NULL,

    semester INT NOT NULL DEFAULT 1,

    admission_date DATE NOT NULL,

    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_student_department
        FOREIGN KEY (department_id)
        REFERENCES departments(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_student_course
        FOREIGN KEY (course_id)
        REFERENCES courses(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);


-- 8. ENROLLMENTS TABLE
CREATE TABLE IF NOT EXISTS enrollments (
    id INT AUTO_INCREMENT PRIMARY KEY,

    student_id INT NOT NULL,
    course_id INT NOT NULL,

    enrollment_date DATE NOT NULL,

    status ENUM('Active', 'Completed', 'Dropped')
        DEFAULT 'Active',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_enrollment_student
        FOREIGN KEY (student_id)
        REFERENCES students(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    CONSTRAINT fk_enrollment_course
        FOREIGN KEY (course_id)
        REFERENCES courses(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    UNIQUE(student_id, course_id)
);


-- 9. ATTENDANCE TABLE
CREATE TABLE IF NOT EXISTS attendance (
    id INT AUTO_INCREMENT PRIMARY KEY,

    student_id INT NOT NULL,
    subject_id INT NOT NULL,

    attendance_date DATE NOT NULL,

    status ENUM('Present', 'Absent') NOT NULL DEFAULT 'Present',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_attendance_student
        FOREIGN KEY (student_id)
        REFERENCES students(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    CONSTRAINT fk_attendance_subject
        FOREIGN KEY (subject_id)
        REFERENCES subjects(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    UNIQUE(student_id, subject_id, attendance_date)
);


-- 10. MARKS TABLE
CREATE TABLE IF NOT EXISTS marks (
    id INT AUTO_INCREMENT PRIMARY KEY,

    student_id INT NOT NULL,
    subject_id INT NOT NULL,

    exam_name VARCHAR(100) NOT NULL,

    marks DECIMAL(5,2) NOT NULL,

    total_marks DECIMAL(5,2) NOT NULL DEFAULT 100,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_marks_student
        FOREIGN KEY (student_id)
        REFERENCES students(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    CONSTRAINT fk_marks_subject
        FOREIGN KEY (subject_id)
        REFERENCES subjects(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    UNIQUE(student_id, subject_id, exam_name)
);


-- SAMPLE ADMIN

INSERT INTO admins
(username, email, password)
VALUES
('admin', 'admin@gmail.com', 'admin123');


-- SAMPLE DEPARTMENTS

INSERT INTO departments
(department_name, description)
VALUES
('Computer Science', 'Computer Science and Programming'),
('Information Technology', 'Information Technology and Software Development'),
('Commerce', 'Business and Commerce Studies');


-- SAMPLE COURSES

INSERT INTO courses
(course_name, course_code, department_id, duration_years)
VALUES
('Bachelor of Computer Applications', 'BCA', 1, 3),
('Bachelor of Science IT', 'BSCIT', 2, 3),
('Bachelor of Commerce', 'BCOM', 3, 3);


-- SAMPLE SUBJECTS

INSERT INTO subjects
(subject_name, subject_code, course_id, semester)
VALUES
('Programming in C', 'BCA101', 1, 1),
('Database Management System', 'BCA102', 1, 1),
('Web Development', 'BCA103', 1, 2),
('Computer Networks', 'BCA104', 1, 2),

('Information Technology Fundamentals', 'IT101', 2, 1),
('Web Technology', 'IT102', 2, 1),

('Financial Accounting', 'BCOM101', 3, 1),
('Business Economics', 'BCOM102', 3, 1);


-- SAMPLE STUDENTS

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
    'STU001',
    'Rahul',
    'Patel',
    'rahul@gmail.com',
    '9876543210',
    '2004-05-15',
    'Male',
    'Ahmedabad',
    'Ahmedabad',
    1,
    1,
    1,
    '2026-06-15',
    'rahul',
    'student123'
),
(
    'STU002',
    'Priya',
    'Shah',
    'priya@gmail.com',
    '9876543211',
    '2005-02-20',
    'Female',
    'Surat',
    'Surat',
    2,
    2,
    1,
    '2026-06-16',
    'priya',
    'student123'
);


-- SAMPLE ENROLLMENTS
INSERT INTO enrollments
(student_id, course_id, enrollment_date, status)
VALUES
(1, 1, '2026-06-15', 'Active'),
(2, 2, '2026-06-16', 'Active');


-- SAMPLE ATTENDANCE
INSERT INTO attendance
(student_id, subject_id, attendance_date, status)
VALUES
(1, 1, '2026-07-01', 'Present'),
(1, 1, '2026-07-02', 'Present'),
(1, 1, '2026-07-03', 'Absent'),

(1, 2, '2026-07-01', 'Present'),
(1, 2, '2026-07-02', 'Present'),

(2, 5, '2026-07-01', 'Present'),
(2, 5, '2026-07-02', 'Absent');


-- SAMPLE MARKS
INSERT INTO marks
(student_id, subject_id, exam_name, marks, total_marks)
VALUES
(1, 1, 'Internal Exam', 85, 100),
(1, 2, 'Internal Exam', 78, 100),

(2, 5, 'Internal Exam', 88, 100);


-- DATABASE COMPLETED
SELECT
    s.student_id,
    CONCAT(s.first_name, ' ', s.last_name) AS student_name,
    d.department_name,
    c.course_name
FROM students s
JOIN departments d
    ON s.department_id = d.id
JOIN courses c
    ON s.course_id = c.id;
    
UPDATE admins
SET password = '32768:8:1$XSdxfnEH3LfLY9d1$86d0d0a065b657a1d933b9eeaef0ebbeb3125f8fcc24c4aa5eb9eca5142aaeec123e6910e96ae05647c201918d499f0dbcd99fc0748c74212539e937457866d5'
WHERE username = 'admin';

SELECT username, email, password
FROM admins;

SELECT id, username, email, password
FROM admins;


UPDATE admins
SET password = 'scrypt:32768:8:1$ax0IwpUVG7AahLaT$0f59b6a9e9314409226f434ac4cc633952acfab36d3afa015ae4907ff220b2cefff0f1396984c69d9c24652a790b0d0b0f587dd23c0cf59ebaaa66ca3068fb66'
WHERE username = 'admin';

SELECT username, email, password
FROM admins
WHERE username = 'admin';

SELECT
    c.id,
    c.course_name,
    c.department_id,
    d.department_name
FROM courses c
LEFT JOIN departments d
ON c.department_id = d.id;

SELECT
    id,
    student_id,
    first_name,
    last_name,
    username,
    password
FROM students;