"""Expense utility functions."""
from datetime import timezone, date, datetime
from sqlalchemy import func
from models.expense import Expense


def generate_expense_number(db):
    year = datetime.now(timezone.utc).year
    prefix = f"EXP-{year}-"
    last = db.query(Expense).filter(Expense.expense_number.like(f"{prefix}%")).order_by(Expense.id.desc()).first()
    seq = int(last.expense_number.split('-')[-1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def get_expense_stats(db, user_id=None, role=None):
    today = date.today()
    month_start = today.replace(day=1)

    query = db.query(Expense)
    if role == 'technician' and user_id:
        query = query.filter(Expense.created_by == user_id)

    mtd_total = query.filter(
        Expense.status == 'approved', Expense.expense_date >= month_start
    ).with_entities(func.sum(Expense.total_amount)).scalar() or 0

    pending_count = query.filter(Expense.status == 'submitted').count()
    pending_amount = query.filter(Expense.status == 'submitted').with_entities(func.sum(Expense.total_amount)).scalar() or 0

    reimburse_count = query.filter(
        Expense.status == 'approved', Expense.is_reimbursable == True, Expense.reimbursed_date == None
    ).count()
    reimburse_amount = query.filter(
        Expense.status == 'approved', Expense.is_reimbursable == True, Expense.reimbursed_date == None
    ).with_entities(func.sum(Expense.total_amount)).scalar() or 0

    billable_uninvoiced = query.filter(
        Expense.is_billable == True, Expense.invoiced == False, Expense.status == 'approved'
    ).with_entities(func.sum(Expense.billable_amount)).scalar() or 0

    return {
        'mtd_total': round(float(mtd_total), 2),
        'pending_approval_count': pending_count,
        'pending_approval_amount': round(float(pending_amount), 2),
        'pending_reimbursement_count': reimburse_count,
        'pending_reimbursement_amount': round(float(reimburse_amount), 2),
        'billable_uninvoiced': round(float(billable_uninvoiced), 2),
    }


def get_job_expense_summary(db, job_id):
    rows = db.query(Expense).filter(
        Expense.job_id == job_id, Expense.status.in_(['approved', 'submitted'])
    ).all()
    total = sum(float(e.total_amount or 0) for e in rows)
    by_cat = {}
    for e in rows:
        by_cat[e.expense_category] = by_cat.get(e.expense_category, 0) + float(e.total_amount or 0)
    return {'expenses': rows, 'total': round(total, 2), 'by_category': by_cat, 'count': len(rows)}
