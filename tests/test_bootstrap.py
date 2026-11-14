import pytest

from chainlex.db.indexes import LegacySchemaError, bootstrap


class LegacyCollection:
    async def list_indexes(self):
        return self._iterate_indexes()

    async def _iterate_indexes(self):
        yield {"name": "legacy_job_version", "unique": True, "key": {"tenant_id": 1, "job_id": 1}}


class LegacyDatabase:
    async def list_collection_names(self):
        return ["agent_action_proposals"]

    def __getitem__(self, name):
        assert name == "agent_action_proposals"
        return LegacyCollection()

    async def create_collection(self, *args, **kwargs):
        pytest.fail("Legacy index detection must happen before any bootstrap mutation")

    async def command(self, *args, **kwargs):
        pytest.fail("Legacy index detection must happen before any bootstrap mutation")


async def test_legacy_unique_job_indexes_require_explicit_migration():
    with pytest.raises(LegacySchemaError, match="explicit migration"):
        await bootstrap(LegacyDatabase())
