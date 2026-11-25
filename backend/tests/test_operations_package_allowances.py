from datetime import datetime, timedelta, timezone

from app.core.nova.work_revenue.operations_package_allowances import (
    VerifiedEntitlement, can_accept_task,
)

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def active(plan="launch_99", **kw):
    values = dict(plan=plan, customer_id="cus_synthetic", paid=True, status="active",
                  subscription_id="sub_test", period_start=NOW-timedelta(days=2),
                  period_end=NOW+timedelta(days=28), payment_id="pi_test")
    values.update(kw)
    return VerifiedEntitlement(**values)


def decide(entitlement, keys=frozenset(), request="new", **kw):
    return can_accept_task(entitlement, customer_id="cus_synthetic",
                           now=NOW, accepted_unique_tasks=keys, request_key=request, **kw)


def test_starter_one_and_deduplicate():
    e = active("starter_49")
    assert decide(e)[0]
    assert decide(e, frozenset({"one"}), "one") == (True, "existing_task_idempotent")
    assert decide(e, frozenset({"one"})) == (False, "allowance_exhausted")


def test_launch_three_and_business_ten():
    for plan, count in (("launch_99", 3), ("business_299", 10)):
        e = active(plan)
        assert decide(e, frozenset(str(i) for i in range(count-1)))[0]
        assert decide(e, frozenset(str(i) for i in range(count))) == (False, "allowance_exhausted")


def test_unpaid_canceled_failed_and_wrong_customer():
    for e in (active(paid=False), active(status="canceled"), active(status="past_due"),
              active(customer_id="other")):
        assert not decide(e)[0]


def test_subscription_period_required_and_no_expired_work():
    for e in (active(period_start=None), active(subscription_id=None),
              active(period_end=NOW), active(period_start=NOW+timedelta(days=1))):
        assert not decide(e)[0]


def test_one_time_requires_payment_proof():
    assert decide(active("starter_49", payment_id=None)) == (False, "unverified_one_time_payment")


def test_reject_missing_or_oversized_idempotency_key():
    assert not decide(active(), request="")[0]
    assert not decide(active(), request="x"*129)[0]
