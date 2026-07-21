"""
Flask CLI commands for contract automation.
Register in app.py then run: flask contracts run-automation

Example crontab (run every hour):
0 * * * * cd /app && flask contracts run-automation >> /var/log/fsp_automation.log 2>&1
"""

import click
from flask import Blueprint

automation_cli = Blueprint('contracts_cli', __name__, cli_group='contracts')


@automation_cli.cli.command('run-automation')
@click.option('--verbose', is_flag=True, default=False)
def run_automation(verbose):
    """Run all contract & SLA automation checks."""
    from models.database import get_session
    from web.utils.contract_automation import run_all_automations

    db = get_session()
    try:
        results = run_all_automations(db)
        click.echo(f"[Contract Automation] {results}")
        if verbose:
            for key, val in results.items():
                click.echo(f"  {key}: {val}")
    except Exception as e:
        click.echo(f"[Contract Automation] ERROR: {e}", err=True)
        raise
    finally:
        db.close()


@automation_cli.cli.command('expire-contracts')
def expire_contracts():
    """Mark overdue contracts as expired."""
    from models.database import get_session
    from web.utils.contract_automation import check_expired_contracts
    db = get_session()
    try:
        result = check_expired_contracts(db)
        click.echo(f"Expired: {result['expired']} contract(s)")
    finally:
        db.close()


@automation_cli.cli.command('create-renewals')
def create_renewals():
    """Create renewal drafts for auto-renew contracts nearing expiry."""
    from models.database import get_session
    from web.utils.contract_automation import create_renewal_drafts
    db = get_session()
    try:
        result = create_renewal_drafts(db)
        click.echo(f"Renewal drafts created: {result['renewal_drafts_created']}")
    finally:
        db.close()


@automation_cli.cli.command('generate-jobs')
def generate_jobs():
    """Generate scheduled jobs from contract line items."""
    from models.database import get_session
    from web.utils.contract_automation import generate_scheduled_jobs
    db = get_session()
    try:
        result = generate_scheduled_jobs(db)
        click.echo(f"Jobs created: {result['scheduled_jobs_created']}")
    finally:
        db.close()


@automation_cli.cli.command('check-sla-breaches')
def check_sla():
    """Flag overdue SLA jobs."""
    from models.database import get_session
    from web.utils.contract_automation import check_sla_breaches
    db = get_session()
    try:
        result = check_sla_breaches(db)
        click.echo(f"SLA breaches flagged: {result['sla_breaches_flagged']}")
    finally:
        db.close()


# ── Recurring Jobs CLI ──────────────────────────────────────────────────────

recurring_cli = Blueprint('recurring_cli', __name__, cli_group='recurring')


@recurring_cli.cli.command('generate')
@click.option('--verbose', is_flag=True, default=False)
def generate_recurring(verbose):
    """Generate jobs from all due recurring schedules and contract line items."""
    from models.database import get_session
    from web.utils.recurring_engine import run_generation_pass

    db = get_session()
    try:
        result = run_generation_pass(db, method='cli')
        click.echo(f"[Recurring] Generated {result.total_created} jobs from {result.schedules_processed} schedules")
        if result.contract_items_processed:
            click.echo(f"  + {result.contract_items_processed} from contract line items")
        if result.errors:
            for err in result.errors:
                click.echo(f"  ERROR: {err}", err=True)
        if verbose:
            for job in result.jobs_created:
                click.echo(f"  Created: {job.job_number} — {job.title}")
    except Exception as e:
        click.echo(f"[Recurring] ERROR: {e}", err=True)
        raise
    finally:
        db.close()


@recurring_cli.cli.command('status')
def recurring_status():
    """Show summary of recurring schedule statuses."""
    from models.database import get_session
    from web.utils.recurring_engine import get_due_schedules
    from models.recurring_schedule import RecurringSchedule

    db = get_session()
    try:
        total = db.query(RecurringSchedule).count()
        active = db.query(RecurringSchedule).filter_by(status='active').count()
        due = get_due_schedules(db)
        click.echo(f"Recurring Schedules: {total} total, {active} active, {len(due)} due")
        for s in due:
            click.echo(f"  {s.schedule_number}: {s.title} (due {s.next_due_date})")
    finally:
        db.close()


@recurring_cli.cli.command('sync-contract')
@click.argument('contract_id', type=int)
@click.option('--user-id', default=1, type=int, help='User ID to credit as creator')
def sync_contract_cmd(contract_id, user_id):
    """Import contract line items as RecurringSchedule records."""
    from models.database import get_session
    from web.utils.recurring_engine import sync_from_contract_line_items

    db = get_session()
    try:
        result = sync_from_contract_line_items(db, contract_id, user_id)
        if result.get('error'):
            click.echo(f"Error: {result['error']}", err=True)
            return
        click.echo(f"Created {len(result['created'])} schedule(s):")
        for c in result['created']:
            click.echo(f"  {c['schedule_number']}: {c['title']} ({c['frequency']}, next: {c['next_due_date']})")
        if result['skipped']:
            click.echo(f"Skipped {len(result['skipped'])}:")
            for s in result['skipped']:
                click.echo(f"  Line item {s['line_item_id']}: {s['reason']}")
    finally:
        db.close()


# ── Warranty & Callback CLI ─────────────────────────────────────────────────

warranty_cli = Blueprint('warranty_cli', __name__, cli_group='warranty')


@warranty_cli.cli.command('refresh-statuses')
def refresh_warranty_statuses_cmd():
    """Update warranty statuses (active/expiring_soon/expired)."""
    from models.database import get_session
    from web.utils.warranty_utils import refresh_all_warranty_statuses
    db = get_session()
    try:
        updated = refresh_all_warranty_statuses(db)
        click.echo(f"Updated {updated} warranty status(es).")
    finally:
        db.close()


@warranty_cli.cli.command('notify-expiring')
def notify_expiring_cmd():
    """Send notifications for warranties expiring within 30 days."""
    from models.database import get_session
    from web.utils.warranty_notifications import notify_expiring_warranties
    db = get_session()
    try:
        result = notify_expiring_warranties(db)
        click.echo(f"Warranty expiry: {result['warranties']} warranties, {result['sent']} notified.")
    finally:
        db.close()


@warranty_cli.cli.command('notify-callbacks')
def notify_callbacks_cmd():
    """Send notification for open callbacks."""
    from models.database import get_session
    from web.utils.warranty_notifications import notify_open_callbacks
    db = get_session()
    try:
        result = notify_open_callbacks(db)
        click.echo(f"Callbacks: {result['callbacks']} open, {result['sent']} notified.")
    finally:
        db.close()


@warranty_cli.cli.command('check-rates')
def check_rates_cmd():
    """Flag techs exceeding callback rate threshold."""
    from models.database import get_session
    from web.utils.warranty_notifications import check_callback_rate_thresholds
    db = get_session()
    try:
        result = check_callback_rate_thresholds(db)
        click.echo(f"Callback rates: {result['flagged']} tech(s) above {result['threshold']}% threshold.")
        for d in result.get('details', []):
            click.echo(f"  {d['tech'].full_name}: {d['rate']}% ({d['callbacks']}/{d['jobs']})")
    finally:
        db.close()


# ── Notification CLI ────────────────────────────────────────────────────────

notif_cli = Blueprint('notif_cli', __name__, cli_group='notifications')


@notif_cli.cli.command('send-scheduled')
@click.option('--dry-run', is_flag=True, default=False, help='Preview without sending.')
def send_scheduled_notifications(dry_run):
    """Daily scheduled notification runner."""
    from datetime import timezone, datetime, timedelta, date as date_type
    from models.database import get_session
    from models.notification import NotificationLog
    from web.utils.notification_service import NotificationService

    db = get_session()
    now = datetime.now(timezone.utc)
    today = now.date()
    stats = {}

    def already_sent(entity_type, entity_id, event_key, within_hours=20):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
        return db.query(NotificationLog).filter(
            NotificationLog.entity_type == entity_type,
            NotificationLog.entity_id == entity_id,
            NotificationLog.created_at >= cutoff,
        ).first() is not None

    click.echo(f"\n{'=' * 60}")
    click.echo(f"FieldServicePro — Scheduled Notifications")
    click.echo(f"Run time: {now.strftime('%Y-%m-%d %H:%M UTC')}  Dry run: {dry_run}")
    click.echo('=' * 60)

    # 1. Appointment Reminders
    try:
        from models.job import Job
        reminder_hours = 24
        try:
            from models.settings import OrganizationSettings
            s = db.query(OrganizationSettings).first()
            if s and s.appointment_reminder_hours:
                reminder_hours = s.appointment_reminder_hours
        except Exception:
            pass

        target_start = now + timedelta(hours=reminder_hours - 1)
        target_end = now + timedelta(hours=reminder_hours + 1)
        upcoming = db.query(Job).filter(
            Job.scheduled_date.between(target_start, target_end),
            Job.status.notin_(['completed', 'cancelled', 'on_hold']),
            Job.assigned_technician_id != None,
        ).all()
        count = 0
        for job in upcoming:
            if not already_sent('job', job.id, 'appointment_reminder'):
                if not dry_run:
                    NotificationService.notify('job_scheduled', job, extra_context={
                        'scheduled_date': job.scheduled_date.strftime('%B %d, %Y') if job.scheduled_date else '',
                    })
                count += 1
                click.echo(f"  + Appointment reminder: {job.job_number}")
        stats['appointment_reminders'] = count
    except Exception as e:
        click.echo(f"  ! Appointment reminders error: {e}")

    # 2. Contract Expiring (30 days)
    try:
        from models.contract import Contract
        threshold = today + timedelta(days=30)
        expiring = db.query(Contract).filter(
            Contract.end_date != None, Contract.end_date <= threshold,
            Contract.end_date >= today,
            Contract.status.notin_(['expired', 'cancelled']),
        ).all()
        count = 0
        for c in expiring:
            days_left = (c.end_date - today).days
            if not already_sent('contract', c.id, 'contract_expiring'):
                if not dry_run:
                    NotificationService.notify('contract_expiring', c,
                                               extra_context={'days_remaining': days_left})
                count += 1
                click.echo(f"  + Contract expiring ({days_left}d): {getattr(c, 'contract_number', c.id)}")
        stats['contract_expiring'] = count
    except Exception as e:
        click.echo(f"  ! Contract expiring error: {e}")

    # 3. Warranty Expiring (30 days)
    try:
        from models.warranty import Warranty
        threshold = today + timedelta(days=30)
        expiring = db.query(Warranty).filter(
            Warranty.end_date != None, Warranty.end_date <= threshold,
            Warranty.end_date >= today, Warranty.is_void == False,
        ).all()
        count = 0
        for w in expiring:
            days_left = (w.end_date - today).days
            if not already_sent('warranty', w.id, 'warranty_expiring'):
                if not dry_run:
                    NotificationService.notify('warranty_expiring', w,
                                               extra_context={'days_remaining': days_left})
                count += 1
                click.echo(f"  + Warranty expiring ({days_left}d): #{w.id}")
        stats['warranty_expiring'] = count
    except Exception as e:
        click.echo(f"  ! Warranty expiring error: {e}")

    # 4. Overdue Follow-Ups
    try:
        from models.communication import CommunicationLog
        overdue = db.query(CommunicationLog).filter(
            CommunicationLog.follow_up_date != None,
            CommunicationLog.follow_up_date < today,
            CommunicationLog.follow_up_completed == False,
        ).all()
        count = 0
        for comm in overdue:
            if not already_sent('communication', comm.id, 'follow_up_overdue'):
                if not dry_run:
                    NotificationService.notify('follow_up_overdue', comm, extra_context={
                        'subject': getattr(comm, 'subject', 'follow-up'),
                    })
                count += 1
                click.echo(f"  + Overdue follow-up: {getattr(comm, 'subject', comm.id)}")
        stats['follow_up_overdue'] = count
    except Exception as e:
        click.echo(f"  ! Follow-up overdue error: {e}")

    # 5. Recurring Job Overdue
    try:
        from models.recurring_schedule import RecurringSchedule
        overdue = db.query(RecurringSchedule).filter(
            RecurringSchedule.next_due_date != None,
            RecurringSchedule.next_due_date < today,
            RecurringSchedule.status == 'active',
        ).all()
        count = 0
        for sched in overdue:
            days_overdue = (today - sched.next_due_date).days if sched.next_due_date else 0
            if not already_sent('recurring', sched.id, 'recurring_overdue'):
                if not dry_run:
                    NotificationService.notify('system', sched, extra_context={
                        'days_overdue': days_overdue,
                    }, title=f'Overdue Recurring Job: {getattr(sched, "title", sched.id)}',
                       message=f'Recurring schedule is {days_overdue} days overdue.')
                count += 1
                click.echo(f"  + Recurring overdue ({days_overdue}d): {getattr(sched, 'title', sched.id)}")
        stats['recurring_overdue'] = count
    except Exception as e:
        click.echo(f"  ! Recurring overdue error: {e}")

    db.close()

    # Summary
    click.echo(f"\n{'-' * 60}")
    total_sent = 0
    for key, count in stats.items():
        if count > 0:
            click.echo(f"  {key.replace('_', ' ').title():<35} {count:>4}")
            total_sent += count
    click.echo(f"  {'Total':<35} {total_sent:>4}")
    if dry_run:
        click.echo("\n  (DRY RUN — nothing was actually sent)")
    click.echo('=' * 60)


@notif_cli.cli.command('cleanup')
@click.option('--days', default=90, help='Remove dismissed notifications older than N days.')
def cleanup_old_notifications(days):
    """Remove old dismissed notifications."""
    from datetime import timezone, datetime, timedelta
    from models.database import get_session
    from models.notification import Notification

    db = get_session()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = db.query(Notification).filter(
            Notification.is_dismissed == True,
            Notification.created_at < cutoff,
        ).delete()
        db.commit()
        click.echo(f"Deleted {deleted} old dismissed notifications.")
    finally:
        db.close()


# ── Project Management CLI ──────────────────────────────────────────────────

project_mgmt_cli = Blueprint('project_mgmt_cli', __name__, cli_group='project-mgmt')


@project_mgmt_cli.cli.command('check-overdue')
def check_overdue_cmd():
    """Send overdue notifications for RFIs and Submittals."""
    from web.utils.project_mgmt_notifications import notify_rfi_overdue, notify_submittal_overdue
    rfi_count = notify_rfi_overdue()
    sub_count = notify_submittal_overdue()
    click.echo(f'Notified: {rfi_count} overdue RFIs, {sub_count} overdue submittals.')


@project_mgmt_cli.cli.command('check-deliveries')
def check_deliveries_cmd():
    """Alert on approaching submittal deliveries."""
    from web.utils.project_mgmt_notifications import notify_delivery_approaching
    count = notify_delivery_approaching()
    click.echo(f'Sent {count} delivery approaching alerts.')
