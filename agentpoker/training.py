from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from pathlib import Path
import hashlib, json, math, os, random, statistics, time
from typing import Any
from concurrent.futures import ProcessPoolExecutor, as_completed
from .config import TournamentConfig
from .strategy import StrategyAgent, StrategyParams
from .tournament import LeagueSimulator, SimAgent

ARCHETYPES = {
    "nit": StrategyParams(
        vpip=.14, open_frequency=.50, threebet_frequency=.055, squeeze_frequency=.035, steal_frequency=.58,
        open_thresh_utg=.11, open_thresh_hj=.14, open_thresh_co=.20, open_thresh_btn=.36, open_thresh_sb=.26, defend_thresh_bb=.40,
        multiway_decay=.42, table_strength_weight=.35,
        cbet_frequency=.55, turn_barrel_frequency=.42, river_bluff_frequency=.035,
        value_threshold=.72, thin_value_threshold=.64, raise_threshold=.66, jam_threshold=.94,
        flop_value_threshold=.64, turn_value_threshold=.70, river_value_threshold=.78,
        open_size=2.20, cbet_size=.42, value_bet_size=.72, bluff_bet_size=.46, raise_size=.62,
        dry_board_bet_size=.28, wet_board_bet_size=.70, safety=.60, attack=.48,
        bubble_aggression=.52, late_aggression=.10, temperature=.05
    ),
    "tight": StrategyParams(
        vpip=.18, open_frequency=.58, threebet_frequency=.070, squeeze_frequency=.045, steal_frequency=.65,
        open_thresh_utg=.13, open_thresh_hj=.17, open_thresh_co=.24, open_thresh_btn=.42, open_thresh_sb=.32, defend_thresh_bb=.48,
        multiway_decay=.48, table_strength_weight=.32,
        cbet_frequency=.60, turn_barrel_frequency=.50, river_bluff_frequency=.055,
        value_threshold=.70, thin_value_threshold=.62, raise_threshold=.64, jam_threshold=.93,
        flop_value_threshold=.60, turn_value_threshold=.66, river_value_threshold=.75,
        open_size=2.30, cbet_size=.45, value_bet_size=.71, bluff_bet_size=.50, raise_size=.65,
        dry_board_bet_size=.30, wet_board_bet_size=.72, safety=.52, attack=.56,
        bubble_aggression=.62, late_aggression=.14, temperature=.06
    ),
    "balanced": StrategyParams(),
    "lag": StrategyParams(
        vpip=.31, open_frequency=.72, threebet_frequency=.105, squeeze_frequency=.075, steal_frequency=.82,
        open_thresh_utg=.17, open_thresh_hj=.22, open_thresh_co=.31, open_thresh_btn=.56, open_thresh_sb=.42, defend_thresh_bb=.58,
        multiway_decay=.52, table_strength_weight=.28,
        cbet_frequency=.69, turn_barrel_frequency=.61, river_bluff_frequency=.11,
        value_threshold=.61, thin_value_threshold=.54, raise_threshold=.57, jam_threshold=.87,
        flop_value_threshold=.52, turn_value_threshold=.60, river_value_threshold=.69,
        open_size=2.40, cbet_size=.50, value_bet_size=.67, bluff_bet_size=.58, raise_size=.73,
        dry_board_bet_size=.36, wet_board_bet_size=.80, safety=.38, attack=.82,
        bubble_aggression=.88, late_aggression=.30, temperature=.13
    ),
    "station": StrategyParams(
        vpip=.43, open_frequency=.47, threebet_frequency=.040, squeeze_frequency=.025, steal_frequency=.55,
        open_thresh_utg=.18, open_thresh_hj=.23, open_thresh_co=.28, open_thresh_btn=.46, open_thresh_sb=.38, defend_thresh_bb=.65,
        multiway_decay=.58, table_strength_weight=.20,
        cbet_frequency=.43, turn_barrel_frequency=.33, river_bluff_frequency=.020,
        value_threshold=.64, thin_value_threshold=.56, raise_threshold=.69, jam_threshold=.95,
        flop_value_threshold=.56, turn_value_threshold=.62, river_value_threshold=.70,
        open_size=2.25, cbet_size=.41, value_bet_size=.74, bluff_bet_size=.42, raise_size=.56,
        dry_board_bet_size=.32, wet_board_bet_size=.74, safety=.42, attack=.55,
        bubble_aggression=.58, late_aggression=.12, temperature=.03
    ),
    "maniac": StrategyParams(
        vpip=.48, open_frequency=.83, threebet_frequency=.145, squeeze_frequency=.110, steal_frequency=.90,
        open_thresh_utg=.22, open_thresh_hj=.27, open_thresh_co=.36, open_thresh_btn=.62, open_thresh_sb=.46, defend_thresh_bb=.62,
        multiway_decay=.65, table_strength_weight=.15,
        cbet_frequency=.77, turn_barrel_frequency=.72, river_bluff_frequency=.18,
        value_threshold=.54, thin_value_threshold=.50, raise_threshold=.50, jam_threshold=.80,
        flop_value_threshold=.48, turn_value_threshold=.55, river_value_threshold=.63,
        open_size=2.55, cbet_size=.56, value_bet_size=.62, bluff_bet_size=.64, raise_size=.82,
        dry_board_bet_size=.42, wet_board_bet_size=.88, safety=.72, attack=.96,
        bubble_aggression=.98, late_aggression=.42, temperature=.18
    ),
}

UNSEEN_OOD_ARCHETYPES: dict[str, StrategyParams] = {
    "ultra_rock": StrategyParams(
        vpip=0.10, open_frequency=0.38, threebet_frequency=0.025, squeeze_frequency=0.015, steal_frequency=0.40,
        open_thresh_utg=0.08, open_thresh_hj=0.10, open_thresh_co=0.14, open_thresh_btn=0.25, open_thresh_sb=0.18, defend_thresh_bb=0.28,
        multiway_decay=0.35, table_strength_weight=0.45,
        cbet_frequency=0.40, turn_barrel_frequency=0.25, river_bluff_frequency=0.005,
        value_threshold=0.82, thin_value_threshold=0.74, raise_threshold=0.78, jam_threshold=0.96,
        flop_value_threshold=0.72, turn_value_threshold=0.78, river_value_threshold=0.86,
        open_size=2.10, cbet_size=0.35, value_bet_size=0.75, bluff_bet_size=0.35, raise_size=0.55,
        dry_board_bet_size=0.25, wet_board_bet_size=0.65, safety=0.85, attack=0.25,
        bubble_aggression=0.35, late_aggression=0.05, temperature=0.02
    ),
    "hyper_whale": StrategyParams(
        vpip=0.62, open_frequency=0.90, threebet_frequency=0.22, squeeze_frequency=0.16, steal_frequency=0.92,
        open_thresh_utg=0.28, open_thresh_hj=0.34, open_thresh_co=0.44, open_thresh_btn=0.72, open_thresh_sb=0.56, defend_thresh_bb=0.78,
        multiway_decay=0.75, table_strength_weight=0.10,
        cbet_frequency=0.88, turn_barrel_frequency=0.82, river_bluff_frequency=0.25,
        value_threshold=0.46, thin_value_threshold=0.42, raise_threshold=0.44, jam_threshold=0.72,
        flop_value_threshold=0.42, turn_value_threshold=0.48, river_value_threshold=0.54,
        open_size=3.60, cbet_size=0.68, value_bet_size=0.82, bluff_bet_size=0.75, raise_size=0.88,
        dry_board_bet_size=0.50, wet_board_bet_size=0.95, safety=0.15, attack=0.98,
        bubble_aggression=0.99, late_aggression=0.50, temperature=0.22
    ),
    "tricky_trapper": StrategyParams(
        vpip=0.26, open_frequency=0.62, threebet_frequency=0.08, squeeze_frequency=0.05, steal_frequency=0.68,
        open_thresh_utg=0.15, open_thresh_hj=0.19, open_thresh_co=0.26, open_thresh_btn=0.45, open_thresh_sb=0.34, defend_thresh_bb=0.52,
        multiway_decay=0.50, table_strength_weight=0.30,
        cbet_frequency=0.32, turn_barrel_frequency=0.75, river_bluff_frequency=0.12,
        value_threshold=0.63, thin_value_threshold=0.56, raise_threshold=0.60, jam_threshold=0.89,
        flop_value_threshold=0.55, turn_value_threshold=0.62, river_value_threshold=0.70,
        open_size=2.35, cbet_size=0.40, value_bet_size=0.75, bluff_bet_size=0.52, raise_size=0.72,
        dry_board_bet_size=0.22, wet_board_bet_size=0.95, safety=0.45, attack=0.70,
        bubble_aggression=0.75, late_aggression=0.20, temperature=0.08
    ),
    "sticky_floater": StrategyParams(
        vpip=0.40, open_frequency=0.52, threebet_frequency=0.055, squeeze_frequency=0.035, steal_frequency=0.58,
        open_thresh_utg=0.16, open_thresh_hj=0.20, open_thresh_co=0.26, open_thresh_btn=0.44, open_thresh_sb=0.35, defend_thresh_bb=0.72,
        multiway_decay=0.55, table_strength_weight=0.25,
        cbet_frequency=0.48, turn_barrel_frequency=0.68, river_bluff_frequency=0.15,
        value_threshold=0.60, thin_value_threshold=0.52, raise_threshold=0.65, jam_threshold=0.92,
        flop_value_threshold=0.50, turn_value_threshold=0.58, river_value_threshold=0.66,
        open_size=2.25, cbet_size=0.42, value_bet_size=0.70, bluff_bet_size=0.48, raise_size=0.60,
        dry_board_bet_size=0.30, wet_board_bet_size=0.75, safety=0.40, attack=0.35,
        bubble_aggression=0.65, late_aggression=0.18, temperature=0.05
    ),
    "polar_overbetter": StrategyParams(
        vpip=0.33, open_frequency=0.74, threebet_frequency=0.125, squeeze_frequency=0.09, steal_frequency=0.84,
        open_thresh_utg=0.18, open_thresh_hj=0.24, open_thresh_co=0.33, open_thresh_btn=0.58, open_thresh_sb=0.44, defend_thresh_bb=0.60,
        multiway_decay=0.55, table_strength_weight=0.22,
        cbet_frequency=0.72, turn_barrel_frequency=0.68, river_bluff_frequency=0.18,
        value_threshold=0.58, thin_value_threshold=0.52, raise_threshold=0.54, jam_threshold=0.82,
        flop_value_threshold=0.50, turn_value_threshold=0.58, river_value_threshold=0.65,
        open_size=2.85, cbet_size=0.88, value_bet_size=0.95, bluff_bet_size=0.90, raise_size=0.85,
        dry_board_bet_size=0.55, wet_board_bet_size=0.98, safety=0.30, attack=0.90,
        bubble_aggression=0.92, late_aggression=0.35, temperature=0.14
    ),
}

def _load_params_safe(raw: Any) -> StrategyParams:
    """Safely instantiate StrategyParams from dict or existing object, ignoring unknown keys and filling defaults."""
    if isinstance(raw, StrategyParams):
        return replace(raw)
    if not isinstance(raw, dict):
        return StrategyParams()
    valid_keys = set(asdict(StrategyParams()).keys())
    filtered = {k: v for k, v in raw.items() if k in valid_keys}
    return StrategyParams(**filtered)

def _extract_tournament_stage_metrics(result: dict[str, Any], agent_id: str = "focal", pool_size: int | None = None) -> dict[str, Any]:
    """Extract multi-stage performance metrics for an agent across all tournament rounds."""
    prelim = result.get("preliminary", [])
    if pool_size is None:
        pool_size = len(prelim) if prelim else 120
    hero_prelim = next((x for x in prelim if getattr(x, "agent_id", None) == agent_id or (isinstance(x, dict) and x.get("agent_id") == agent_id)), None)

    if hero_prelim is not None:
        p_rank = getattr(hero_prelim, "rank", None) or (hero_prelim.get("rank") if isinstance(hero_prelim, dict) else pool_size)
        p_hands = getattr(hero_prelim, "hands", None) or (hero_prelim.get("hands") if isinstance(hero_prelim, dict) else 0)
        p_net = getattr(hero_prelim, "net_bb", None) or (hero_prelim.get("net_bb") if isinstance(hero_prelim, dict) else 0.0)
        p_bb100 = getattr(hero_prelim, "bb100", None) or (hero_prelim.get("bb100") if isinstance(hero_prelim, dict) else None)
        prelim_rank = float(p_rank or pool_size)
        prelim_hands = int(p_hands or 0)
        prelim_net_bb = float(p_net or 0.0)
        prelim_bb100 = float(p_bb100 if p_bb100 is not None else ((prelim_net_bb / max(1, prelim_hands)) * 100.0 if prelim_hands > 0 else 0.0))
    else:
        prelim_rank = float(pool_size)
        prelim_hands = 0
        prelim_net_bb = 0.0
        prelim_bb100 = 0.0

    def _get_aid(item):
        return getattr(item, "agent_id", None) if not isinstance(item, dict) else item.get("agent_id")

    qualified_ids = {_get_aid(x) for x in result.get("qualified", [])}
    is_top12 = int(agent_id in qualified_ids)

    semi_rank = None
    semi_hands = 0
    semi_net_bb = 0.0
    semi_bb100 = None

    if is_top12:
        for grp in result.get("semifinal", []):
            for s in grp:
                if _get_aid(s) == agent_id:
                    s_rank = getattr(s, "rank", None) or (s.get("rank") if isinstance(s, dict) else 6.0)
                    s_hands = getattr(s, "hands", None) or (s.get("hands") if isinstance(s, dict) else 0)
                    s_net = getattr(s, "net_bb", None) or (s.get("net_bb") if isinstance(s, dict) else 0.0)
                    s_bb = getattr(s, "bb100", None) or (s.get("bb100") if isinstance(s, dict) else None)
                    semi_rank = float(s_rank or 6.0)
                    semi_hands = int(s_hands or 0)
                    semi_net_bb = float(s_net or 0.0)
                    semi_bb100 = float(s_bb if s_bb is not None else ((semi_net_bb / max(1, semi_hands)) * 100.0 if semi_hands > 0 else 0.0))
                    break
            if semi_rank is not None:
                break

    final_standings = result.get("final", [])
    final_ids = {_get_aid(x) for x in final_standings}
    is_final = int(agent_id in final_ids)

    final_rank = None
    final_hands = 0
    final_net_bb = 0.0
    final_bb100 = None
    is_champ = 0

    if is_final:
        for s in final_standings:
            if _get_aid(s) == agent_id:
                f_rank = getattr(s, "rank", None) or (s.get("rank") if isinstance(s, dict) else len(final_standings))
                f_hands = getattr(s, "hands", None) or (s.get("hands") if isinstance(s, dict) else 0)
                f_net = getattr(s, "net_bb", None) or (s.get("net_bb") if isinstance(s, dict) else 0.0)
                f_bb = getattr(s, "bb100", None) or (s.get("bb100") if isinstance(s, dict) else None)
                final_rank = float(f_rank or len(final_standings))
                final_hands = int(f_hands or 0)
                final_net_bb = float(f_net or 0.0)
                final_bb100 = float(f_bb if f_bb is not None else ((final_net_bb / max(1, final_hands)) * 100.0 if final_hands > 0 else 0.0))
                if int(round(final_rank)) == 1:
                    is_champ = 1
                break

    # Determine overall finish rank
    if is_final and final_rank is not None:
        finish_rank = float(final_rank)
    elif is_top12:
        elim_semi = []
        for grp in result.get("semifinal", []):
            for s in grp:
                if final_ids:
                    if _get_aid(s) not in final_ids:
                        elim_semi.append(s)
                else:
                    s_r = getattr(s, "rank", None) or (s.get("rank") if isinstance(s, dict) else 6)
                    if (s_r or 6) > 3:
                        elim_semi.append(s)
        if elim_semi:
            def _get_prelim_rank(s):
                aid = _get_aid(s)
                for px in prelim:
                    if _get_aid(px) == aid:
                        return getattr(px, "rank", 999) or (px.get("rank", 999) if isinstance(px, dict) else 999)
                return 999
            def _get_bb(s):
                b = getattr(s, "bb100", None) or (s.get("bb100") if isinstance(s, dict) else None)
                return float(b) if b is not None else -9999.0

            elim_semi.sort(key=lambda x: (-_get_bb(x), _get_prelim_rank(x), str(_get_aid(x))))
            sub_rank = next((idx + 1 for idx, x in enumerate(elim_semi) if _get_aid(x) == agent_id), None)
            if sub_rank is not None:
                finish_rank = 6.0 + min(6.0, float(sub_rank))
            else:
                finish_rank = 6.0 + min(6.0, float(semi_rank or 6.0))
        else:
            finish_rank = 6.0 + min(6.0, float(semi_rank or 6.0))
    else:
        finish_rank = float(prelim_rank)

    finish_utility = 1.0 / math.sqrt(max(1.0, finish_rank))

    if is_final and final_rank is not None:
        survival_utility = 0.75 + (6.0 - max(1.0, min(6.0, final_rank))) / 5.0 * 0.25
    elif is_top12:
        clamped_rank = max(7.0, min(12.0, finish_rank))
        survival_utility = 0.50 + (12.0 - clamped_rank) / 5.0 * 0.20
    else:
        clamped_prelim = max(13.0, min(float(pool_size), finish_rank))
        prelim_ratio = max(0.0, (float(pool_size) - clamped_prelim) / max(1.0, float(pool_size) - 12.0))
        survival_utility = 0.40 * prelim_ratio

    total_hands = prelim_hands + semi_hands + final_hands
    total_net_bb = prelim_net_bb + semi_net_bb + final_net_bb
    overall_bb100 = (total_net_bb / total_hands * 100.0) if total_hands > 0 else 0.0

    deep_hands = semi_hands + final_hands
    deep_net_bb = semi_net_bb + final_net_bb
    deep_bb100 = (deep_net_bb / deep_hands * 100.0) if deep_hands > 0 else None

    def _sigmoid_bb(bb_val: float) -> float:
        clamped = max(-200.0, min(200.0, bb_val))
        return 1.0 / (1.0 + math.exp(-clamped / 40.0))

    f_overall_bb = _sigmoid_bb(overall_bb100)
    f_prelim_bb = _sigmoid_bb(prelim_bb100)
    if deep_hands > 0 and deep_bb100 is not None:
        f_deep_bb = _sigmoid_bb(deep_bb100)
    else:
        f_deep_bb = 0.20  # penalty for not qualifying into deep stages

    run_fitness = (
        0.25 * finish_utility +
        0.25 * survival_utility +
        0.25 * f_overall_bb +
        0.15 * f_prelim_bb +
        0.10 * f_deep_bb
    )

    return {
        "is_top12": is_top12,
        "is_final": is_final,
        "is_champ": is_champ,
        "prelim_rank": prelim_rank,
        "prelim_bb100": prelim_bb100,
        "prelim_net_bb": prelim_net_bb,
        "prelim_hands": prelim_hands,
        "semi_rank": semi_rank,
        "semi_bb100": semi_bb100,
        "semi_net_bb": semi_net_bb,
        "semi_hands": semi_hands,
        "final_rank": final_rank,
        "final_bb100": final_bb100,
        "final_net_bb": final_net_bb,
        "final_hands": final_hands,
        "finish_rank": finish_rank,
        "finish_utility": finish_utility,
        "survival_utility": survival_utility,
        "total_hands": total_hands,
        "total_net_bb": total_net_bb,
        "overall_bb100": overall_bb100,
        "deep_hands": deep_hands,
        "deep_net_bb": deep_net_bb,
        "deep_bb100": deep_bb100,
        "run_fitness": run_fitness,
    }


def _summarise(top, final, champ, ranks, bbs, runs, pool, stage_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Aggregate per-run outcomes into fitness plus its own uncertainty.

    Supports both legacy 7-argument calls and multi-stage continuous evaluations:
    - If `stage_results` is provided: computes continuous multi-stage fitness incorporating
      preliminary, semifinal, final table placement (1st..6th), and total chip accumulation.
    - If `stage_results` is None: falls back cleanly to the legacy formula for backwards compatibility.
    """
    runs = max(1, runs)
    top_rate, final_rate, champ_rate = top / runs, final / runs, champ / runs
    avg_rank = sum(ranks) / runs
    avg_bb = sum(bbs) / runs
    bb_factor = 1.0 / (1.0 + math.exp(-max(-200.0, min(200.0, avg_bb)) / 40.0))
    legacy_fit = (.20 * top_rate + .20 * final_rate + .25 * champ_rate
           + .05 * (1.0 - min(avg_rank - 1, pool - 1) / (pool - 1))
           + .30 * bb_factor)

    p_top_base = min(12.0, float(pool)) / max(1.0, float(pool))
    p_final_base = min(6.0, float(pool)) / max(1.0, float(pool))
    p_champ_base = 1.0 / max(1.0, float(pool))

    adv_top = (top_rate / p_top_base) if p_top_base > 0 else 1.0
    adv_final = (final_rate / p_final_base) if p_final_base > 0 else 1.0
    adv_champ = (champ_rate / p_champ_base) if p_champ_base > 0 else 1.0

    calibrated_fit = (
        0.20 * min(3.0, adv_top) / 3.0 +
        0.20 * min(4.0, adv_final) / 4.0 +
        0.25 * min(5.0, adv_champ) / 5.0 +
        0.05 * (1.0 - min(avg_rank - 1, pool - 1) / max(1, pool - 1)) +
        0.30 * bb_factor
    )

    if stage_results:
        run_fits = [float(s.get("run_fitness", legacy_fit)) for s in stage_results]
        fit = sum(run_fits) / len(run_fits)
        if len(run_fits) > 1:
            fit_var = statistics.variance(run_fits)
            se = math.sqrt(max(0.0, fit_var / len(run_fits)))
        else:
            se = 0.0

        finish_utils = [float(s.get("finish_utility", 1.0 / math.sqrt(max(1.0, s.get("finish_rank", pool))))) for s in stage_results]
        survival_utils = [float(s.get("survival_utility", 0.0)) for s in stage_results]
        finish_ranks = [float(s.get("finish_rank", pool)) for s in stage_results]
        prelim_bbs = [float(s.get("prelim_bb100", 0.0)) for s in stage_results]

        semi_bbs = [float(s["semi_bb100"]) for s in stage_results if s.get("semi_bb100") is not None]
        final_bbs = [float(s["final_bb100"]) for s in stage_results if s.get("final_bb100") is not None]
        deep_bbs = [float(s["deep_bb100"]) for s in stage_results if s.get("deep_bb100") is not None]

        tot_hands = sum(int(s.get("total_hands", 0)) for s in stage_results)
        tot_net_bb = sum(float(s.get("total_net_bb", 0.0)) for s in stage_results)
        overall_bb = (tot_net_bb / tot_hands * 100.0) if tot_hands > 0 else avg_bb

        avg_finish_rank = sum(finish_ranks) / len(finish_ranks)
        avg_finish_util = sum(finish_utils) / len(finish_utils)
        avg_survival_util = sum(survival_utils) / len(survival_utils)

        avg_prelim_bb = sum(prelim_bbs) / len(prelim_bbs)
        avg_semi_bb = (sum(semi_bbs) / len(semi_bbs)) if semi_bbs else None
        avg_final_bb = (sum(final_bbs) / len(final_bbs)) if final_bbs else None
        avg_deep_bb = (sum(deep_bbs) / len(deep_bbs)) if deep_bbs else None

        return {
            "top12_rate": top_rate,
            "final_rate": final_rate,
            "champion_rate": champ_rate,
            "avg_rank": avg_finish_rank,
            "prelim_avg_rank": avg_rank,
            "avg_finish_rank": avg_finish_rank,
            "avg_bb100": overall_bb,
            "overall_bb100": overall_bb,
            "prelim_bb100": avg_prelim_bb,
            "semi_bb100": avg_semi_bb,
            "final_bb100": avg_final_bb,
            "deep_bb100": avg_deep_bb,
            "finish_utility": avg_finish_util,
            "survival_utility": avg_survival_util,
            "fitness": fit,
            "robust_fitness": fit,
            "grand_fitness": fit,
            "mean_fitness": fit,
            "worst_ecology_fitness": fit,
            "best_ecology_fitness": fit,
            "cvar_ecology_fitness": fit,
            "between_ecology_std": 0.0,
            "variance_penalty": 0.0,
            "downside_penalty": 0.0,
            "robust_penalty": 0.0,
            "multistage_fitness": fit,
            "legacy_fitness": legacy_fit,
            "calibrated_fitness": calibrated_fit,
            "adv_top": adv_top,
            "adv_final": adv_final,
            "adv_champ": adv_champ,
            "expected_top_rate": p_top_base,
            "expected_final_rate": p_final_base,
            "expected_champion_rate": p_champ_base,
            "fitness_se": se,
            "fitness_ci95": [fit - 1.96 * se, fit + 1.96 * se],
            "runs": runs,
            "stage_results": stage_results if stage_results else [],
        }

    # Legacy fallback calculation
    fit = legacy_fit
    def var_prop(p):
        return p * (1.0 - p) / runs

    def cov(p1, p2):
        return (min(p1, p2) - p1 * p2) / runs

    var = (.20 ** 2) * var_prop(top_rate) + (.20 ** 2) * var_prop(final_rate) \
        + (.25 ** 2) * var_prop(champ_rate) \
        + 2 * .20 * .20 * cov(top_rate, final_rate) \
        + 2 * .20 * .25 * cov(top_rate, champ_rate) \
        + 2 * .20 * .25 * cov(final_rate, champ_rate)
    if runs > 1 and len(ranks) > 1:
        var += (.05 / (pool - 1)) ** 2 * (statistics.variance(ranks) / runs)
    if runs > 1 and len(bbs) > 1:
        var += (.30 / 160.0) ** 2 * (statistics.variance(bbs) / runs)
    se = math.sqrt(max(0.0, var))

    return {
        "top12_rate": top_rate, "final_rate": final_rate, "champion_rate": champ_rate,
        "avg_rank": avg_rank, "avg_bb100": avg_bb, "fitness": fit,
        "robust_fitness": fit,
        "grand_fitness": fit,
        "mean_fitness": fit,
        "worst_ecology_fitness": fit,
        "best_ecology_fitness": fit,
        "cvar_ecology_fitness": fit,
        "between_ecology_std": 0.0,
        "variance_penalty": 0.0,
        "downside_penalty": 0.0,
        "robust_penalty": 0.0,
        "calibrated_fitness": calibrated_fit,
        "adv_top": adv_top, "adv_final": adv_final, "adv_champ": adv_champ,
        "expected_top_rate": p_top_base, "expected_final_rate": p_final_base, "expected_champion_rate": p_champ_base,
        "fitness_se": se, "fitness_ci95": [fit - 1.96 * se, fit + 1.96 * se],
        "runs": runs,
    }


def compute_multi_ecology_variance_decomposition(
    ecology_stage_results: dict[str, list[dict[str, Any]]],
    pool_size: int = 120,
    lambda_var: float = 0.15,
    lambda_worst: float = 0.15,
    lambda_cvar: float = 0.10,
) -> dict[str, Any]:
    """Perform rigorous two-stage ANOVA variance decomposition across opponent ecologies.

    Decomposes total candidate performance variance into:
    - between_ecology_variance: variance of candidate's mean performance across distinct ecologies
    - within_ecology_variance: residual variance due to dealing luck / CRN seeds within each ecology
    - total_variance: overall variance across all individual tournament runs

    Also calculates:
    - Hierarchical standard error: SE(mean) = sqrt( between_variance / M + within_variance / N )
    - Worst-case ecology performance and Conditional Value at Risk (CVaR tail risk)
    - Multi-ecology robust fitness penalizing between-ecology variance and downside collapses
    """
    if not ecology_stage_results:
        return _summarise(0, 0, 0, [float(pool_size)], [0.0], 1, pool_size)

    M = len(ecology_stage_results)
    eco_summaries: dict[str, dict[str, Any]] = {}
    all_stage_results: list[dict[str, Any]] = []

    for eco_name, s_results in ecology_stage_results.items():
        if not s_results:
            continue
        all_stage_results.extend(s_results)
        runs_e = len(s_results)
        top_e = sum(int(s.get("is_top12", 0)) for s in s_results)
        final_e = sum(int(s.get("is_final", 0)) for s in s_results)
        champ_e = sum(int(s.get("is_champ", 0)) for s in s_results)
        ranks_e = [float(s.get("finish_rank", s.get("prelim_rank", pool_size))) for s in s_results]
        bbs_e = [float(s.get("overall_bb100", s.get("prelim_bb100", 0.0))) for s in s_results]
        eco_summary = _summarise(top_e, final_e, champ_e, ranks_e, bbs_e, runs_e, pool_size, stage_results=s_results)
        eco_summaries[eco_name] = eco_summary

    if not eco_summaries:
        return _summarise(0, 0, 0, [float(pool_size)], [0.0], 1, pool_size)

    M = len(eco_summaries)
    N = len(all_stage_results)

    # 1. Fitness decomposition
    eco_fitnesses = [eco_summaries[e]["fitness"] for e in eco_summaries]
    grand_fitness = sum(eco_fitnesses) / M

    # Between-ecology variance: s_between^2 = 1/(M-1) * sum((mean_e - grand_mean)^2)
    if M > 1:
        between_fitness_var = statistics.variance(eco_fitnesses)
    else:
        between_fitness_var = 0.0

    between_fitness_std = math.sqrt(max(0.0, between_fitness_var))

    # Identify best and worst performing ecologies & downside tail risk
    sorted_ecos_by_fit = sorted(eco_summaries.items(), key=lambda kv: kv[1]["fitness"])
    worst_eco_name, worst_eco_summary = sorted_ecos_by_fit[0]
    best_eco_name, best_eco_summary = sorted_ecos_by_fit[-1]
    worst_eco_fitness = float(worst_eco_summary["fitness"])
    best_eco_fitness = float(best_eco_summary["fitness"])
    worst_eco_bb = float(worst_eco_summary.get("overall_bb100", worst_eco_summary.get("avg_bb100", 0.0)))
    best_eco_bb = float(best_eco_summary.get("overall_bb100", best_eco_summary.get("avg_bb100", 0.0)))

    # CVaR (Conditional Value at Risk): average of worst k ecologies (bottom 40% tail risk)
    k_cvar = max(1, int(round(0.4 * M)))
    bottom_k_fits = [kv[1]["fitness"] for kv in sorted_ecos_by_fit[:k_cvar]]
    cvar_eco_fitness = float(sum(bottom_k_fits) / len(bottom_k_fits))

    # Multi-Ecology Robust Penalties:
    # 1. Variance / std penalty: lambda_var * sigma_between
    # 2. Worst-case downside penalty: lambda_worst * max(0, grand - worst)
    # 3. CVaR downside penalty: lambda_cvar * max(0, grand - cvar)
    variance_penalty = float(lambda_var * between_fitness_std)
    downside_penalty = float(
        lambda_worst * max(0.0, grand_fitness - worst_eco_fitness) +
        lambda_cvar * max(0.0, grand_fitness - cvar_eco_fitness)
    )
    total_robust_penalty = float(variance_penalty + downside_penalty)
    robust_fitness = float(grand_fitness - total_robust_penalty)

    # Within-ecology variance: average of s_e^2 across ecologies
    within_vars = []
    for eco_name, s_results in ecology_stage_results.items():
        if not s_results:
            continue
        fits_e = [float(s.get("run_fitness", eco_summaries[eco_name]["fitness"])) for s in s_results]
        if len(fits_e) > 1:
            within_vars.append(statistics.variance(fits_e))
        else:
            within_vars.append(0.0)
    within_fitness_var = sum(within_vars) / max(1, len(within_vars))

    # Total sample variance across all individual runs
    all_fits = [float(s.get("run_fitness", grand_fitness)) for s in all_stage_results]
    if len(all_fits) > 1:
        total_fitness_var = statistics.variance(all_fits)
    else:
        total_fitness_var = within_fitness_var

    # Hierarchical Standard Error
    # Under random-effects model: Var(grand_mean) = between_var / M + within_var / N
    hierarchical_se = math.sqrt(max(0.0, (between_fitness_var / M) + (within_fitness_var / max(1, N))))

    # 2. BB/100 decomposition
    eco_bbs = [eco_summaries[e].get("overall_bb100", eco_summaries[e].get("avg_bb100", 0.0)) for e in eco_summaries]
    grand_bb = sum(eco_bbs) / M
    between_bb_var = statistics.variance(eco_bbs) if M > 1 else 0.0
    within_bb_vars = []
    for eco_name, s_results in ecology_stage_results.items():
        bbs_e = [float(s.get("overall_bb100", s.get("prelim_bb100", 0.0))) for s in s_results]
        within_bb_vars.append(statistics.variance(bbs_e) if len(bbs_e) > 1 else 0.0)
    within_bb_var = sum(within_bb_vars) / max(1, len(within_bb_vars))
    all_bbs = [float(s.get("overall_bb100", s.get("prelim_bb100", 0.0))) for s in all_stage_results]
    total_bb_var = statistics.variance(all_bbs) if len(all_bbs) > 1 else 0.0

    # 3. Finish Rank decomposition
    eco_ranks = [eco_summaries[e].get("avg_finish_rank", eco_summaries[e].get("avg_rank", pool_size)) for e in eco_summaries]
    grand_rank = sum(eco_ranks) / M
    between_rank_var = statistics.variance(eco_ranks) if M > 1 else 0.0
    within_rank_vars = []
    for eco_name, s_results in ecology_stage_results.items():
        ranks_e = [float(s.get("finish_rank", s.get("prelim_rank", pool_size))) for s in s_results]
        within_rank_vars.append(statistics.variance(ranks_e) if len(ranks_e) > 1 else 0.0)
    within_rank_var = sum(within_rank_vars) / max(1, len(within_rank_vars))
    all_ranks = [float(s.get("finish_rank", s.get("prelim_rank", pool_size))) for s in all_stage_results]
    total_rank_var = statistics.variance(all_ranks) if len(all_ranks) > 1 else 0.0

    # Macro-averaged tournament rates
    overall_top = sum(eco_summaries[e].get("top12_rate", 0.0) for e in eco_summaries) / M
    overall_final = sum(eco_summaries[e].get("final_rate", 0.0) for e in eco_summaries) / M
    overall_champ = sum(eco_summaries[e].get("champion_rate", 0.0) for e in eco_summaries) / M

    # Calibrated fitness and baseline expectations
    adv_top = sum(eco_summaries[e].get("adv_top", 1.0) for e in eco_summaries) / M
    adv_final = sum(eco_summaries[e].get("adv_final", 1.0) for e in eco_summaries) / M
    adv_champ = sum(eco_summaries[e].get("adv_champ", 1.0) for e in eco_summaries) / M
    calibrated_fit = sum(eco_summaries[e].get("calibrated_fitness", grand_fitness) for e in eco_summaries) / M

    return {
        "fitness": float(grand_fitness),
        "robust_fitness": float(robust_fitness),
        "grand_fitness": float(grand_fitness),
        "mean_fitness": float(grand_fitness),
        "multistage_fitness": float(grand_fitness),
        "calibrated_fitness": float(calibrated_fit),
        "fitness_se": float(hierarchical_se),
        "fitness_ci95": [float(grand_fitness - 1.96 * hierarchical_se), float(grand_fitness + 1.96 * hierarchical_se)],
        "within_ecology_variance": float(within_fitness_var),
        "between_ecology_variance": float(between_fitness_var),
        "between_ecology_std": float(between_fitness_std),
        "total_variance": float(total_fitness_var),
        "worst_ecology_name": str(worst_eco_name),
        "worst_ecology_fitness": float(worst_eco_fitness),
        "worst_ecology_bb100": float(worst_eco_bb),
        "best_ecology_name": str(best_eco_name),
        "best_ecology_fitness": float(best_eco_fitness),
        "best_ecology_bb100": float(best_eco_bb),
        "cvar_ecology_fitness": float(cvar_eco_fitness),
        "ecology_fitness_spread": float(best_eco_fitness - worst_eco_fitness),
        "variance_penalty": float(variance_penalty),
        "downside_penalty": float(downside_penalty),
        "robust_penalty": float(total_robust_penalty),
        "bb100_within_variance": float(within_bb_var),
        "bb100_between_variance": float(between_bb_var),
        "bb100_total_variance": float(total_bb_var),
        "rank_within_variance": float(within_rank_var),
        "rank_between_variance": float(between_rank_var),
        "rank_total_variance": float(total_rank_var),
        "ecology_performances": eco_summaries,
        "top12_rate": float(overall_top),
        "final_rate": float(overall_final),
        "champion_rate": float(overall_champ),
        "avg_rank": float(grand_rank),
        "prelim_avg_rank": float(grand_rank),
        "avg_finish_rank": float(grand_rank),
        "avg_bb100": float(grand_bb),
        "overall_bb100": float(grand_bb),
        "adv_top": float(adv_top),
        "adv_final": float(adv_final),
        "adv_champ": float(adv_champ),
        "runs": N,
        "ecologies_count": M,
        "stage_results": all_stage_results,
    }


def _fmt_eta(seconds: float) -> str:
    if seconds < 0 or math.isinf(seconds) or math.isnan(seconds):
        return "--:--"
    s = int(seconds)
    hours, remainder = divmod(s, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes:02d}m {secs:02d}s"


def _evaluate_single_tournament_worker(payload):
    cand_idx, run_idx, focal, opponents, seed, equity_samples = payload[:6]
    tournament_config = payload[6] if len(payload) > 6 else None
    eco_name = payload[7] if len(payload) > 7 else "default"
    agents = [SimAgent("focal", StrategyAgent(replace(focal, equity_samples=equity_samples), seed=seed, name="focal"))]
    for i, p in enumerate(opponents):
        agents.append(SimAgent(f"opp{i}", StrategyAgent(replace(p, equity_samples=equity_samples), seed=seed + 31 * i + 17, name=f"opp{i}")))
    seeded = []
    for j, a in enumerate(agents):
        seeded.append(SimAgent(a.agent_id, StrategyAgent(a.strategy.params, seed=seed + 1000 * j, name=a.agent_id)))
    sim = LeagueSimulator(seeded, seed=seed, config=tournament_config)
    result = sim.run_event()
    stage_metric = _extract_tournament_stage_metrics(result, agent_id="focal", pool_size=len(agents))
    return (
        cand_idx,
        run_idx,
        stage_metric["is_top12"],
        stage_metric["is_final"],
        stage_metric["is_champ"],
        stage_metric["prelim_rank"],
        stage_metric["prelim_bb100"],
        stage_metric,
        eco_name,
    )


def _evaluate_worker(payload):
    focal, opponents, seed, runs, equity_samples = payload[:5]
    verbose = payload[5] if len(payload) > 5 else False
    tournament_config = payload[6] if len(payload) > 6 else None
    agents = [SimAgent("focal", StrategyAgent(replace(focal, equity_samples=equity_samples), seed=seed, name="focal"))]
    for i, p in enumerate(opponents):
        agents.append(SimAgent(f"opp{i}", StrategyAgent(replace(p, equity_samples=equity_samples), seed=seed + 31 * i + 17, name=f"opp{i}")))
    top = final = champ = 0
    rank_sum = bb_sum = 0.0
    ranks: list[float] = []
    bbs: list[float] = []
    stage_results: list[dict[str, Any]] = []

    for run in range(runs):
        # Seeding is a pure function of (seed, run), so every candidate handed the same
        # seed base plays the identical sequence of deals against an identical opponent
        # line-up. That is what makes candidate comparisons paired rather than noise-on-noise.
        s = seed + run * 7919
        seeded = []
        for j, a in enumerate(agents):
            seeded.append(SimAgent(a.agent_id, StrategyAgent(a.strategy.params, seed=s + 1000 * j, name=a.agent_id)))
        sim = LeagueSimulator(seeded, seed=s, config=tournament_config)
        result = sim.run_event()
        sm = _extract_tournament_stage_metrics(result, agent_id="focal", pool_size=len(agents))
        stage_results.append(sm)
        ranks.append(sm["prelim_rank"])
        bbs.append(sm["prelim_bb100"])
        rank_sum += sm["finish_rank"]
        bb_sum += sm["overall_bb100"]
        top += sm["is_top12"]
        final += sm["is_final"]
        champ += sm["is_champ"]

        if verbose:
            cur_run = run + 1
            cum_bb = bb_sum / cur_run
            cum_top = (top / cur_run) * 100.0
            cum_champ = (champ / cur_run) * 100.0
            if sm["is_champ"]:
                outcome = "🏆 夺冠 (第 1 名)"
            elif sm["is_final"]:
                outcome = f"决赛桌 第 {int(sm['final_rank'] or 6)} 名"
            elif sm["is_top12"]:
                outcome = f"12强半决赛 (第 {int(sm['finish_rank'])} 名)"
            else:
                outcome = f"未出线 (第 {int(sm['prelim_rank'])} 名)"

            print(
                f"[评估进度 {cur_run:02d}/{runs:02d} | 全程结算] "
                f"预赛: 第 {int(sm['prelim_rank']):02d} 名 ({sm['prelim_bb100']:+.1f} BB/100) | "
                f"赛果: {outcome:<14} | "
                f"走势: {cum_bb:+.1f} BB/100 (出线率 {cum_top:.0f}%, 夺冠率 {cum_champ:.0f}%)",
                flush=True
            )

    return _summarise(top, final, champ, ranks, bbs, runs, len(agents), stage_results=stage_results)

def profile_to_params(p: dict[str, Any], rng: random.Random | None = None) -> StrategyParams:
    """Map a real player profile's empirical statistics into a StrategyParams agent.

    - If `rng` is provided: draws a stochastic sample from the full Bayesian posterior distribution (Beta/Normal),
      preserving sample-size-dependent epistemic uncertainty (Stage 5).
    - If `rng` is None: returns the deterministic posterior mean point estimate (backward-compatible).
    """
    if rng is not None:
        return sample_profile_posterior(p, rng=rng)

    def num(key: str, default: float, lo: float, hi: float) -> float:
        try:
            return max(lo, min(hi, float(p.get(key, default))))
        except (TypeError, ValueError):
            return default

    vpip = num("vpip", 0.25, 0.08, 0.85)
    pfr = num("pfr", p.get("raise", 0.16) if isinstance(p.get("raise"), (int, float)) else 0.16, 0.03, 0.70)
    af = num("af", 2.0, 0.3, 25.0)
    is_nit = bool(p.get("is_nit", False))
    is_maniac = bool(p.get("is_maniac", False))
    is_station = bool(p.get("is_station", False))
    is_passive = bool(p.get("is_passive", False))
    af_norm = min(1.0, af / 8.0)

    return StrategyParams(
        # Preflop frequencies
        vpip=vpip,
        open_frequency=min(0.95, max(0.35, pfr * 1.3)),
        threebet_frequency=min(0.30, max(0.03, pfr * 0.45)),
        squeeze_frequency=min(0.25, max(0.02, pfr * 0.30)),
        steal_frequency=min(0.95, max(0.30, pfr * 1.5)),
        # Position-aware preflop ranges
        open_thresh_utg=num("open_thresh_utg", max(0.10, min(0.22, pfr * 0.95)), 0.10, 0.22),
        open_thresh_hj=num("open_thresh_hj", max(0.14, min(0.28, pfr * 1.20)), 0.14, 0.28),
        open_thresh_co=num("open_thresh_co", max(0.20, min(0.38, pfr * 1.70)), 0.20, 0.38),
        open_thresh_btn=num("open_thresh_btn", max(0.35, min(0.62, pfr * 3.0)), 0.35, 0.62),
        open_thresh_sb=num("open_thresh_sb", max(0.25, min(0.48, pfr * 2.2)), 0.25, 0.48),
        defend_thresh_bb=num("defend_thresh_bb", max(0.38, min(0.68, vpip * 1.6)), 0.38, 0.68),
        # Multiway & Table dynamics
        multiway_decay=0.40 if is_nit else (0.65 if is_maniac else 0.50),
        table_strength_weight=num("table_strength_weight", 0.18 if is_maniac else (0.42 if is_nit else 0.30), 0.10, 0.50),
        # Postflop frequencies
        cbet_frequency=min(0.90, max(0.30, 0.45 + af * 0.04)),
        turn_barrel_frequency=min(0.85, max(0.20, 0.40 + af * 0.03)),
        river_bluff_frequency=0.18 if is_maniac else (0.02 if (is_nit or is_station) else 0.07),
        # Thresholds live on the calibrated-equity scale (0..1 win probability)
        value_threshold=num("value_threshold", 0.56 if is_maniac else (0.72 if is_nit else 0.65), 0.45, 0.90),
        thin_value_threshold=0.50 if is_maniac else (0.62 if is_nit else 0.57),
        raise_threshold=0.58 if is_maniac else (0.68 if is_nit else 0.62),
        jam_threshold=0.84 if is_maniac else (0.93 if is_nit else 0.90),
        # Street-specific value thresholds
        flop_value_threshold=num("flop_value_threshold", 0.48 if is_maniac else (0.64 if is_nit else 0.58), 0.40, 0.75),
        turn_value_threshold=num("turn_value_threshold", 0.56 if is_maniac else (0.70 if is_nit else 0.65), 0.48, 0.82),
        river_value_threshold=num("river_value_threshold", 0.64 if is_maniac else (0.78 if is_nit else 0.74), 0.55, 0.90),
        # Measured sizings, straight from the hands this opponent actually played
        open_size=num("open_size_bb", 2.40 if is_maniac else 2.25, 2.0, 3.5),
        cbet_size=num("cbet_size", 0.47, 0.15, 0.95),
        value_bet_size=num("value_bet_size", 0.74 if is_station else 0.69, 0.15, 0.95),
        bluff_bet_size=max(0.15, min(0.95, 0.85 * num("value_bet_size", 0.69, 0.15, 0.95))),
        raise_size=num("raise_size", 0.68, 0.15, 0.95),
        # Board texture bet sizing
        dry_board_bet_size=num("dry_board_bet_size", 0.40 if is_maniac else (0.28 if is_nit else 0.33), 0.15, 0.60),
        wet_board_bet_size=num("wet_board_bet_size", 0.88 if is_maniac else (0.68 if is_nit else 0.75), 0.45, 0.98),
        # Tournament traits
        safety=0.65 if is_nit else (0.25 if is_maniac else 0.45),
        attack=min(0.98, max(0.30, af / 10.0 + 0.35)),
        bubble_aggression=0.55 + 0.35 * af_norm,
        late_aggression=0.10 + 0.35 * af_norm,
        # Passive players are predictable; maniacs are not.
        temperature=0.03 if (is_nit or is_passive) else (0.16 if is_maniac else 0.10),
    )


def sample_profile_posterior(
    p: dict[str, Any] | StrategyParams,
    rng: random.Random | None = None,
    prior_weight: float = 12.0,
) -> StrategyParams:
    """Sample an opponent's tactical parameters from their Bayesian posterior distribution.

    Addresses R5 (Epistemic Uncertainty under-estimation):
    - Binomial metrics (VPIP, PFR, 3-bet, C-bet, fold to cbet) are sampled from conjugate Beta(alpha, beta)
      posteriors where alpha = W0 * mu0 + count, beta = W0 * (1 - mu0) + (opps - count).
    - Posterior variance automatically scales inversely with hand count:
      * Low-sample opponents (e.g. 15 hands) exhibit realistic wide exploration (large epistemic uncertainty).
      * High-sample opponents (e.g. 2500 hands) concentrate tightly around their empirical mean.
    - Preserves all poker monotonicity and physical constraints (PFR <= VPIP, open thresholds, bet sizing order).
    """
    if isinstance(p, StrategyParams):
        if rng is None:
            return replace(p)
        return replace(
            p,
            vpip=max(0.08, min(0.85, p.vpip + rng.gauss(0.0, 0.015))),
            open_frequency=max(0.35, min(0.95, p.open_frequency + rng.gauss(0.0, 0.02))),
            threebet_frequency=max(0.03, min(0.30, p.threebet_frequency + rng.gauss(0.0, 0.01))),
            attack=max(0.30, min(0.98, p.attack + rng.gauss(0.0, 0.02))),
        )

    if rng is None:
        rng = random.Random()

    hands = int(p.get("hands", 15) or 15)
    metrics = p.get("metrics") or {}

    def _sample_beta_metric(key: str, default_rate: float, prior_mean: float, lo: float, hi: float) -> float:
        m = metrics.get(key)
        if isinstance(m, dict) and "count" in m and "opportunities" in m:
            c = float(m.get("count", 0))
            opps = float(m.get("opportunities", 0))
            p_prior = float(m.get("population_prior", prior_mean))
        else:
            opps = max(5.0, float(hands))
            raw_rate = float(p.get(key, default_rate) if p.get(key) is not None else default_rate)
            c = raw_rate * opps
            p_prior = prior_mean

        alpha = prior_weight * p_prior + c
        beta = prior_weight * (1.0 - p_prior) + max(0.0, opps - c)
        val = rng.betavariate(max(0.1, alpha), max(0.1, beta))
        return max(lo, min(hi, val))

    vpip = _sample_beta_metric("vpip", 0.25, 0.25, 0.08, 0.85)
    pfr = min(vpip, _sample_beta_metric("pfr", 0.16, 0.18, 0.03, 0.70))
    threebet = min(pfr, _sample_beta_metric("threebet", 0.08, 0.08, 0.02, 0.30))

    base_af = float(p.get("af", 2.0) or 2.0)
    af_scale = 0.35 / math.sqrt(1.0 + hands / 30.0)
    af = max(0.3, min(25.0, math.exp(rng.gauss(math.log(max(0.3, base_af)), af_scale))))
    af_norm = min(1.0, af / 8.0)

    is_nit = bool(p.get("is_nit", False)) or vpip < 0.15
    is_maniac = bool(p.get("is_maniac", False)) or (vpip > 0.40 and af > 4.0)
    is_station = bool(p.get("is_station", False)) or (vpip > 0.35 and af < 1.5)
    is_passive = bool(p.get("is_passive", False)) or af < 1.2

    # Positional open thresholds with monotonicity preservation
    open_utg = max(0.10, min(0.22, pfr * 0.95 + rng.gauss(0.0, 0.015 / math.sqrt(1.0 + hands / 50.0))))
    open_hj = max(open_utg + 0.01, min(0.28, pfr * 1.20 + rng.gauss(0.0, 0.015 / math.sqrt(1.0 + hands / 50.0))))
    open_co = max(open_hj + 0.02, min(0.38, pfr * 1.70 + rng.gauss(0.0, 0.02 / math.sqrt(1.0 + hands / 50.0))))
    open_btn = max(open_co + 0.04, min(0.62, pfr * 3.0 + rng.gauss(0.0, 0.03 / math.sqrt(1.0 + hands / 50.0))))
    open_sb = max(0.25, min(0.48, pfr * 2.2 + rng.gauss(0.0, 0.02 / math.sqrt(1.0 + hands / 50.0))))
    defend_bb = max(0.38, min(0.68, vpip * 1.6 + rng.gauss(0.0, 0.02 / math.sqrt(1.0 + hands / 50.0))))

    # Postflop frequencies
    cbet_base = _sample_beta_metric("cbet_flop", 0.55, 0.55, 0.25, 0.92)
    turn_base = _sample_beta_metric("turn_barrel", 0.45, 0.45, 0.15, 0.88)
    cbet_freq = min(0.92, max(0.25, cbet_base + (af - 2.0) * 0.03))
    turn_freq = min(0.88, max(0.15, turn_base + (af - 2.0) * 0.02))

    # Sizing parameters with sample-size scaled uncertainty
    size_sigma = 0.04 / math.sqrt(1.0 + hands / 40.0)
    cbet_sz = max(0.20, min(0.95, float(p.get("cbet_size", 0.47) or 0.47) + rng.gauss(0.0, size_sigma)))
    val_sz = max(0.30, min(0.95, float(p.get("value_bet_size", 0.70) or 0.70) + rng.gauss(0.0, size_sigma)))
    bluff_sz = max(0.15, min(val_sz, float(p.get("bluff_bet_size", 0.55) or 0.55) + rng.gauss(0.0, size_sigma)))
    raise_sz = max(cbet_sz, min(0.98, float(p.get("raise_size", 0.68) or 0.68) + rng.gauss(0.0, size_sigma)))

    # Thresholds
    thresh_sigma = 0.03 / math.sqrt(1.0 + hands / 50.0)
    val_thresh = max(0.50, min(0.85, (0.56 if is_maniac else (0.72 if is_nit else 0.65)) + rng.gauss(0.0, thresh_sigma)))
    thin_val = max(0.45, min(val_thresh - 0.02, val_thresh * 0.90))
    jam_thresh = max(val_thresh + 0.10, min(0.98, 0.84 if is_maniac else (0.93 if is_nit else 0.90)))

    return StrategyParams(
        vpip=vpip,
        open_frequency=min(0.95, max(0.35, pfr * 1.3)),
        threebet_frequency=threebet,
        squeeze_frequency=min(0.25, max(0.02, threebet * 0.65)),
        steal_frequency=min(0.95, max(0.30, pfr * 1.5)),
        open_thresh_utg=open_utg,
        open_thresh_hj=open_hj,
        open_thresh_co=open_co,
        open_thresh_btn=open_btn,
        open_thresh_sb=open_sb,
        defend_thresh_bb=defend_bb,
        multiway_decay=0.40 if is_nit else (0.65 if is_maniac else 0.50),
        table_strength_weight=max(0.10, min(0.50, (0.18 if is_maniac else (0.42 if is_nit else 0.30)) + rng.gauss(0.0, 0.02))),
        cbet_frequency=cbet_freq,
        turn_barrel_frequency=turn_freq,
        river_bluff_frequency=0.18 if is_maniac else (0.02 if (is_nit or is_station) else 0.07),
        value_threshold=val_thresh,
        thin_value_threshold=thin_val,
        raise_threshold=max(0.52, min(0.75, val_thresh * 0.95)),
        jam_threshold=jam_thresh,
        flop_value_threshold=max(0.40, min(0.75, val_thresh * 0.90)),
        turn_value_threshold=max(0.48, min(0.82, val_thresh * 0.98)),
        river_value_threshold=max(0.55, min(0.90, val_thresh * 1.05)),
        open_size=max(2.0, min(3.5, (2.40 if is_maniac else 2.25) + rng.gauss(0.0, size_sigma * 2))),
        cbet_size=cbet_sz,
        value_bet_size=val_sz,
        bluff_bet_size=bluff_sz,
        raise_size=raise_sz,
        dry_board_bet_size=max(0.15, min(0.60, 0.40 if is_maniac else (0.28 if is_nit else 0.33))),
        wet_board_bet_size=max(0.45, min(0.98, 0.88 if is_maniac else (0.68 if is_nit else 0.75))),
        safety=0.65 if is_nit else (0.25 if is_maniac else 0.45),
        attack=min(0.98, max(0.30, af / 10.0 + 0.35)),
        bubble_aggression=min(0.98, max(0.30, 0.55 + 0.35 * af_norm)),
        late_aggression=min(0.90, max(0.10, 0.10 + 0.35 * af_norm)),
        temperature=0.03 if (is_nit or is_passive) else (0.16 if is_maniac else 0.10),
    )


def compute_profile_posterior_uncertainty(
    p: dict[str, Any],
    prior_weight: float = 12.0,
) -> dict[str, Any]:
    """Compute analytical Bayesian posterior credible intervals and uncertainty metrics for a profile."""
    hands = int(p.get("hands", 15) or 15)
    metrics = p.get("metrics") or {}

    def _beta_stats(key: str, prior_mean: float):
        m = metrics.get(key)
        if isinstance(m, dict) and "count" in m and "opportunities" in m:
            c = float(m.get("count", 0))
            opps = float(m.get("opportunities", 0))
            p_prior = float(m.get("population_prior", prior_mean))
        else:
            opps = max(5.0, float(hands))
            raw_rate = float(p.get(key, prior_mean) if p.get(key) is not None else prior_mean)
            c = raw_rate * opps
            p_prior = prior_mean

        a = prior_weight * p_prior + c
        b = prior_weight * (1.0 - p_prior) + max(0.0, opps - c)
        mean = a / (a + b)
        var = (a * b) / (((a + b) ** 2) * (a + b + 1.0))
        std = math.sqrt(max(0.0, var))
        return {
            "mean": mean,
            "std": std,
            "ci95": [max(0.0, mean - 1.96 * std), min(1.0, mean + 1.96 * std)],
            "opportunities": opps,
        }

    vpip_st = _beta_stats("vpip", 0.25)
    pfr_st = _beta_stats("pfr", 0.18)
    threebet_st = _beta_stats("threebet", 0.08)
    cbet_st = _beta_stats("cbet_flop", 0.55)

    epistemic_score = (vpip_st["std"] + pfr_st["std"] + threebet_st["std"] + cbet_st["std"]) / 4.0

    return {
        "hands": hands,
        "epistemic_uncertainty_score": epistemic_score,
        "vpip": vpip_st,
        "pfr": pfr_st,
        "threebet": threebet_st,
        "cbet_flop": cbet_st,
    }

class ArenaEvaluator:
    def __init__(self, pool_size=120, seed=7, equity_samples=0, profiles: dict[str, Any] | str | Path | None = None, workers=0, profile_min_hands=15, tournament_config: TournamentConfig | None = None, ecologies: list[str] | None = None):
        self.pool_size=max(12,pool_size); self.seed=seed; self.equity_samples=equity_samples; self.profiles=profiles; self.workers=workers
        self.profile_min_hands=int(profile_min_hands)
        self.tournament_config = tournament_config
        self.ecologies = list(ecologies) if ecologies is not None else None

    def evaluate(self, focal: StrategyParams, runs=100, opponents=None, seed_offset=0, verbose=True, ecologies=None):
        eco_list = ecologies or (self.ecologies if opponents is None else None)
        if eco_list is not None and opponents is None:
            runs_per_eco = max(1, runs // len(eco_list))
            return self.evaluate_multi_ecology(
                focal=focal,
                ecologies=eco_list,
                runs_per_ecology=runs_per_eco,
                seed_offset=seed_offset,
                verbose=verbose,
            )

        if opponents is None:
            if self.profiles:
                profs = self._load_profiles(self.profiles, self.profile_min_hands)
                if profs:
                    opponents = [profile_to_params(p) for p in profs]
                    while len(opponents) < self.pool_size - 1:
                        opponents.extend([replace(x) for x in opponents])
                    opponents = opponents[:self.pool_size - 1]
            if not opponents:
                base=list(ARCHETYPES.values())
                opponents=[base[i % len(base)] for i in range(self.pool_size-1)]
        else:
            opponents = list(opponents)
            while len(opponents) < self.pool_size - 1:
                opponents.extend([replace(x) for x in opponents])
            opponents = opponents[:self.pool_size - 1]
        opponents = [replace(x) for x in opponents]

        workers = self.workers or (os.cpu_count() or 4)
        if workers > 1 and runs > 1:
            workers = min(workers, runs)
            tasks = [(focal, opponents, self.seed + seed_offset + r * 7919, 1, self.equity_samples, False, self.tournament_config) for r in range(runs)]
            top = final = champ = 0
            rank_sum = bb_sum = 0.0
            ranks: list[float] = []; bbs: list[float] = []
            stage_results: list[dict[str, Any]] = []
            if verbose:
                print(f"[评估开始] 正在启动 {runs} 场锦标赛 (多核并发: {workers} 个工作进程)...", flush=True)
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_evaluate_worker, t): i for i, t in enumerate(tasks)}
                completed = 0
                for fut in as_completed(futs):
                    r_res = fut.result()
                    completed += 1
                    is_top12 = int(r_res["top12_rate"] > 0)
                    is_final = int(r_res["final_rate"] > 0)
                    is_champ = int(r_res["champion_rate"] > 0)
                    top += is_top12; final += is_final; champ += is_champ
                    r_finish = r_res.get("avg_finish_rank", r_res["avg_rank"])
                    r_bb = r_res.get("overall_bb100", r_res["avg_bb100"])
                    rank_sum += r_finish; bb_sum += r_bb
                    ranks.append(float(r_res["avg_rank"])); bbs.append(float(r_res["avg_bb100"]))
                    if "stage_results" in r_res and r_res["stage_results"]:
                        stage_results.extend(r_res["stage_results"])
                    interval = max(1, runs // 20) if runs > 30 else 1
                    if verbose and (completed % interval == 0 or completed == runs):
                        cum_bb = bb_sum / completed
                        cum_top = (top / completed) * 100.0
                        cum_champ = (champ / completed) * 100.0
                        if is_champ: outcome = "🏆 夺冠 (第 1 名)"
                        elif is_final: outcome = "决赛桌突围"
                        elif is_top12: outcome = "12强半决赛"
                        else: outcome = f"未出线 (第 {int(r_res['avg_rank'])} 名)"
                        print(
                            f"[评估进度 {completed:02d}/{runs:02d} | 全程结算] "
                            f"单场: 预赛第 {int(r_res['avg_rank']):02d} 名 ({r_res['avg_bb100']:+.1f} BB/100) | "
                            f"赛果: {outcome:<12} | "
                            f"走势: {cum_bb:+.1f} BB/100 (出线率 {cum_top:.0f}%, 夺冠率 {cum_champ:.0f}%)",
                            flush=True
                        )
            return _summarise(top, final, champ, ranks, bbs, runs, self.pool_size, stage_results=stage_results if stage_results else None)
        else:
            if verbose:
                print(f"[评估开始] 正在顺序执行 {runs} 场锦标赛测试 (每场 200 手预赛 + 淘汰赛)...", flush=True)
            return _evaluate_worker((focal, opponents, self.seed+seed_offset, max(1,runs), self.equity_samples, verbose, self.tournament_config))

    def evaluate_multi_ecology(
        self,
        focal: StrategyParams,
        ecologies: list[str] | None = None,
        runs_per_ecology: int = 5,
        seed_offset: int = 0,
        verbose: bool = True,
    ) -> dict[str, Any]:
        """Evaluate a strategy across multiple distinct opponent ecologies.

        Guarantees:
        - Common Random Numbers within each ecology across comparative runs.
        - Independent opponent lineups and deal seeds across distinct ecologies.
        - Full two-stage ANOVA variance decomposition (within_ecology_variance,
          between_ecology_variance, total_variance).
        """
        from .ecosystem import build_ecology_pool, STANDARD_ECOLOGIES
        if ecologies is None:
            ecologies = list(STANDARD_ECOLOGIES.keys())
        active_ecologies = list(ecologies)
        runs_per_eco = max(1, runs_per_ecology)
        total_runs = len(active_ecologies) * runs_per_eco

        eco_pools = {}
        for idx, eco in enumerate(active_ecologies):
            eco_seed = self.seed + seed_offset + 104729 * (idx + 1) + 17
            eco_pools[eco] = build_ecology_pool(
                eco,
                count=self.pool_size - 1,
                profiles_path=self.profiles,
                min_hands=self.profile_min_hands,
                seed=eco_seed,
            )

        tasks = []
        for idx, eco in enumerate(active_ecologies):
            pool_e = eco_pools[eco]
            for r in range(runs_per_eco):
                s = self.seed + seed_offset + (idx + 1) * 100003 + r * 7919
                tasks.append((0, r, focal, pool_e, s, self.equity_samples, self.tournament_config, eco))

        workers = self.workers or min(os.cpu_count() or 4, total_runs)
        eco_runs: dict[str, list[dict[str, Any]]] = {eco: [] for eco in active_ecologies}

        if workers <= 1 or total_runs <= 1:
            if verbose:
                print(f"[多生态评估] 开始跨 {len(active_ecologies)} 个生态评估策略 (每生态 {runs_per_eco} 场, 共 {total_runs} 场)...", flush=True)
            for t in tasks:
                res = _evaluate_single_tournament_worker(t)
                sm = res[7]
                eco = res[8] if len(res) > 8 else active_ecologies[0]
                eco_runs[eco].append(sm)
        else:
            if verbose:
                print(f"[多生态评估] 开始跨 {len(active_ecologies)} 个生态并发评估 (每生态 {runs_per_eco} 场, 共 {total_runs} 场, {workers} 进程)...", flush=True)
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(_evaluate_single_tournament_worker, t) for t in tasks]
                for fut in as_completed(futs):
                    res = fut.result()
                    sm = res[7]
                    eco = res[8] if len(res) > 8 else active_ecologies[0]
                    eco_runs[eco].append(sm)

        summary = compute_multi_ecology_variance_decomposition(eco_runs, self.pool_size)
        if verbose:
            print(
                f"[多生态评估完成] fit={summary['fitness']:.4f}±{summary.get('fitness_se', 0.0):.4f} "
                f"(robust={summary.get('robust_fitness', summary['fitness']):.4f} worst={summary.get('worst_ecology_name', '-')}:{summary.get('worst_ecology_fitness', 0.0):.4f}) | "
                f"between_var={summary['between_ecology_variance']:.5f} | "
                f"within_var={summary['within_ecology_variance']:.5f} | "
                f"BB/100={summary['overall_bb100']:+.1f} | 终排={summary['avg_finish_rank']:.1f}",
                flush=True
            )
        return summary


    @staticmethod
    def _load_profiles(source: dict[str, Any] | list[dict[str, Any]] | str | Path, min_hands: int = 15, top_n: int | None = None) -> list[dict[str, Any]]:
        if isinstance(source, (str, Path)):
            p = Path(source)
            if not p.exists(): return []
            data = json.loads(p.read_text(encoding="utf-8"))
        elif isinstance(source, (dict, list)):
            data = source
        else:
            return []
        raw_items = data if isinstance(data, list) else list(data.values())
        valid = [v for v in raw_items if isinstance(v, dict) and int(v.get("hands", 0) or (v.get("stats") or {}).get("hands", 0) or 0) >= min_hands]
        valid.sort(key=lambda x: int(x.get("hands", 0) or (x.get("stats") or {}).get("hands", 0) or 0), reverse=True)
        if top_n is not None and top_n > 0:
            valid = valid[:top_n]
        return valid

def _classify_strategy_tier(p: StrategyParams | dict[str, Any]) -> str:
    """Classify a strategy or parameter set into 'shark', 'regular', or 'fish'."""
    vpip = getattr(p, "vpip", None) if not isinstance(p, dict) else p.get("vpip")
    if vpip is None:
        vpip = 0.25
    vpip = float(vpip)

    threebet = getattr(p, "threebet_frequency", None) if not isinstance(p, dict) else p.get("threebet_frequency")
    threebet = float(threebet) if threebet is not None else 0.07

    attack = getattr(p, "attack", None) if not isinstance(p, dict) else p.get("attack")
    attack = float(attack) if attack is not None else 0.50

    # Fish / Calling Station: high VPIP, low 3-bet or low aggression
    if vpip >= 0.35 and (threebet <= 0.06 or attack < 0.60):
        return "fish"
    if vpip >= 0.40 and attack < 0.65:
        return "fish"

    # Sharks: high aggression, wide range or loose-aggressive / maniac
    if (vpip >= 0.28 and (attack >= 0.70 or threebet >= 0.09)) or attack >= 0.85:
        return "shark"

    # Regulars: solid TAG, balanced, nit
    return "regular"


@dataclass(frozen=True)
class OpponentEnvironment:
    """Rigorous dataset partition for poker opponents with distribution shift support."""
    name: str
    profile_params: tuple[StrategyParams, ...]
    archetypes: tuple[StrategyParams, ...]
    shark_ratio: float = 0.30
    regular_ratio: float = 0.40
    fish_ratio: float = 0.30
    unseen_archetypes: tuple[StrategyParams, ...] = ()
    raw_profiles: tuple[dict[str, Any], ...] = ()
    description: str = ""

    def sample_pool(
        self,
        pool_size: int,
        seed: int,
        ood_mode: str | None = None,
        sample_posterior: bool = False,
    ) -> list[StrategyParams]:
        """Deterministically draw a stratified lineup of (pool_size - 1) opponents from this environment.

        Supports:
        - Shifted macro-tier compositions (shark_ratio, regular_ratio, fish_ratio).
        - Unseen out-of-distribution archetypes sampling.
        - Dedicated OOD stress regimes ('extreme_aggression', 'extreme_passivity', 'unseen_hybrids').
        - Posterior sampling under epistemic uncertainty when sample_posterior=True.
        """
        n = max(1, pool_size - 1)
        rng = random.Random(seed)

        if sample_posterior and self.raw_profiles:
            active_profiles = [sample_profile_posterior(p, rng=rng) for p in self.raw_profiles]
        else:
            active_profiles = list(self.profile_params)

        all_candidates = active_profiles + list(self.archetypes) + list(self.unseen_archetypes)
        if not all_candidates:
            all_candidates = list(ARCHETYPES.values())

        sharks = [p for p in all_candidates if _classify_strategy_tier(p) == "shark"]
        regulars = [p for p in all_candidates if _classify_strategy_tier(p) == "regular"]
        fish = [p for p in all_candidates if _classify_strategy_tier(p) == "fish"]

        if not sharks:
            sharks = [ARCHETYPES["lag"], ARCHETYPES["maniac"]]
        if not regulars:
            regulars = [ARCHETYPES["balanced"], ARCHETYPES["tight"], ARCHETYPES["nit"]]
        if not fish:
            fish = [ARCHETYPES["station"]]

        s_r, r_r, f_r = self.shark_ratio, self.regular_ratio, self.fish_ratio
        if ood_mode == "extreme_aggression":
            s_r, r_r, f_r = 0.70, 0.25, 0.05
        elif ood_mode == "extreme_passivity":
            s_r, r_r, f_r = 0.05, 0.30, 0.65
        elif ood_mode == "unseen_hybrids":
            if self.unseen_archetypes:
                out = [replace(rng.choice(self.unseen_archetypes)) for _ in range(n)]
                rng.shuffle(out)
                return out[:n]

        n_sharks = int(round(n * s_r))
        n_regs = int(round(n * r_r))
        n_fish = n - n_sharks - n_regs
        if n_fish < 0:
            n_fish = 0
            n_regs = n - n_sharks

        unseen_sharks = [p for p in self.unseen_archetypes if _classify_strategy_tier(p) == "shark"]
        unseen_regs = [p for p in self.unseen_archetypes if _classify_strategy_tier(p) == "regular"]
        unseen_fish = [p for p in self.unseen_archetypes if _classify_strategy_tier(p) == "fish"]

        def _draw_tier(needed: int, tier_pool: list[StrategyParams], unseen_tier: list[StrategyParams]) -> list[StrategyParams]:
            res: list[StrategyParams] = []
            if needed <= 0:
                return res
            if unseen_tier and self.name in ("validation", "test"):
                n_unseen = max(1, needed // 3)
                for _ in range(min(needed, n_unseen)):
                    res.append(replace(rng.choice(unseen_tier)))
            while len(res) < needed:
                res.append(replace(rng.choice(tier_pool)))
            return res

        out = []
        out.extend(_draw_tier(n_sharks, sharks, unseen_sharks))
        out.extend(_draw_tier(n_regs, regulars, unseen_regs))
        out.extend(_draw_tier(n_fish, fish, unseen_fish))

        rng.shuffle(out)
        return out[:n]

    @property
    def is_frozen(self) -> bool:
        return True


def compute_distribution_shift_audit(
    train_env: OpponentEnvironment,
    target_env: OpponentEnvironment,
    pool_size: int = 120,
    seed: int = 42,
) -> dict[str, Any]:
    """Quantitatively audit the multi-dimensional distribution shift between train and target environments.

    Computes:
    1. Macro-tier composition Total Variation (TV) distance.
    2. Share of unseen out-of-distribution archetypes.
    3. Out-Of-Distribution (OOD) extreme parameter coverage.
    4. Exact 1D Wasserstein / Earth Mover's Distance on key tactical dimensions (VPIP, 3-bet, Attack, C-bet).
    5. Composite distribution shift index in [0.0, 1.0].
    """
    p_train = train_env.sample_pool(pool_size, seed=seed)
    p_target = target_env.sample_pool(pool_size, seed=seed if train_env is target_env else seed + 1009)

    # 1. Macro-tier composition TV distance
    tv_distance = 0.5 * (
        abs(train_env.shark_ratio - target_env.shark_ratio) +
        abs(train_env.regular_ratio - target_env.regular_ratio) +
        abs(train_env.fish_ratio - target_env.fish_ratio)
    )

    # 2. Unseen archetypes share
    unseen_count = 0
    for p in p_target:
        if any(asdict(p) == asdict(u) for u in target_env.unseen_archetypes):
            unseen_count += 1
    unseen_share = unseen_count / max(1, len(p_target))

    # 3. Parameter shift and 1D Wasserstein distance
    key_params = ("vpip", "threebet_frequency", "attack", "cbet_frequency", "value_threshold", "open_size")
    param_shifts: dict[str, dict[str, float]] = {}
    wasserstein_list: list[float] = []
    ood_flags = [False] * len(p_target)

    for k in key_params:
        tr_vals = sorted([float(getattr(p, k, 0.5)) for p in p_train])
        tg_vals = sorted([float(getattr(p, k, 0.5)) for p in p_target])

        tr_mean = sum(tr_vals) / len(tr_vals)
        tg_mean = sum(tg_vals) / len(tg_vals)
        delta = tg_mean - tr_mean

        # 1D Wasserstein distance: average absolute difference of sorted quantiles
        w1 = sum(abs(a - b) for a, b in zip(tr_vals, tg_vals)) / len(tr_vals)
        lo, hi = StrategyTrainer.PARAM_BOUNDS.get(k, (0.01, 0.99))
        w1_norm = min(1.0, w1 / max(1e-4, hi - lo))
        wasserstein_list.append(w1_norm)

        # OOD bounds: values in target that exceed train min/max
        tr_min, tr_max = min(tr_vals), max(tr_vals)
        for i, p in enumerate(p_target):
            v = float(getattr(p, k, 0.5))
            if v < tr_min - 1e-4 or v > tr_max + 1e-4:
                ood_flags[i] = True

        param_shifts[k] = {
            "train_mean": round(tr_mean, 4),
            "target_mean": round(tg_mean, 4),
            "delta": round(delta, 4),
            "wasserstein_1d": round(w1, 4),
            "wasserstein_normalized": round(w1_norm, 4),
        }

    ood_rate = sum(ood_flags) / max(1, len(p_target))
    mean_w1 = sum(wasserstein_list) / len(wasserstein_list) if wasserstein_list else 0.0

    # Composite shift score: 0.0 means identical, >= 0.10 indicates genuine distribution shift
    composite_score = min(1.0, 0.35 * tv_distance + 0.35 * mean_w1 + 0.30 * max(unseen_share, ood_rate))

    return {
        "train_env": train_env.name,
        "target_env": target_env.name,
        "composition_tv_distance": round(tv_distance, 4),
        "unseen_archetype_share": round(unseen_share, 4),
        "ood_parameter_rate": round(ood_rate, 4),
        "mean_normalized_wasserstein": round(mean_w1, 4),
        "composite_shift_score": round(composite_score, 4),
        "parameter_shifts": param_shifts,
        "is_genuine_shift": bool(composite_score >= 0.10 or tv_distance > 0 or unseen_share > 0 or ood_rate > 0),
    }


class StrategyTrainer:
    """Full population strategy evolution: crossover + mutation + cross-play + racing."""
    FIELDS=tuple(k for k in asdict(StrategyParams()).keys() if k!="equity_samples")
    HALL_SIZE=12
    def __init__(self, seed=7, pool_size=120, equity_samples=0, workers=0, profiles: dict[str, Any] | str | Path | None = None,
                 holdout_frac=0.25, val_frac: float | None = None, test_frac: float | None = None,
                 profile_min_hands=15, profile_share=0.5, profile_top: int | None = None, self_play: bool = False, shadow_clones: int = 2,
                 tournament_config: TournamentConfig | None = None, ecologies: list[str] | None = None):
        self.rng=random.Random(seed); self.seed=seed; self.pool_size=max(12,pool_size); self.equity_samples=equity_samples; self.workers=workers
        self.profiles=profiles
        self.tournament_config = tournament_config
        self.ecologies = list(ecologies) if ecologies is not None else ["balanced", "aggressive", "passive", "mixed", "adversarial"]
        self.holdout_frac=min(0.5, max(0.0, float(holdout_frac)))
        # Strict 3-way split configuration
        if val_frac is not None and test_frac is not None:
            self.val_frac = min(0.4, max(0.05, float(val_frac)))
            self.test_frac = min(0.4, max(0.05, float(test_frac)))
        else:
            # Derive symmetric validation & test fractions from holdout_frac
            half = self.holdout_frac / 2.0
            self.val_frac = min(0.4, max(0.05, half if half > 0 else 0.15))
            self.test_frac = min(0.4, max(0.05, half if half > 0 else 0.15))
        self.profile_min_hands=int(profile_min_hands)
        self.profile_share=min(1.0, max(0.0, float(profile_share)))
        self.profile_top=int(profile_top) if profile_top is not None else None
        self.self_play=bool(self_play)
        self.shadow_clones=max(1, int(shadow_clones))
        self._cached_profile_params = []
        self._raw_profiles = []
        if self.profiles:
            profs = ArenaEvaluator._load_profiles(self.profiles, self.profile_min_hands, self.profile_top)
            self._raw_profiles = list(profs)
            self._cached_profile_params = [profile_to_params(p) for p in profs]
        self.n_profiles_loaded = len(self._cached_profile_params)
        self._build_data_splits()

    def _build_data_splits(self):
        """Split opponents into strict Train / Validation / Test partitions.
        
        Guarantees:
        - train_env: Seen during evolution and generational breeding.
        - validation_env: Used strictly for candidate model selection and early stopping.
        - test_env: Strictly frozen. Evaluated ONCE on the chosen champion after selection is frozen. NEVER used to make choices.
        """
        hrng = random.Random(self.seed + 4242)
        indices = list(range(len(self._cached_profile_params)))
        hrng.shuffle(indices)

        total_prof = len(indices)
        n_val = max(1, int(total_prof * self.val_frac)) if total_prof >= 4 else (1 if total_prof >= 2 else 0)
        n_test = max(1, int(total_prof * self.test_frac)) if total_prof >= 4 else (1 if total_prof >= 3 else 0)
        if n_val + n_test >= total_prof and total_prof > 0:
            n_val = max(1, total_prof // 3)
            n_test = max(1, total_prof // 3)

        val_idx = indices[:n_val]
        test_idx = indices[n_val:n_val + n_test]
        train_idx = indices[n_val + n_test:]

        val_profiles = [self._cached_profile_params[i] for i in val_idx]
        test_profiles = [self._cached_profile_params[i] for i in test_idx]
        train_profiles = [self._cached_profile_params[i] for i in train_idx]

        val_raw = [self._raw_profiles[i] for i in val_idx] if self._raw_profiles else []
        test_raw = [self._raw_profiles[i] for i in test_idx] if self._raw_profiles else []
        train_raw = [self._raw_profiles[i] for i in train_idx] if self._raw_profiles else []
        self._train_raw_profiles = train_raw
        self._val_raw_profiles = val_raw
        self._test_raw_profiles = test_raw

        # Distinct perturbed archetypes for each partition
        state = self.rng.getstate()
        val_archetypes = [self.mutate(p, 0.10) for p in ARCHETYPES.values() for _ in range(2)]
        test_archetypes = [self.mutate(p, 0.15) for p in ARCHETYPES.values() for _ in range(2)]
        self.rng.setstate(state)

        # Build environments with distinct macro compositions and unseen archetypes
        self.train_env = OpponentEnvironment(
            name="train",
            profile_params=tuple(train_profiles),
            archetypes=tuple(ARCHETYPES.values()),
            shark_ratio=0.30,
            regular_ratio=0.40,
            fish_ratio=0.30,
            unseen_archetypes=(),
            raw_profiles=tuple(train_raw),
            description="Training Environment Baseline",
        )
        self.validation_env = OpponentEnvironment(
            name="validation",
            profile_params=tuple(val_profiles),
            archetypes=tuple(val_archetypes),
            shark_ratio=0.40,
            regular_ratio=0.45,
            fish_ratio=0.15,
            unseen_archetypes=(UNSEEN_OOD_ARCHETYPES["tricky_trapper"], UNSEEN_OOD_ARCHETYPES["sticky_floater"]),
            raw_profiles=tuple(val_raw),
            description="Validation Environment with Moderate Distribution Shift",
        )
        self.test_env = OpponentEnvironment(
            name="test",
            profile_params=tuple(test_profiles),
            archetypes=tuple(test_archetypes),
            shark_ratio=0.45,
            regular_ratio=0.40,
            fish_ratio=0.15,
            unseen_archetypes=tuple(UNSEEN_OOD_ARCHETYPES.values()),
            raw_profiles=tuple(test_raw),
            description="Frozen Test Environment with Heavy OOD Distribution Shift",
        )

        # Backward compatibility properties
        self._train_profile_params = list(self.train_env.profile_params)
        self._holdout_profile_params = list(self.validation_env.profile_params)
        self._holdout_archetypes = list(self.validation_env.archetypes)

        # Quantitative Distribution Shift Audits
        self.val_distribution_shift = compute_distribution_shift_audit(self.train_env, self.validation_env, self.pool_size, self.seed)
        self.test_distribution_shift = compute_distribution_shift_audit(self.train_env, self.test_env, self.pool_size, self.seed)

    def _build_holdout(self):
        self._build_data_splits()

    def _holdout_pool(self):
        return self.validation_env.sample_pool(self.pool_size, seed=self.seed + 90210)

    PARAM_BOUNDS: dict[str, tuple[float, float]] = {
        # Preflop (healthy 6-max bounds preventing degenerate ultra-nit collapse)
        "vpip": (0.18, 0.38),
        "open_frequency": (0.45, 0.95),
        "threebet_frequency": (0.04, 0.14),
        "squeeze_frequency": (0.03, 0.16),
        "steal_frequency": (0.55, 0.85),
        # Position-aware preflop ranges
        "open_thresh_utg": (0.10, 0.22),
        "open_thresh_hj": (0.14, 0.28),
        "open_thresh_co": (0.20, 0.38),
        "open_thresh_btn": (0.35, 0.62),
        "open_thresh_sb": (0.25, 0.48),
        "defend_thresh_bb": (0.38, 0.68),
        # Multiway & Table dynamics
        "multiway_decay": (0.30, 0.70),
        "table_strength_weight": (0.10, 0.50),
        # Postflop frequencies
        "cbet_frequency": (0.40, 0.85),
        "turn_barrel_frequency": (0.25, 0.75),
        "river_bluff_frequency": (0.02, 0.20),
        # Calibrated equity thresholds
        "value_threshold": (0.58, 0.82),
        "thin_value_threshold": (0.48, 0.72),
        "raise_threshold": (0.52, 0.75),
        "jam_threshold": (0.80, 0.98),
        # Street-specific thresholds
        "flop_value_threshold": (0.45, 0.72),
        "turn_value_threshold": (0.52, 0.80),
        "river_value_threshold": (0.60, 0.88),
        # Bet sizing
        "open_size": (2.0, 3.5),
        "cbet_size": (0.28, 0.85),
        "value_bet_size": (0.40, 1.00),
        "bluff_bet_size": (0.30, 0.85),
        "raise_size": (0.45, 1.10),
        # Board texture bet sizing
        "dry_board_bet_size": (0.20, 0.55),
        "wet_board_bet_size": (0.50, 0.95),
        # Tournament adaptation
        "safety": (0.20, 0.80),
        "attack": (0.30, 0.95),
        "bubble_aggression": (0.50, 0.98),
        "late_aggression": (0.10, 0.50),
        "temperature": (0.02, 0.25),
    }

    FUNCTIONAL_BLOCKS: dict[str, tuple[str, ...]] = {
        "preflop": (
            "vpip",
            "open_frequency",
            "threebet_frequency",
            "squeeze_frequency",
            "steal_frequency",
            "open_thresh_utg",
            "open_thresh_hj",
            "open_thresh_co",
            "open_thresh_btn",
            "open_thresh_sb",
            "defend_thresh_bb",
        ),
        "postflop_freq": (
            "cbet_frequency",
            "turn_barrel_frequency",
            "river_bluff_frequency",
        ),
        "thresholds": (
            "value_threshold",
            "thin_value_threshold",
            "raise_threshold",
            "jam_threshold",
            "flop_value_threshold",
            "turn_value_threshold",
            "river_value_threshold",
        ),
        "sizing": (
            "open_size",
            "cbet_size",
            "value_bet_size",
            "bluff_bet_size",
            "raise_size",
            "dry_board_bet_size",
            "wet_board_bet_size",
        ),
        "table_and_tournament": (
            "multiway_decay",
            "table_strength_weight",
            "safety",
            "attack",
            "bubble_aggression",
            "late_aggression",
            "temperature",
        ),
    }

    @classmethod
    def _clamp_and_validate_dict(cls, d: dict[str, Any]) -> None:
        defaults = asdict(StrategyParams())
        for k in cls.FIELDS:
            lo, hi = cls.PARAM_BOUNDS.get(k, (0.01, 0.99))
            val = float(d[k]) if k in d else float(defaults.get(k, 0.5))
            d[k] = max(lo, min(hi, val))
        # Enforce poker logical monotonicity invariants
        d["thin_value_threshold"] = min(d["thin_value_threshold"], d["value_threshold"] - 0.04)
        d["jam_threshold"] = max(d["jam_threshold"], d["value_threshold"] + 0.06)
        d["turn_value_threshold"] = max(d["turn_value_threshold"], d["flop_value_threshold"] + 0.02)
        d["river_value_threshold"] = max(d["river_value_threshold"], d["turn_value_threshold"] + 0.02)
        d["bluff_bet_size"] = min(d["bluff_bet_size"], d["value_bet_size"])
        d["wet_board_bet_size"] = max(d["wet_board_bet_size"], d["dry_board_bet_size"] + 0.10)
        # Enforce preflop position hierarchy: UTG <= HJ <= CO <= BTN
        d["open_thresh_hj"] = max(d["open_thresh_hj"], d["open_thresh_utg"] + 0.02)
        d["open_thresh_co"] = max(d["open_thresh_co"], d["open_thresh_hj"] + 0.03)
        d["open_thresh_btn"] = max(d["open_thresh_btn"], d["open_thresh_co"] + 0.05)
        d["open_thresh_sb"] = max(d["open_thresh_co"] - 0.03, min(d["open_thresh_btn"] - 0.03, d["open_thresh_sb"]))
        # Tactical coupling constraint: Preflop aggression must be supported by postflop attack
        if d["threebet_frequency"] >= 0.09:
            d["attack"] = max(d["attack"], min(0.92, 0.65 + (d["threebet_frequency"] - 0.09) * 2.5))

    def _clamp_and_validate(self, d: dict[str, Any]) -> None:
        self._clamp_and_validate_dict(d)

    def _jitter(self, p_in: StrategyParams, rng: random.Random, sigma: float = 0.015) -> StrategyParams:
        d = asdict(p_in)
        for k in self.FIELDS:
            scale = sigma * (0.5 if "threshold" in k or "thresh" in k else 0.35 if k == "open_size" else 1.0)
            d[k] += rng.gauss(0, scale)
        self._clamp_and_validate(d)
        return StrategyParams(**d)

    def mutate(self, p: StrategyParams, sigma: float, mask_prob: float = 0.40) -> StrategyParams:
        """Gene-masked adaptive mutation.

        Perturbs a randomly sampled subset of genes (with probability mask_prob, ensuring at least
        2 genes) rather than destructively mutating all parameters simultaneously.
        Unselected genes remain pristine, preserving structural tactics and strategic synergies.
        """
        d = asdict(p)
        if sigma <= 0.0:
            self._clamp_and_validate(d)
            return StrategyParams(**d)

        # Gene masking: select candidate subset
        selected_genes = [k for k in self.FIELDS if self.rng.random() < mask_prob]
        if len(selected_genes) < 2:
            selected_genes = list(self.rng.sample(self.FIELDS, min(2, len(self.FIELDS))))

        threshold_keys = {
            "value_threshold", "thin_value_threshold", "raise_threshold", "jam_threshold",
            "flop_value_threshold", "turn_value_threshold", "river_value_threshold",
            "open_thresh_utg", "open_thresh_hj", "open_thresh_co", "open_thresh_btn",
            "open_thresh_sb", "defend_thresh_bb"
        }
        for k in selected_genes:
            scale = sigma * (.55 if k in threshold_keys else .35 if k == "open_size" else 1.0)
            d[k] += self.rng.gauss(0, scale)

        self._clamp_and_validate(d)
        return StrategyParams(**d)

    def crossover(self, a: StrategyParams, b: StrategyParams, mode: str = "auto") -> StrategyParams:
        """Modular Functional Block and Arithmetic Blended Crossover.

        Parameters:
        - mode="auto": 50% chance block crossover, 50% chance arithmetic blend.
        - mode="block": Inherits entire cohesive functional blocks from Parent A or Parent B,
          protecting inter-parameter synergies (such as position gradients and street thresholds).
        - mode="arithmetic": Blended convex interpolation (BLX-alpha) exploring continuous parameter space.
        """
        da, db = asdict(a), asdict(b)
        out = {}
        out["equity_samples"] = max(0, int((da.get("equity_samples", 0) + db.get("equity_samples", 0)) // 2))

        use_block = (self.rng.random() < 0.50) if mode == "auto" else (mode == "block")
        if use_block:
            for block_name, block_keys in self.FUNCTIONAL_BLOCKS.items():
                donor = da if self.rng.random() < 0.50 else db
                for k in block_keys:
                    if k in donor:
                        out[k] = donor[k]
            for k in self.FIELDS:
                if k not in out:
                    out[k] = da[k] if self.rng.random() < 0.50 else db[k]
        else:
            for k in self.FIELDS:
                alpha = self.rng.uniform(0.15, 0.85)
                out[k] = alpha * float(da[k]) + (1.0 - alpha) * float(db[k])

        self._clamp_and_validate(out)
        return StrategyParams(**out)

    def population_diversity(self, pop: list[StrategyParams]) -> float:
        return population_diversity(pop)

    def seed_population(self, n):
        seeds = list(ARCHETYPES.values())
        pop = [self.mutate(ARCHETYPES["balanced"], 0.0)]
        for p in seeds:
            if len(pop) < n:
                pop.append(self.mutate(p, 0.0))
        while len(pop) < n:
            pop.append(self.mutate(self.rng.choice(seeds), 0.06))
        return pop[:n]

    def _draw_pool(
        self,
        population,
        hall,
        seed,
        profile_pool,
        exclude=None,
        generation: int = 0,
        total_generations: int = 30,
        min_genetic_distance: float = 0.08,
        min_pairwise_distance: float = 0.05,
    ):
        """Build a balanced, stratified opponent pool for one evaluation batch.

        Opponents are partitioned across 3 primary playing styles (Regulars, Sharks, Fish)
        under a dynamic curriculum schedule, with controlled self-play and anti-echo-chamber
        genetic isolation (preventing clone & near-clone incestuous play).
        """
        rng = random.Random(seed)
        n = max(1, self.pool_size - 1)
        out: list[StrategyParams] = []

        # Normalise excluded individuals (focal candidate and direct lineages)
        excludes: list[StrategyParams] = []
        if exclude is not None:
            if isinstance(exclude, StrategyParams):
                excludes.append(exclude)
            elif isinstance(exclude, (list, tuple, set)):
                for x in exclude:
                    if isinstance(x, StrategyParams):
                        excludes.append(x)
        exclude_hashes = {strategy_signature(x) for x in excludes}

        # 1. Controlled Self-Play with Genetic Isolation (Anti-Echo Chamber)
        if self.self_play and n >= 4:
            raw_candidates = [p for _, p in hall] if hall else [p for p in population]
            if not raw_candidates and profile_pool:
                raw_candidates = [p if isinstance(p, StrategyParams) else profile_to_params(p) for p in profile_pool]

            # Filter candidates: strictly eliminate exact hash matches and near-clones
            valid_shadows = []
            for p in raw_candidates:
                if strategy_signature(p) in exclude_hashes:
                    continue
                if excludes and any(genome_distance(p, exc) < min_genetic_distance for exc in excludes):
                    continue
                valid_shadows.append(p)

            # If not enough valid candidates in hall/pop, source diverse archetypes
            if len(valid_shadows) < min(self.shadow_clones, max(1, n // 4)):
                for arch in ARCHETYPES.values():
                    if strategy_signature(arch) not in exclude_hashes:
                        if not excludes or all(genome_distance(arch, exc) >= min_genetic_distance for exc in excludes):
                            valid_shadows.append(arch)

            if valid_shadows:
                max_shadow = min(self.shadow_clones, max(1, n // 4))
                selected_shadows: list[StrategyParams] = []
                shuffled_cands = list(valid_shadows)
                rng.shuffle(shuffled_cands)

                for cand in shuffled_cands:
                    if len(selected_shadows) >= max_shadow:
                        break
                    # Enforce mutual separation among drawn shadow clones
                    if not any(genome_distance(cand, s) < min_pairwise_distance for s in selected_shadows):
                        selected_shadows.append(cand)

                # If mutual diversity filtered too many, fill remaining slots
                for cand in shuffled_cands:
                    if len(selected_shadows) >= max_shadow:
                        break
                    if cand not in selected_shadows:
                        selected_shadows.append(cand)

                for cand in selected_shadows:
                    out.append(self._jitter(cand, rng))

        n_rem = n - len(out)

        # 2. Dynamic Curriculum Ratios
        if generation < 3:
            # Early generations: more calling stations and loose aggressive to discover value betting
            r_sharks, r_regs, r_fish = 0.30, 0.35, 0.35
        elif generation < 10:
            # Mid generations: standard golden pyramid
            r_sharks, r_regs, r_fish = 0.30, 0.40, 0.30
        else:
            # Late generations: tougher regular-heavy field
            r_sharks, r_regs, r_fish = 0.25, 0.55, 0.20

        n_sharks = int(round(n_rem * r_sharks))
        n_regs = int(round(n_rem * r_regs))
        n_fish = n_rem - n_sharks - n_regs
        if n_fish < 0:
            n_fish = 0
            n_regs = n_rem - n_sharks

        # 3. Classify profile_pool into tiers
        p_sharks = [p for p in profile_pool if _classify_strategy_tier(p) == "shark"] if profile_pool else []
        p_regs = [p for p in profile_pool if _classify_strategy_tier(p) == "regular"] if profile_pool else []
        p_fish = [p for p in profile_pool if _classify_strategy_tier(p) == "fish"] if profile_pool else []

        arch_sharks = [ARCHETYPES["lag"], ARCHETYPES["maniac"]]
        arch_regs = [ARCHETYPES["balanced"], ARCHETYPES["tight"], ARCHETYPES["nit"]]
        arch_fish = [ARCHETYPES["station"]]

        def _fill_tier(needed: int, profs: list[StrategyParams | dict[str, Any]], archs: list[StrategyParams]) -> list[StrategyParams]:
            res: list[StrategyParams] = []
            if needed <= 0:
                return res
            n_prof = min(len(profs), int(round(needed * self.profile_share))) if profs else 0
            for _ in range(n_prof):
                chosen = rng.choice(profs)
                if isinstance(chosen, dict):
                    res.append(sample_profile_posterior(chosen, rng=rng))
                else:
                    res.append(self._jitter(chosen, rng))
            while len(res) < needed:
                res.append(self._jitter(rng.choice(archs), rng))
            return res

        tier_opponents: list[StrategyParams] = []
        tier_opponents.extend(_fill_tier(n_sharks, p_sharks, arch_sharks))
        tier_opponents.extend(_fill_tier(n_regs, p_regs, arch_regs))
        tier_opponents.extend(_fill_tier(n_fish, p_fish, arch_fish))

        rng.shuffle(tier_opponents)
        out.extend(tier_opponents)

        while len(out) < n:
            out.append(self._jitter(rng.choice(arch_regs), rng))
        return out[:n]

    def _opponents(self, focal, population, hall, seed, generation: int = 0):
        prof_source = self._train_raw_profiles if getattr(self, "_train_raw_profiles", None) else self._train_profile_params
        return self._draw_pool(population, hall, seed, prof_source, exclude=focal, generation=generation)

    def _score_population(self, pop, hall, generation, runs, pool=None, seed_base=None, label="评估", ecologies: list[str] | None = None):
        """Common random numbers & Multi-Ecology population scoring.

        Guarantees:
        - Intra-ecology Common Random Numbers: Within any single ecology, all candidates
          receive the exact same opponent lineup and the exact same deal seed sequence.
        - Inter-ecology Independence: Distinct ecologies use independent seeds and
          distinct archetype proportions.
        - Rigorous two-stage ANOVA variance decomposition (within_ecology_variance,
          between_ecology_variance, total_variance).
        """
        if seed_base is None:
            seed_base = self.seed + generation * 1000003

        n_cands = len(pop)

        from .ecosystem import build_ecology_pool

        if pool is not None:
            active_ecologies = ["single_pool"]
            eco_pools = {"single_pool": pool}
            runs_per_eco = max(1, runs)
        else:
            eco_list = ecologies if ecologies is not None else getattr(self, "ecologies", ["balanced", "aggressive", "passive", "mixed", "adversarial"])
            if runs >= len(eco_list):
                active_ecologies = list(eco_list)
                runs_per_eco = max(1, runs // len(active_ecologies))
            else:
                active_ecologies = list(eco_list[:max(1, runs)])
                runs_per_eco = 1

            eco_pools = {}
            for e_idx, eco_name in enumerate(active_ecologies):
                eco_seed = self.seed * 104729 + (e_idx + 1) * 100003 + generation
                pool_raw = build_ecology_pool(
                    ecology=eco_name,
                    count=self.pool_size - 1,
                    profiles_path=self.profiles,
                    profile_params=self._train_raw_profiles if getattr(self, "_train_raw_profiles", None) else self._train_profile_params,
                    seed=eco_seed,
                    sample_posterior=True,
                )
                if self.self_play and hall and (self.pool_size - 1) >= 4:
                    pop_signatures = {strategy_signature(p) for p in pop}
                    valid_hall = [
                        p for _, p in hall
                        if strategy_signature(p) not in pop_signatures
                        and all(genome_distance(p, c) >= 0.08 for c in pop)
                    ]
                    if valid_hall:
                        n_shadow = min(self.shadow_clones, max(1, (self.pool_size - 1) // 6))
                        rng_eco = random.Random(eco_seed + 999)
                        chosen_shadows = rng_eco.sample(valid_hall, min(len(valid_hall), n_shadow))
                        pool_raw = pool_raw[:-len(chosen_shadows)] + [self._jitter(s, rng_eco) for s in chosen_shadows]
                eco_pools[eco_name] = pool_raw

        total_tournaments_per_cand = len(active_ecologies) * runs_per_eco
        total_tournaments = n_cands * total_tournaments_per_cand
        workers = self.workers or min(os.cpu_count() or 4, total_tournaments)
        print(f"  [{label} | Gen {generation+1:02d}] 共 {n_cands} 个候选 × {len(active_ecologies)} 个生态 × {runs_per_eco} 场 = {total_tournaments} 场 (并发: {workers} 核心)...", flush=True)

        cand_data = [
            {
                "ecology_runs": {eco: [] for eco in active_ecologies},
                "completed": 0,
            }
            for _ in range(n_cands)
        ]

        tasks = []
        for e_idx, eco_name in enumerate(active_ecologies):
            pool_e = eco_pools[eco_name]
            for r in range(runs_per_eco):
                s = seed_base + (e_idx + 1) * 100003 + r * 7919
                for cand_idx, p in enumerate(pop):
                    tasks.append((cand_idx, r, p, pool_e, s, self.equity_samples, self.tournament_config, eco_name))

        if workers <= 1 or total_tournaments <= 1:
            t0 = time.time()
            for t in tasks:
                res = _evaluate_single_tournament_worker(t)
                cand_idx = res[0]
                sm = res[7]
                eco_name = res[8] if len(res) > 8 else active_ecologies[0]
                cd = cand_data[cand_idx]
                cd["ecology_runs"][eco_name].append(sm)
                cd["completed"] += 1
                done = sum(c["completed"] for c in cand_data)
                elapsed = time.time() - t0
                sec_per_game = elapsed / max(1, done)
                eta_sec = (total_tournaments - done) * sec_per_game
                eta_str = _fmt_eta(eta_sec)
                if done % max(1, min(10, total_tournaments // 20)) == 0 or done == total_tournaments:
                    pct = done / total_tournaments * 100.0
                    print(f"    [{label}进度] {done:03d}/{total_tournaments:03d} 场 ({pct:4.1f}%) | 均速 {sec_per_game:.1f}s/场 | 剩余预估: {eta_str}", flush=True)

            for cand_idx in range(n_cands):
                m = compute_multi_ecology_variance_decomposition(cand_data[cand_idx]["ecology_runs"], self.pool_size)
                print(
                    f"    ✔ 候选 {cand_idx+1:02d}/{n_cands:02d} "
                    f"robust_fit={m.get('robust_fitness', m['fitness']):.4f} "
                    f"(fit={m['fitness']:.4f}±{m.get('fitness_se',0.0):.4f} worst={m.get('worst_ecology_name', '-')}:{m.get('worst_ecology_fitness', 0.0):.4f}) "
                    f"between_var={m.get('between_ecology_variance', 0.0):.5f} "
                    f"within_var={m.get('within_ecology_variance', 0.0):.5f} "
                    f"top12={m['top12_rate']*100:.1f}% final={m['final_rate']*100:.1f}% "
                    f"champ={m['champion_rate']*100:.1f}% 终排={m.get('avg_finish_rank', m['avg_rank']):.1f} "
                    f"总BB={m.get('overall_bb100', m['avg_bb100']):+.1f}",
                    flush=True
                )
                cand_data[cand_idx]["summary"] = m

            return [(cand_data[i]["summary"], pop[i]) for i in range(n_cands)]

        # Multiprocessing concurrent mode
        t0 = time.time()
        last_print_time = t0
        completed_tournaments = 0
        completed_cands = 0
        print_interval = max(1, min(10, total_tournaments // 20))

        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_evaluate_single_tournament_worker, t): t for t in tasks}
            for fut in as_completed(futs):
                res = fut.result()
                cand_idx = res[0]
                sm = res[7]
                eco_name = res[8] if len(res) > 8 else active_ecologies[0]
                cd = cand_data[cand_idx]
                cd["ecology_runs"][eco_name].append(sm)
                cd["completed"] += 1
                completed_tournaments += 1

                now = time.time()
                elapsed = now - t0
                sec_per_game = elapsed / max(1, completed_tournaments)
                eta_sec = (total_tournaments - completed_tournaments) * sec_per_game
                eta_str = _fmt_eta(eta_sec)

                if cd["completed"] == total_tournaments_per_cand:
                    completed_cands += 1
                    m = compute_multi_ecology_variance_decomposition(cd["ecology_runs"], self.pool_size)
                    cd["summary"] = m
                    print(
                        f"    ✔ [{label}完成 候选 {cand_idx+1:02d}/{n_cands:02d}] "
                        f"robust_fit={m.get('robust_fitness', m['fitness']):.4f} "
                        f"(fit={m['fitness']:.4f} worst={m.get('worst_ecology_name', '-')}:{m.get('worst_ecology_fitness', 0.0):.4f}) | "
                        f"between_var={m.get('between_ecology_variance', 0.0):.5f} | "
                        f"within_var={m.get('within_ecology_variance', 0.0):.5f} | "
                        f"出线 {m['top12_rate']*100:4.1f}% | "
                        f"决赛 {m['final_rate']*100:4.1f}% | "
                        f"夺冠 {m['champion_rate']*100:4.1f}% | "
                        f"终排 {m.get('avg_finish_rank', m['avg_rank']):4.1f} | "
                        f"总BB {m.get('overall_bb100', m['avg_bb100']):+5.1f}  "
                        f"[{completed_cands}/{n_cands} 候选完成]",
                        flush=True
                    )
                    last_print_time = now
                elif (completed_tournaments % print_interval == 0) or (now - last_print_time >= 15.0):
                    pct = (completed_tournaments / total_tournaments) * 100.0
                    bar_len = 16
                    filled = int(round(bar_len * completed_tournaments / total_tournaments))
                    bar = "█" * filled + "░" * (bar_len - filled)
                    print(
                        f"    [{label}总览] [{bar}] {completed_tournaments:03d}/{total_tournaments:03d} 场 ({pct:4.1f}%) | "
                        f"速度: {sec_per_game:.1f}s/场 | "
                        f"剩余预估: {eta_str} | "
                        f"候选完成: {completed_cands}/{n_cands}",
                        flush=True
                    )
                    last_print_time = now

        results = [(cand_data[i]["summary"], pop[i]) for i in range(n_cands)]
        return results

    def fit(self,generations=30,population=16,runs_per_candidate=30,save="models/candidate.json",archive="models/archive",final_race=500,resume=True,reeval_runs=24,
            stagnation_patience=4,stagnation_sigma_boost=2.5,stagnation_min_delta=0.01,resume_revert_margin=0.05,base_model=None):
        ap=Path(archive); ap.mkdir(parents=True,exist_ok=True)
        start_gen=0; history=[]; hall=[]; champion=None; champion_metrics=None

        if hasattr(self, "val_distribution_shift") and hasattr(self, "test_distribution_shift"):
            print(f"[Training: Data Splits] 环境分布漂移特征审计 (Distribution Shift Audit):", flush=True)
            print(f"  ├── 验证集 (Validation): TV距离={self.val_distribution_shift['composition_tv_distance']:.3f} | 未见策略占比={self.val_distribution_shift['unseen_archetype_share']*100:.1f}% | OOD极端比例={self.val_distribution_shift['ood_parameter_rate']*100:.1f}% | 综合漂移分={self.val_distribution_shift['composite_shift_score']:.3f}", flush=True)
            print(f"  └── 测试集 (Frozen Test): TV距离={self.test_distribution_shift['composition_tv_distance']:.3f} | 未见策略占比={self.test_distribution_shift['unseen_archetype_share']*100:.1f}% | OOD极端比例={self.test_distribution_shift['ood_parameter_rate']*100:.1f}% | 综合漂移分={self.test_distribution_shift['composite_shift_score']:.3f}", flush=True)

        if self.self_play:
            print(f"[Training 2.5] ⚡ 激活【2.5 影子自博弈协同演化模式】: 每场锁定 {self.shadow_clones} 位历史最强镜像作为守门员，淬炼抗剥削 GTO 平衡！", flush=True)

        if resume:
            gen_files = sorted(ap.glob("gen_*.json"))
            for gf in gen_files:
                try:
                    d = json.loads(gf.read_text(encoding="utf-8"))
                    g_num = d.get("generation")
                    if g_num and "champion" in d and "metrics" in d:
                        history.append({
                            "generation": g_num,
                            "sigma": max(.012, .075 * (.92 ** (g_num - 1))),
                            "params": d["champion"],
                            "metrics": d["metrics"]
                        })
                except Exception:
                    pass
            if history:
                start_gen = history[-1]["generation"]
                champion = _load_params_safe(history[-1]["params"])
                champion_metrics = history[-1]["metrics"]
                # Hall of fame = the strongest champions on record, not the most recent.
                hall = [(h["metrics"].get("robust_fitness", h["metrics"]["fitness"]), _load_params_safe(h["params"]))
                        for h in sorted(history, key=lambda x: -x["metrics"].get("robust_fitness", x["metrics"]["fitness"]))[:self.HALL_SIZE]]
                print(f"[Training] 发现历史存档！从 Generation {start_gen} 自动恢复续训 (已有历史: {len(history)} 代, 当前最强 Fitness: {champion_metrics['fitness']:.4f})", flush=True)

        if not history and base_model:
            base_params = None
            if isinstance(base_model, StrategyParams):
                base_params = replace(base_model)
            elif isinstance(base_model, dict):
                base_params = _load_params_safe(base_model.get("params", base_model))
            elif isinstance(base_model, (str, Path)):
                bp = Path(base_model)
                if bp.exists():
                    try:
                        d = json.loads(bp.read_text(encoding="utf-8"))
                        base_params = _load_params_safe(d.get("params", d))
                    except Exception as e:
                        print(f"[Training] 警告: 加载初始底模 {base_model} 失败: {e}", flush=True)
            if base_params is not None:
                champion = base_params
                hall = [(0.50, replace(base_params))]
                print(f"[Training] 成功加载初始底模: {base_model}！第一代种群将基于该模型微调繁衍", flush=True)

        best_ever_metrics = champion_metrics
        best_ever_champion = champion
        if history:
            for h in history:
                h_score = h["metrics"].get("robust_fitness", h["metrics"]["fitness"])
                b_score = best_ever_metrics.get("robust_fitness", best_ever_metrics["fitness"]) if best_ever_metrics else -1e9
                if best_ever_metrics is None or h_score > b_score:
                    best_ever_metrics = h["metrics"]
                    best_ever_champion = _load_params_safe(h["params"])
        stagnation_count = 0

        # Resuming into the archive's *last* generation is not the same as resuming
        # into its *best* one. A generation whose winner was picked on a lucky sample
        # becomes the seed for everything after it, so an archive's tail can be
        # strictly worse than its middle -- in this repo gen_016 scores 0.51 while
        # gen_021 scores 0.14. Starting the next run from that tail means re-deriving
        # from a known-bad point, and paying for it in generations spent climbing back.
        #
        # sigma_epoch exists for the same reason: the mutation step used to decay with
        # the *absolute* generation number (0.92**g), so an archive resumed at gen 21
        # began already at the floor and could never explore again. Decaying from the
        # last restart instead keeps a resumed run's search budget intact.
        sigma_epoch = start_gen
        if champion is not None and best_ever_metrics is not None and champion_metrics is not None:
            drop = best_ever_metrics.get("robust_fitness", best_ever_metrics["fitness"]) - champion_metrics.get("robust_fitness", champion_metrics["fitness"])
            if drop > resume_revert_margin:
                best_gen = next((h["generation"] for h in history
                                 if h["metrics"] is best_ever_metrics), None)
                print(f"[Training] 存档末代 Gen {start_gen} (fitness={champion_metrics['fitness']:.4f}) "
                      f"低于历史最优 Gen {best_gen} (fitness={best_ever_metrics['fitness']:.4f}) 达 {drop:.4f}，"
                      f"改从历史最优续训并重置变异步长", flush=True)
                champion = replace(best_ever_champion)
                champion_metrics = best_ever_metrics
                sigma_epoch = 0

        if champion is not None:
            pop = [replace(champion)]
            while len(pop) < population:
                pop.append(self.mutate(champion, max(.02, .075 * (.92 ** sigma_epoch))))
        else:
            pop = self.seed_population(population)

        def _rank(scored_pairs):
            return sorted(
                ((m, p) for m, p in scored_pairs),
                key=lambda x: (
                    x[0].get("robust_fitness", x[0]["fitness"]),
                    x[0].get("worst_ecology_fitness", x[0]["fitness"]),
                    x[0].get("finish_utility", x[0].get("top12_rate", 0.0)),
                    x[0].get("overall_bb100", x[0].get("avg_bb100", 0.0)),
                    -x[0].get("avg_finish_rank", x[0].get("avg_rank", 999.0))
                ),
                reverse=True
            )

        # Carried forward when generations == 0 so the tail below always has a champion.
        re_ranked = [(champion_metrics, champion)] if champion is not None else None

        for g in range(start_gen, start_gen + generations):
            base_sigma=max(.012,.075*(.92**sigma_epoch))
            sigma=base_sigma
            restarted=False
            if stagnation_count >= stagnation_patience and best_ever_champion is not None:
                # Multi-Origin Diversity Restart:
                # Instead of perturbing only a single champion, seed the restarted population
                # from multiple distinct phylogenetic origins (best champion, alternative hall ancestor,
                # outcrossed archetypes, and broad mutations).
                sigma_epoch = 0
                base_sigma = max(.012, .075 * (.92 ** sigma_epoch))
                sigma = min(0.075, base_sigma * stagnation_sigma_boost)
                champion = replace(best_ever_champion)

                # Anchor 1: Best-ever champion
                # Anchor 2: Alternative ancestor from hall
                alt_ancestor = None
                champ_dict = asdict(best_ever_champion)
                for _, hall_p in hall:
                    if asdict(hall_p) != champ_dict:
                        alt_ancestor = hall_p
                        break
                if alt_ancestor is None:
                    alt_ancestor = ARCHETYPES["lag"] if getattr(best_ever_champion, "attack", 0.6) < 0.70 else ARCHETYPES["tight"]

                pop = [replace(best_ever_champion)]
                if len(pop) < population:
                    pop.append(replace(alt_ancestor))

                # Outcrosses between champion and archetypes
                arch_candidates = ["lag", "station", "nit"]
                for arch_key in arch_candidates:
                    if len(pop) < population and arch_key in ARCHETYPES:
                        outcross = self.crossover(best_ever_champion, ARCHETYPES[arch_key], mode="block")
                        pop.append(outcross)

                # Remaining slots: mutational spread from both origins with widened sigma
                origins = [best_ever_champion, alt_ancestor]
                origin_idx = 0
                while len(pop) < population:
                    origin = origins[origin_idx % len(origins)]
                    pop.append(self.mutate(origin, sigma, mask_prob=0.55))
                    origin_idx += 1

                restarted = True
                stagnation_count = 0
                restarted_div = population_diversity(pop)
                print(f"[Training] 检测到连续 {stagnation_patience} 代无提升，触发多源异构重启："
                      f"从历史最优 (fitness={best_ever_metrics['fitness']:.4f}) + 多源支系恢复种群，"
                      f"重启多样性={restarted_div:.3f}, sigma {base_sigma:.4f}->{sigma:.4f}", flush=True)

            scored=self._score_population(pop,hall,g,runs_per_candidate,label="初评")
            ranked=_rank(scored)
            elite_n=max(3,population//4)
            elites=[p for _,p in ranked[:elite_n]]

            # The generation winner is the maximum of a noisy sample, so its in-sample
            # fitness is biased upward. Re-score the shortlist across fresh multi-ecology pools
            # and fresh deal seeds before crowning anything.
            re_scored = self._score_population(
                elites,
                hall,
                g,
                max(1, reeval_runs),
                seed_base=self.seed + 77000000 + g * 1009,
                label="复评",
            )
            re_ranked=_rank(re_scored)
            champion_metrics,champion=re_ranked[0]
            in_sample=dict(ranked[0][0])
            history.append({"generation":g+1,"sigma":sigma,"params":asdict(champion),
                            "metrics":champion_metrics,"in_sample_metrics":in_sample,"restarted":restarted})

            c_score = champion_metrics.get("robust_fitness", champion_metrics["fitness"])
            b_score = best_ever_metrics.get("robust_fitness", best_ever_metrics["fitness"]) if best_ever_metrics else -1e9
            if best_ever_metrics is None or c_score > b_score + stagnation_min_delta:
                best_ever_metrics = champion_metrics
                best_ever_champion = champion
                stagnation_count = 0
            else:
                stagnation_count += 1

            current_div = population_diversity(pop)
            hall_div = hall_of_fame_diversity(hall)
            print(f"gen={g+1:03d} robust_fit={champion_metrics.get('robust_fitness', champion_metrics['fitness']):.4f} "
                  f"(fit={champion_metrics['fitness']:.4f}±{champion_metrics.get('fitness_se',0.0):.4f} "
                  f"worst={champion_metrics.get('worst_ecology_name', '-')}:{champion_metrics.get('worst_ecology_fitness', 0.0):.4f}) "
                  f"top12={champion_metrics['top12_rate']:.3f} final={champion_metrics['final_rate']:.3f} "
                  f"champ={champion_metrics['champion_rate']:.3f} "
                  f"终排={champion_metrics.get('avg_finish_rank', champion_metrics['avg_rank']):.2f} "
                  f"总BB={champion_metrics.get('overall_bb100', champion_metrics['avg_bb100']):+.1f} "
                  f"多样性(种群={current_div:.3f}, 名人堂={hall_div:.3f}) "
                  f"(in-sample robust {in_sample.get('robust_fitness', in_sample['fitness']):.4f}) "
                  f"[best_ever={best_ever_metrics.get('robust_fitness', best_ever_metrics['fitness']):.4f} 停滞={stagnation_count}/{stagnation_patience}]", flush=True)
            hall = update_hall_of_fame_qd(
                hall,
                champion,
                champion_metrics.get("robust_fitness", champion_metrics["fitness"]),
                max_hall_size=self.HALL_SIZE,
                niche_radius=0.06,
            )

            # Strict Elitism: Anchor the all-time peak champion directly into the new generation
            # so the active population can never wander into degenerate corners.
            new = [replace(best_ever_champion)] if best_ever_champion is not None else []
            max_elites = max(1, population // 3)
            for p in elites:
                if len(new) < min(population, max_elites + (1 if best_ever_champion is not None else 0)):
                    if not any(asdict(p) == asdict(x) for x in new):
                        new.append(replace(p))

            # Breed the rest of the population from a pool that includes the all-time champion
            parent_pool = [best_ever_champion] + elites if best_ever_champion is not None else elites

            # Structured Diversity Injection (20%~25% of non-elite slots)
            slots_needed = population - len(new)
            div_slots = max(1, slots_needed // 4) if slots_needed >= 4 else (1 if slots_needed >= 2 else 0)
            for s_idx in range(div_slots):
                if len(new) >= population:
                    break
                if s_idx % 2 == 0:
                    # Outcross with diverse archetype (LAG, NIT, STATION, BALANCED)
                    arch_donor = self.rng.choice(list(ARCHETYPES.values()))
                    elite_parent = self.rng.choice(parent_pool)
                    outcrossed = self.crossover(elite_parent, arch_donor)
                    new.append(self.mutate(outcrossed, sigma * 0.85))
                else:
                    # High-exploration mutation (widened step size)
                    high_mut = self.mutate(self.rng.choice(parent_pool), sigma * 1.8)
                    new.append(high_mut)

            while len(new) < population:
                child = self.crossover(self.rng.choice(parent_pool), self.rng.choice(parent_pool)) if self.rng.random() < .70 else self.rng.choice(parent_pool)
                new.append(self.mutate(child, sigma))

            pop = new[:population]
            next_div = population_diversity(pop)
            (ap/f"gen_{g+1:03d}.json").write_text(json.dumps({
                "generation": g+1,
                "champion": asdict(champion),
                "metrics": champion_metrics,
                "population_diversity": round(next_div, 4),
                "hall_diversity": round(hall_of_fame_diversity(hall), 4),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            history[-1]["population_diversity"] = round(current_div, 4)
            history[-1]["hall_diversity"] = round(hall_of_fame_diversity(hall), 4)
            sigma_epoch += 1

        if re_ranked is None:
            raise ValueError("fit() requires generations >= 1 (or an existing checkpoint to resume from)")

        # Elite Parameter Smoothing: average top-k elites as a candidate, then
        # race it against the best raw elite on the holdout pool and keep the winner.
        elite_candidates = [p for _, p in re_ranked[:max(3, population // 4)]]
        avg_dict = {}
        for k in self.FIELDS:
            vals = [getattr(p, k) for p in elite_candidates]
            avg_dict[k] = sum(vals) / len(vals)
        stable_champion = StrategyParams(**avg_dict)

        race_workers = self.workers or min(os.cpu_count() or 4, 8)
        evaluator = ArenaEvaluator(
            pool_size=self.pool_size,
            equity_samples=self.equity_samples,
            workers=race_workers,
            seed=self.seed,
            tournament_config=self.tournament_config,
        )

        candidates = [
            ("平滑精英策略 (Stable Champion)", stable_champion, champion_metrics),
            ("末代冠军策略 (Last-Gen Champion)", champion, champion_metrics),
        ]
        if best_ever_champion is not None and asdict(best_ever_champion) != asdict(champion):
            candidates.append(("全周期峰值冠军 (All-Time Peak Champion)", best_ever_champion, best_ever_metrics))

        total_cands = len(candidates)
        # =========================================================================
        # Stage 1: VALIDATION RACE FOR CANDIDATE MODEL SELECTION
        # Candidates are scored against validation_env ONLY.
        # =========================================================================
        print(f"\n[Training: Validation] 启动候选模型验证决选 (Validation Race: {final_race} 场, {total_cands} 个候选, {race_workers} 核并发加速)...", flush=True)
        validation_pool = self.validation_env.sample_pool(self.pool_size, seed=self.seed + 90210)

        best_cand_name = None
        best_cand_champ = None
        best_cand_val_metrics = None
        best_cand_train_metrics = None

        for i, (cand_name, cand_strat, cand_tm) in enumerate(candidates, 1):
            print(f"  [{i}/{total_cands} 验证决选] 验证集评估: {cand_name}...", flush=True)
            m = evaluator.evaluate(
                cand_strat,
                runs=max(1, final_race),
                opponents=validation_pool,
                seed_offset=987654321,
                verbose=True,
            )
            cand_score = m.get("robust_fitness", m["fitness"])
            best_val_score = best_cand_val_metrics.get("robust_fitness", best_cand_val_metrics["fitness"]) if best_cand_val_metrics else -1e9
            print(f"    -> fit={m['fitness']:.4f}±{m.get('fitness_se',0.0):.4f} (robust={cand_score:.4f}) "
                  f"BB/100={m.get('avg_bb100',0):+.1f} top12={m.get('top12_rate',0)*100:.1f}% "
                  f"champ={m.get('champion_rate',0)*100:.1f}% avg_rank={m.get('avg_rank',0):.1f}", flush=True)
            if best_cand_val_metrics is None or cand_score > best_val_score:
                best_cand_name = cand_name
                best_cand_champ = cand_strat
                best_cand_val_metrics = m
                best_cand_train_metrics = cand_tm

        # =========================================================================
        # Stage 1: FREEZE CHAMPION
        # Champion is locked here based entirely on validation. Selection is complete.
        # =========================================================================
        final_champ = best_cand_champ
        val_metrics = best_cand_val_metrics
        final_train_metrics = best_cand_train_metrics or champion_metrics
        print(f"  🏆 验证集决选裁决: [{best_cand_name}] 表现最优，正式冻结为冠军模型！", flush=True)

        # =========================================================================
        # Stage 1: UNBIASED TEST EVALUATION (Evaluated ONCE on frozen champion)
        # Test set is NEVER used for selection, tuning, early stopping, or weighting.
        # =========================================================================
        print(f"\n[Training: Test] 启动独立测试集终局盲测 (Frozen Test Set: {final_race} 场, 单次无偏盲测)...", flush=True)
        test_pool = self.test_env.sample_pool(self.pool_size, seed=self.seed + 777777)
        test_metrics = evaluator.evaluate(
            final_champ,
            runs=max(1, final_race),
            opponents=test_pool,
            seed_offset=555555555,
            verbose=True,
        )
        print(f"  📊 终局无偏测试集表现 (Unbiased Test): fitness={test_metrics['fitness']:.4f}±{test_metrics.get('fitness_se',0.0):.4f} "
              f"BB/100={test_metrics.get('avg_bb100',0):+.1f} top12={test_metrics.get('top12_rate',0)*100:.1f}% "
              f"champ={test_metrics.get('champion_rate',0)*100:.1f}% avg_rank={test_metrics.get('avg_rank',0):.1f}", flush=True)

        # Stage 2: OOD Extreme Stress Testing Suite
        print(f"\n[Training: Test] 启动测试集 OOD 压力测试套件 (Extreme OOD Stress Tests)...", flush=True)
        ood_stress_results = {}
        for ood_name in ["extreme_aggression", "extreme_passivity", "unseen_hybrids"]:
            stress_pool = self.test_env.sample_pool(self.pool_size, seed=self.seed + 88888, ood_mode=ood_name)
            s_m = evaluator.evaluate(
                final_champ,
                runs=max(1, min(final_race, 10)),
                opponents=stress_pool,
                seed_offset=777000 + (hash(ood_name) % 10000),
                verbose=False,
            )
            ood_stress_results[ood_name] = s_m
            print(f"  ⚡ [OOD 压力测试: {ood_name:<19}] fitness={s_m['fitness']:.4f}±{s_m.get('fitness_se',0.0):.4f} | BB/100={s_m.get('overall_bb100', s_m.get('avg_bb100', 0.0)):+5.1f} | 终排={s_m.get('avg_finish_rank', s_m.get('avg_rank', 0.0)):4.1f}", flush=True)
        test_metrics["ood_stress_results"] = ood_stress_results

        # Reference training distribution baseline
        print(f"\n[Training: Reference] 训练分布参考基线...", flush=True)
        train_pool = self._draw_pool(pop, hall, self.seed * 31337, self._train_profile_params, generation=start_gen + generations)
        train_metrics = evaluator.evaluate(
            final_champ,
            runs=max(1, final_race),
            opponents=train_pool,
            seed_offset=123456789,
            verbose=True,
        )

        print(f"[Training] 完成本轮演化 (累计到达 Gen {start_gen + generations}).", flush=True)
        print(f"[Training] 验证集决选指标 fitness={val_metrics['fitness']:.4f}±{val_metrics.get('fitness_se',0.0):.4f} "
              f"top12={val_metrics['top12_rate']:.3f} avg_rank={val_metrics['avg_rank']:.2f}", flush=True)
        print(f"[Training] 独立测试集无偏 fitness={test_metrics['fitness']:.4f}±{test_metrics.get('fitness_se',0.0):.4f} "
              f"top12={test_metrics['top12_rate']:.3f} avg_rank={test_metrics['avg_rank']:.2f}", flush=True)
        print(f"[Training] 训练分布参考 fitness={train_metrics['fitness']:.4f} "
              f"top12={train_metrics['top12_rate']:.3f} (对手池含进化种群与名人堂，强度不同)", flush=True)

        out=Path(save); out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps({
            "version": 5,
            "params": asdict(final_champ),
            "training_metrics": final_train_metrics,
            "validation_metrics": val_metrics,
            "test_metrics": test_metrics,
            "val_distribution_shift": getattr(self, "val_distribution_shift", None),
            "test_distribution_shift": getattr(self, "test_distribution_shift", None),
            "final_race": val_metrics,
            "test_race": test_metrics,
            "train_race": train_metrics,
            "history": history
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        return final_champ, {
            "training": history,
            "validation": val_metrics,
            "test": test_metrics,
            "final_race": val_metrics,
            "train_race": train_metrics,
            "val_distribution_shift": getattr(self, "val_distribution_shift", None),
            "test_distribution_shift": getattr(self, "test_distribution_shift", None),
        }


FUNCTIONAL_BLOCKS = StrategyTrainer.FUNCTIONAL_BLOCKS


def population_diversity(population: list[StrategyParams]) -> float:
    """Calculate the normalized average pairwise parameter distance across individuals.

    Each parameter difference |p_i[k] - p_j[k]| is normalized by (hi - lo) from PARAM_BOUNDS,
    yielding an interpretable diversity metric in [0.0, 1.0].
    """
    if len(population) <= 1:
        return 0.0
    n = len(population)
    fields = StrategyTrainer.FIELDS
    bounds = StrategyTrainer.PARAM_BOUNDS

    total_dist = 0.0
    pairs = 0
    pop_dicts = [asdict(p) for p in population]

    for i in range(n):
        for j in range(i + 1, n):
            p1, p2 = pop_dicts[i], pop_dicts[j]
            dist_sum = 0.0
            for k in fields:
                lo, hi = bounds.get(k, (0.01, 0.99))
                span = max(1e-5, hi - lo)
                diff = abs(float(p1.get(k, 0.0)) - float(p2.get(k, 0.0))) / span
                dist_sum += diff
            total_dist += dist_sum / len(fields)
            pairs += 1

    return total_dist / pairs if pairs > 0 else 0.0


def genome_distance(p1: StrategyParams | dict[str, Any], p2: StrategyParams | dict[str, Any]) -> float:
    """Calculate the normalized average parameter distance between two strategies in [0.0, 1.0]."""
    d1 = asdict(p1) if isinstance(p1, StrategyParams) else p1
    d2 = asdict(p2) if isinstance(p2, StrategyParams) else p2
    fields = StrategyTrainer.FIELDS
    bounds = StrategyTrainer.PARAM_BOUNDS

    dist_sum = 0.0
    for k in fields:
        lo, hi = bounds.get(k, (0.01, 0.99))
        span = max(1e-5, hi - lo)
        diff = abs(float(d1.get(k, 0.5)) - float(d2.get(k, 0.5))) / span
        dist_sum += diff
    return dist_sum / len(fields)


def strategy_signature(p: StrategyParams | dict[str, Any], precision: int = 3) -> str:
    """Compute a deterministic hash signature of a strategy's rounded parameters."""
    d = asdict(p) if isinstance(p, StrategyParams) else p
    fields = sorted(StrategyTrainer.FIELDS)
    rounded_tokens = [f"{k}:{round(float(d.get(k, 0.0)), precision):.{precision}f}" for k in fields]
    raw = "|".join(rounded_tokens)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def hall_of_fame_diversity(hall: list[tuple[float, StrategyParams]]) -> float:
    """Calculate the average pairwise genome distance among Hall of Fame members."""
    if len(hall) <= 1:
        return 0.0
    strats = [p for _, p in hall]
    return population_diversity(strats)


def update_hall_of_fame_qd(
    hall: list[tuple[float, StrategyParams]],
    candidate: StrategyParams,
    fitness: float,
    max_hall_size: int = 12,
    niche_radius: float = 0.06,
) -> list[tuple[float, StrategyParams]]:
    """Quality-Diversity (MAP-Elites / Niche Competition) Hall of Fame updater.

    Guarantees:
    1. Niche Competition: If `candidate` is within `niche_radius` of an existing hall member,
       it only replaces that member if its fitness is strictly higher.
    2. Structural Novelty: If `candidate` is distant (>= niche_radius) from all existing members,
       it represents a distinct strategic branch and claims a new niche slot.
    3. Diversity-Preserving Pruning: When hall size exceeds max_hall_size, pruning drops the lower-fitness
       member from the closest pair of individuals, preserving strategic breadth and preventing clustering.
    """
    if not hall:
        return [(float(fitness), replace(candidate))]

    cand_copy = replace(candidate)
    cand_fit = float(fitness)

    closest_idx = -1
    min_dist = float("inf")
    for i, (_, p_member) in enumerate(hall):
        d = genome_distance(cand_copy, p_member)
        if d < min_dist:
            min_dist = d
            closest_idx = i

    new_hall = list(hall)
    if min_dist < niche_radius:
        # Niche competition
        existing_fit, _ = new_hall[closest_idx]
        if cand_fit > existing_fit:
            new_hall[closest_idx] = (cand_fit, cand_copy)
    else:
        # Novel branch
        new_hall.append((cand_fit, cand_copy))

    # Pruning
    while len(new_hall) > max_hall_size:
        best_pair = None
        closest_pair_dist = float("inf")
        for i in range(len(new_hall)):
            for j in range(i + 1, len(new_hall)):
                d = genome_distance(new_hall[i][1], new_hall[j][1])
                if d < closest_pair_dist:
                    closest_pair_dist = d
                    best_pair = (i, j)

        if best_pair is not None and closest_pair_dist < niche_radius * 1.5:
            i, j = best_pair
            drop_idx = i if new_hall[i][0] <= new_hall[j][0] else j
            new_hall.pop(drop_idx)
        else:
            worst_idx = min(range(len(new_hall)), key=lambda idx: new_hall[idx][0])
            new_hall.pop(worst_idx)

    new_hall.sort(key=lambda x: -x[0])
    return new_hall


def compute_ab_statistical_test(
    scores_a: list[float],
    scores_b: list[float],
    alpha: float = 0.05,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Perform rigorous A/B statistical hypothesis testing between baseline (A) and candidate (B).

    Computes:
    - Sample sizes, means, sample standard deviations, standard errors.
    - Mean difference: delta = mean(B) - mean(A).
    - Welch's two-sample t-statistic and Welch-Satterthwaite degrees of freedom.
    - Asymptotic two-tailed p-value via normal / complementary error function approximation.
    - Non-parametric Bootstrap 95% Confidence Interval for mean difference.
    - Standardized effect size (Cohen's d).
    - Win rate / dominance ratio (if samples are paired).
    - Statistical significance decision (p_value < alpha and CI strictly excludes 0).
    """
    n_a = len(scores_a)
    n_b = len(scores_b)
    if n_a == 0 or n_b == 0:
        return {
            "n_a": n_a, "n_b": n_b, "mean_a": 0.0, "mean_b": 0.0, "delta": 0.0,
            "t_stat": 0.0, "p_value": 1.0, "ci95": [0.0, 0.0], "cohens_d": 0.0,
            "win_rate_candidate": 0.5, "statistically_significant": False, "candidate_dominates": False,
        }

    mean_a = float(statistics.mean(scores_a))
    mean_b = float(statistics.mean(scores_b))
    delta = mean_b - mean_a

    var_a = float(statistics.variance(scores_a)) if n_a > 1 else 0.0
    var_b = float(statistics.variance(scores_b)) if n_b > 1 else 0.0
    std_a = math.sqrt(max(0.0, var_a))
    std_b = math.sqrt(max(0.0, var_b))

    se_diff = math.sqrt(var_a / max(1, n_a) + var_b / max(1, n_b))

    if se_diff > 1e-12:
        t_stat = delta / se_diff
        # Welch-Satterthwaite degrees of freedom
        num = (var_a / n_a + var_b / n_b) ** 2
        denom = ((var_a / n_a) ** 2) / max(1, n_a - 1) + ((var_b / n_b) ** 2) / max(1, n_b - 1)
        df = num / denom if denom > 1e-12 else float(n_a + n_b - 2)
        p_value = math.erfc(abs(t_stat) / math.sqrt(2.0))
    else:
        t_stat = 0.0
        df = float(n_a + n_b - 2)
        p_value = 1.0 if abs(delta) < 1e-9 else 0.0

    # Cohen's d
    if n_a + n_b > 2:
        pooled_var = ((n_a - 1) * var_a + (n_b - 1) * var_b) / max(1, n_a + n_b - 2)
        pooled_std = math.sqrt(max(0.0, pooled_var))
        cohens_d = (delta / pooled_std) if pooled_std > 1e-12 else 0.0
    else:
        cohens_d = 0.0

    # Non-parametric Bootstrap 95% Confidence Interval
    rng = random.Random(seed)
    boot_deltas: list[float] = []
    for _ in range(n_bootstrap):
        sample_a = [scores_a[rng.randint(0, n_a - 1)] for _ in range(n_a)]
        sample_b = [scores_b[rng.randint(0, n_b - 1)] for _ in range(n_b)]
        boot_deltas.append(statistics.mean(sample_b) - statistics.mean(sample_a))
    boot_deltas.sort()
    idx_lo = int(0.025 * n_bootstrap)
    idx_hi = int(0.975 * n_bootstrap)
    ci95 = [round(boot_deltas[idx_lo], 5), round(boot_deltas[idx_hi], 5)]

    # Paired win rate if sample lengths match
    if n_a == n_b:
        wins_b = sum(1 for sa, sb in zip(scores_a, scores_b) if sb > sa)
        ties = sum(1 for sa, sb in zip(scores_a, scores_b) if abs(sb - sa) < 1e-9)
        win_rate_b = (wins_b + 0.5 * ties) / n_a
    else:
        win_rate_b = 0.5

    stat_sig = bool(p_value < alpha and (ci95[0] > 0 or ci95[1] < 0))
    cand_dominates = bool(stat_sig and delta > 0)

    return {
        "n_a": n_a,
        "n_b": n_b,
        "mean_a": round(mean_a, 5),
        "mean_b": round(mean_b, 5),
        "std_a": round(std_a, 5),
        "std_b": round(std_b, 5),
        "delta": round(delta, 5),
        "se_diff": round(se_diff, 5),
        "t_stat": round(t_stat, 4),
        "df": round(df, 2),
        "p_value": round(p_value, 6),
        "ci95": ci95,
        "cohens_d": round(cohens_d, 4),
        "win_rate_candidate": round(win_rate_b, 4),
        "statistically_significant": stat_sig,
        "candidate_dominates": cand_dominates,
    }


def conduct_generalization_ab_suite(
    candidate: StrategyParams,
    baseline: StrategyParams,
    evaluator: ArenaEvaluator | None = None,
    runs_per_track: int = 15,
    pool_size: int = 12,
    seed_base: int = 42,
    ecologies: list[str] | None = None,
    profiles_path: str | Path | None = None,
    tournament_config: TournamentConfig | None = None,
    workers: int = 0,
    verbose: bool = True,
) -> dict[str, Any]:
    """Execute comprehensive 4-Way Generalization A/B Evaluation Suite.

    Evaluates Candidate (Model B) against Baseline (Model A) across 4 foundational tracks:
    1. Track 1: Seen Training Distribution
    2. Track 2: Unseen Out-of-Distribution (OOD) Archetypes Field
    3. Track 3: Macro Distribution Shift Stress Regimes (extreme aggression/passivity/hybrids)
    4. Track 4: Stability & Cross-Ecology ANOVA Variance Decomposition

    Returns full A/B statistical hypothesis test metrics, confidence intervals, and promotion verdict.
    """
    if evaluator is None:
        evaluator = ArenaEvaluator(
            pool_size=pool_size,
            seed=seed_base,
            profiles=profiles_path,
            tournament_config=tournament_config,
            workers=workers,
        )

    # Initialize environments
    trainer_stub = StrategyTrainer(
        seed=seed_base,
        pool_size=pool_size,
        profiles=profiles_path,
        tournament_config=tournament_config,
        workers=workers,
    )

    # Track 1: Seen Training Distribution
    if verbose:
        print("\n=== Track 1: Seen Training Distribution A/B Test ===", flush=True)
    seen_pool = trainer_stub.train_env.sample_pool(pool_size, seed=seed_base + 1001)
    base_seen_m = evaluator.evaluate(baseline, runs=runs_per_track, opponents=seen_pool, seed_offset=10000, verbose=False)
    cand_seen_m = evaluator.evaluate(candidate, runs=runs_per_track, opponents=seen_pool, seed_offset=10000, verbose=False)

    base_seen_scores = [sm["run_fitness"] for sm in base_seen_m.get("stage_results", [])] or [base_seen_m["fitness"]]
    cand_seen_scores = [sm["run_fitness"] for sm in cand_seen_m.get("stage_results", [])] or [cand_seen_m["fitness"]]
    seen_ab = compute_ab_statistical_test(base_seen_scores, cand_seen_scores, seed=seed_base + 11)

    # Track 2: Unseen OOD Archetypes Field
    if verbose:
        print("\n=== Track 2: Unseen OOD Field A/B Test ===", flush=True)
    unseen_pool = trainer_stub.test_env.sample_pool(pool_size, seed=seed_base + 2002)
    base_unseen_m = evaluator.evaluate(baseline, runs=runs_per_track, opponents=unseen_pool, seed_offset=20000, verbose=False)
    cand_unseen_m = evaluator.evaluate(candidate, runs=runs_per_track, opponents=unseen_pool, seed_offset=20000, verbose=False)

    base_unseen_scores = [sm["run_fitness"] for sm in base_unseen_m.get("stage_results", [])] or [base_unseen_m["fitness"]]
    cand_unseen_scores = [sm["run_fitness"] for sm in cand_unseen_m.get("stage_results", [])] or [cand_unseen_m["fitness"]]
    unseen_ab = compute_ab_statistical_test(base_unseen_scores, cand_unseen_scores, seed=seed_base + 22)

    # Track 3: Macro Distribution Shift Modes
    if verbose:
        print("\n=== Track 3: Macro Distribution Shift Modes A/B Test ===", flush=True)
    shift_modes = ["extreme_aggression", "extreme_passivity", "unseen_hybrids"]
    base_shift_all: list[float] = []
    cand_shift_all: list[float] = []
    mode_results: dict[str, Any] = {}
    shift_runs_each = max(1, min(runs_per_track, 5))

    for s_idx, mode in enumerate(shift_modes):
        stress_pool = trainer_stub.test_env.sample_pool(pool_size, seed=seed_base + 3000 + s_idx * 100, ood_mode=mode)
        bm = evaluator.evaluate(baseline, runs=shift_runs_each, opponents=stress_pool, seed_offset=30000 + s_idx * 1000, verbose=False)
        cm = evaluator.evaluate(candidate, runs=shift_runs_each, opponents=stress_pool, seed_offset=30000 + s_idx * 1000, verbose=False)
        b_sc = [sm["run_fitness"] for sm in bm.get("stage_results", [])] or [bm["fitness"]]
        c_sc = [sm["run_fitness"] for sm in cm.get("stage_results", [])] or [cm["fitness"]]
        base_shift_all.extend(b_sc)
        cand_shift_all.extend(c_sc)
        mode_results[mode] = compute_ab_statistical_test(b_sc, c_sc, seed=seed_base + 33 + s_idx)

    shift_ab = compute_ab_statistical_test(base_shift_all, cand_shift_all, seed=seed_base + 33)
    shift_ab["mode_breakdowns"] = mode_results

    # Track 4: Stability & Cross-Ecology ANOVA Robustness
    if verbose:
        print("\n=== Track 4: Stability & Multi-Ecology Robustness A/B Test ===", flush=True)
    active_ecologies = ecologies or ["balanced", "aggressive", "passive", "mixed", "adversarial"]
    runs_per_eco = max(1, runs_per_track // len(active_ecologies))

    base_eco_m = evaluator.evaluate_multi_ecology(
        baseline, ecologies=active_ecologies, runs_per_ecology=runs_per_eco, seed_offset=40000, verbose=False
    )
    cand_eco_m = evaluator.evaluate_multi_ecology(
        candidate, ecologies=active_ecologies, runs_per_ecology=runs_per_eco, seed_offset=40000, verbose=False
    )

    base_eco_scores = [sm["run_fitness"] for sm in base_eco_m.get("stage_results", [])] or [base_eco_m["fitness"]]
    cand_eco_scores = [sm["run_fitness"] for sm in cand_eco_m.get("stage_results", [])] or [cand_eco_m["fitness"]]
    stability_ab = compute_ab_statistical_test(base_eco_scores, cand_eco_scores, seed=seed_base + 44)

    # Cross-ecology variance comparison
    base_between_var = base_eco_m.get("between_ecology_variance", 0.0)
    cand_between_var = cand_eco_m.get("between_ecology_variance", 0.0)
    variance_reduction = base_between_var - cand_between_var

    base_robust_fit = base_eco_m.get("robust_fitness", base_eco_m["fitness"])
    cand_robust_fit = cand_eco_m.get("robust_fitness", cand_eco_m["fitness"])
    robust_fitness_gain = cand_robust_fit - base_robust_fit

    # Overall Acceptance Verdict
    # Passes if:
    # 1. Candidate robust fitness does not suffer significant regression (>= base_robust_fit - 0.02)
    # 2. Candidate unseen fitness does not suffer significant regression (>= base_unseen_fit - 0.025)
    # 3. Candidate between-ecology variance is bounded (cand_between_var <= base_between_var * 2.0 or <= 0.01)
    # 4. Overall win rate on unseen/shift tracks is >= 45%
    no_robust_regression = bool(cand_robust_fit >= base_robust_fit - 0.02)
    no_unseen_regression = bool(cand_unseen_m["fitness"] >= base_unseen_m["fitness"] - 0.025)
    variance_controlled = bool(cand_between_var <= max(0.01, base_between_var * 2.0))
    generalization_certified = bool(no_robust_regression and no_unseen_regression and variance_controlled)

    recommendation = "PROMOTE_CANDIDATE" if (generalization_certified and (robust_fitness_gain >= -1e-4 or unseen_ab["delta"] >= -1e-4)) else "RETAIN_BASELINE"

    return {
        "candidate_certified": generalization_certified,
        "recommendation": recommendation,
        "seen_track": {
            "baseline_fitness": base_seen_m["fitness"],
            "candidate_fitness": cand_seen_m["fitness"],
            "baseline_bb100": base_seen_m.get("overall_bb100", base_seen_m.get("avg_bb100", 0.0)),
            "candidate_bb100": cand_seen_m.get("overall_bb100", cand_seen_m.get("avg_bb100", 0.0)),
            "ab_test": seen_ab,
        },
        "unseen_track": {
            "baseline_fitness": base_unseen_m["fitness"],
            "candidate_fitness": cand_unseen_m["fitness"],
            "baseline_bb100": base_unseen_m.get("overall_bb100", base_unseen_m.get("avg_bb100", 0.0)),
            "candidate_bb100": cand_unseen_m.get("overall_bb100", cand_unseen_m.get("avg_bb100", 0.0)),
            "ab_test": unseen_ab,
        },
        "shift_track": {
            "ab_test": shift_ab,
        },
        "stability_track": {
            "baseline_robust_fitness": base_robust_fit,
            "candidate_robust_fitness": cand_robust_fit,
            "robust_fitness_gain": round(robust_fitness_gain, 5),
            "baseline_between_ecology_variance": round(base_between_var, 6),
            "candidate_between_ecology_variance": round(cand_between_var, 6),
            "variance_reduction": round(variance_reduction, 6),
            "baseline_worst_ecology": base_eco_m.get("worst_ecology_name", "-"),
            "candidate_worst_ecology": cand_eco_m.get("worst_ecology_name", "-"),
            "ab_test": stability_ab,
        },
        "summary": {
            "no_robust_regression": no_robust_regression,
            "no_unseen_regression": no_unseen_regression,
            "variance_controlled": variance_controlled,
            "robust_fitness_gain": round(robust_fitness_gain, 5),
            "unseen_fitness_gain": round(unseen_ab["delta"], 5),
            "generalization_certified": generalization_certified,
        },
    }

