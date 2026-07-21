#!/usr/bin/env python3
"""Seed: RFIs, Submittals, Punch Lists, Daily Logs."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, datetime, timedelta
from models.database import get_session
from models.rfi import RFI
from models.submittal import Submittal
from models.punch_list import PunchList, PunchListItem
from models.daily_log import DailyLog
from models.project import Project
from models.user import User
from models.technician import Technician


def seed():
    db = get_session()
    try:
        projects = db.query(Project).all()
        users = db.query(User).all()
        technicians = db.query(Technician).filter_by(is_active=True).all()

        if not projects:
            print("No projects found. Run seed_projects.py first.")
            return
        if not users:
            print("No users found.")
            return

        admin = next((u for u in users if u.role in ('admin', 'owner')), users[0])
        dispatcher = next((u for u in users if u.role == 'dispatcher'), admin)
        proj1 = projects[0]
        proj2 = projects[1] if len(projects) > 1 else proj1
        today = date.today()

        # ── RFIs ──────────────────────────────────────────────────────────
        existing_rfis = db.query(RFI).count()
        if existing_rfis == 0:
            rfis = [
                RFI(rfi_number='RFI-001', project_id=proj1.id,
                    subject='Pipe routing conflict at column B3',
                    question='Mechanical drawings show 4" supply line through structural column at grid B3. Column cannot be penetrated. How should supply be rerouted?',
                    context='Discovered during rough-in inspection. Cannot proceed with mechanical rough-in floors 3-5.',
                    reference='Drawing M-201 / S-201 Detail 4',
                    submitted_by_id=admin.id, assigned_to_id=dispatcher.id,
                    directed_to='Smith & Associates Architects',
                    status='open', priority='high',
                    date_submitted=today - timedelta(days=3),
                    date_required=today + timedelta(days=7),
                    cost_impact='potential', cost_impact_amount=4500.00,
                    schedule_impact='potential', schedule_impact_days=3),
                RFI(rfi_number='RFI-002', project_id=proj1.id,
                    subject='Electrical panel location clarification',
                    question='Drawing E-104 shows panel on west wall, but M-115 shows HVAC equipment there. Which takes precedence?',
                    reference='Drawings E-104, M-115',
                    submitted_by_id=admin.id, assigned_to_id=admin.id,
                    status='answered', priority='normal',
                    date_submitted=today - timedelta(days=10),
                    response='Move panel to east wall per revised E-104 Rev 2.',
                    responded_by_id=admin.id, responded_by_external='Jane Doe, PE',
                    response_date=datetime.utcnow() - timedelta(days=7),
                    cost_impact='none', schedule_impact='none'),
                RFI(rfi_number='RFI-001', project_id=proj2.id,
                    subject='HVAC duct clearance above drop ceiling',
                    question='Spec requires 3" clearance between ductwork and ceiling grid. Only 2.25" available in corridor C. Can we use flat oval duct?',
                    reference='Spec 23 31 00, Drawing M-305',
                    submitted_by_id=admin.id,
                    directed_to='Mechanical Engineer',
                    status='pending_response', priority='normal',
                    date_submitted=today - timedelta(days=5),
                    date_required=today + timedelta(days=2),
                    cost_impact='potential', schedule_impact='none'),
                RFI(rfi_number='RFI-003', project_id=proj1.id,
                    subject='Fire rating specification for corridor walls',
                    question='Spec calls for 2-hour fire rated walls. Is 1 layer 5/8" Type X each side sufficient?',
                    submitted_by_id=dispatcher.id, assigned_to_id=admin.id,
                    status='closed', priority='normal',
                    date_submitted=today - timedelta(days=15),
                    response='Assembly is correct. Blocking only required for walls over 14ft. Proceed as drawn.',
                    responded_by_id=admin.id,
                    response_date=datetime.utcnow() - timedelta(days=13),
                    cost_impact='none', schedule_impact='none'),
                RFI(rfi_number='RFI-002', project_id=proj2.id,
                    subject='Loading dock door motor specification',
                    question='Drawing A-401 shows 12x12 dock door but no motor spec.',
                    submitted_by_id=dispatcher.id,
                    status='draft', priority='low',
                    date_submitted=today, cost_impact='none', schedule_impact='none'),
            ]
            for rfi in rfis:
                db.add(rfi)
            db.flush()
            print(f"  [OK] Created {len(rfis)} RFIs")
        else:
            print(f"  [SKIP] RFIs exist ({existing_rfis})")

        # ── Submittals ────────────────────────────────────────────────────
        existing_subs = db.query(Submittal).count()
        if existing_subs == 0:
            subs = [
                Submittal(submittal_number='SUB-001', project_id=proj1.id,
                    title='Carrier 25HCB660A003 Condensing Unit',
                    spec_section='23 81 26', submittal_type='product_data',
                    manufacturer='Carrier', model_number='25HCB660A003',
                    quantity=6, unit_cost=2850.00, total_cost=17100.00,
                    submitted_by_id=admin.id, submitted_to='Architect of Record',
                    reviewer_name='Tom Baker, AIA',
                    status='approved',
                    date_submitted=today - timedelta(days=30),
                    date_reviewed=today - timedelta(days=22),
                    lead_time_days=21, delivery_date=today + timedelta(days=10)),
                Submittal(submittal_number='SUB-001', project_id=proj2.id,
                    title='200A Siemens Main Electrical Panel',
                    spec_section='26 24 16', submittal_type='product_data',
                    manufacturer='Siemens', model_number='P3200L3200CU',
                    quantity=1, unit_cost=1200.00, total_cost=1200.00,
                    submitted_by_id=admin.id, submitted_to='Electrical Engineer',
                    status='approved_as_noted',
                    review_comments='Verify bus rating matches spec. Submit documentation prior to install.',
                    date_submitted=today - timedelta(days=14),
                    date_reviewed=today - timedelta(days=9),
                    lead_time_days=14, delivery_date=today + timedelta(days=7)),
                Submittal(submittal_number='SUB-002', project_id=proj1.id,
                    title='Copper Pipe - Type L Supply',
                    spec_section='22 11 16', submittal_type='product_data',
                    manufacturer='Mueller Industries',
                    submitted_by_id=admin.id, submitted_to='Plumbing Engineer',
                    status='under_review',
                    date_submitted=today - timedelta(days=4),
                    date_required=today + timedelta(days=10), lead_time_days=5),
                Submittal(submittal_number='SUB-003', project_id=proj1.id,
                    title='Shop Drawing - Mechanical Room Layout',
                    submittal_type='shop_drawing',
                    submitted_by_id=admin.id,
                    submitted_to='Mechanical Engineer',
                    status='revise_and_resubmit',
                    review_comments='Clearance around boiler insufficient. Code requires 24" service side. Revise and resubmit.',
                    date_submitted=today - timedelta(days=12),
                    date_reviewed=today - timedelta(days=8)),
            ]
            for sub in subs:
                db.add(sub)
            db.flush()
            print(f"  [OK] Created {len(subs)} submittals")
        else:
            print(f"  [SKIP] Submittals exist ({existing_subs})")

        # ── Punch List ────────────────────────────────────────────────────
        existing_pl = db.query(PunchList).count()
        if existing_pl == 0:
            pl = PunchList(
                punch_list_number=PunchList.next_number(db),
                project_id=proj1.id,
                title=f'Pre-Completion Walkthrough - {proj1.title}',
                description='Final walkthrough items from owner and architect review',
                inspection_date=today - timedelta(weeks=1),
                inspected_by='Michael Torres (Owner Rep)',
                status='in_progress',
                due_date=today + timedelta(weeks=2),
                created_by_id=admin.id,
            )
            db.add(pl)
            db.flush()

            tech1 = technicians[0] if technicians else None
            tech2 = technicians[1] if len(technicians) > 1 else tech1
            tech3 = technicians[2] if len(technicians) > 2 else tech1

            items = [
                dict(item_number=1, location='Unit 302 Hallway', description='Paint touch-up needed - scuffs from delivery',
                     category='cosmetic', severity='minor', trade='painting', status='verified',
                     completed_date=today-timedelta(days=4), verified_by_id=admin.id, verified_date=today-timedelta(days=3),
                     assigned_to_id=tech1.id if tech1 else None, sort_order=1),
                dict(item_number=2, location='Unit 305 Kitchen', description='Outlet cover plate missing on south wall',
                     category='incomplete', severity='minor', trade='electrical', status='verified',
                     completed_date=today-timedelta(days=5), verified_by_id=admin.id, verified_date=today-timedelta(days=4),
                     assigned_to_id=tech2.id if tech2 else None, sort_order=2),
                dict(item_number=3, location='Unit 301 Living Room', description='Thermostat not plumb - off-level ~3 degrees',
                     category='cosmetic', severity='minor', trade='hvac', status='assigned',
                     assigned_to_id=tech1.id if tech1 else None, sort_order=3),
                dict(item_number=4, location='Unit 304 Master Bath', description='Slow drain - 45 sec to clear after 30 sec running',
                     category='functional', severity='moderate', trade='plumbing', status='in_progress',
                     assigned_to_id=tech3.id if tech3 else None, sort_order=4),
                dict(item_number=5, location='Unit 303 Entry', description='Scuff marks on LVP flooring ~3 sq ft',
                     category='cosmetic', severity='minor', trade='flooring', status='open', sort_order=5),
                dict(item_number=6, location='Unit 306 Bathroom', description='GFCI outlet does not trip - possible wiring issue',
                     category='safety', severity='critical', trade='electrical', status='assigned',
                     assigned_to_id=tech2.id if tech2 else None, sort_order=6),
                dict(item_number=7, location='Unit 302 Kitchen', description='Cabinet door alignment - drops 3/8" when opened',
                     category='cosmetic', severity='minor', trade='general', status='verified',
                     completed_date=today-timedelta(days=3), verified_by_id=admin.id, verified_date=today-timedelta(days=2),
                     assigned_to_id=tech1.id if tech1 else None, sort_order=7),
                dict(item_number=8, location='Unit 305 Bathroom', description='Grout missing ~6" between floor tile and tub surround',
                     category='incomplete', severity='moderate', trade='general', status='open', sort_order=8),
                dict(item_number=9, location='Unit 301 Bedroom', description='Light fixture flickering - possible loose connection',
                     category='functional', severity='moderate', trade='electrical', status='assigned',
                     assigned_to_id=tech2.id if tech2 else None, sort_order=9),
                dict(item_number=10, location='Unit 304 Bathroom', description='Caulking gap at tub surround ~3/8"',
                     category='cosmetic', severity='minor', trade='plumbing', status='deferred',
                     notes='Client accepted as-is. Will address in Phase 3.',
                     assigned_to_id=tech3.id if tech3 else None, sort_order=10),
            ]
            for data in items:
                db.add(PunchListItem(punch_list_id=pl.id, **data))
            db.flush()
            print(f"  [OK] Created punch list with {len(items)} items")
        else:
            print(f"  [SKIP] Punch lists exist ({existing_pl})")

        # ── Daily Logs ────────────────────────────────────────────────────
        existing_logs = db.query(DailyLog).count()
        if existing_logs == 0:
            business_days = []
            check = today
            while len(business_days) < 5:
                if check.weekday() < 5:
                    business_days.append(check)
                check -= timedelta(days=1)
            business_days.reverse()

            logs = [
                dict(log_date=business_days[0], weather='Sunny, 65F', temperature_high=65, temperature_low=48,
                     weather_impact='none', total_workers=8, hours_worked=64,
                     crew_on_site=json.dumps([{'trade':'plumbing','count':3,'names':'Dave M., Ryan P., Alex N.'},{'trade':'electrical','count':3,'names':'James T., Chris B., Pat W.'},{'trade':'general','count':2,'names':'Mike K., Steve L.'}]),
                     work_description='Electrical rough-in units 305-308. Plumbing rough-in units 309-310. Framing inspection prep.',
                     areas_worked='Units 305-310, 3rd floor', status='reviewed'),
                dict(log_date=business_days[1], weather='Partly Cloudy, 58F', temperature_high=58, temperature_low=44,
                     weather_impact='none', total_workers=10, hours_worked=80,
                     crew_on_site=json.dumps([{'trade':'plumbing','count':3,'names':''},{'trade':'electrical','count':4,'names':''},{'trade':'hvac','count':2,'names':''},{'trade':'general','count':1,'names':''}]),
                     work_description='Completed electrical rough-in units 305-306. Started HVAC ductwork units 301-304.',
                     milestones_reached='Electrical rough-in complete Units 305-306', status='reviewed'),
                dict(log_date=business_days[2], weather='Rain, 50F', temperature_high=50, temperature_low=43,
                     weather_impact='minor_delay', site_conditions='Wet entry points. Site road muddy.',
                     total_workers=6, hours_worked=48,
                     crew_on_site=json.dumps([{'trade':'hvac','count':2,'names':''},{'trade':'plumbing','count':2,'names':''},{'trade':'electrical','count':2,'names':''}]),
                     work_description='Indoor work only. HVAC ductwork units 301-304. Plumbing fixture rough-in 307-308.',
                     delays='Outdoor deliveries postponed due to rain.', status='submitted'),
                dict(log_date=business_days[3], weather='Sunny, 62F', temperature_high=62, temperature_low=46,
                     weather_impact='none', total_workers=9, hours_worked=72,
                     crew_on_site=json.dumps([{'trade':'plumbing','count':3,'names':''},{'trade':'electrical','count':3,'names':''},{'trade':'hvac','count':2,'names':''},{'trade':'general','count':1,'names':''}]),
                     work_description='Plumbing pressure test units 301-305 passed. Electrical panel install unit 301. HVAC ductwork 302-304 complete.',
                     milestones_reached='Plumbing rough-in 100% complete Units 301-305.', status='submitted'),
                dict(log_date=business_days[4], weather='Sunny, 68F', temperature_high=68, temperature_low=52,
                     weather_impact='none', total_workers=7, hours_worked=56,
                     crew_on_site=json.dumps([{'trade':'hvac','count':2,'names':''},{'trade':'electrical','count':3,'names':''},{'trade':'general','count':2,'names':''}]),
                     work_description='HVAC installation units 306-308. Electrical rough-in units 307-310. City mechanical inspection passed.',
                     milestones_reached='Mechanical rough-in inspection passed Units 301-305',
                     visitor_log='City Inspector - mechanical rough-in inspection. PASSED.', status='draft'),
            ]
            for i, data in enumerate(logs):
                db.add(DailyLog(log_number=f'DL-{i+1:03d}', project_id=proj1.id, reported_by_id=admin.id, **data))
            db.flush()
            print(f"  [OK] Created {len(logs)} daily logs")
        else:
            print(f"  [SKIP] Daily logs exist ({existing_logs})")

        db.commit()
        print(f"\nProject management seed complete.")

    except Exception as e:
        db.rollback()
        print(f"Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == '__main__':
    print("Seeding project management data...\n")
    seed()
