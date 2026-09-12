import json
import tempfile
from pathlib import Path
import pytest
from agentpoker.battle import (
    promote_champion,
    ChampionCertificationResult,
    CertificationCriterion,
    CertificationError,
)


def test_uncertified_call_raises_certification_error():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cand = tmp_path / "candidate.json"
        cand.write_text(json.dumps({"name": "Cand", "version": 1}))
        target = tmp_path / "champion.json"

        # 1. Calling without certification_result must raise CertificationError
        with pytest.raises(CertificationError, match="strictly requires a valid ChampionCertificationResult"):
            promote_champion(candidate_source=cand, target_path=target)

        # Ensure target file was not created
        assert not target.exists()


def test_failed_certification_raises_certification_error():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cand = tmp_path / "candidate.json"
        cand.write_text(json.dumps({"name": "Cand", "version": 1}))
        target = tmp_path / "champion.json"

        failed_result = ChampionCertificationResult(
            certified=False,
            candidate_id="cand",
            candidate_name="Cand",
            criteria=[CertificationCriterion(name="H2H", required=">=50%", actual="40%", passed=False)],
            summary="Candidate failed 1 criteria",
            recommendation="REJECT",
        )

        with pytest.raises(CertificationError, match="certification failed"):
            promote_champion(candidate_source=cand, target_path=target, certification_result=failed_result)

        # Ensure target file was not created
        assert not target.exists()


def test_certified_true_promotes_and_creates_backup():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # Create existing champion
        target = tmp_path / "champion.json"
        target.write_text(json.dumps({"name": "Old Champ", "version": 1}))

        # Create new certified candidate
        cand = tmp_path / "new_candidate.json"
        cand.write_text(json.dumps({"name": "New Champ", "version": 2}))

        passed_result = ChampionCertificationResult(
            certified=True,
            candidate_id="new_champ",
            candidate_name="New Champ",
            criteria=[CertificationCriterion(name="All", required="Req", actual="Act", passed=True)],
            summary="Candidate passed all criteria",
            recommendation="PROMOTE_TO_CHAMPION",
        )

        res_path = promote_champion(
            candidate_source=cand,
            target_path=target,
            backup=True,
            certification_result=passed_result,
        )

        assert res_path == target
        promoted = json.loads(target.read_text(encoding="utf-8"))
        assert promoted["name"] == "New Champ"
        assert promoted["version"] == 2
        assert "certification" in promoted
        assert promoted["certification"]["certified"] is True

        # Check that backup file was created
        backups = list(tmp_path.glob("champion_backup_*.json"))
        assert len(backups) == 1
        backup_data = json.loads(backups[0].read_text(encoding="utf-8"))
        assert backup_data["name"] == "Old Champ"
