#!/usr/bin/env python3
"""Migration: Advanced Reports (Phase 20)
Creates: tech_performance_scores, tech_achievements tables
Run: python migrate_advanced_reports.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import engine
from models.tech_performance import TechPerformanceScore, TechAchievement


def run_migration():
    print('Running Phase 20 Advanced Reports migration...')
    TechPerformanceScore.__table__.create(engine, checkfirst=True)
    print('  Created tech_performance_scores table')
    TechAchievement.__table__.create(engine, checkfirst=True)
    print('  Created tech_achievements table')
    print('Migration complete.')


if __name__ == '__main__':
    run_migration()
