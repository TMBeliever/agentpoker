"""Stage 2 Verification: Multi-Stage Continuous Fitness.

Tests:
1. Extraction of full-tournament stage metrics (preliminary, semifinal, final table, overall).
2. Continuous separation on the final table (2nd place vs 6th place produces continuous score separation without championships).
3. Preliminary-only grinders do not dominate balanced or deep-run contenders.
4. Semifinal and final chip trajectories directly modulate overall BB/100 and fitness.
5. Backward compatibility for legacy _summarise calls when stage_results is omitted.
"""
import math
import pytest
from dataclasses import dataclass
from agentpoker.training import _extract_tournament_stage_metrics, _summarise


@dataclass
class MockStanding:
    agent_id: str
    hands: int
    net_bb: float
    bb100: float
    rank: int = 1


def _make_tournament_result(hero_id="focal",
                            prelim_rank=1, prelim_hands=200, prelim_net_bb=50.0,
                            in_qualified=True,
                            semi_rank=1, semi_hands=50, semi_net_bb=20.0,
                            in_final=True,
                            final_rank=1, final_hands=50, final_net_bb=30.0,
                            pool_size=120):
    prelim = []
    for i in range(1, pool_size + 1):
        aid = hero_id if i == prelim_rank else f"opp_{i}"
        net = prelim_net_bb if i == prelim_rank else (0.0 if i > 12 else 10.0)
        prelim.append(MockStanding(aid, prelim_hands, net, (net / prelim_hands) * 100.0, rank=i))

    qualified = prelim[:12] if in_qualified else [p for p in prelim if p.agent_id != hero_id][:12]

    semifinal = []
    if in_qualified:
        # 2 groups of 6
        grp1_aids = [qualified[i].agent_id for i in (0, 3, 4, 7, 8, 11)]
        grp2_aids = [qualified[i].agent_id for i in (1, 2, 5, 6, 9, 10)]
        hero_in_grp1 = hero_id in grp1_aids
        target_grp = grp1_aids if hero_in_grp1 else grp2_aids
        other_grp = grp2_aids if hero_in_grp1 else grp1_aids

        # Build hero group
        t_standings = []
        for idx, aid in enumerate(target_grp, 1):
            if aid == hero_id:
                t_standings.append(MockStanding(aid, semi_hands, semi_net_bb, (semi_net_bb / semi_hands) * 100.0, rank=semi_rank))
            else:
                r = idx if idx < semi_rank else idx + 1
                t_standings.append(MockStanding(aid, semi_hands, 5.0, 10.0, rank=min(6, r)))
        t_standings.sort(key=lambda x: x.rank)

        o_standings = []
        for idx, aid in enumerate(other_grp, 1):
            o_standings.append(MockStanding(aid, semi_hands, 5.0, 10.0, rank=idx))

        semifinal = [t_standings, o_standings]

    final = []
    if in_final:
        final_aids = [hero_id] + [f"final_opp_{i}" for i in range(1, 6)]
        for idx, aid in enumerate(final_aids, 1):
            if aid == hero_id:
                final.append(MockStanding(aid, final_hands, final_net_bb, (final_net_bb / final_hands) * 100.0, rank=final_rank))
            else:
                r = idx if idx < final_rank else idx + 1
                final.append(MockStanding(aid, final_hands, 0.0, 0.0, rank=min(6, r)))
        final.sort(key=lambda x: x.rank)

    return {
        "preliminary": prelim,
        "qualified": qualified,
        "semifinal": semifinal,
        "final": final,
    }


def test_extract_tournament_stage_metrics_cases():
    """Verify accurate extraction of all tournament stages and strict utility monotonicity."""
    # Case A: Eliminated in Preliminary (rank 45)
    res_a = _make_tournament_result(prelim_rank=45, prelim_net_bb=-20.0, in_qualified=False, in_final=False)
    m_a = _extract_tournament_stage_metrics(res_a, "focal")
    assert m_a["is_top12"] == 0
    assert m_a["is_final"] == 0
    assert m_a["is_champ"] == 0
    assert m_a["prelim_rank"] == 45.0
    assert m_a["finish_rank"] == 45.0
    assert m_a["semi_rank"] is None
    assert m_a["final_rank"] is None
    assert m_a["overall_bb100"] == pytest.approx(-10.0)

    # Case B: Eliminated in Semifinal (group rank 5, not advancing to final)
    res_b = _make_tournament_result(prelim_rank=8, prelim_net_bb=40.0, in_qualified=True,
                                    semi_rank=5, semi_net_bb=-15.0, in_final=False)
    m_b = _extract_tournament_stage_metrics(res_b, "focal")
    assert m_b["is_top12"] == 1
    assert m_b["is_final"] == 0
    assert m_b["is_champ"] == 0
    assert 7.0 <= m_b["finish_rank"] <= 12.0
    assert m_b["semi_rank"] == 5.0
    assert m_b["final_rank"] is None

    # Case C: Final Table Runner-up (rank 2, not champion)
    res_c = _make_tournament_result(prelim_rank=3, prelim_net_bb=50.0, in_qualified=True,
                                    semi_rank=2, semi_net_bb=20.0, in_final=True,
                                    final_rank=2, final_net_bb=25.0)
    m_c = _extract_tournament_stage_metrics(res_c, "focal")
    assert m_c["is_top12"] == 1
    assert m_c["is_final"] == 1
    assert m_c["is_champ"] == 0
    assert m_c["finish_rank"] == 2.0
    assert m_c["final_rank"] == 2.0
    assert m_c["finish_utility"] == pytest.approx(1.0 / math.sqrt(2.0))
    assert m_c["survival_utility"] == pytest.approx(0.75 + (4.0 / 5.0) * 0.25)

    # Case D: Tournament Champion (rank 1)
    res_d = _make_tournament_result(prelim_rank=1, prelim_net_bb=60.0, in_qualified=True,
                                    semi_rank=1, semi_net_bb=30.0, in_final=True,
                                    final_rank=1, final_net_bb=50.0)
    m_d = _extract_tournament_stage_metrics(res_d, "focal")
    assert m_d["is_top12"] == 1
    assert m_d["is_final"] == 1
    assert m_d["is_champ"] == 1
    assert m_d["finish_rank"] == 1.0
    assert m_d["finish_utility"] == pytest.approx(1.0)
    assert m_d["survival_utility"] == pytest.approx(1.0)

    # Check strict progressive ordering
    assert m_a["finish_utility"] < m_b["finish_utility"] < m_c["finish_utility"] < m_d["finish_utility"]
    assert m_a["survival_utility"] < m_b["survival_utility"] < m_c["survival_utility"] < m_d["survival_utility"]
    assert m_a["run_fitness"] < m_b["run_fitness"] < m_c["run_fitness"] < m_d["run_fitness"]


def test_final_stage_continuous_separation_without_championship():
    """Verify that 2nd place vs 6th place on the final table creates continuous fitness separation even with 0 champions."""
    runs = 10
    pool = 120

    stages_runner_up = []
    stages_sixth_place = []

    for i in range(runs):
        if i < 5:
            # Runner up (2nd place on final table, +40 BB/100 on final table)
            r_up = _make_tournament_result(prelim_rank=4, prelim_net_bb=40.0, in_qualified=True,
                                          semi_rank=2, semi_net_bb=20.0, in_final=True,
                                          final_rank=2, final_net_bb=20.0)
            stages_runner_up.append(_extract_tournament_stage_metrics(r_up, "focal"))

            # 6th place on final table (-80 BB/100 on final table)
            r_six = _make_tournament_result(prelim_rank=4, prelim_net_bb=40.0, in_qualified=True,
                                           semi_rank=3, semi_net_bb=5.0, in_final=True,
                                           final_rank=6, final_net_bb=-40.0)
            stages_sixth_place.append(_extract_tournament_stage_metrics(r_six, "focal"))
        else:
            # Both eliminated in preliminary at rank 30
            r_out = _make_tournament_result(prelim_rank=30, prelim_net_bb=-10.0, in_qualified=False, in_final=False)
            stages_runner_up.append(_extract_tournament_stage_metrics(r_out, "focal"))
            stages_sixth_place.append(_extract_tournament_stage_metrics(r_out, "focal"))

    sum_up = _summarise(
        top=5, final=5, champ=0,
        ranks=[s["prelim_rank"] for s in stages_runner_up],
        bbs=[s["prelim_bb100"] for s in stages_runner_up],
        runs=runs, pool=pool,
        stage_results=stages_runner_up
    )
    sum_six = _summarise(
        top=5, final=5, champ=0,
        ranks=[s["prelim_rank"] for s in stages_sixth_place],
        bbs=[s["prelim_bb100"] for s in stages_sixth_place],
        runs=runs, pool=pool,
        stage_results=stages_sixth_place
    )

    assert sum_up["champion_rate"] == 0.0
    assert sum_six["champion_rate"] == 0.0
    assert sum_up["final_rate"] == 0.5
    assert sum_six["final_rate"] == 0.5

    # But Runner-Up must have significantly higher continuous fitness
    assert sum_up["finish_utility"] > sum_six["finish_utility"]
    assert sum_up["survival_utility"] > sum_six["survival_utility"]
    assert sum_up["overall_bb100"] > sum_six["overall_bb100"]
    assert sum_up["fitness"] > sum_six["fitness"] + 0.08, (
        f"Runner-up fitness ({sum_up['fitness']:.4f}) should dominate 6th place ({sum_six['fitness']:.4f}) by >0.08"
    )


def test_preliminary_only_does_not_dominate():
    """Verify that an agent with high prelim BB but bad deep-run play loses to balanced/deep-run agents."""
    runs = 10
    pool = 120

    # Candidate A: Prelim-only grinder (+120 BB/100 in prelim, but chokes in semi with -100 BB/100, 6th in group, never in final)
    stages_a = []
    for _ in range(runs):
        r_a = _make_tournament_result(prelim_rank=1, prelim_net_bb=240.0, in_qualified=True,
                                     semi_rank=6, semi_net_bb=-50.0, in_final=False)
        stages_a.append(_extract_tournament_stage_metrics(r_a, "focal"))

    # Candidate B: Balanced performer (+35 BB/100 in prelim, +25 BB/100 in semi, 2nd on final table)
    stages_b = []
    for _ in range(runs):
        r_b = _make_tournament_result(prelim_rank=6, prelim_net_bb=70.0, in_qualified=True,
                                     semi_rank=2, semi_net_bb=12.5, in_final=True,
                                     final_rank=2, final_net_bb=15.0)
        stages_b.append(_extract_tournament_stage_metrics(r_b, "focal"))

    sum_a = _summarise(
        top=runs, final=0, champ=0,
        ranks=[s["prelim_rank"] for s in stages_a],
        bbs=[s["prelim_bb100"] for s in stages_a],
        runs=runs, pool=pool, stage_results=stages_a
    )
    sum_b = _summarise(
        top=runs, final=runs, champ=0,
        ranks=[s["prelim_rank"] for s in stages_b],
        bbs=[s["prelim_bb100"] for s in stages_b],
        runs=runs, pool=pool, stage_results=stages_b
    )

    # Candidate B reaches final table and takes 2nd place consistently;
    # Candidate A only grinds preliminary and spews in deep rounds.
    assert sum_b["fitness"] > sum_a["fitness"]
    assert sum_b["avg_finish_rank"] < sum_a["avg_finish_rank"]
    assert sum_b["finish_utility"] > sum_a["finish_utility"]


def test_semifinal_and_final_chips_affect_fitness():
    """Verify that deep stage chips won/lost directly change overall BB/100 and fitness."""
    runs = 6
    pool = 120

    stages_win = []
    stages_lose = []

    for _ in range(runs):
        # Prelim identical: rank 5, +30 BB/100
        # Winner wins +60 BB/100 across semi and final
        r_w = _make_tournament_result(prelim_rank=5, prelim_net_bb=60.0, in_qualified=True,
                                     semi_rank=3, semi_net_bb=25.0, in_final=True,
                                     final_rank=3, final_net_bb=25.0)
        stages_win.append(_extract_tournament_stage_metrics(r_w, "focal"))

        # Loser loses -60 BB/100 across semi and final (same placement 3rd, but spews chips)
        r_l = _make_tournament_result(prelim_rank=5, prelim_net_bb=60.0, in_qualified=True,
                                     semi_rank=3, semi_net_bb=-25.0, in_final=True,
                                     final_rank=3, final_net_bb=-25.0)
        stages_lose.append(_extract_tournament_stage_metrics(r_l, "focal"))

    sum_w = _summarise(top=runs, final=runs, champ=0, ranks=[5]*runs, bbs=[30.0]*runs, runs=runs, pool=pool, stage_results=stages_win)
    sum_l = _summarise(top=runs, final=runs, champ=0, ranks=[5]*runs, bbs=[30.0]*runs, runs=runs, pool=pool, stage_results=stages_lose)

    assert sum_w["overall_bb100"] > sum_l["overall_bb100"]
    assert sum_w["deep_bb100"] > sum_l["deep_bb100"]
    assert sum_w["fitness"] > sum_l["fitness"]


def test_backward_compatibility_when_stage_results_omitted():
    """Verify that omitting stage_results falls back to exact legacy fitness and SE."""
    m = _summarise(12, 6, 3, [4.0] * 24, [0.0] * 24, 24, 24)
    expected = .20 * 0.5 + .20 * 0.25 + .25 * 0.125 + .05 * (1 - 3 / 23) + .30 * 0.5
    assert math.isclose(m["fitness"], expected, rel_tol=1e-9)
    assert "fitness_se" in m
    assert "fitness_ci95" in m


def test_candidate_ranking_incorporates_deep_stage_performance():
    """Verify that candidate ranking prefers multi-stage deep contenders over prelim-only grinders."""
    runs = 10
    pool = 120

    # Cand A: Prelim-only grinder (+150 BB/100 in prelim, -120 BB/100 in semi, rank 6, out)
    stages_a = []
    for _ in range(runs):
        r_a = _make_tournament_result(prelim_rank=1, prelim_net_bb=300.0, in_qualified=True,
                                     semi_rank=6, semi_net_bb=-60.0, in_final=False)
        stages_a.append(_extract_tournament_stage_metrics(r_a, "focal"))
    sum_a = _summarise(top=runs, final=0, champ=0, ranks=[1]*runs, bbs=[150.0]*runs, runs=runs, pool=pool, stage_results=stages_a)

    # Cand B: Consistent deep competitor (+40 BB/100 prelim, +30 BB/100 semi, 2nd on final table)
    stages_b = []
    for _ in range(runs):
        r_b = _make_tournament_result(prelim_rank=5, prelim_net_bb=80.0, in_qualified=True,
                                     semi_rank=2, semi_net_bb=15.0, in_final=True,
                                     final_rank=2, final_net_bb=20.0)
        stages_b.append(_extract_tournament_stage_metrics(r_b, "focal"))
    sum_b = _summarise(top=runs, final=runs, champ=0, ranks=[5]*runs, bbs=[40.0]*runs, runs=runs, pool=pool, stage_results=stages_b)

    scored_pairs = [(sum_a, "CandA_PrelimOnly"), (sum_b, "CandB_DeepFinalist")]
    ranked = sorted(
        scored_pairs,
        key=lambda x: (
            x[0]["fitness"],
            x[0].get("finish_utility", x[0].get("top12_rate", 0.0)),
            x[0].get("overall_bb100", x[0].get("avg_bb100", 0.0)),
            -x[0].get("avg_finish_rank", x[0].get("avg_rank", 999.0))
        ),
        reverse=True
    )

    assert ranked[0][1] == "CandB_DeepFinalist", "Candidate B must outrank Candidate A in multi-stage tournament ranking"

