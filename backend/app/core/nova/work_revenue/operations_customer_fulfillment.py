"""Read-only fulfillment lane for an authenticated Operations package.

Reports the existing gated lane. It does not reserve quota, store a file,
execute work, or open a payment.
"""

from __future__ import annotations

from app.core.nova.work_revenue.operations_package_allowances import LIMITS

PACKAGES = ("starter", "starter_49", "launch_99", "business_299")


def customer_fulfillment(package: str) -> dict:
    if package not in PACKAGES:
        raise ValueError("Unknown Operations package")
    allowance = 0 if package == "starter" else int(LIMITS[package])
    if package == "starter":
        from app.core.nova.billing.starter_authenticated_access import starter_access_mode

        return {
            "package": package,
            "kind": "self_service",
            "managed_task_allowance": allowance,
            "executes_work": False,
            "gate": starter_access_mode() or "disabled",
        }
    if package == "starter_49":
        from app.core.nova.work_revenue.operations_customer_delivery import (
            customer_delivery_mode,
        )
        from app.core.nova.work_revenue.operations_starter_payment_binding import (
            starter_binding_mode,
        )

        return {
            "package": package,
            "kind": "paid_binding_private_delivery",
            "managed_task_allowance": allowance,
            "executes_work": False,
            "binding_gate": starter_binding_mode() or "disabled",
            "delivery_gate": customer_delivery_mode() or "disabled",
        }
    from app.core.nova.work_revenue.operations_authenticated_subscription_adapter import (
        subscription_adapter_mode,
    )
    from app.core.nova.work_revenue.operations_subscription_delivery_guard import (
        subscription_delivery_mode,
    )
    from app.core.nova.work_revenue.operations_subscription_execution_guard import (
        subscription_execution_mode,
    )

    return {
        "package": package,
        "kind": "subscription_quota_with_owner_approval",
        "managed_task_allowance": allowance,
        "executes_work": False,
        "adapter_gate": subscription_adapter_mode() or "disabled",
        "execution_gate": subscription_execution_mode() or "disabled",
        "delivery_gate": subscription_delivery_mode() or "disabled",
    }
