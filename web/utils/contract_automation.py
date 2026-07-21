"""
Automated contract behaviors.
Each function takes an open db session and returns a summary dict.
Safe to run multiple times (idempotent).
"""

from datetime import timezone, date, datetime, timedelta
from models.contract import (Contract, ContractStatus, ContractActivityLog,
                              ContractLineItem, ServiceFrequency)
from models.job import Job
from models.sla import SLA


def check_expired_contracts(db):
    """Mark active contracts whose end_date has passed as expired."""
    today = date.today()
    expired = (db.query(Contract)
                 .filter(
                     Contract.status == ContractStatus.active,
                     Contract.end_date < today
                 )
                 .all())
    count = 0
    for c in expired:
        c.status = ContractStatus.expired
        log = ContractActivityLog(
            contract_id=c.id,
            action='Auto-expired by system',
            detail=f'End date was {c.end_date}'
        )
        db.add(log)
        count += 1
    if count:
        db.commit()
    return {'expired': count}


def create_renewal_drafts(db):
    """
    For auto_renew contracts approaching end_date within renewal_reminder_days,
    create a renewal draft if one doesn't already exist.
    """
    today = date.today()
    created_count = 0

    active = (db.query(Contract)
                .filter(
                    Contract.status == ContractStatus.active,
                    Contract.auto_renew == True
                )
                .all())

    for c in active:
        days_left = (c.end_date - today).days
        if 0 <= days_left <= c.renewal_reminder_days:
            # Check if a renewal draft already exists
            existing_renewal = (db.query(Contract)
                                  .filter(
                                      Contract.client_id == c.client_id,
                                      Contract.status == ContractStatus.draft,
                                      Contract.internal_notes.like(
                                          f'%RENEWAL OF {c.contract_number}%'
                                      )
                                  )
                                  .first())
            if existing_renewal:
                continue

            # Calculate new dates (same duration)
            duration = c.end_date - c.start_date
            new_start = c.end_date + timedelta(days=1)
            new_end = new_start + duration

            renewal = Contract(
                organization_id=c.organization_id,
                contract_number=Contract.generate_contract_number(db),
                client_id=c.client_id,
                division_id=c.division_id,
                title=f'{c.title} (Renewal)',
                description=c.description,
                contract_type=c.contract_type,
                status=ContractStatus.draft,
                start_date=new_start,
                end_date=new_end,
                value=c.value,
                billing_frequency=c.billing_frequency,
                auto_renew=c.auto_renew,
                renewal_terms=c.renewal_terms,
                renewal_reminder_days=c.renewal_reminder_days,
                terms_and_conditions=c.terms_and_conditions,
                internal_notes=(
                    f'RENEWAL OF {c.contract_number} -- '
                    f'Auto-created on {today}'
                ),
            )
            db.add(renewal)
            db.flush()

            # Copy SLAs
            renewal.slas = list(c.slas)

            # Copy properties
            renewal.properties = list(c.properties)

            # Copy line items
            for li in c.line_items:
                new_li = ContractLineItem(
                    contract_id=renewal.id,
                    service_type=li.service_type,
                    description=li.description,
                    frequency=li.frequency,
                    quantity=li.quantity,
                    unit_price=li.unit_price,
                    estimated_hours_per_visit=li.estimated_hours_per_visit,
                    is_included=li.is_included,
                    sort_order=li.sort_order,
                )
                db.add(new_li)

            log = ContractActivityLog(
                contract_id=c.id,
                action='Renewal draft created',
                detail=f'New draft: {renewal.contract_number}'
            )
            db.add(log)
            created_count += 1

    if created_count:
        db.commit()
    return {'renewal_drafts_created': created_count}


def generate_scheduled_jobs(db):
    """
    For line items with next_scheduled_date <= today on active contracts,
    create draft jobs and advance next_scheduled_date.
    """
    today = date.today()
    due_items = (db.query(ContractLineItem)
                   .join(Contract)
                   .filter(
                       Contract.status == ContractStatus.active,
                       ContractLineItem.next_scheduled_date <= today,
                       ContractLineItem.frequency != ServiceFrequency.one_time,
                   )
                   .all())

    created_jobs = 0
    for li in due_items:
        contract = li.contract

        # Check if a draft/scheduled job for this line item already exists
        existing = (db.query(Job)
                      .filter(
                          Job.contract_id == contract.id,
                          Job.status.in_(['draft', 'scheduled']),
                          Job.title.like(f'%{li.service_type}%')
                      )
                      .first())
        if existing:
            li.next_scheduled_date = li.calculate_next_scheduled_date()
            continue

        # Detect best property for the job
        property_id = (contract.properties[0].id
                       if contract.properties else None)

        # Create draft job
        job = Job(
            organization_id=contract.organization_id,
            division_id=contract.division_id,
            client_id=contract.client_id,
            contract_id=contract.id,
            property_id=property_id,
            title=f'{li.service_type} -- {contract.contract_number}',
            description=(li.description or
                         f'Scheduled service from contract {contract.contract_number}'),
            status='draft',
            priority='medium',
            job_type='maintenance',
            estimated_amount=li.line_total,
            created_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.flush()

        # Apply SLA
        from web.utils.sla_engine import detect_sla_for_job, apply_sla_to_job
        sla = detect_sla_for_job(contract, 'medium')
        if sla:
            apply_sla_to_job(job, contract, sla)

        # Advance next_scheduled_date
        li.next_scheduled_date = li.calculate_next_scheduled_date()

        log = ContractActivityLog(
            contract_id=contract.id,
            action='Scheduled job created',
            detail=f'Job for "{li.service_type}" (next: {li.next_scheduled_date})'
        )
        db.add(log)
        created_jobs += 1

    if created_jobs:
        db.commit()
    return {'scheduled_jobs_created': created_jobs}


def check_sla_breaches(db):
    """
    Find jobs whose SLA deadline has passed without resolution.
    Mark sla_response_met / sla_resolution_met = False for tracking.
    """
    now = datetime.now(timezone.utc)
    newly_flagged = 0

    # Response deadline passed, no response recorded
    overdue_response = (db.query(Job)
                          .filter(
                              Job.sla_id.isnot(None),
                              Job.sla_response_deadline <= now,
                              Job.actual_response_time.is_(None),
                              Job.sla_response_met.is_(None),
                          )
                          .all())
    for job in overdue_response:
        job.sla_response_met = False
        newly_flagged += 1

    # Resolution deadline passed, not completed
    overdue_resolution = (db.query(Job)
                            .filter(
                                Job.sla_id.isnot(None),
                                Job.sla_resolution_deadline <= now,
                                Job.actual_resolution_time.is_(None),
                                Job.sla_resolution_met.is_(None),
                            )
                            .all())
    for job in overdue_resolution:
        job.sla_resolution_met = False
        newly_flagged += 1

    if newly_flagged:
        db.commit()
    return {'sla_breaches_flagged': newly_flagged}


def run_all_automations(db):
    """Run all automation checks in sequence. Returns combined summary."""
    results = {}
    results.update(check_expired_contracts(db))
    results.update(create_renewal_drafts(db))
    results.update(generate_scheduled_jobs(db))
    results.update(check_sla_breaches(db))
    return results
