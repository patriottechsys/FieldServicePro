"""Database configuration and session management."""

import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # Render (and Heroku) expose postgres:// but SQLAlchemy 2.x requires postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_recycle=300,
        pool_pre_ping=True,
    )
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    os.makedirs(DATA_DIR, exist_ok=True)
    DATABASE_PATH = os.path.join(DATA_DIR, 'fieldservicepro.db')
    DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
    engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_session():
    """Get a new database session."""
    return SessionLocal()


def dispose_engine():
    """Dispose of the engine's connection pool. Call on app shutdown."""
    engine.dispose()


def init_db():
    """Initialize the database, creating all tables."""
    from . import user, division, client, job, quote, invoice, technician, sla, contract, purchase_order, po_attachment, app_settings, settings, job_phase, change_order, document, permit, insurance, certification, checklist, lien_waiver, portal_user, portal_message, portal_notification, portal_settings, service_request, equipment, project, time_entry, part, inventory, job_material, stock_transfer, recurring_schedule, warranty, callback, communication, expense, notification, vehicle_profile, vehicle_mileage_log, vehicle_fuel_log, payroll_period, payroll_line_item, rfi, submittal, punch_list, daily_log, vendor, vendor_price, supplier_po, vendor_payment, restock_request, feedback_survey, tech_performance  # noqa: F401
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error("Failed to initialize database: %s", e)
        raise
