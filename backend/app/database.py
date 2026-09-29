from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def run_schema_migrations():
    """Apply small additive SQLite migrations for existing local demo databases."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(clubs)")}
        added_coordinator_column = bool(columns) and "faculty_coordinator_id" not in columns
        if added_coordinator_column:
            connection.exec_driver_sql(
                "ALTER TABLE clubs ADD COLUMN faculty_coordinator_id INTEGER REFERENCES users(id)"
            )
        certificate_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(certificates)")}
        if certificate_columns and "participation_role" not in certificate_columns:
            connection.exec_driver_sql(
                "ALTER TABLE certificates ADD COLUMN participation_role VARCHAR(64) NOT NULL DEFAULT 'Participant'"
            )
        timetable_columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(timetable_structures)")
        }
        if timetable_columns and "working_days_json" not in timetable_columns:
            connection.exec_driver_sql(
                "ALTER TABLE timetable_structures ADD COLUMN working_days_json TEXT NOT NULL DEFAULT '[0,1,2,3,4]'"
            )
            # Older local databases stored this JSON field under `working_days`.
            if "working_days" in timetable_columns:
                connection.exec_driver_sql(
                    "UPDATE timetable_structures SET working_days_json = working_days "
                    "WHERE working_days IS NOT NULL AND working_days != ''"
                )
        if added_coordinator_column:
            connection.exec_driver_sql(
                "UPDATE clubs SET faculty_coordinator_id = "
                "(SELECT id FROM users WHERE role = 'FACULTY' AND is_active = 1 ORDER BY id LIMIT 1) "
                "WHERE faculty_coordinator_id IS NULL"
            )
        if columns:
            connection.exec_driver_sql(
                "UPDATE users SET ra_number = CASE email "
                "WHEN 'student@college.edu' THEN 'RA2411001001001' "
                "WHEN 'student2@college.edu' THEN 'RA2411001001002' "
                "WHEN 'student3@college.edu' THEN 'RA2411001001003' "
                "ELSE ra_number END "
                "WHERE email IN ('student@college.edu', 'student2@college.edu', 'student3@college.edu') "
                "AND length(ra_number) != 15"
            )
        connection.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS trg_student_ra_insert "
            "BEFORE INSERT ON users WHEN NEW.role = 'STUDENT' AND "
            "(NEW.ra_number IS NULL OR length(NEW.ra_number) != 15 OR NEW.ra_number GLOB '*[^A-Za-z0-9]*') "
            "BEGIN SELECT RAISE(ABORT, 'Student RA Number must contain exactly 15 letters or digits'); END"
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS trg_student_ra_update "
            "BEFORE UPDATE OF role, ra_number ON users WHEN NEW.role = 'STUDENT' AND "
            "(NEW.ra_number IS NULL OR length(NEW.ra_number) != 15 OR NEW.ra_number GLOB '*[^A-Za-z0-9]*') "
            "BEGIN SELECT RAISE(ABORT, 'Student RA Number must contain exactly 15 letters or digits'); END"
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
