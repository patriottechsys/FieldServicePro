"""Communication Activity Report."""
import csv, io
from datetime import timezone, datetime, date, timedelta
from flask import Blueprint, render_template, request, Response
from flask_login import login_required, current_user
from sqlalchemy import func, desc

from models.database import get_session
from models.communication import CommunicationLog, COMM_TYPES
from models.client import Client
from models.user import User
from models.division import Division
from web.auth import role_required

comm_reports_bp = Blueprint('comm_reports', __name__, url_prefix='/reports/communications')


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


@comm_reports_bp.route('/')
@login_required
@role_required('owner', 'admin', 'dispatcher')
def comm_report():
    db = get_session()
    try:
        # Date range
        df = request.args.get('date_from', '')
        dt = request.args.get('date_to', '')
        try:
            date_from = datetime.strptime(df, '%Y-%m-%d') if df else datetime.now(timezone.utc) - timedelta(days=30)
            date_to = datetime.strptime(dt + ' 23:59:59', '%Y-%m-%d %H:%M:%S') if dt else datetime.now(timezone.utc)
        except ValueError:
            date_from = datetime.now(timezone.utc) - timedelta(days=30)
            date_to = datetime.now(timezone.utc)

        base = db.query(CommunicationLog).filter(
            CommunicationLog.communication_date.between(date_from, date_to)
        )
        total_comms = base.count()

        # By type
        type_data = {}
        for row in db.query(CommunicationLog.communication_type, func.count(CommunicationLog.id)).filter(
            CommunicationLog.communication_date.between(date_from, date_to)
        ).group_by(CommunicationLog.communication_type).all():
            type_data[row[0]] = row[1]

        # Inbound/outbound
        inbound = base.filter(CommunicationLog.direction == 'inbound').count()
        outbound = base.filter(CommunicationLog.direction == 'outbound').count()

        # Follow-up compliance
        total_req = base.filter(CommunicationLog.follow_up_required == True).count()
        total_done = base.filter(CommunicationLog.follow_up_required == True, CommunicationLog.follow_up_completed == True).count()
        compliance = round(total_done / total_req * 100, 1) if total_req > 0 else 0

        # Escalations
        escalations = base.filter(CommunicationLog.is_escalation == True).count()

        # By client (top 10)
        client_counts = db.query(Client.company_name, func.count(CommunicationLog.id)).join(
            CommunicationLog, CommunicationLog.client_id == Client.id
        ).filter(CommunicationLog.communication_date.between(date_from, date_to)
        ).group_by(Client.company_name).order_by(desc(func.count(CommunicationLog.id))).limit(10).all()

        # By user
        user_counts = db.query(User.first_name, func.count(CommunicationLog.id)).join(
            CommunicationLog, CommunicationLog.logged_by_id == User.id
        ).filter(CommunicationLog.communication_date.between(date_from, date_to)
        ).group_by(User.first_name).order_by(desc(func.count(CommunicationLog.id))).all()

        # Sentiment
        sentiment_data = {}
        for row in db.query(CommunicationLog.sentiment, func.count(CommunicationLog.id)).filter(
            CommunicationLog.communication_date.between(date_from, date_to),
            CommunicationLog.sentiment != None
        ).group_by(CommunicationLog.sentiment).all():
            sentiment_data[row[0]] = row[1]

        # CSV export
        if request.args.get('export') == 'csv':
            logs = base.order_by(desc(CommunicationLog.communication_date)).all()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Log #', 'Date', 'Type', 'Direction', 'Client', 'Subject', 'Priority', 'Sentiment', 'Escalation', 'Follow-up', 'Logged By'])
            for l in logs:
                writer.writerow([
                    l.log_number, l.communication_date.strftime('%Y-%m-%d %H:%M') if l.communication_date else '',
                    l.communication_type, l.direction or '', l.client.display_name if l.client else '',
                    l.subject, l.priority, l.sentiment or '', 'Yes' if l.is_escalation else 'No',
                    'Yes' if l.follow_up_required else 'No', l.logged_by.full_name if l.logged_by else '',
                ])
            return Response(output.getvalue(), mimetype='text/csv',
                headers={'Content-Disposition': f'attachment;filename=communications_{date_from.strftime("%Y%m%d")}_{date_to.strftime("%Y%m%d")}.csv'})

        return render_template('reports/communications_report.html',
            active_page='reports', user=current_user, divisions=_get_divisions(),
            date_from=date_from.strftime('%Y-%m-%d'), date_to=date_to.strftime('%Y-%m-%d'),
            total_comms=total_comms, type_data=type_data, comm_types=COMM_TYPES,
            inbound_count=inbound, outbound_count=outbound,
            total_required=total_req, compliance_pct=compliance,
            escalation_count=escalations,
            client_counts=client_counts, user_counts=user_counts,
            sentiment_data=sentiment_data,
        )
    finally:
        db.close()
