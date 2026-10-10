"""Static safeguards for inactive casting persistence models."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "app/core/nova/creative_studio/casting_db_models.py"
SCHEMA = ROOT / "app/core/nova/creative_studio/schema_ensure.py"
ROUTER = ROOT / "app/core/nova/creative_studio/router.py"


def test_casting_tables_are_defined_but_not_activated():
    models = MODELS.read_text(encoding="utf-8")
    for table in ("nova_casting_campaigns", "nova_casting_applications", "nova_casting_reviews", "nova_casting_media"):
        assert table in models
    assert "UniqueConstraint" in models
    assert "CheckConstraint" in models
    assert "casting_db_models" not in SCHEMA.read_text(encoding="utf-8")
    assert "casting_db_models" not in ROUTER.read_text(encoding="utf-8")


def test_media_metadata_is_private_and_quarantined_by_default():
    models = MODELS.read_text(encoding="utf-8")
    assert 'class NovaCastingMedia(Base):' in models
    assert 'ForeignKey("nova_casting_applications.id")' in models
    assert 'default="PENDING"' in models
    assert "ck_nova_casting_media_status" in models
    assert "storage_key" in models
