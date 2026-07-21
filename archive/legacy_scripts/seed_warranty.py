#!/usr/bin/env python3
"""Seed data: Warranties, claims, and callbacks."""
import sys, os
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import get_session, Base, engine
from models.warranty import Warranty, WarrantyClaim
from models.callback import Callback
from models.job import Job
from models.client import Client
from models.technician import Technician
from models.user import User


def seed():
    Base.metadata.create_all(engine)
    db = get_session()
    try:
        admin = db.query(User).first()
        if not admin:
            print("No users found.")
            return

        # Check existing
        if db.query(Warranty).count() > 0:
            print(f"Already have {db.query(Warranty).count()} warranties. Skipping.")
            return

        org_id = admin.organization_id
        today = date.today()

        # Get completed jobs
        completed_jobs = db.query(Job).filter(
            Job.organization_id == org_id, Job.status == 'completed'
        ).order_by(Job.id).limit(10).all()

        if len(completed_jobs) < 4:
            print("Need at least 4 completed jobs. Skipping.")
            return

        tech = db.query(Technician).filter_by(is_active=True).first()
        wty_seq = 0
        wcl_seq = 0
        cb_seq = 0
        year = today.year

        def wty_num():
            nonlocal wty_seq; wty_seq += 1; return f"WTY-{year}-{wty_seq:04d}"
        def wcl_num():
            nonlocal wcl_seq; wcl_seq += 1; return f"WCL-{year}-{wcl_seq:04d}"
        def cb_num():
            nonlocal cb_seq; cb_seq += 1; return f"CB-{year}-{cb_seq:04d}"

        # ── 8 WARRANTIES ──────────────────────────────────────────────
        print("[1/3] Creating warranties...")
        warranties = []

        w_data = [
            # (title, type, months, days_ago_start, status, max_claim, serial, model, covers_parts)
            ('Water Heater Installation — 1 Year', 'parts_and_labor', 12, 30, 'active', 500, 'AOS-2026-44821', 'AOS-50-12YR', True),
            ('Furnace Replacement — Extended', 'extended', 24, 60, 'active', None, 'LNX-2026-88821', 'SL280V', True),
            ('Electrical Panel Upgrade 200A', 'labor_only', 12, 45, 'active', None, None, None, False),
            ('Kitchen Stack Repair', 'labor_only', 6, 160, 'expiring_soon', None, None, None, False),
            ('Whole-Home Rewire', 'parts_and_labor', 12, 15, 'active', 2000, None, None, True),
            ('Backflow Preventer Install', 'manufacturer', 60, 20, 'active', None, 'WBF-2026-3312', 'LF007M2', True),
            ('Boiler Annual Service', 'labor_only', 3, 104, 'expired', None, None, None, False),
            ('Curb Stop Assessment Phase 1', 'labor_only', 6, 10, 'active', None, None, None, False),
        ]

        for i, (title, wtype, months, days_start, status, max_claim, serial, model, parts) in enumerate(w_data):
            j = completed_jobs[i % len(completed_jobs)]
            start = today - timedelta(days=days_start)
            end = start + timedelta(days=30 * months)
            # Fix status for expiring_soon / expired
            if status == 'expiring_soon':
                end = today + timedelta(days=20)
            elif status == 'expired':
                end = today - timedelta(days=14)

            w = Warranty(
                warranty_number=wty_num(),
                job_id=j.id, client_id=j.client_id,
                property_id=j.property_id if hasattr(j, 'property_id') else None,
                title=title, warranty_type=wtype,
                start_date=start, end_date=end, duration_months=months,
                status=status, max_claim_value=max_claim, total_claimed=0,
                covers_parts=parts,
                equipment_serial_number=serial, model_number=model,
                created_by=admin.id,
            )
            db.add(w)
            warranties.append(w)
        db.flush()
        print(f"  {len(warranties)} warranties created")

        # ── 2 CLAIMS ─────────────────────────────────────────────────
        print("[2/3] Creating warranty claims...")
        # Claim 1: Against water heater warranty (completed)
        c1 = WarrantyClaim(
            claim_number=wcl_num(), warranty_id=warranties[0].id,
            job_id=completed_jobs[0].id,
            description='Thermostat replacement — temperature fluctuations reported.',
            claim_type='parts', labor_cost=0, parts_cost=85.00,
            status='completed', claimed_date=today - timedelta(days=10),
            resolved_date=today - timedelta(days=5),
            resolution='Replaced thermostat. Temperature now stable.',
            created_by=admin.id,
        )
        db.add(c1)
        warranties[0].total_claimed = 85.00

        # Claim 2: Against panel warranty (open)
        c2 = WarrantyClaim(
            claim_number=wcl_num(), warranty_id=warranties[2].id,
            job_id=completed_jobs[1].id,
            description='Breaker tripping intermittently on 20A kitchen circuit.',
            claim_type='labor', labor_cost=120.00, parts_cost=0,
            status='open', claimed_date=today - timedelta(days=3),
            created_by=admin.id,
        )
        db.add(c2)
        warranties[2].total_claimed = 120.00
        db.flush()
        print("  2 claims created")

        # ── 4 CALLBACKS ──────────────────────────────────────────────
        print("[3/3] Creating callbacks...")

        def make_cb_job(orig_job, title, is_warranty=False, status='completed'):
            j = Job(
                organization_id=org_id,
                job_number=f"CB-JOB-{cb_seq + 1:03d}",
                title=title, client_id=orig_job.client_id,
                division_id=orig_job.division_id,
                status=status, is_callback=True,
                is_warranty_work=is_warranty,
                original_job_id=orig_job.id,
                description=f'Callback for: {orig_job.title}',
                created_by_id=admin.id,
            )
            if hasattr(orig_job, 'property_id'):
                j.property_id = orig_job.property_id
            db.add(j)
            db.flush()
            return j

        cb_data = [
            # (orig_idx, title, reason, severity, status, is_warranty, warranty_idx, resolved_ago, root_cause)
            (0, 'Callback — Furnace Cycling', 'equipment_failure', 'moderate', 'resolved', True, 1, 14,
             'Flame sensor fouled with dust'),
            (1, 'Callback — Slow Drain', 'incomplete_repair', 'minor', 'resolved', False, None, 25,
             'P-trap installed at incorrect slope'),
            (2, 'Callback — Floor Drain Backup', 'recurring_issue', 'moderate', 'in_progress', False, None, None,
             'Root intrusion not fully addressed'),
            (3, 'Callback — Backflow Leaking', 'quality_issue', 'major', 'reported', True, 5, None,
             None),
        ]

        for orig_idx, title, reason, severity, status, is_warranty, w_idx, resolved_ago, root_cause in cb_data:
            orig_job = completed_jobs[orig_idx]
            cb_status = 'in_progress' if status == 'in_progress' else ('scheduled' if status == 'reported' else 'completed')
            cb_job = make_cb_job(orig_job, title, is_warranty, cb_status)

            cb = Callback(
                callback_number=cb_num(),
                original_job_id=orig_job.id, callback_job_id=cb_job.id,
                client_id=orig_job.client_id,
                reason=reason, description=f'{title}: Customer reported issue.',
                severity=severity,
                is_warranty=is_warranty,
                warranty_id=warranties[w_idx].id if w_idx is not None else None,
                is_billable=False,
                root_cause=root_cause,
                responsible_technician_id=tech.id if tech else None,
                status=status,
                reported_date=today - timedelta(days=resolved_ago + 6 if resolved_ago else 5),
                resolved_date=today - timedelta(days=resolved_ago) if resolved_ago else None,
                created_by=admin.id,
            )
            db.add(cb)

        db.commit()
        print(f"  4 callbacks created")

        print(f"\nWarranty seed complete!")
        print(f"  Warranties: {db.query(Warranty).count()}")
        print(f"  Claims: {db.query(WarrantyClaim).count()}")
        print(f"  Callbacks: {db.query(Callback).count()}")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    seed()
