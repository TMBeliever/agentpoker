import json
from pathlib import Path
import pytest


def test_production_champion_matches_certification_report():
    champ_path = Path("models/champion.json")
    rep_path = Path("docs/production_certification_report.json")

    assert champ_path.exists(), "models/champion.json must exist"
    assert rep_path.exists(), "docs/production_certification_report.json must exist"

    champ = json.loads(champ_path.read_text(encoding="utf-8"))
    rep = json.loads(rep_path.read_text(encoding="utf-8"))

    # 1. candidate_cid must match
    assert champ["candidate_cid"] == rep["candidate_cid"]

    # 2. parameters must match exactly
    champ_params = champ.get("parameters") or champ.get("params")
    rep_params = rep.get("parameters") or rep.get("params")
    assert champ_params == rep_params, "Champion parameters must match certification report parameters"

    # 3. version must match
    assert champ.get("model_version") == rep.get("model_version")

    # 4. timestamp must match
    assert champ.get("created_at") == rep.get("created_at")
    assert champ["certification"]["timestamp"] == rep["certification"]["timestamp"]

    # 5. Certification status must be verified
    assert champ["certification"]["certified"] is True
    assert rep["certification"]["certified"] is True
    assert rep.get("is_current_production") is True


def test_stage11_report_marked_historical_and_not_production():
    legacy_path = Path("docs/stage11_certification_report.json")
    assert legacy_path.exists(), "docs/stage11_certification_report.json must exist"

    legacy_data = json.loads(legacy_path.read_text(encoding="utf-8"))
    assert legacy_data.get("historical") is True, "stage11 report must be marked historical: true"
    assert legacy_data.get("legacy") is True, "stage11 report must be marked legacy: true"
    assert legacy_data.get("is_current_production") is False, "stage11 report must not be current production"
