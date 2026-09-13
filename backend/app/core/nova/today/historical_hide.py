"""Allowlisted hide/deactivate of verified historical Today excess rows. Never deletes."""
from __future__ import annotations

from sqlalchemy import inspect, text

CANONICAL_ACTION_IDS = frozenset(
    {
        "NV2-477323621851",  # business/rec-attention/acknowledge
        "NV2-34BB06D12F95",  # communications/rec-drafts/acknowledge
        "NV2-844561D2D0C2",  # link/health/open_link DONE + history
        "NV2-5E15DACE6CE8",  # link/delivery/open_link
        "NV2-6C7F7AB048EB",  # link/freight/open_link
    }
)
EXCESS_ACTION_IDS = frozenset(
    {
        "NV2-6C52A4405CB5",
        "NV2-2D3DF53111E7",
        "NV2-1ABF0CB67D1C",
        "NV2-B8FFE992B33A",
        "NV2-5AB018BD3F54",
        "NV2-98176376ED08",
        "NV2-5BDF5CDFAD34",
        "NV2-14DAD334D451",
        "NV2-5D00AA5EAF7E",
        "NV2-34A65A654C4C",
        "NV2-11DC7695C5CC",
        "NV2-C2906CEF131E",
        "NV2-D6275D2479A3",
        "NV2-08C678C20404",
        "NV2-516C6E0F8811",
    }
)
DEACTIVATED_STATUS = "deactivated"


def _sql_in(ids: frozenset[str]) -> str:
    return ",".join("'" + action_id.replace("'", "") + "'" for action_id in sorted(ids))


def hide_verified_excess_today_rows(engine) -> int:
    """Set allowlisted excess rows to deactivated. No DELETE. Canonicals/smoke untouched."""
    inspector = inspect(engine)
    if "nova_v2_command_actions" not in set(inspector.get_table_names()):
        return 0
    sql = text(
        "UPDATE nova_v2_command_actions "
        f"SET status = '{DEACTIVATED_STATUS}' "
        f"WHERE action_id IN ({_sql_in(EXCESS_ACTION_IDS)}) "
        f"AND action_id NOT IN ({_sql_in(CANONICAL_ACTION_IDS)}) "
        "AND status = 'proposed' "
        "AND (result_ref_id IS NULL OR result_ref_id = '')"
    )
    with engine.begin() as conn:
        result = conn.execute(sql)
        return int(result.rowcount or 0)
