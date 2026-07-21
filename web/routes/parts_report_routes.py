"""Parts usage reporting."""
import io
import csv
from datetime import timezone, datetime, timedelta
from flask import Blueprint, render_template, request, Response
from flask_login import login_required, current_user
from sqlalchemy import desc

from models.database import get_session
from models.job_material import JobMaterial
from models.part import Part
from models.job import Job
from models.user import User
from models.division import Division
from web.auth import role_required

parts_reports_bp = Blueprint('parts_reports', __name__, url_prefix='/reports/parts')


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


def _get_date_range():
    date_from_str = request.args.get('date_from', '')
    date_to_str = request.args.get('date_to', '')

    if date_from_str:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d')
    else:
        date_from = datetime.now(timezone.utc) - timedelta(days=30)
        date_from_str = date_from.strftime('%Y-%m-%d')

    if date_to_str:
        date_to = datetime.strptime(date_to_str + ' 23:59:59', '%Y-%m-%d %H:%M:%S')
    else:
        date_to = datetime.now(timezone.utc)
        date_to_str = date_to.strftime('%Y-%m-%d')

    return date_from, date_to, date_from_str, date_to_str


@parts_reports_bp.route('/usage')
@login_required
@role_required('admin', 'owner', 'dispatcher')
def parts_usage():
    db = get_session()
    try:
        date_from, date_to, date_from_str, date_to_str = _get_date_range()

        materials = db.query(JobMaterial).filter(
            JobMaterial.added_at >= date_from,
            JobMaterial.added_at <= date_to,
            JobMaterial.quantity > 0,
        ).all()

        # By Part
        by_part = {}
        for m in materials:
            key = m.part_id or f'custom_{m.id}'
            if key not in by_part:
                by_part[key] = {
                    'part_id': m.part_id,
                    'name': m.display_name,
                    'part_number': m.part.part_number if m.part else '—',
                    'unit': m.unit_of_measure or '',
                    'total_qty': 0, 'total_cost': 0, 'total_sell': 0,
                    'job_count': set(),
                }
            by_part[key]['total_qty'] += float(m.quantity)
            by_part[key]['total_cost'] += float(m.total_cost or 0)
            by_part[key]['total_sell'] += float(m.total_sell or 0)
            by_part[key]['job_count'].add(m.job_id)
        for v in by_part.values():
            v['job_count'] = len(v['job_count'])
        by_part_list = sorted(by_part.values(), key=lambda x: x['total_cost'], reverse=True)

        # By Job
        by_job = {}
        for m in materials:
            jid = m.job_id
            if jid not in by_job:
                by_job[jid] = {
                    'job_id': jid,
                    'job_title': m.job.title if m.job else f'Job #{jid}',
                    'job_number': m.job.job_number if m.job else '',
                    'total_cost': 0, 'total_sell': 0, 'item_count': 0,
                }
            by_job[jid]['total_cost'] += float(m.total_cost or 0)
            by_job[jid]['total_sell'] += float(m.total_sell or 0)
            by_job[jid]['item_count'] += 1
        by_job_list = sorted(by_job.values(), key=lambda x: x['total_cost'], reverse=True)[:20]

        # By Tech (added_by user)
        by_tech = {}
        for m in materials:
            uid = m.added_by
            if uid not in by_tech:
                user = m.added_by_user
                by_tech[uid] = {
                    'user_id': uid,
                    'name': user.full_name if user else f'User #{uid}',
                    'total_cost': 0, 'total_sell': 0, 'item_count': 0,
                }
            by_tech[uid]['total_cost'] += float(m.total_cost or 0)
            by_tech[uid]['total_sell'] += float(m.total_sell or 0)
            by_tech[uid]['item_count'] += 1
        by_tech_list = sorted(by_tech.values(), key=lambda x: x['total_cost'], reverse=True)

        # Totals
        totals = {
            'total_cost': round(sum(float(m.total_cost or 0) for m in materials), 2),
            'total_sell': round(sum(float(m.total_sell or 0) for m in materials if m.is_billable), 2),
            'item_count': len(materials),
            'unique_parts': len(set(m.part_id for m in materials if m.part_id)),
        }
        totals['margin'] = round(totals['total_sell'] - totals['total_cost'], 2)

        return render_template('reports/parts_usage.html',
            active_page='reports', user=current_user, divisions=_get_divisions(),
            by_part=by_part_list, by_job=by_job_list, by_tech=by_tech_list,
            totals=totals, date_from=date_from_str, date_to=date_to_str,
        )
    finally:
        db.close()


@parts_reports_bp.route('/usage/export')
@login_required
@role_required('admin', 'owner')
def export_parts_usage():
    db = get_session()
    try:
        date_from, date_to, _, _ = _get_date_range()

        materials = db.query(JobMaterial).filter(
            JobMaterial.added_at >= date_from,
            JobMaterial.added_at <= date_to,
            JobMaterial.quantity > 0,
        ).order_by(desc(JobMaterial.added_at)).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Date', 'Job #', 'Job Title', 'Part Number', 'Part Name',
            'Quantity', 'Unit', 'Unit Cost', 'Sell Price/Unit',
            'Total Cost', 'Total Sell', 'Billable', 'Status', 'Source', 'Added By',
        ])
        for m in materials:
            writer.writerow([
                m.added_at.strftime('%Y-%m-%d') if m.added_at else '',
                m.job.job_number if m.job else '', m.job.title if m.job else '',
                m.part.part_number if m.part else '', m.display_name,
                float(m.quantity), m.unit_of_measure or '',
                float(m.unit_cost or 0), float(m.sell_price_per_unit or 0),
                float(m.total_cost or 0), float(m.total_sell or 0),
                'Yes' if m.is_billable else 'No', m.status,
                m.source_location.name if m.source_location else 'On-site',
                m.added_by_user.full_name if m.added_by_user else '',
            ])

        return Response(
            output.getvalue(), mimetype='text/csv',
            headers={'Content-Disposition': f'attachment;filename=parts_usage_{date_from.strftime("%Y%m%d")}_{date_to.strftime("%Y%m%d")}.csv'},
        )
    finally:
        db.close()
