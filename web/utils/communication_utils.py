"""Utility functions for Communication Log module."""
from datetime import timezone, datetime, date, timedelta
from sqlalchemy import func, or_
from models.communication import CommunicationLog, CommunicationTemplate, DIRECTION_MAP


def generate_log_number(db):
    year = datetime.now(timezone.utc).year
    prefix = f"COM-{year}-"
    last = db.query(CommunicationLog).filter(
        CommunicationLog.log_number.like(f"{prefix}%")
    ).order_by(CommunicationLog.id.desc()).first()
    seq = int(last.log_number.split('-')[-1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def derive_direction(comm_type):
    return DIRECTION_MAP.get(comm_type)


def get_communication_stats(db):
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())
    week_start = today_start - timedelta(days=today_start.weekday())

    total_today = db.query(CommunicationLog).filter(
        CommunicationLog.communication_date.between(today_start, today_end)
    ).count()

    follow_ups_overdue = db.query(CommunicationLog).filter(
        CommunicationLog.follow_up_required == True,
        CommunicationLog.follow_up_completed == False,
        CommunicationLog.follow_up_date < date.today()
    ).count()

    follow_ups_due_today = db.query(CommunicationLog).filter(
        CommunicationLog.follow_up_required == True,
        CommunicationLog.follow_up_completed == False,
        CommunicationLog.follow_up_date == date.today()
    ).count()

    escalations_week = db.query(CommunicationLog).filter(
        CommunicationLog.is_escalation == True,
        CommunicationLog.communication_date >= week_start
    ).count()

    total_pending = db.query(CommunicationLog).filter(
        CommunicationLog.follow_up_required == True,
        CommunicationLog.follow_up_completed == False,
    ).count()

    return {
        'total_today': total_today,
        'follow_ups_overdue': follow_ups_overdue,
        'follow_ups_due_today': follow_ups_due_today,
        'escalations_this_week': escalations_week,
        'total_pending_follow_ups': total_pending,
    }


def get_overdue_follow_up_count(db):
    return db.query(CommunicationLog).filter(
        CommunicationLog.follow_up_required == True,
        CommunicationLog.follow_up_completed == False,
        CommunicationLog.follow_up_date < date.today()
    ).count()
