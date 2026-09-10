from __future__ import annotations
from dataclasses import asdict, replace
from pathlib import Path
import json, random
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

def _evaluate_worker(payload):
    focal, opponents, seed, runs, equity_samples = payload[:5]
    verbose = payload[5] if len(payload) > 5 else False
    agents=[SimAgent("focal", StrategyAgent(replace(focal, equity_samples=equity_samples), seed=seed, name="focal"))]
    for i,p in enumerate(opponents):
        agents.append(SimAgent(f"opp{i}", StrategyAgent(replace(p, equity_samples=equity_samples), seed=seed+31*i+17, name=f"opp{i}")))
    top=final=champ=0; rank_sum=bb_sum=0.0
    for run in range(runs):
        s=seed+run*7919
        seeded=[]
        for j,a in enumerate(agents):
            seeded.append(SimAgent(a.agent_id, StrategyAgent(a.strategy.params, seed=s+1000*j, name=a.agent_id)))
        sim=LeagueSimulator(seeded, seed=s)
        result=sim.run_event()
        standings=result["preliminary"]
        me=next(x for x in standings if x.agent_id=="focal")
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

    top_rate, final_rate, champ_rate=top/runs, final/runs, champ/runs
    avg_rank, avg_bb=rank_sum/runs, bb_sum/runs
    fit=.58*top_rate+.22*final_rate+.15*champ_rate+.05*(1.0-min(avg_rank-1, len(agents)-1)/(len(agents)-1))
    return {"top12_rate":top_rate,"final_rate":final_rate,"champion_rate":champ_rate,"avg_rank":avg_rank,"avg_bb100":avg_bb,"fitness":fit}

def profile_to_params(p: dict[str, Any]) -> StrategyParams:
    """Map a real player profile's empirical statistics into a StrategyParams agent."""
    vpip = max(0.08, min(0.85, float(p.get("vpip", 0.25))))
    pfr = max(0.03, min(0.70, float(p.get("pfr", p.get("raise", 0.16)))))
    af = float(p.get("af", 2.0))
    is_nit = bool(p.get("is_nit", False))
    is_maniac = bool(p.get("is_maniac", False))
    is_station = bool(p.get("is_station", False))

    return StrategyParams(
        vpip=vpip,
        open_frequency=min(0.95, max(0.35, pfr * 1.3)),
        threebet_frequency=min(0.30, max(0.03, pfr * 0.45)),
        steal_frequency=min(0.95, max(0.30, pfr * 1.5)),
        cbet_frequency=min(0.90, max(0.30, 0.45 + af * 0.04)),
        turn_barrel_frequency=min(0.85, max(0.20, 0.40 + af * 0.03)),
        river_bluff_frequency=0.18 if is_maniac else (0.02 if (is_nit or is_station) else 0.07),
        value_threshold=0.55 if is_maniac else (0.72 if is_nit else 0.65),
        open_size=2.40 if is_maniac else 2.25,
        attack=min(0.98, max(0.30, af / 10.0 + 0.35)),
        safety=0.65 if is_nit else (0.25 if is_maniac else 0.45),
    )

class ArenaEvaluator:
    def __init__(self, pool_size=36, seed=7, equity_samples=0, profiles: dict[str, Any] | str | Path | None = None, workers=0):
        self.pool_size=max(12,pool_size); self.seed=seed; self.equity_samples=equity_samples; self.profiles=profiles; self.workers=workers

    def evaluate(self, focal: StrategyParams, runs=100, opponents=None, seed_offset=0, verbose=True):
        if opponents is None:
            if self.profiles:
                profs = self._load_profiles(self.profiles)
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
            top_rate, final_rate, champ_rate = top / runs, final / runs, champ / runs
            avg_rank, avg_bb = rank_sum / runs, bb_sum / runs
            fit = .58 * top_rate + .22 * final_rate + .15 * champ_rate + .05 * (1.0 - min(avg_rank - 1, self.pool_size - 1) / (self.pool_size - 1))
            return {"top12_rate": top_rate, "final_rate": final_rate, "champion_rate": champ_rate, "avg_rank": avg_rank, "avg_bb100": avg_bb, "fitness": fit}
        else:
            if verbose:
                print(f"[评估开始] 正在顺序执行 {runs} 场锦标赛测试 (每场 200 手预赛 + 淘汰赛)...", flush=True)
            return _evaluate_worker((focal, opponents, self.seed+seed_offset, max(1,runs), self.equity_samples, verbose))

    @staticmethod
    def _load_profiles(source: dict[str, Any] | str | Path) -> list[dict[str, Any]]:
        if isinstance(source, (str, Path)):
            p = Path(source)
            if not p.exists(): return []
            data = json.loads(p.read_text(encoding="utf-8"))
        elif isinstance(source, dict): data = source
        else: return []
        valid = [v for v in data.values() if isinstance(v, dict) and v.get("hands", 0) >= 15]
        valid.sort(key=lambda x: x.get("hands", 0), reverse=True)
        return valid

class StrategyTrainer:
    """Full population strategy evolution: crossover + mutation + cross-play + racing."""
    FIELDS=tuple(k for k in asdict(StrategyParams()).keys() if k!="equity_samples")
    def __init__(self, seed=7, pool_size=36, equity_samples=0, workers=0, profiles: dict[str, Any] | str | Path | None = None):
        self.rng=random.Random(seed); self.seed=seed; self.pool_size=max(12,pool_size); self.equity_samples=equity_samples; self.workers=workers
        self.profiles=profiles
        self._cached_profile_params = []
        if self.profiles:
            profs = ArenaEvaluator._load_profiles(self.profiles)
            self._cached_profile_params = [profile_to_params(p) for p in profs]

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

    def _opponents(self, focal, population, hall, seed):
        candidates=[]
        if self._cached_profile_params:
            candidates.extend(self._cached_profile_params)
        candidates.extend(ARCHETYPES.values()); candidates.extend(population); candidates.extend(hall)
        out=[]
        self.rng.seed(seed)
        while len(out)<self.pool_size-1:
            p=self.rng.choice(candidates)
            if p is focal: continue
            out.append(replace(p))
        self.rng.seed(self.seed + seed)
        return out

    def _score_population(self,pop,hall,generation,runs):
        tasks=[]
        for i,p in enumerate(pop):
            opp=self._opponents(p,pop,hall,generation*100000+i)
            tasks.append((p,opp,self.seed+generation*1000003+i*1009,runs,self.equity_samples))
        workers=self.workers or min(8,len(tasks))
        if workers<=1:
            return [(_evaluate_worker(t),p) for t,p in zip(tasks,pop)]
        results=[None]*len(tasks)
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs={ex.submit(_evaluate_worker,t):i for i,t in enumerate(tasks)}
            for fut in as_completed(futs): results[futs[fut]]=fut.result()
        return list(zip(results,pop))

    def fit(self,generations=30,population=16,runs_per_candidate=30,save="models/champion.json",archive="models/archive",final_race=500,resume=True):
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
                        hall.append(StrategyParams(**d["champion"]))
                except Exception:
                    pass
            if history:
                start_gen = history[-1]["generation"]
                champion = StrategyParams(**history[-1]["params"])
                champion_metrics = history[-1]["metrics"]
                hall = hall[-12:]
                print(f"[Training] 发现历史存档！从 Generation {start_gen} 自动恢复续训 (已有历史: {len(history)} 代, 当前最强 Fitness: {champion_metrics['fitness']:.4f})", flush=True)

        if champion is not None:
            pop = [replace(champion)]
            while len(pop) < population:
                pop.append(self.mutate(champion, max(.02, .075 * (.92 ** start_gen))))
        else:
            pop = self.seed_population(population)

        for g in range(start_gen, start_gen + generations):
            sigma=max(.012,.075*(.92**g))
            scored=self._score_population(pop,hall,g,runs_per_candidate)
            ranked=sorted(((m,p) for m,p in scored),key=lambda x:(x[0]["fitness"],x[0]["top12_rate"],x[0]["champion_rate"],-x[0]["avg_rank"]),reverse=True)
            champion_metrics,champion=ranked[0]
            history.append({"generation":g+1,"sigma":sigma,"params":asdict(champion),"metrics":champion_metrics})
            print(f"gen={g+1:03d} fitness={champion_metrics['fitness']:.4f} top12={champion_metrics['top12_rate']:.3f} final={champion_metrics['final_rate']:.3f} champ={champion_metrics['champion_rate']:.3f} avg_rank={champion_metrics['avg_rank']:.2f}", flush=True)
            hall.append(champion); hall=hall[-12:]
            elite_n=max(3,population//4); elites=[p for _,p in ranked[:elite_n]]
            new=elites[:]
            while len(new)<population:
                child=self.crossover(self.rng.choice(elites),self.rng.choice(elites)) if self.rng.random()<.65 else self.rng.choice(elites)
                new.append(self.mutate(child,sigma))
            pop=new
            (ap/f"gen_{g+1:03d}.json").write_text(json.dumps({"generation":g+1,"champion":asdict(champion),"metrics":champion_metrics},ensure_ascii=False,indent=2),encoding="utf-8")

        # Elite Parameter Smoothing for maximum stability against variance
        elite_candidates = [p for _, p in ranked[:max(3, population // 4)]]
        avg_dict = {}
        for k in self.FIELDS:
            vals = [getattr(p, k) for p in elite_candidates]
            avg_dict[k] = sum(vals) / len(vals)
        stable_champion = StrategyParams(**avg_dict)

        final_payload = (stable_champion, self._opponents(stable_champion, pop, hall, 999999), self.seed + 987654321, max(1, final_race), max(0, self.equity_samples))
        final_metrics = _evaluate_worker(final_payload)
        final_champ = stable_champion if final_metrics["fitness"] >= 0.70 or final_metrics["fitness"] >= champion_metrics["fitness"] * 0.90 else champion

        print(f"[Training] 完成本轮演化 (累计到达 Gen {start_gen + generations}). 独立验证指标: {final_metrics}", flush=True)
        out=Path(save); out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps({"version":4,"params":asdict(final_champ),"training_metrics":champion_metrics,"final_race":final_metrics,"history":history},ensure_ascii=False,indent=2),encoding="utf-8")
        return final_champ,{"training":history,"final_race":final_metrics}
