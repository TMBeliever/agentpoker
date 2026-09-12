import json
from pathlib import Path
import pytest
from agentpoker.strategy import validate_model_schema, migrate_model_schema, StrategyAgent


def test_champion_json_conforms_to_schema_v2():
    champ_path = Path("models/champion.json")
    assert champ_path.exists()
    data = json.loads(champ_path.read_text(encoding="utf-8"))

    # Validate against schema v2
    assert validate_model_schema(data) is True

    # Check required fields
    assert data["schema_version"] == 2
    assert isinstance(data["model_version"], str)
    assert isinstance(data["candidate_cid"], str)
    assert isinstance(data["archetype"], str)
    assert isinstance(data["parameters"], dict)
    assert isinstance(data["certification"], dict)
    assert isinstance(data["created_at"], str)


def test_schema_validation_rejects_missing_keys():
    invalid_data = {
        "schema_version": 2,
        "model_version": "2.2.0",
        # missing candidate_cid
        "archetype": "TAG",
        "parameters": {},
        "certification": {},
        "created_at": "2026-09-12T00:00:00",
    }
    with pytest.raises(ValueError, match="missing required key 'candidate_cid'"):
        validate_model_schema(invalid_data)


def test_schema_validation_rejects_wrong_schema_version():
    invalid_data = {
        "schema_version": 1,
        "model_version": "2.2.0",
        "candidate_cid": "model:test",
        "archetype": "TAG",
        "parameters": {},
        "certification": {},
        "created_at": "2026-09-12T00:00:00",
    }
    with pytest.raises(ValueError, match="expected schema_version 2"):
        validate_model_schema(invalid_data)


def test_legacy_v1_migration_to_v2():
    legacy_data = {
        "version": 7,
        "name": "Old Champion",
        "params": {
            "vpip": 0.20,
            "open_frequency": 0.60,
        },
        "certification": {
            "certified": True,
            "candidate_id": "model:legacy_v1",
            "timestamp": "2026-09-01T12:00:00",
        },
    }

    migrated = migrate_model_schema(legacy_data)
    assert migrated["schema_version"] == 2
    assert migrated["candidate_cid"] == "model:legacy_v1"
    assert migrated["parameters"]["vpip"] == 0.20
    assert migrated["created_at"] == "2026-09-01T12:00:00"
    assert validate_model_schema(migrated) is True


def test_strategy_agent_loads_schema_v2_model():
    agent = StrategyAgent.load("models/champion.json")
    assert agent is not None
    assert agent.params.vpip == 0.18
    assert agent.params.cbet_frequency == 0.6
