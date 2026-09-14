"""Golden Pyramid Ecosystem and Opponent Field Generation for AgentPoker.

Provides realistic 120-player competitive ecosystems:
- Sharks (30%): Exploitative, highly aggressive, high pressure (LAG, Maniac, Top Sharks)
- Regulars (40%): Balanced, tight-aggressive, solid discipline (TAG, Nit, Balanced GTO)
- Fish (30%): Calling stations, passive recreationals, high VPIP, low fold (Station, Passive)
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from random import Random
from typing import Any
import json

from .strategy import StrategyParams
from .training import ARCHETYPES, profile_to_params, sample_profile_posterior


SHARK_ARCHETYPES = ["lag", "maniac"]
REGULAR_ARCHETYPES = ["balanced", "tight", "nit"]
FISH_ARCHETYPES = ["station"]


def classify_profile_dict(p: dict[str, Any]) -> str:
    """Classify a player profile dictionary into 'shark', 'regular', or 'fish'."""
    st = p.get("stats") or p
    hands = int(st.get("hands", 0) or 0)
    vpip_c = float(st.get("vpip_count", 0) or 0)
    pfr_c = float(st.get("pfr_count", 0) or 0)
    vpip = (vpip_c / max(1, hands)) if hands > 0 else float(st.get("vpip", 0.25) or 0.25)
    pfr = (pfr_c / max(1, hands)) if hands > 0 else float(st.get("pfr", 0.15) or 0.15)
    af = float(st.get("aggression_factor", 1.5) or 1.5)

    # Calling station / passive fish
    if vpip >= 0.35 and (pfr <= 0.12 or af < 1.0):
        return "fish"
    if vpip >= 0.40 and af < 1.5:
        return "fish"

    # Sharks: high aggression, wide range or loose-aggressive
    if (vpip >= 0.28 and pfr >= 0.18) or af >= 2.5:
        return "shark"

    # Regulars: tight-aggressive or balanced
    return "regular"


@dataclass(frozen=True)
class PyramidRatios:
    """Target ecosystem ratios."""
    shark_ratio: float = 0.30
    regular_ratio: float = 0.40
    fish_ratio: float = 0.30

    def compute_counts(self, total: int) -> tuple[int, int, int]:
        """Compute integer counts (sharks, regulars, fish) that strictly sum to `total`."""
        if total <= 0:
            return 0, 0, 0
        n_sharks = int(round(total * self.shark_ratio))
        n_regulars = int(round(total * self.regular_ratio))
        n_fish = total - n_sharks - n_regulars
        # Ensure non-negative
        if n_fish < 0:
            n_fish = 0
            n_regulars = total - n_sharks
        return n_sharks, n_regulars, n_fish


@dataclass(frozen=True)
class EcologySpec:
    """Specification of an opponent ecology regime."""
    name: str
    description: str
    archetype_weights: dict[str, float]
    shark_ratio: float = 0.30
    regular_ratio: float = 0.40
    fish_ratio: float = 0.30


STANDARD_ECOLOGIES: dict[str, EcologySpec] = {
    "balanced": EcologySpec(
        name="balanced",
        description="Standard balanced field with equal mix of TAG, LAG, Nit, Station, and Balanced GTO",
        archetype_weights={"balanced": 0.25, "tight": 0.25, "lag": 0.20, "nit": 0.15, "station": 0.15},
        shark_ratio=0.20,
        regular_ratio=0.50,
        fish_ratio=0.30,
    ),
    "aggressive": EcologySpec(
        name="aggressive",
        description="Aggressive heavy shark field dominated by LAG and Maniac pressure",
        archetype_weights={"lag": 0.45, "maniac": 0.35, "tight": 0.15, "station": 0.05},
        shark_ratio=0.60,
        regular_ratio=0.30,
        fish_ratio=0.10,
    ),
    "passive": EcologySpec(
        name="passive",
        description="Passive recreational field dominated by calling stations and tight nits",
        archetype_weights={"station": 0.55, "nit": 0.25, "tight": 0.15, "balanced": 0.05},
        shark_ratio=0.05,
        regular_ratio=0.35,
        fish_ratio=0.60,
    ),
    "mixed": EcologySpec(
        name="mixed",
        description="Classic Golden Pyramid combining real opponent profiles and balanced archetypes",
        archetype_weights={"balanced": 0.25, "lag": 0.25, "station": 0.25, "tight": 0.15, "nit": 0.10},
        shark_ratio=0.30,
        regular_ratio=0.40,
        fish_ratio=0.30,
    ),
    "adversarial": EcologySpec(
        name="adversarial",
        description="Adversarial field of extreme polar play: hyper-maniacs, tight rocks, and trapping regulars",
        archetype_weights={"maniac": 0.45, "nit": 0.25, "lag": 0.20, "tight": 0.10},
        shark_ratio=0.55,
        regular_ratio=0.35,
        fish_ratio=0.10,
    ),
}


def load_profile_params_by_tier(
    profiles_path: str | Path | None,
    min_hands: int = 15,
    sample_posterior: bool = False,
    rng: Random | None = None,
) -> tuple[list[StrategyParams], list[StrategyParams], list[StrategyParams]]:
    """Load profiles and partition into (sharks, regulars, fish)."""
    if not profiles_path:
        return [], [], []
    path = Path(profiles_path)
    if not path.exists():
        return [], [], []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return [], [], []

    raw_list = data if isinstance(data, list) else list(data.values())
    filtered = [p for p in raw_list if isinstance(p, dict) and int(p.get("hands", 0) or (p.get("stats") or {}).get("hands", 0) or 0) >= min_hands]

    sharks: list[StrategyParams] = []
    regulars: list[StrategyParams] = []
    fish: list[StrategyParams] = []

    for p in filtered:
        tier = classify_profile_dict(p)
        params = sample_profile_posterior(p, rng=rng) if (sample_posterior and rng is not None) else profile_to_params(p)
        if tier == "shark":
            sharks.append(params)
        elif tier == "fish":
            fish.append(params)
        else:
            regulars.append(params)

    return sharks, regulars, fish


def build_ecosystem_pool(
    count: int,
    mode: str = "pyramid",
    profiles_path: str | Path | None = "models/opponent_profiles.json",
    min_hands: int = 15,
    ratios: PyramidRatios = PyramidRatios(),
    seed: int | None = None,
) -> list[StrategyParams]:
    """Build an opponent pool of exact length `count` matching the specified mode."""
    if count <= 0:
        return []

    rng = Random(seed) if seed is not None else Random()

    shark_archetypes = [ARCHETYPES[k] for k in SHARK_ARCHETYPES]
    regular_archetypes = [ARCHETYPES[k] for k in REGULAR_ARCHETYPES]
    fish_archetypes = [ARCHETYPES[k] for k in FISH_ARCHETYPES]
    all_archetypes = list(ARCHETYPES.values())

    p_sharks, p_regs, p_fish = load_profile_params_by_tier(profiles_path, min_hands)

    def _fill_tier(needed: int, real_pool: list[StrategyParams], arch_pool: list[StrategyParams]) -> list[StrategyParams]:
        res: list[StrategyParams] = []
        if real_pool:
            shuffled = list(real_pool)
            rng.shuffle(shuffled)
            for i in range(min(needed, len(shuffled))):
                res.append(replace(shuffled[i]))
        # Supplement remainder from archetype pool
        rem = needed - len(res)
        for i in range(rem):
            res.append(replace(arch_pool[i % len(arch_pool)]))
        return res

    if mode == "pyramid":
        n_sharks, n_regs, n_fish = ratios.compute_counts(count)
        pool: list[StrategyParams] = []
        pool.extend(_fill_tier(n_sharks, p_sharks, shark_archetypes))
        pool.extend(_fill_tier(n_regs, p_regs, regular_archetypes))
        pool.extend(_fill_tier(n_fish, p_fish, fish_archetypes))
        rng.shuffle(pool)
        return pool[:count]

    elif mode == "sharks":
        return _fill_tier(count, p_sharks, shark_archetypes)

    elif mode == "fish":
        return _fill_tier(count, p_fish, fish_archetypes)

    elif mode == "profiles" and (p_sharks or p_regs or p_fish):
        all_profs = p_sharks + p_regs + p_fish
        rng.shuffle(all_profs)
        out: list[StrategyParams] = []
        for i in range(count):
            out.append(replace(all_profs[i % len(all_profs)]))
        return out

    elif mode == "mix" and (p_sharks or p_regs or p_fish):
        all_profs = p_sharks + p_regs + p_fish
        n_prof = count // 2
        n_arch = count - n_prof
        out = []
        for i in range(n_prof):
            out.append(replace(all_profs[i % len(all_profs)]))
        for i in range(n_arch):
            out.append(replace(all_archetypes[i % len(all_archetypes)]))
        rng.shuffle(out)
        return out

    else:  # "archetypes" fallback
        out = []
        for i in range(count):
            out.append(replace(all_archetypes[i % len(all_archetypes)]))
        return out


def build_120_pyramid_field(
    profiles_path: str | Path | None = "models/opponent_profiles.json",
    min_hands: int = 15,
    seed: int | None = 42,
) -> list[StrategyParams]:
    """Convenience helper to generate standard 120-player field under Golden Pyramid ratios."""
    return build_ecosystem_pool(
        count=120,
        mode="pyramid",
        profiles_path=profiles_path,
        min_hands=min_hands,
        ratios=PyramidRatios(0.30, 0.40, 0.30),
        seed=seed,
    )


def build_ecology_pool(
    ecology: str | EcologySpec,
    count: int,
    profiles_path: str | Path | None = "models/opponent_profiles.json",
    profile_params: list[StrategyParams | dict[str, Any]] | None = None,
    min_hands: int = 15,
    seed: int | None = None,
    sample_posterior: bool = False,
) -> list[StrategyParams]:
    """Build an opponent pool of exact length `count` matching the specified ecology.

    Guarantees:
    - Independent sampling across seeds.
    - Deterministic output given the same seed.
    - Real profiles partitioned and weighted according to ecology archetype/tier targets.
    - Full Bayesian posterior sampling under epistemic uncertainty when sample_posterior=True.
    """
    if count <= 0:
        return []

    if isinstance(ecology, EcologySpec):
        spec = ecology
    else:
        eco_key = str(ecology).lower().strip()
        spec = STANDARD_ECOLOGIES.get(eco_key, STANDARD_ECOLOGIES["balanced"])

    rng = Random(seed) if seed is not None else Random()

    shark_archs = [ARCHETYPES[k] for k in SHARK_ARCHETYPES if k in ARCHETYPES]
    regular_archs = [ARCHETYPES[k] for k in REGULAR_ARCHETYPES if k in ARCHETYPES]
    fish_archs = [ARCHETYPES[k] for k in FISH_ARCHETYPES if k in ARCHETYPES]

    if profile_params is not None:
        p_sharks: list[StrategyParams] = []
        p_regs: list[StrategyParams] = []
        p_fish: list[StrategyParams] = []
        for p in profile_params:
            if isinstance(p, dict):
                tier = classify_profile_dict(p)
                p_item = sample_profile_posterior(p, rng=rng) if sample_posterior else profile_to_params(p)
            else:
                vpip = getattr(p, "vpip", 0.25)
                pfr = getattr(p, "threebet_frequency", 0.07) * 2.5
                af = getattr(p, "attack", 0.5) * 3.0
                if vpip >= 0.35 and (pfr <= 0.12 or af < 1.0):
                    tier = "fish"
                elif (vpip >= 0.28 and pfr >= 0.18) or af >= 2.5:
                    tier = "shark"
                else:
                    tier = "regular"
                p_item = sample_profile_posterior(p, rng=rng) if sample_posterior else replace(p)
            if tier == "shark":
                p_sharks.append(p_item)
            elif tier == "fish":
                p_fish.append(p_item)
            else:
                p_regs.append(p_item)
    else:
        p_sharks, p_regs, p_fish = load_profile_params_by_tier(
            profiles_path, min_hands, sample_posterior=sample_posterior, rng=rng
        )

    ratios = PyramidRatios(spec.shark_ratio, spec.regular_ratio, spec.fish_ratio)
    n_sharks, n_regs, n_fish = ratios.compute_counts(count)

    arch_keys = list(spec.archetype_weights.keys())
    arch_weights = [spec.archetype_weights[k] for k in arch_keys]

    def _fill_tier_weighted(
        needed: int,
        real_pool: list[StrategyParams],
        arch_pool: list[StrategyParams],
    ) -> list[StrategyParams]:
        res: list[StrategyParams] = []
        if needed <= 0:
            return res
        if real_pool:
            n_real = min(len(real_pool), max(1, int(round(needed * 0.50))))
            shuffled = list(real_pool)
            rng.shuffle(shuffled)
            for i in range(n_real):
                res.append(replace(shuffled[i]))
        rem = needed - len(res)
        matching_keys = [
            k for k in arch_keys
            if k in ARCHETYPES and (
                (k in SHARK_ARCHETYPES and arch_pool == shark_archs) or
                (k in REGULAR_ARCHETYPES and arch_pool == regular_archs) or
                (k in FISH_ARCHETYPES and arch_pool == fish_archs)
            )
        ]
        for _ in range(rem):
            if matching_keys:
                m_weights = [spec.archetype_weights[k] for k in matching_keys]
                chosen_key = rng.choices(matching_keys, weights=m_weights, k=1)[0]
                res.append(replace(ARCHETYPES[chosen_key]))
            elif arch_pool:
                res.append(replace(rng.choice(arch_pool)))
            else:
                res.append(replace(ARCHETYPES["balanced"]))
        return res

    pool: list[StrategyParams] = []
    pool.extend(_fill_tier_weighted(n_sharks, p_sharks, shark_archs))
    pool.extend(_fill_tier_weighted(n_regs, p_regs, regular_archs))
    pool.extend(_fill_tier_weighted(n_fish, p_fish, fish_archs))

    while len(pool) < count:
        chosen_k = rng.choices(arch_keys, weights=arch_weights, k=1)[0]
        pool.append(replace(ARCHETYPES[chosen_k]))

    pool = pool[:count]
    rng.shuffle(pool)
    return pool


def build_multi_ecology_pools(
    ecologies: list[str] | list[EcologySpec] | None = None,
    count: int = 120,
    profiles_path: str | Path | None = "models/opponent_profiles.json",
    profile_params: list[StrategyParams | dict[str, Any]] | None = None,
    min_hands: int = 15,
    seed_base: int = 42,
    sample_posterior: bool = False,
) -> dict[str, list[StrategyParams]]:
    """Build independent opponent pools for each requested ecology.

    Guarantees:
    - Intra-ecology pairing: pool for ecology E is uniquely determined by its seed.
    - Inter-ecology independence: distinct ecologies use independent seeds.
    """
    if ecologies is None:
        ecologies = list(STANDARD_ECOLOGIES.keys())

    pools: dict[str, list[StrategyParams]] = {}
    for idx, eco in enumerate(ecologies):
        eco_name = eco.name if isinstance(eco, EcologySpec) else str(eco)
        eco_seed = seed_base + 104729 * (idx + 1) + 17
        pools[eco_name] = build_ecology_pool(
            ecology=eco,
            count=count,
            profiles_path=profiles_path,
            profile_params=profile_params,
            min_hands=min_hands,
            seed=eco_seed,
            sample_posterior=sample_posterior,
        )
    return pools

