# Legacy Migration & Seed Scripts

These 40 scripts were moved from the repo root on 2026-07-21 as part of Phase 0a cleanup.

## Why archived

- No active code imports or references them
- The app now uses `Base.metadata.create_all()` on startup for schema management
- Demo seeding is handled by `/auth/demo` route in `web/auth.py`
- They cluttered the repo root and confused new contributors

## What they are

### `migrate_*.py` (20 files)
Standalone SQLite migration scripts that manually add columns/tables. Each was run once during development to evolve the schema without Alembic. They are **not idempotent** and should not be re-run.

### `seed_*.py` (20 files)
Standalone scripts that populate the database with demo/development data. Superseded by the `/auth/demo` route which creates a full demo org with realistic data.

## If you need them

These scripts are kept for historical reference. If you need to understand how a particular feature's schema was originally added, check the corresponding `migrate_*.py` file.

**Do not re-run these scripts on an existing database.**
