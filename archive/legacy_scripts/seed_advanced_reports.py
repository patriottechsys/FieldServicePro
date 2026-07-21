#!/usr/bin/env python3
"""Seed: Tech performance scores + achievements for last 3 months.
Run: python seed_advanced_reports.py
"""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta
from models.database import get_session
from models.user import Organization
from models.technician import Technician
from models.tech_performance import TechPerformanceScore, TechAchievement, ACHIEVEMENT_DEFINITIONS


def seed():
    db = get_session()
    try:
        org = db.query(Organization).first()
        if not org:
            print('No organization found.')
            return

        techs = db.query(Technician).filter_by(
            organization_id=org.id, is_active=True,
        ).all()
        if not techs:
            print('No technicians found.')
            return

        print(f'  Found {len(techs)} techs in {org.name}')
        today = date.today()
        profiles = [
            (88, 0.5, 3), (82, 1.2, 4), (75, -0.8, 5), (70, 2.0, 6),
            (65, -1.5, 4), (79, 0.0, 3), (91, 0.3, 2), (68, 3.0, 7),
        ]

        months = []
        for i in range(3, -1, -1):
            m = (today.month - i - 1) % 12 + 1
            y = today.year - ((i + 12 - today.month) // 12)
            months.append(date(y, m, 1))

        for mi, ps in enumerate(months):
            pe = (date(ps.year, ps.month + 1, 1) if ps.month < 12
                  else date(ps.year + 1, 1, 1)) - timedelta(days=1)
            scores = []

            for ti, tech in enumerate(techs):
                base, trend, vol = profiles[ti % len(profiles)]
                score = max(0, min(100, base + trend * mi + random.uniform(-vol, vol)))

                existing = db.query(TechPerformanceScore).filter_by(
                    organization_id=org.id, technician_id=tech.id,
                    period_type='monthly', period_start=ps,
                ).first()
                s = existing or TechPerformanceScore(
                    organization_id=org.id, technician_id=tech.id,
                    period_type='monthly', period_start=ps, period_end=pe,
                )
                if not existing:
                    db.add(s)

                s.overall_score = round(score, 1)
                s.customer_rating_score = round(min(100, max(0, score + random.uniform(-8, 8))), 1)
                s.completion_rate_score = round(min(100, max(0, score + random.uniform(-5, 10))), 1)
                s.callback_rate_score = round(min(100, max(0, score + random.uniform(-10, 15))), 1)
                s.utilization_score = round(min(100, max(0, score + random.uniform(-12, 8))), 1)
                s.revenue_score = round(min(100, max(0, score + random.uniform(-15, 15))), 1)
                s.efficiency_score = round(min(100, max(0, score + random.uniform(-8, 8))), 1)
                s.profitability_score = round(min(100, max(0, score + random.uniform(-10, 10))), 1)
                s.jobs_completed = random.randint(8, 25)
                s.jobs_total = s.jobs_completed + random.randint(0, 2)
                s.total_hours = round(random.uniform(120, 200), 1)
                s.billable_hours = round(s.total_hours * (s.utilization_score / 100), 1)
                s.total_revenue = round(random.uniform(15000, 55000) * (s.revenue_score / 100), 2)
                s.total_callbacks = max(0, int(s.jobs_completed * (1 - s.callback_rate_score / 100) * 0.5))
                s.avg_customer_rating = round(s.customer_rating_score / 100 * 5, 2)
                s.avg_job_margin = round(min(60, max(5, s.profitability_score * 0.5)), 1)
                scores.append(s)

            db.flush()
            scores.sort(key=lambda x: x.overall_score, reverse=True)
            for rank, s in enumerate(scores, 1):
                s.rank = rank
            print(f'  {ps.strftime("%b %Y")}: {len(scores)} scores')

        db.commit()

        # Achievements for current period
        current = months[-1]
        pe = (date(current.year, current.month + 1, 1) if current.month < 12
              else date(current.year + 1, 1, 1)) - timedelta(days=1)
        cur_scores = db.query(TechPerformanceScore).filter_by(
            organization_id=org.id, period_type='monthly', period_start=current,
        ).order_by(TechPerformanceScore.rank).all()

        if cur_scores:
            top_rev = max(cur_scores, key=lambda s: s.total_revenue)
            _award(db, org.id, top_rev.technician_id, 'revenue_king', current, pe)
            top_hrs = max(cur_scores, key=lambda s: s.total_hours)
            _award(db, org.id, top_hrs.technician_id, 'iron_horse', current, pe)
            top_rat = max(cur_scores, key=lambda s: s.avg_customer_rating)
            if top_rat.avg_customer_rating >= 4.5:
                _award(db, org.id, top_rat.technician_id, 'customer_favorite', current, pe)
            for s in cur_scores:
                if s.total_callbacks == 0 and s.jobs_completed >= 3:
                    _award(db, org.id, s.technician_id, 'zero_callbacks', current, pe)

        db.commit()
        print('  Achievements seeded')
        print('\nAdvanced reports seed complete!')
    except Exception as e:
        db.rollback()
        print(f'ERROR: {e}')
        raise
    finally:
        db.close()


def _award(db, org_id, tech_id, atype, ps, pe):
    if db.query(TechAchievement).filter_by(
        organization_id=org_id, technician_id=tech_id,
        achievement_type=atype, period_start=ps,
    ).first():
        return
    d = ACHIEVEMENT_DEFINITIONS[atype]
    db.add(TechAchievement(
        organization_id=org_id, technician_id=tech_id,
        achievement_type=atype, achievement_name=d['name'],
        description=d['description'], icon=d['icon'],
        period_type='monthly', period_start=ps, period_end=pe, notified=True,
    ))
    print(f'    {d["icon"]} {d["name"]} -> tech {tech_id}')


if __name__ == '__main__':
    print('Seeding advanced reports...')
    seed()
