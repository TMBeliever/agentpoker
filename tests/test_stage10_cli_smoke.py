import subprocess
import sys
import pytest
from pathlib import Path


def run_cli(*args):
    cmd = [sys.executable, "-m", "agentpoker.cli"] + list(args)
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res


def test_cli_help_smoke():
    # Top-level help
    r0 = run_cli("--help")
    assert r0.returncode == 0
    assert "agentpoker" in r0.stdout

    # Subcommands help
    for sub in ["train", "evaluate", "battle", "arena", "live"]:
        r = run_cli(sub, "--help")
        assert r.returncode == 0, f"Failed for {sub}: {r.stderr}"
        assert "usage: agentpoker" in r.stdout


def test_cli_default_field_size_is_120():
    # Evaluate help has 120
    r_eval = run_cli("evaluate", "--help")
    assert "默认 120" in r_eval.stdout or "120" in r_eval.stdout

    # Battle help has 120
    r_bat = run_cli("battle", "--help")
    assert "默认 120" in r_bat.stdout or "120" in r_bat.stdout

    # Train help has 120
    r_tr = run_cli("train", "--help")
    assert "默认 120" in r_tr.stdout or "120" in r_tr.stdout


def test_cli_evaluate_champion_smoke():
    """Smoke test: evaluate models/champion.json for 1 run."""
    champ_path = Path("models/champion.json")
    assert champ_path.exists()

    res = run_cli(
        "evaluate",
        "--strategy", str(champ_path),
        "--runs", "1",
        "--agents", "12",  # Fast smoke
    )
    assert res.returncode == 0, f"evaluate failed: {res.stderr}\n{res.stdout}"
    assert "评估报告" in res.stdout or "BB/100" in res.stdout


def test_cli_battle_champion_smoke():
    """Smoke test: battle models/champion.json against tight archetype for 1 run."""
    res = run_cli(
        "battle",
        "--models", "models/champion.json",
        "--archetypes", "tight",
        "--runs", "1",
        "--agents", "12",  # Fast smoke
        "--opponents", "pyramid",
    )
    assert res.returncode == 0, f"battle failed: {res.stderr}\n{res.stdout}"
    assert "锦标赛擂台赛最终战报" in res.stdout or "战报" in res.stdout
