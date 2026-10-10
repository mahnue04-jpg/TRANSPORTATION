"""Static contract: casting DB reads remain server scoped and unregistered."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READS = ROOT / "app/core/nova/creative_studio/casting_db_reads.py"


def test_db_read_requires_server_side_membership_and_tenant_filters():
    src = READS.read_text(encoding="utf-8")
    assert "NovaCastingOrganization.verification_status" not in src  # checked from fetched row
    assert 'organization.verification_status == "VERIFIED"' in src
    assert "NovaCastingMembership.nova_tenant_id == tenant_id" in src
    assert "NovaCastingOrganization.nova_tenant_id == tenant_id" in src
    assert "NovaCastingApplication.owner_id == organization_id" in src
    assert "NovaCastingCampaign.owner_id == organization_id" in src
    for path in ("app/main.py", "app/core/nova/creative_studio/router.py"):
        assert "casting_db_reads" not in (ROOT / path).read_text(encoding="utf-8")
