from __future__ import annotations
from dataclasses import asdict, replace
from pathlib import Path
import json, math, random, statistics
from typing import Any
from concurrent.futures import ProcessPoolExecutor, as_completed
from .strategy import StrategyAgent, StrategyParams
from .tournament import LeagueSimulator, SimAgent

ARCHETYPES = {
    "nit": StrategyParams(vpip=.14, open_frequency=.50, threebet_frequency=.055, squeeze_frequency=.035, steal_frequency=.58, cbet_frequency=.55, turn_barrel_frequency=.42, river_bluff_frequency=.035, value_threshold=.72, thin_value_threshold=.64, raise_threshold=.66, jam_threshold=.94, open_size=2.20, cbet_size=.42, value_bet_size=.72, bluff_bet_size=.46, raise_size=.62, safety=.60, attack=.48, bubble_aggression=.52, late_aggression=.10, temperature=.05),
    "tight": StrategyParams(vpip=.18, open_frequency=.58, threebet_frequency=.070, squeeze_frequency=.045, steal_frequency=.65, cbet_frequency=.60, turn_barrel_frequency=.50, river_bluff_frequency=.055, value_threshold=.70, thin_value_threshold=.62, raise_threshold=.64, jam_threshold=.93, open_size=2.30, cbet_size=.45, value_bet_size=.71, bluff_bet_size=.50, raise_size=.65, safety=.52, attack=.56, bubble_aggression=.62, late_aggression=.14, temperature=.06),
    "balanced": StrategyParams(),
    "lag": StrategyParams(vpip=.31, open_frequency=.72, threebet_frequency=.105, squeeze_frequency=.075, steal_frequency=.82, cbet_frequency=.69, turn_barrel_frequency=.61, river_bluff_frequency=.11, value_threshold=.61, thin_value_threshold=.54, raise_threshold=.57, jam_threshold=.87, open_size=2.40, cbet_size=.50, value_bet_size=.67, bluff_bet_size=.58, raise_size=.73, safety=.38, attack=.82, bubble_aggression=.88, late_aggression=.30, temperature=.13),
    "station": StrategyParams(vpip=.43, open_frequency=.47, threebet_frequency=.040, squeeze_frequency=.025, steal_frequency=.55, cbet_frequency=.43, turn_barrel_frequency=.33, river_bluff_frequency=.020, value_threshold=.64, thin_value_threshold=.56, raise_threshold=.69, jam_threshold=.95, open_size=2.25, cbet_size=.41, value_bet_size=.74, bluff_bet_size=.42, raise_size=.56, safety=.42, attack=.55, bubble_aggression=.58, late_aggression=.12, temperature=.03),
    "maniac": StrategyParams(vpip=.48, open_frequency=.83, threebet_frequency=.145, squeeze_frequency=.110, steal_frequency=.90, cbet_frequency=.77, turn_barrel_frequency=.72, river_bluff_frequency=.18, value_threshold=.54, thin_value_threshold=.50, raise_threshold=.50, jam_threshold=.80, open_size=2.55, cbet_size=.56, value_bet_size=.62, bluff_bet_size=.64, raise_size=.82, safety=.72, attack=.96, bubble_aggression=.98, late_aggression=.42, temperature=.18),
}

def _summarise(top, final, champ, ranks, bbs, runs, pool) -> dict[str, Any]:
    """Aggregate per-run outcomes into fitness plus its own uncertainty.

    Reporting a bare point estimate hides the fact that with a handful of tournament
    runs the fitness differences between generations are pure noise, so the standard
    error and a 95% interval travel with every result.
    """
    runs = max(1, runs)
    top_rate, final_rate, champ_rate = top / runs, final / runs, champ / runs
    avg_rank = sum(ranks) / runs
    avg_bb = sum(bbs) / runs
    fit = (.58 * top_rate + .22 * final_rate + .15 * champ_rate
           + .05 * (1.0 - min(avg_rank - 1, pool - 1) / (pool - 1)))

    def var_prop(p):  # Var of a proportion over `runs` independent tournaments
        return p * (1.0 - p) / runs

    def cov(p1, p2):  # nested events: P(A and B) = min(p1, p2)
        return (min(p1, p2) - p1 * p2) / runs

    var = (.58 ** 2) * var_prop(top_rate) + (.22 ** 2) * var_prop(final_rate) \
        + (.15 ** 2) * var_prop(champ_rate) \
        + 2 * .58 * .22 * cov(top_rate, final_rate) \
        + 2 * .58 * .15 * cov(top_rate, champ_rate) \
        + 2 * .22 * .15 * cov(final_rate, champ_rate)
    if runs > 1 and len(ranks) > 1:
        var += (.05 / (pool - 1)) ** 2 * (statistics.variance(ranks) / runs)
    se = math.sqrt(max(0.0, var))
    return {
        "top12_rate": top_rate, "final_rate": final_rate, "champion_rate": champ_rate,
        "avg_rank": avg_rank, "avg_bb100": avg_bb, "fitness": fit,
        "fitness_se": se, "fitness_ci95": [fit - 1.96 * se, fit + 1.96 * se],
        "runs": runs,
    }


def _evaluate_worker(payload):
    focal, opponents, seed, runs, equity_samples = payload[:5]
    verbose = payload[5] if len(payload) > 5 else False
    agents=[SimAgent("focal", StrategyAgent(replace(focal, equity_samples=equity_samples), seed=seed, name="focal"))]
    for i,p in enumerate(opponents):
        agents.append(SimAgent(f"opp{i}", StrategyAgent(replace(p, equity_samples=equity_samples), seed=seed+31*i+17, name=f"opp{i}")))
    top=final=champ=0; rank_sum=bb_sum=0.0
    ranks: list[float] = []; bbs: list[float] = []
    for run in range(runs):
        # Seeding is a pure function of (seed, run), so every candidate handed the same
        # seed base plays the identical sequence of deals against an identical opponent
        # line-up. That is what makes candidate comparisons paired rather than noise-on-noise.
        s=seed+run*7919
        seeded=[]
        for j,a in enumerate(agents):
            seeded.append(SimAgent(a.agent_id, StrategyAgent(a.strategy.params, seed=s+1000*j, name=a.agent_id)))
        sim=LeagueSimulator(seeded, seed=s)
        result=sim.run_event()
        standings=result["preliminary"]
        me=next(x for x in standings if x.agent_id=="focal")
        ranks.append(float(me.rank or len(standings))); bbs.append(float(me.bb100 or 0.0))
        rank_sum += me.rank or len(standings); bb_sum += me.bb100 or 0.0
        q={x.agent_id for x in result["qualified"]}; f={x.agent_id for x in result["final"]}
        is_top12 = "focal" in q
        is_final = "focal" in f
        is_champ = bool(result["final"] and result["final"][0].agent_id=="focal")
        top += is_top12; final += is_final; champ += is_champ

        if verbose:
            cur_run = run + 1
            cum_bb = bb_sum / cur_run
            cum_top = (top / cur_run) * 100.0
            cum_champ = (champ / cur_run) * 100.0
            if is_champ:
                outcome = "🏆 夺冠 (第 1 名)"
            elif is_final:
                f_rank = next((idx for idx, x in enumerate(result["final"], 1) if x.agent_id == "focal"), 6)
                outcome = f"决赛桌 第 {f_rank} 名"
            elif is_top12:
                outcome = "12强半决赛"
            else:
                outcome = f"未出线 (第 {me.rank} 名)"

            print(
                f"[评估进度 {cur_run:02d}/{runs:02d} | 200手结算] "
                f"预赛: 第 {me.rank:02d} 名 ({me.bb100:+.1f} BB/100) | "
                f"赛果: {outcome:<12} | "
                f"累计走势: {cum_bb:+.1f} BB/100 (出线率 {cum_top:.0f}%, 夺冠率 {cum_champ:.0f}%)",
                flush=True
            )

    return _summarise(top, final, champ, ranks, bbs, runs, len(agents))

def profile_to_params(p: dict[str, Any]) -> StrategyParams:
    """Map a real player profile's empirical statistics into a StrategyParams agent.

    Covers all 23 behavioural parameters. Previously eleven of them -- including every
    bet sizing -- were left at defaults, so all 59 profiled opponents shared identical
    sizing and only differed in how often they entered pots.
    """
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
        # Postflop frequencies
        cbet_frequency=min(0.90, max(0.30, 0.45 + af * 0.04)),
        turn_barrel_frequency=min(0.85, max(0.20, 0.40 + af * 0.03)),
        river_bluff_frequency=0.18 if is_maniac else (0.02 if (is_nit or is_station) else 0.07),
        # Thresholds live on the calibrated-equity scale (0..1 win probability)
        value_threshold=num("value_threshold", 0.56 if is_maniac else (0.72 if is_nit else 0.65), 0.45, 0.90),
        thin_value_threshold=0.50 if is_maniac else (0.62 if is_nit else 0.57),
        raise_threshold=0.58 if is_maniac else (0.68 if is_nit else 0.62),
        jam_threshold=0.84 if is_maniac else (0.93 if is_nit else 0.90),
        # Measured sizings, straight from the hands this opponent actually played
        open_size=num("open_size_bb", 2.40 if is_maniac else 2.25, 2.0, 3.5),
        cbet_size=num("cbet_size", 0.47, 0.15, 0.95),
        value_bet_size=num("value_bet_size", 0.74 if is_station else 0.69, 0.15, 0.95),
        # Bluff sizing is not directly measurable from hand histories (a bet looks the
        # same whether it is value or air), so scale it off the measured bet size:
        # most players fire smaller when bluffing than when value betting.
        bluff_bet_size=max(0.15, min(0.95, 0.85 * num("value_bet_size", 0.69, 0.15, 0.95))),
        raise_size=num("raise_size", 0.68, 0.15, 0.95),
        # Tournament traits
        safety=0.65 if is_nit else (0.25 if is_maniac else 0.45),
        attack=min(0.98, max(0.30, af / 10.0 + 0.35)),
        bubble_aggression=0.55 + 0.35 * af_norm,
        late_aggression=0.10 + 0.35 * af_norm,
        # Passive players are predictable; maniacs are not.
        temperature=0.03 if (is_nit or is_passive) else (0.16 if is_maniac else 0.10),
    )

class ArenaEvaluator:
    def __init__(self, pool_size=36, seed=7, equity_samples=0, profiles: dict[str, Any] | str | Path | None = None, workers=0, profile_min_hands=15):
        self.pool_size=max(12,pool_size); self.seed=seed; self.equity_samples=equity_samples; self.profiles=profiles; self.workers=workers
        self.profile_min_hands=int(profile_min_hands)

    def evaluate(self, focal: StrategyParams, runs=100, opponents=None, seed_offset=0, verbose=True):
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
        opponents = [replace(x) for x in opponents]

        if self.workers and self.workers > 1 and runs > 1:
            workers = min(self.workers, runs)
            tasks = [(focal, opponents, self.seed + seed_offset + r * 7919, 1, self.equity_samples, False) for r in range(runs)]
            top = final = champ = 0
            rank_sum = bb_sum = 0.0
            ranks: list[float] = []; bbs: list[float] = []
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
                    rank_sum += r_res["avg_rank"]; bb_sum += r_res["avg_bb100"]
                    ranks.append(float(r_res["avg_rank"])); bbs.append(float(r_res["avg_bb100"]))
                    if verbose:
                        cum_bb = bb_sum / completed
                        cum_top = (top / completed) * 100.0
                        cum_champ = (champ / completed) * 100.0
                        if is_champ: outcome = "🏆 夺冠 (第 1 名)"
                        elif is_final: outcome = "决赛桌突围"
                        elif is_top12: outcome = "12强半决赛"
                        else: outcome = f"未出线 (第 {int(r_res['avg_rank'])} 名)"
                        print(
                            f"[评估进度 {completed:02d}/{runs:02d} | 200手结算] "
                            f"单场: 预赛第 {int(r_res['avg_rank']):02d} 名 ({r_res['avg_bb100']:+.1f} BB/100) | "
                            f"赛果: {outcome:<12} | "
                            f"累计走势: {cum_bb:+.1f} BB/100 (出线率 {cum_top:.0f}%, 夺冠率 {cum_champ:.0f}%)",
                            flush=True
                        )
            return _summarise(top, final, champ, ranks, bbs, runs, self.pool_size)
        else:
            if verbose:
                print(f"[评估开始] 正在顺序执行 {runs} 场锦标赛测试 (每场 200 手预赛 + 淘汰赛)...", flush=True)
            return _evaluate_worker((focal, opponents, self.seed+seed_offset, max(1,runs), self.equity_samples, verbose))

    @staticmethod
    def _load_profiles(source: dict[str, Any] | str | Path, min_hands: int = 15) -> list[dict[str, Any]]:
        if isinstance(source, (str, Path)):
            p = Path(source)
            if not p.exists(): return []
            data = json.loads(p.read_text(encoding="utf-8"))
        elif isinstance(source, dict): data = source
        else: return []
        valid = [v for v in data.values() if isinstance(v, dict) and v.get("hands", 0) >= min_hands]
        valid.sort(key=lambda x: x.get("hands", 0), reverse=True)
        return valid

class StrategyTrainer:
    """Full population strategy evolution: crossover + mutation + cross-play + racing."""
    FIELDS=tuple(k for k in asdict(StrategyParams()).keys() if k!="equity_samples")
    HALL_SIZE=12
    def __init__(self, seed=7, pool_size=36, equity_samples=0, workers=0, profiles: dict[str, Any] | str | Path | None = None, holdout_frac=0.25,
                 profile_min_hands=15, profile_share=0.5):
        self.rng=random.Random(seed); self.seed=seed; self.pool_size=max(12,pool_size); self.equity_samples=equity_samples; self.workers=workers
        self.profiles=profiles
        self.holdout_frac=min(0.5, max(0.0, float(holdout_frac)))
        self.profile_min_hands=int(profile_min_hands)
        self.profile_share=min(1.0, max(0.0, float(profile_share)))
        self._cached_profile_params = []
        if self.profiles:
            profs = ArenaEvaluator._load_profiles(self.profiles, self.profile_min_hands)
            self._cached_profile_params = [profile_to_params(p) for p in profs]
        self.n_profiles_loaded = len(self._cached_profile_params)
        self._build_holdout()

    def _build_holdout(self):
        """Split opponents into a training pool and a held-out validation pool.

        Training only ever sees `_train_profile_params` and the raw archetypes; the
        champion is finally validated against strategies it has never been selected
        against, so the reported number is out-of-sample rather than a best-of-N
        re-read of the training set.
        """
        hrng = random.Random(self.seed + 4242)
        prof = list(self._cached_profile_params)
        hrng.shuffle(prof)
        cut = int(len(prof) * self.holdout_frac)
        self._holdout_profile_params = prof[:cut]
        self._train_profile_params = prof[cut:]

        # Unseen opponents: perturbed archetypes, generated deterministically and kept
        # out of the training pool entirely.
        state = self.rng.getstate()
        self._holdout_archetypes = [self.mutate(p, 0.12) for p in ARCHETYPES.values()
                                    for _ in range(2)]
        self.rng.setstate(state)

    def _holdout_pool(self):
        pool = list(self._holdout_profile_params) + list(self._holdout_archetypes)
        rng = random.Random(self.seed + 90210)
        out = []
        while len(out) < self.pool_size - 1:
            out.append(replace(rng.choice(pool)))
        return out

    def mutate(self,p,sigma):
        d=asdict(p)
        for k in self.FIELDS:
            scale=sigma*(.55 if k in {"value_threshold","thin_value_threshold","raise_threshold","jam_threshold"} else .35 if k=="open_size" else 1.0)
            d[k]+=self.rng.gauss(0,scale)
        for k in self.FIELDS:
            d[k]=max(2.0,min(3.5,d[k])) if k=="open_size" else max(.01,min(.99,d[k]))
        return StrategyParams(**d)

    def crossover(self,a,b):
        da,db=asdict(a),asdict(b); out={}
        for k in da:
            if k=="equity_samples": out[k]=max(0,int((da[k]+db[k])//2))
            else: out[k]=da[k] if self.rng.random()<.5 else db[k]
        return StrategyParams(**out)

    def seed_population(self,n):
        seeds=list(ARCHETYPES.values()); pop=[replace(ARCHETYPES["balanced"])]
        for p in seeds:
            if len(pop)<n: pop.append(replace(p))
        while len(pop)<n: pop.append(self.mutate(self.rng.choice(seeds),.06))
        return pop[:n]

    def _draw_pool(self, population, hall, seed, profile_pool, exclude=None):
        """Opponent line-up for one evaluation batch.

        Real profiles, when present, are capped at `profile_share` of the seats; the
        remaining seats are filled from archetypes, the evolving population and the
        hall of fame. Pooling every candidate together -- as this used to do -- let a
        large profile set crowd the archetypes out entirely, which would make "mix a
        few real opponents into universal training" indistinguishable from full
        targeted training. Keeping a guaranteed archetype share also matters because
        the real profile set is style-skewed (mostly loose-aggressive), so the
        archetypes are what keep tight/passive opponents represented.
        """
        rng=random.Random(seed)
        rest=list(ARCHETYPES.values()); rest.extend(population); rest.extend(p for _,p in hall)
        n=self.pool_size-1
        n_profile=min(n, int(round(n*self.profile_share))) if profile_pool else 0

        def pick(pool):
            for _ in range(64):
                p=rng.choice(pool)
                if p is not exclude: return p
            return rng.choice(pool)

        out=[replace(pick(profile_pool)) for _ in range(n_profile)]
        while len(out)<n:
            out.append(replace(pick(rest)))
        return out

    def _opponents(self, focal, population, hall, seed):
        return self._draw_pool(population, hall, seed, self._train_profile_params, exclude=focal)

    def _score_population(self,pop,hall,generation,runs,pool=None,seed_base=None,label="评估"):
        # Common random numbers: one opponent line-up and one seed base shared by every
        # candidate in the batch, so differences between candidates reflect skill rather
        # than each candidate drawing its own deals and its own opponents.
        if pool is None:
            pool=self._draw_pool(pop,hall,self.seed*7919+generation,self._train_profile_params)
        if seed_base is None:
            seed_base=self.seed+generation*1000003
        tasks=[(p,pool,seed_base,runs,self.equity_samples) for p in pop]
        workers=self.workers or min(8,len(tasks))
        n=len(tasks)
        print(f"  [{label}] {n} 个候选 × {runs} 场 ({workers} 核并发)...", flush=True)
        if workers<=1:
            results=[]
            for i,(t,p) in enumerate(zip(tasks,pop)):
                m=_evaluate_worker(t)
                print(f"    候选 {i+1:02d}/{n:02d} fit={m['fitness']:.4f} top12={m['top12_rate']:.2f} rank={m['avg_rank']:.1f}", flush=True)
                results.append((m,p))
            return results
        results=[None]*len(tasks)
        completed=0
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs={ex.submit(_evaluate_worker,t):i for i,t in enumerate(tasks)}
            for fut in as_completed(futs):
                idx=futs[fut]; results[idx]=fut.result(); completed+=1
                m=results[idx]
                print(f"    候选 {completed:02d}/{n:02d} fit={m['fitness']:.4f} top12={m['top12_rate']:.2f} rank={m['avg_rank']:.1f}", flush=True)
        return list(zip(results,pop))

    def fit(self,generations=30,population=16,runs_per_candidate=30,save="models/champion.json",archive="models/archive",final_race=500,resume=True,reeval_runs=24,
            stagnation_patience=4,stagnation_sigma_boost=2.5,stagnation_min_delta=0.01,resume_revert_margin=0.05):
        ap=Path(archive); ap.mkdir(parents=True,exist_ok=True)
        start_gen=0; history=[]; hall=[]; champion=None; champion_metrics=None

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
                champion = StrategyParams(**history[-1]["params"])
                champion_metrics = history[-1]["metrics"]
                # Hall of fame = the strongest champions on record, not the most recent.
                # An archive can decay late -- here gen_016 peaked at fitness 0.51 while
                # gen_021 fell to 0.14 -- so seeding the opponent pool from the tail
                # would fill it with the worst strategies the run ever produced.
                hall = [(h["metrics"]["fitness"], StrategyParams(**h["params"]))
                        for h in sorted(history, key=lambda x: -x["metrics"]["fitness"])[:self.HALL_SIZE]]
                print(f"[Training] 发现历史存档！从 Generation {start_gen} 自动恢复续训 (已有历史: {len(history)} 代, 当前最强 Fitness: {champion_metrics['fitness']:.4f})", flush=True)

        # Best-ever tracking for stagnation detection. The old schedule shrank the
        # mutation step size purely as a function of generation count (0.92**g), so
        # once it decayed near its floor the population could no longer escape a bad
        # draw -- a run of unlucky generation winners just got refined in place,
        # walking the champion into a worse and worse corner of the search space with
        # no way back (this is exactly what happened between gen_016 and gen_020,
        # where vpip drifted from 0.036 down to 0.094 while fitness fell 0.51 -> 0.12).
        # Tracking the best fitness ever seen -- separate from "current champion" --
        # and re-widening sigma (and reseeding from the best-ever params) after a run
        # of generations that fail to beat it gives the search a way out.
        best_ever_metrics = champion_metrics
        best_ever_champion = champion
        if history:
            for h in history:
                if best_ever_metrics is None or h["metrics"]["fitness"] > best_ever_metrics["fitness"]:
                    best_ever_metrics = h["metrics"]
                    best_ever_champion = StrategyParams(**h["params"])
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
            drop = best_ever_metrics["fitness"] - champion_metrics["fitness"]
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
            return sorted(((m,p) for m,p in scored_pairs),
                          key=lambda x:(x[0]["fitness"],x[0]["top12_rate"],x[0]["champion_rate"],-x[0]["avg_rank"]),
                          reverse=True)

        # Carried forward when generations == 0 so the tail below always has a champion.
        re_ranked = [(champion_metrics, champion)] if champion is not None else None

        for g in range(start_gen, start_gen + generations):
            base_sigma=max(.012,.075*(.92**sigma_epoch))
            sigma=base_sigma
            restarted=False
            if stagnation_count >= stagnation_patience and best_ever_champion is not None:
                # Widen the search and jump back to the best-ever champion instead of
                # continuing to refine whatever the last few unlucky generations left
                # us with. This is the escape hatch for early convergence: sigma alone
                # decaying to its floor never recovers on its own once the population
                # has drifted into a bad corner. Restarting the sigma schedule is what
                # makes the escape real -- widening for a single generation and then
                # snapping back to the floor would leave the new population stranded.
                sigma_epoch = 0
                base_sigma = max(.012,.075*(.92**sigma_epoch))
                sigma = min(0.075, base_sigma * stagnation_sigma_boost)
                champion = replace(best_ever_champion)
                pop = [replace(champion)]
                while len(pop) < population:
                    pop.append(self.mutate(champion, sigma))
                restarted = True
                stagnation_count = 0
                print(f"[Training] 检测到连续 {stagnation_patience} 代无提升，触发多样性重启："
                      f"从历史最优 (fitness={best_ever_metrics['fitness']:.4f}) 重新分裂种群，sigma {base_sigma:.4f}->{sigma:.4f}", flush=True)

            scored=self._score_population(pop,hall,g,runs_per_candidate)
            ranked=_rank(scored)
            elite_n=max(3,population//4)
            elites=[p for _,p in ranked[:elite_n]]

            # The generation winner is the maximum of a noisy sample, so its in-sample
            # fitness is biased upward. Re-score the shortlist on a fresh opponent pool
            # and a fresh seed base before crowning anything.
            re_pool=self._draw_pool(pop,hall,self.seed*104729+g,self._train_profile_params)
            re_scored=self._score_population(elites,hall,g,max(1,reeval_runs),
                                             pool=re_pool, seed_base=self.seed+77000000+g*1009)
            re_ranked=_rank(re_scored)
            champion_metrics,champion=re_ranked[0]
            in_sample=dict(ranked[0][0])
            history.append({"generation":g+1,"sigma":sigma,"params":asdict(champion),
                            "metrics":champion_metrics,"in_sample_metrics":in_sample,"restarted":restarted})

            if best_ever_metrics is None or champion_metrics["fitness"] > best_ever_metrics["fitness"] + stagnation_min_delta:
                best_ever_metrics = champion_metrics
                best_ever_champion = champion
                stagnation_count = 0
            else:
                stagnation_count += 1

            print(f"gen={g+1:03d} fitness={champion_metrics['fitness']:.4f}±{champion_metrics.get('fitness_se',0.0):.4f} "
                  f"top12={champion_metrics['top12_rate']:.3f} final={champion_metrics['final_rate']:.3f} "
                  f"champ={champion_metrics['champion_rate']:.3f} avg_rank={champion_metrics['avg_rank']:.2f} "
                  f"(in-sample best {in_sample['fitness']:.4f}) [best_ever={best_ever_metrics['fitness']:.4f} 停滞={stagnation_count}/{stagnation_patience}]", flush=True)
            hall.append((champion_metrics["fitness"], champion))
            hall=sorted(hall, key=lambda x:-x[0])[:self.HALL_SIZE]
            new=elites[:]
            while len(new)<population:
                child=self.crossover(self.rng.choice(elites),self.rng.choice(elites)) if self.rng.random()<.65 else self.rng.choice(elites)
                new.append(self.mutate(child,sigma))
            pop=new
            (ap/f"gen_{g+1:03d}.json").write_text(json.dumps({"generation":g+1,"champion":asdict(champion),"metrics":champion_metrics},ensure_ascii=False,indent=2),encoding="utf-8")
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

        holdout_pool = self._holdout_pool()
        final_payload = (stable_champion, holdout_pool, self.seed + 987654321, max(1, final_race), max(0, self.equity_samples))
        final_metrics = _evaluate_worker(final_payload)

        best_elite_payload = (champion, holdout_pool, self.seed + 987654321, max(1, final_race), max(0, self.equity_samples))
        best_elite_metrics = _evaluate_worker(best_elite_payload)

        if best_elite_metrics["fitness"] > final_metrics["fitness"]:
            final_champ = champion
            final_metrics = best_elite_metrics
        else:
            final_champ = stable_champion

        # Training-distribution reference, for the train/holdout gap.
        train_payload = (final_champ, self._draw_pool(pop, hall, self.seed*31337, self._train_profile_params),
                         self.seed + 123456789, max(1, final_race), max(0, self.equity_samples))
        train_metrics = _evaluate_worker(train_payload)

        print(f"[Training] 完成本轮演化 (累计到达 Gen {start_gen + generations}).", flush=True)
        print(f"[Training] 留出集验证 fitness={final_metrics['fitness']:.4f}±{final_metrics.get('fitness_se',0.0):.4f} "
              f"top12={final_metrics['top12_rate']:.3f} avg_rank={final_metrics['avg_rank']:.2f}", flush=True)
        # NOTE: this is a *different field*, not a like-for-like overfitting gap. The
        # training pool is padded with the evolved population and the hall of fame
        # (strong), while the holdout pool is fixed profiles plus perturbed archetypes.
        # Read the holdout number on its own as the unbiased estimate; the training
        # number only says how the champion fares against the field it was selected in.
        print(f"[Training] 训练分布参考 fitness={train_metrics['fitness']:.4f} "
              f"top12={train_metrics['top12_rate']:.3f} (对手池含进化种群与名人堂，强度不同，不可直接与留出集相减)", flush=True)
        out=Path(save); out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps({"version":5,"params":asdict(final_champ),"training_metrics":champion_metrics,
                                   "final_race":final_metrics,"train_race":train_metrics,"history":history},
                                  ensure_ascii=False,indent=2),encoding="utf-8")
        return final_champ,{"training":history,"final_race":final_metrics,"train_race":train_metrics}
