from __future__ import annotations
import time, copy, json, os
from pathlib import Path
from typing import Any
from .protocol import AgentPokerClient, APIError, Config
from .strategy import StrategyAgent
from .collector import JSONLCollector
from .profiler import OpponentProfiler

class LiveRunner:
    def __init__(
        self,
        client: AgentPokerClient,
        strategy: StrategyAgent,
        competition_id: str | None = None,
        collector: JSONLCollector | None = None,
        idle_seconds: int = 30,
        queued_seconds: int = 5,
        seated_seconds: int = 2,
        round_hands: int = 20,
        cycle_hands: int = 200,
        auto_profile: bool = True,
        profiles_path: str = "models/opponent_profiles.json",
    ):
        self.client = client
        self.strategy = strategy
        self.cid = competition_id or client.cfg.competition_id
        self.table_id = None
        self.collector = collector
        self.idle = idle_seconds
        self.queued = queued_seconds
        self.seated = seated_seconds
        self.stop_requested = False

        # Round & Cycle tournament tracker
        self.round_hands = max(1, int(round_hands))
        self.cycle_hands = max(self.round_hands, int(cycle_hands))
        self.auto_profile = auto_profile
        self.profiles_path = profiles_path
        self.profiler = OpponentProfiler()

        self.total_hands_played = 0
        self.current_round = 1
        self.current_cycle = 1
        self.round_net_bb = 0.0
        self.cycle_net_bb = 0.0

        self.prev_hand_id: str | None = None
        self.hand_start_stack: int | None = None
        self.last_completed_hand_obj: dict[str, Any] | None = None

        if not self.cid:
            raise ValueError('AGENTPOKER_COMPETITION_ID is required for live mode')

    def run(self, max_steps: int | None = None, max_hands: int | None = None):
        if not self.client.cfg.key:
            raise ValueError('AGENTPOKER_KEY is required')
        steps = 0
        obs = None
        print(f"[Live] Starting Agent loop for competition: {self.cid}")
        print(f"[Live] In-Place Round Controller activated: {self.round_hands} hands/round, {self.cycle_hands} hands/cycle")
        try:
            while True:
                if max_steps and steps >= max_steps:
                    return
                if max_hands and self.total_hands_played >= max_hands:
                    print(f"\n[Live] Reached target max_hands ({max_hands}). Safely stopping...")
                    if obs:
                        self._leave(obs)
                    return

                steps += 1
                if obs is None:
                    self._join_until_ready()
                    obs = self._observe_competition()

                self._record(obs)
                self._track_hand_progress(obs)

                if obs.get('table'):
                    self.table_id = obs['table']['id']
                elif obs.get('status') != 'seated':
                    self.table_id = None

                if self.stop_requested:
                    self._leave(obs)
                    return

                status = obs.get('status')
                cstatus = obs.get('competitionStatus')

                if status == 'idle':
                    if cstatus in ('ended', 'cancelled'):
                        print(f"[Live] Competition {cstatus}. Final bankroll: {obs.get('bankroll')}")
                        return
                    time.sleep(self.idle)
                    obs = None
                    continue

                if status == 'queued':
                    self.table_id = None
                    time.sleep(self.queued)
                    obs = self._observe_competition()
                    continue

                if status == 'seated' and obs.get('actionRequest') is None:
                    time.sleep(self.seated)
                    obs = self._observe_current()
                    continue

                if obs.get('actionRequest') is not None:
                    body = self._make_action_body(obs)
                    dec = body.get('decision', {})
                    amt_str = f" amount={dec.get('amount')}" if 'amount' in dec else ""
                    print(f"[Live] Hand #{self.total_hands_played + 1} | Action -> {dec.get('type')}{amt_str}")
                    obs = self._action_with_retry(body, obs)
                    continue

                obs = self._observe_current()
        except KeyboardInterrupt:
            print("\n[Live] User interrupt received. Executing Leave Play...")
            if obs:
                self._leave(obs)
            elif self.table_id:
                try:
                    self.client.leave({'tableId': self.table_id})
                except Exception:
                    pass
            elif self.cid:
                try:
                    self.client.leave({'competitionId': self.cid})
                except Exception:
                    pass
            print("[Live] Safely left competition. Stopped.")

    def _track_hand_progress(self, obs: dict[str, Any]) -> None:
        table = obs.get("table")
        if not table:
            return
        hand = table.get("hand") or {}
        hid = hand.get("id")
        if not hid:
            return

        hero_id = obs.get("agentId")
        players = table.get("players") or []
        hero_p = next((p for p in players if p.get("agentId") == hero_id), None)
        curr_stack = hero_p.get("stack") if hero_p else None
        bb_size = float(table.get("bigBlind") or 200.0)

        # Initial hand tracking
        if self.prev_hand_id is None:
            self.prev_hand_id = hid
            self.hand_start_stack = curr_stack
            self.last_completed_hand_obj = hand
            return

        # Detect new hand transition
        if hid != self.prev_hand_id:
            self.total_hands_played += 1

            # Ingest previous completed hand into profiler
            if self.last_completed_hand_obj:
                try:
                    self.profiler.ingest_hand({"table": table, "hand": self.last_completed_hand_obj})
                except Exception:
                    pass

            # Calculate chip delta
            net_change = None
            if self.last_completed_hand_obj:
                prev_players = self.last_completed_hand_obj.get("players") or []
                prev_hero = next((p for p in prev_players if p.get("agentId") == hero_id), None)
                if prev_hero and "netChange" in prev_hero and prev_hero["netChange"] is not None:
                    net_change = float(prev_hero["netChange"])

            if net_change is None:
                if curr_stack is not None and self.hand_start_stack is not None:
                    net_change = float(curr_stack - self.hand_start_stack)
                else:
                    net_change = 0.0

            delta_bb = net_change / bb_size
            self.round_net_bb += delta_bb
            self.cycle_net_bb += delta_bb

            # Check for round completion
            hands_in_round = self.total_hands_played % self.round_hands
            if hands_in_round == 0:
                self._on_round_complete(bb_size)

            # Check for cycle completion
            hands_in_cycle = self.total_hands_played % self.cycle_hands
            if hands_in_cycle == 0:
                self._on_cycle_complete()

            # Advance tracking pointers
            self.prev_hand_id = hid
            self.hand_start_stack = curr_stack
            self.last_completed_hand_obj = hand
        else:
            # Same hand, refresh snapshot
            self.last_completed_hand_obj = hand

    def _on_round_complete(self, bb_size: float) -> None:
        round_bb100 = (self.round_net_bb / max(1, self.round_hands)) * 100.0
        hands_in_cycle = self.total_hands_played % self.cycle_hands
        if hands_in_cycle == 0:
            hands_in_cycle = self.cycle_hands
        cycle_bb100 = (self.cycle_net_bb / max(1, hands_in_cycle)) * 100.0

        stage = "探索建仓期 (R1~R3)" if self.current_round <= 3 else ("积分保线期 (R4~R8)" if self.current_round <= 8 else "气泡冲线期 (R9~R10)")
        status_str = "🟢 稳居保线区" if cycle_bb100 >= 20.0 else "🔴 濒死冲线区"

        print("\n" + "=" * 68)
        print(f" 🏆 【第 {self.current_round} 轮预选赛结算】 (周期手牌: {hands_in_cycle}/{self.cycle_hands} 手 | 累计总局: {self.total_hands_played} 手)")
        print(f" • 比赛阶段: {stage} | 状态评估: {status_str}")
        print(f" • 本轮盈亏: {self.round_net_bb:+.1f} BB ({round_bb100:+.1f} BB/100)")
        print(f" • 赛季累计: {self.cycle_net_bb:+.1f} BB ({cycle_bb100:+.1f} BB/100) vs 晋级黄金线 (+20.0 BB/100)")

        if self.auto_profile:
            self._update_and_reload_profiles()

        print("=" * 68 + "\n", flush=True)

        self.round_net_bb = 0.0
        self.current_round = (self.current_round % 10) + 1

    def _on_cycle_complete(self) -> None:
        cycle_bb100 = (self.cycle_net_bb / max(1, self.cycle_hands)) * 100.0
        qualified = cycle_bb100 >= 20.0
        qual_str = "🎉 成功锁定 TOP 12 晋级资格！" if qualified else "⚠️ 遗憾未达出线基准线 (+20.0 BB/100)"

        print("\n" + "#" * 68)
        print(f" 🌟 【第 {self.current_cycle} 届虚拟锦标赛 200 手全赛季大结账】")
        print(f" • 赛季总战绩: {self.cycle_net_bb:+.1f} BB ({cycle_bb100:+.1f} BB/100)")
        print(f" • 晋级推演: {qual_str}")
        print(f" • 下一届虚拟锦标赛 (Cycle {self.current_cycle + 1}) 原地平滑开启...")
        print("#" * 68 + "\n", flush=True)

        self.current_cycle += 1
        self.cycle_net_bb = 0.0
        self.current_round = 1

    def _update_and_reload_profiles(self) -> None:
        try:
            new_profiles = self.profiler.build_profiles(prior_weight=8.0, min_hands=2, filter_afk=False)
            if new_profiles:
                p_path = Path(self.profiles_path)
                existing = {}
                if p_path.exists():
                    try:
                        existing = json.loads(p_path.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                existing.update(new_profiles)
                p_path.parent.mkdir(parents=True, exist_ok=True)
                p_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

                loaded = self.strategy.load_opponent_profiles(existing)
                print(f" • [画像热更] 已实时沉淀并更新 {len(new_profiles)} 位同桌对手画像 (总画像库: {loaded})")
        except Exception as e:
            print(f" • [画像热更] 提示: 增量更新画像跳过 ({e})")

    def _join_until_ready(self):
        while True:
            try:
                r = self.client.join(self.cid)
            except APIError as e:
                if e.code == 'registration_required':
                    raise
                if e.code == 'competition_not_active':
                    self.cid = self._rediscover()
                    continue
                if e.code == 'insufficient_bankroll':
                    raise
                raise
            if r.get('status') in ('queued', 'seated'):
                return
            time.sleep(self.idle)

    def _rediscover(self):
        data = self.client.discover('active')
        cs = data.get('competitions') or []
        if not cs:
            raise RuntimeError('no active competitions')
        if self.cid and any(c.get('id') == self.cid for c in cs):
            return self.cid
        return cs[0]['id']

    def _observe_competition(self):
        try:
            return self.client.observe(self.cid)
        except APIError as e:
            if e.code == 'stale_table':
                return self.client.observe(self.cid)
            if e.code == 'participation_not_found':
                self._join_until_ready()
                return self.client.observe(self.cid)
            raise

    def _observe_current(self):
        if not self.table_id:
            return self._observe_competition()
        try:
            return self.client.observe(self.cid, self.table_id)
        except APIError as e:
            if e.code == 'stale_table':
                self.table_id = None
                return self.client.observe(self.cid)
            raise

    def _make_action_body(self, obs: dict[str, Any]) -> dict[str, Any]:
        # Construct & inject virtual tournament context
        hands_in_cycle = self.total_hands_played % self.cycle_hands
        rem = max(0, self.cycle_hands - hands_in_cycle)
        cycle_bb100 = (self.cycle_net_bb / max(1, hands_in_cycle)) * 100.0 if hands_in_cycle > 0 else 0.0

        if cycle_bb100 >= 50.0:
            sim_rank = 3
        elif cycle_bb100 >= 25.0:
            sim_rank = 8
        elif cycle_bb100 >= 15.0:
            sim_rank = 12
        elif cycle_bb100 >= 0.0:
            sim_rank = 16
        else:
            sim_rank = 21

        obs["tournamentContext"] = {
            "rank": sim_rank,
            "bb100": cycle_bb100,
            "rank12_bb100": 20.0,
            "rank13_bb100": 15.0,
            "hands_remaining": rem,
            "round_no": self.current_round,
            "cycle_no": self.current_cycle,
        }

        req = copy.deepcopy(obs['actionRequest'])
        decision = self.strategy.choose(obs)
        allowed = req.get('allowedActions') or []
        legal = {a['type']: a for a in allowed}
        if decision.get('type') not in legal:
            raise RuntimeError('strategy emitted action not in allowedActions')
        if decision['type'] in ('bet', 'raise'):
            spec = legal[decision['type']]
            lo = int(spec['minAmount'])
            hi = int(spec['maxAmount'])
            amt = int(decision.get('amount', 0))
            if not (lo <= amt <= hi) or amt <= 0:
                raise RuntimeError('strategy emitted invalid amount')
        elif 'amount' in decision:
            decision.pop('amount', None)
        return {
            'competitionId': obs['competitionId'],
            'tableId': obs['table']['id'],
            'actionRequestId': req['id'],
            'decision': decision,
        }

    def _action_with_retry(self, body, original_obs):
        frozen = json.loads(json.dumps(body, ensure_ascii=False))
        while True:
            try:
                return self.client.action(frozen)
            except APIError as e:
                if e.code in ('temporarily_unavailable',):
                    time.sleep(e.retry_after or 1)
                    continue
                if e.code in ('stale_action_request', 'idempotency_conflict'):
                    return self._observe_current()
                if e.code == 'stale_table':
                    self.table_id = None
                    return self.client.observe(self.cid)
                if e.code == 'invalid_decision':
                    fresh = self._observe_current()
                    return self.client.action(self._make_action_body(fresh))
                if e.code == 'authentication_required':
                    raise
                raise

    def _leave(self, obs):
        body = {'tableId': obs['table']['id']} if obs.get('table') else {'competitionId': self.cid}
        while True:
            try:
                r = self.client.leave(body)
                if r.get('status') == 'accepted':
                    return
            except APIError as e:
                if e.code == 'stale_table' and 'tableId' in body:
                    body = {'competitionId': self.cid}
                    continue
                if e.code == 'temporarily_unavailable':
                    time.sleep(e.retry_after or 1)
                    continue
                raise

    def _record(self, obs):
        if self.collector:
            self.collector.write({'kind': 'observation', 'data': obs})
