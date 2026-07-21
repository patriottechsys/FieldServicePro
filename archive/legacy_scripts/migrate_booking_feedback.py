#!/usr/bin/env python3
"""
Migration: Online Booking additions to service_requests +
           New tables: survey_templates, feedback_surveys
Run: python migrate_booking_feedback.py
"""
import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.environ.get('DATABASE_URL', 'fieldservicepro.db')
if DB_PATH.startswith('sqlite:///'):
    DB_PATH = DB_PATH.replace('sqlite:///', '')


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ── Create survey_templates table ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS survey_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            include_quality BOOLEAN NOT NULL DEFAULT 1,
            include_punctuality BOOLEAN NOT NULL DEFAULT 1,
            include_communication BOOLEAN NOT NULL DEFAULT 1,
            include_professionalism BOOLEAN NOT NULL DEFAULT 1,
            include_value BOOLEAN NOT NULL DEFAULT 1,
            include_nps BOOLEAN NOT NULL DEFAULT 1,
            include_recommend BOOLEAN NOT NULL DEFAULT 1,
            include_comments BOOLEAN NOT NULL DEFAULT 1,
            include_what_went_well BOOLEAN NOT NULL DEFAULT 1,
            include_what_could_improve BOOLEAN NOT NULL DEFAULT 1,
            custom_questions TEXT,
            is_default BOOLEAN NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            created_by INTEGER REFERENCES users(id),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  Ensured survey_templates table")

    # ── Create feedback_surveys table ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback_surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_number VARCHAR(20) UNIQUE NOT NULL,
            job_id INTEGER NOT NULL REFERENCES jobs(id),
            client_id INTEGER NOT NULL REFERENCES clients(id),
            technician_id INTEGER REFERENCES technicians(id),
            template_id INTEGER REFERENCES survey_templates(id),
            overall_rating INTEGER,
            quality_rating INTEGER,
            punctuality_rating INTEGER,
            communication_rating INTEGER,
            professionalism_rating INTEGER,
            value_rating INTEGER,
            comments TEXT,
            would_recommend BOOLEAN,
            what_went_well TEXT,
            what_could_improve TEXT,
            nps_score INTEGER,
            status VARCHAR(20) NOT NULL DEFAULT 'sent',
            sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            opened_at DATETIME,
            completed_at DATETIME,
            token VARCHAR(64) UNIQUE NOT NULL,
            expires_at DATETIME,
            reminder_sent BOOLEAN DEFAULT 0,
            reminder_sent_at DATETIME,
            ip_address VARCHAR(45),
            user_agent VARCHAR(500),
            is_public BOOLEAN DEFAULT 0,
            internal_notes TEXT,
            follow_up_required BOOLEAN DEFAULT 0,
            follow_up_notes TEXT,
            follow_up_completed BOOLEAN DEFAULT 0,
            google_review_link_clicked BOOLEAN DEFAULT 0,
            google_review_clicked_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  Ensured feedback_surveys table")

    # ── Service request additions ──
    sr_cols = [
        ("preferred_dates", "TEXT"),
        ("preferred_time_slot", "VARCHAR(20)"),
        ("referral_source", "VARCHAR(50)"),
        ("access_instructions", "TEXT"),
        ("customer_address", "TEXT"),
        ("street_address", "VARCHAR(200)"),
        ("unit_apt", "VARCHAR(50)"),
        ("city", "VARCHAR(100)"),
        ("state_province", "VARCHAR(100)"),
        ("postal_code", "VARCHAR(20)"),
        ("is_existing_customer", "BOOLEAN DEFAULT 0"),
        ("existing_customer_ref", "VARCHAR(200)"),
        ("confirmation_sent", "BOOLEAN DEFAULT 0"),
        ("confirmation_sent_at", "DATETIME"),
        ("booking_token", "VARCHAR(64)"),
        ("honeypot_check", "BOOLEAN DEFAULT 0"),
        ("submitter_ip", "VARCHAR(45)"),
    ]

    for col, col_type in sr_cols:
        try:
            cursor.execute(f"ALTER TABLE service_requests ADD COLUMN {col} {col_type}")
            print(f"  Added service_requests.{col}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                pass
            else:
                print(f"  Skip service_requests.{col}: {e}")

    # ── Create indexes ──
    indexes = [
        ("ix_feedback_surveys_job_id", "feedback_surveys", "job_id"),
        ("ix_feedback_surveys_client_id", "feedback_surveys", "client_id"),
        ("ix_feedback_surveys_token", "feedback_surveys", "token"),
        ("ix_feedback_surveys_status", "feedback_surveys", "status"),
    ]
    for idx_name, table, col in indexes:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({col})")
        except Exception:
            pass

    conn.commit()
    conn.close()
    print("\nBooking & Feedback migration complete.")


if __name__ == '__main__':
    migrate()
