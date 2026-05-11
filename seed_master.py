#!/usr/bin/env python3
"""
seed_master.py -- Run ALL seed modules against the database in dependency order.

Designed to run ONCE during initial deploy on Render. After that, the
PostgreSQL database persists the data and every subsequent spin-up sees
it already populated.

Each individual seed is idempotent -- safe to re-run if needed.

Usage:
    # Against Render (production) -- typically called from build.sh:
    DATABASE_URL="postgresql://..." python seed_master.py

    # Against local SQLite (default):
    python seed_master.py
"""
import sys
import os
import importlib
import time

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Load .env if present (so DATABASE_URL is picked up)
try:
    from dotenv import load_dotenv
    for envpath in ['.env', os.path.join(os.path.dirname(__file__), '.env')]:
        if os.path.exists(envpath):
            load_dotenv(envpath)
            break
except ImportError:
    pass


# --- Ordered seed modules -------------------------------------------------------
# Dependencies flow top-to-bottom: each module may depend on data from above.
SEED_MODULES = [
    # Layer 0: Core infrastructure (org, users, divisions, clients, techs, jobs)
    # These are assumed to already exist from the app's initial setup.

    # Layer 1: Contracts, SLAs, and commercial scaffolding
    ("seed_contracts",          "SLAs, Contracts, Line Items, Contract Jobs"),
    ("seed_commercial",         "Extended Contracts, POs, Service Requests, Change Orders, "
                                "Payments, Certs, Insurance, Permits, Checklists, "
                                "Lien Waivers, Documents, Equipment"),

    # Layer 2: Commercial invoicing (depends on contracts, clients, POs)
    ("seed_phase3",             "Commercial Invoices, PO Linking, Approval Queue, "
                                "Aging Scenarios"),

    # Layer 3: Projects (depend on clients, divisions, contracts)
    ("seed_projects",           "Projects (3 commercial projects with job links)"),

    # Layer 4: Project management tabs (depend on projects)
    ("seed_project_mgmt",       "RFIs, Submittals, Punch Lists, Daily Logs"),

    # Layer 5: Phases and additional change orders (depend on jobs)
    ("seed_phases_and_cos",     "Job Phases and Change Orders"),

    # Layer 6: Parts catalog and inventory
    ("seed_parts",              "Parts, Inventory Locations, Stock, Job Materials, "
                                "Stock Transfers"),

    # Layer 7: Vendors and supply chain
    ("seed_vendors",            "Vendors, Vendor Pricing, Supplier POs, Vendor Payments"),

    # Layer 8: Warranties and callbacks (depend on completed jobs)
    ("seed_warranty",           "Warranties, Warranty Claims, Callbacks"),

    # Layer 9: Time tracking
    ("seed_time_tracking",      "Time Entries and Active Clocks"),

    # Layer 10: Expenses
    ("seed_expenses",           "Expenses"),

    # Layer 11: Communications
    ("seed_communications",     "Communication Logs and Templates"),

    # Layer 12: Recurring schedules
    ("seed_recurring",          "Recurring Maintenance Schedules"),

    # Layer 13: Vehicles and payroll
    ("seed_vehicles_payroll",   "Vehicle Profiles, Mileage Logs, Fuel Logs"),

    # Layer 14: Feedback and surveys
    ("seed_booking_feedback",   "Survey Templates, Feedback Surveys, Online Bookings"),

    # Layer 15: Notifications
    ("seed_notifications",      "Notifications"),

    # Layer 16: Portal
    ("seed_portal",             "Portal Users and Settings"),

    # Layer 17: Compliance extras
    ("seed_compliance",         "Compliance Data"),

    # Layer 18: Advanced reports / performance
    ("seed_advanced_reports",   "Tech Performance Scores, Achievements, Report Data"),

    # Layer 19: Mobile demo data
    ("seed_mobile_demo",        "Mobile Demo Data"),
]


def _already_seeded(engine):
    """Quick check: if projects and RFIs already exist, seed has already run."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COUNT(*) FROM projects"
            ))
            count = result.scalar()
            return count is not None and count > 0
    except Exception:
        return False


def run_all():
    db_url = os.environ.get('DATABASE_URL', '(local SQLite)')
    # Mask credentials for display
    if 'postgresql' in db_url:
        display_url = db_url.split('@')[-1] if '@' in db_url else db_url
        display_url = "postgresql://***@" + display_url
    else:
        display_url = db_url

    print("=" * 70)
    print("  4MAN Services Pro -- Master Seed Runner")
    print("=" * 70)
    print("  Target DB: " + display_url)
    print("  Modules:   " + str(len(SEED_MODULES)))
    print("=" * 70)

    # Ensure all tables exist first
    print("\n[0/N] Ensuring all tables exist...")
    from models.database import Base, engine, init_db
    try:
        init_db()
        print("  Tables OK.\n")
    except Exception as e:
        print("  WARNING: init_db issue: " + str(e) + "\n")
        Base.metadata.create_all(engine)

    # Skip if data already exists (prevents re-seeding on every deploy)
    if _already_seeded(engine):
        print("  Data already exists in the database (projects table has rows).")
        print("  Skipping seed to avoid duplicates.")
        print("  To force re-seed, drop the projects table or pass --force.\n")
        if '--force' not in sys.argv:
            print("  Done (no changes).")
            return 0
        print("  --force flag detected. Proceeding with seed...\n")

    succeeded = []
    failed = []
    skipped = []

    for i, (module_name, description) in enumerate(SEED_MODULES, 1):
        header = "[%d/%d] %s" % (i, len(SEED_MODULES), module_name)
        print("\n" + "-" * 60)
        print(header)
        print("  " + description)
        print("-" * 60)

        t0 = time.time()
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, 'seed'):
                mod.seed()
                elapsed = time.time() - t0
                print("  [OK] Done (%.1fs)" % elapsed)
                succeeded.append(module_name)
            else:
                print("  [SKIP] No seed() function found")
                skipped.append(module_name)
        except Exception as e:
            elapsed = time.time() - t0
            print("  [FAIL] (%.1fs): %s" % (elapsed, e))
            import traceback
            traceback.print_exc()
            failed.append((module_name, str(e)))

    # -- Summary --
    print("\n" + "=" * 70)
    print("  SEED COMPLETE -- Summary")
    print("=" * 70)
    print("  Succeeded: %d" % len(succeeded))
    if skipped:
        print("  Skipped:   %d (%s)" % (len(skipped), ', '.join(skipped)))
    if failed:
        print("  Failed:    %d" % len(failed))
        for name, err in failed:
            print("    - %s: %s" % (name, err[:80]))
    print("=" * 70)

    if failed:
        print("\n  WARNING: Some seeds failed. Re-run after fixing errors.")
        return 1
    print("\n  All seeds completed successfully.")
    return 0


if __name__ == '__main__':
    sys.exit(run_all())
