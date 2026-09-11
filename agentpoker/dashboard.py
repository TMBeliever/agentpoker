from __future__ import annotations
import os, sys, json, time, signal, subprocess, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent

class ProcessManager:
    def __init__(self):
        self.train_proc: subprocess.Popen | None = None
        self.live_proc: subprocess.Popen | None = None
        self.train_start_time: float | None = None
        self.live_start_time: float | None = None
        self.live_strategy: str | None = None
        self.logs_dir = ROOT_DIR / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.train_log_file = self.logs_dir / "training.log"
        self.live_log_file = self.logs_dir / "live.log"

    def is_training(self) -> bool:
        if self.train_proc is not None:
            if self.train_proc.poll() is None:
                return True
            self.train_proc = None
        # Check system processes
        return self._find_proc("agentpoker.cli train") is not None

    def is_live(self) -> bool:
        if self.live_proc is not None:
            if self.live_proc.poll() is None:
                return True
            self.live_proc = None
        return self._find_proc("agentpoker.cli live") is not None

    def _find_proc(self, pattern: str) -> int | None:
        try:
            out = subprocess.check_output(["ps", "-ef"], text=True)
            for line in out.splitlines():
                if pattern in line and "grep" not in line and "dashboard" not in line:
                    parts = line.split()
                    if len(parts) > 1:
                        return int(parts[1])
        except Exception:
            pass
        return None

    def start_training(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.is_training():
            return {"status": "error", "message": "训练已在运行中，请勿重复启动"}
        
        generations = str(params.get("generations", 10))
        population = str(params.get("population", 8))
        runs = str(params.get("runs", 40))
        agents = str(params.get("agents", 36))
        workers = str(params.get("workers", 2))
        base_model = params.get("base_model") or "models/champion_optimized.json"
        archive = params.get("archive") or "models/archive_v2"
        save_path = params.get("save") or "models/champion_v2.json"
        mix_profiles = bool(params.get("mix_profiles", True))

        cmd = [
            sys.executable, "-m", "agentpoker.cli", "train",
            "--generations", generations,
            "--population", population,
            "--runs", runs,
            "--agents", agents,
            "--workers", workers,
            "--save", save_path,
            "--archive", archive,
            "--base-model", base_model,
            "--no-resume"
        ]
        if mix_profiles:
            cmd.extend(["--mix-profiles", "--profile-min-hands", "100", "--profile-share", "0.5"])

        f_log = open(self.train_log_file, "a", encoding="utf-8")
        f_log.write(f"\n=== [Dashboard] 训练启动于 {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        f_log.write(f"命令: {' '.join(cmd)}\n\n")
        f_log.flush()

        self.train_proc = subprocess.Popen(
            cmd, cwd=str(ROOT_DIR), stdout=f_log, stderr=subprocess.STDOUT, text=True, preexec_fn=os.setsid
        )
        self.train_start_time = time.time()
        return {"status": "success", "message": f"训练已成功启动 (PID: {self.train_proc.pid})"}

    def stop_training(self) -> dict[str, Any]:
        stopped = False
        if self.train_proc and self.train_proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.train_proc.pid), signal.SIGTERM)
                stopped = True
            except Exception:
                pass
            self.train_proc = None

        pid = self._find_proc("agentpoker.cli train")
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                stopped = True
            except Exception:
                pass

        return {"status": "success", "message": "训练已终止" if stopped else "没有运行中的训练"}

    def start_live(self, strategy: str = "models/champion_optimized.json") -> dict[str, Any]:
        if self.is_live():
            return {"status": "error", "message": "比赛已在进行中"}
        
        cmd = [sys.executable, "-m", "agentpoker.cli", "live", "--strategy", strategy]
        f_log = open(self.live_log_file, "a", encoding="utf-8")
        f_log.write(f"\n=== [Dashboard] 比赛对战启动于 {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        f_log.write(f"使用策略: {strategy}\n\n")
        f_log.flush()

        self.live_proc = subprocess.Popen(
            cmd, cwd=str(ROOT_DIR), stdout=f_log, stderr=subprocess.STDOUT, text=True, preexec_fn=os.setsid
        )
        self.live_start_time = time.time()
        self.live_strategy = strategy
        return {"status": "success", "message": f"比赛已成功启动 (PID: {self.live_proc.pid})"}

    def stop_live(self) -> dict[str, Any]:
        stopped = False
        if self.live_proc and self.live_proc.poll() is None:
            try:
                # Send SIGINT so live runner exits cleanly with self._leave()
                os.killpg(os.getpgid(self.live_proc.pid), signal.SIGINT)
                stopped = True
            except Exception:
                pass
            self.live_proc = None

        pid = self._find_proc("agentpoker.cli live")
        if pid:
            try:
                os.kill(pid, signal.SIGINT)
                stopped = True
            except Exception:
                pass

        return {"status": "success", "message": "已安全发送离桌指令并停止比赛" if stopped else "当前没有运行中的比赛"}

    def switch_table(self) -> dict[str, Any]:
        flag = ROOT_DIR / "data" / ".switch_table_flag"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(str(time.time()), encoding="utf-8")
        return {"status": "success", "message": "已发送换桌指令！将在本手结束后安全离桌并重新排队进新桌"}

    def get_logs(self, which: str = "train", max_lines: int = 120) -> str:
        fpath = self.train_log_file if which == "train" else self.live_log_file
        if not fpath.exists():
            return "暂无日志输出。"
        try:
            lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
            return "\n".join(lines[-max_lines:])
        except Exception as e:
            return f"读取日志出错: {e}"

pm = ProcessManager()

def get_archive_data() -> list[dict[str, Any]]:
    # Find active archive
    candidates = ["models/archive_v2", "models/archive_targeted", "models/archive_optimized", "models/archive_universal"]
    archive_dir = None
    for c in candidates:
        p = ROOT_DIR / c
        if p.exists() and list(p.glob("gen_*.json")):
            archive_dir = p
            break
    if not archive_dir:
        return []

    results = []
    for gf in sorted(archive_dir.glob("gen_*.json")):
        try:
            d = json.loads(gf.read_text(encoding="utf-8"))
            gen_no = d.get("generation")
            m = d.get("metrics") or d.get("training_metrics") or {}
            p = d.get("champion") or d.get("params") or {}
            results.append({
                "generation": gen_no,
                "fitness": round(float(m.get("fitness", 0)), 4),
                "top12_rate": round(float(m.get("top12_rate", 0)) * 100, 1),
                "champion_rate": round(float(m.get("champion_rate", 0)) * 100, 1),
                "avg_bb100": round(float(m.get("avg_bb100", 0)), 1),
                "params": {
                    "vpip": round(float(p.get("vpip", 0)), 3),
                    "cbet_frequency": round(float(p.get("cbet_frequency", 0)), 3),
                    "flop_value_threshold": round(float(p.get("flop_value_threshold", 0.58)), 3),
                    "turn_value_threshold": round(float(p.get("turn_value_threshold", 0.65)), 3),
                    "river_value_threshold": round(float(p.get("river_value_threshold", 0.74)), 3),
                    "dry_board_bet_size": round(float(p.get("dry_board_bet_size", 0.33)), 3),
                    "wet_board_bet_size": round(float(p.get("wet_board_bet_size", 0.75)), 3),
                }
            })
        except Exception:
            pass
    return sorted(results, key=lambda x: x["generation"])

def get_models_list() -> list[str]:
    out = []
    models_dir = ROOT_DIR / "models"
    if models_dir.exists():
        for p in sorted(models_dir.glob("*.json")):
            if "profile" not in p.name:
                out.append(f"models/{p.name}")
    return out or ["models/champion_optimized.json"]

def get_recent_hands(limit: int = 30) -> list[dict[str, Any]]:
    hands_file = ROOT_DIR / "data" / "processed" / "hands.jsonl"
    if not hands_file.exists():
        # Fallback to replay export if raw exists
        raw_events = ROOT_DIR / "data" / "raw" / "events.jsonl"
        if raw_events.exists():
            try:
                from agentpoker.collector import ReplayBuilder
                ReplayBuilder(raw_events).export(str(hands_file))
            except Exception:
                return []
        else:
            return []

    lines = []
    try:
        with open(hands_file, "r", encoding="utf-8", errors="ignore") as f:
            for l in f:
                if l.strip():
                    lines.append(l)
    except Exception:
        return []

    recent = lines[-limit:]
    recent.reverse()
    results = []
    for line in recent:
        try:
            h = json.loads(line)
            table_id = h.get("tableId", "Unknown")
            completed_at = h.get("completedAt", "")
            pot = h.get("pot", 0)
            board = h.get("communityCards", [])
            players = h.get("players", [])
            hero = next((p for p in players if p.get("agentId") and ("hero" in p.get("name", "").lower() or p.get("netChange") is not None)), None)
            
            results.append({
                "id": h.get("id"),
                "tableId": table_id[:8],
                "time": completed_at[11:19] if len(completed_at) >= 19 else completed_at,
                "pot": pot,
                "board": board,
                "players_count": len(players),
                "players": [{
                    "name": p.get("name", p.get("agentId", "P")[:6]),
                    "seat": p.get("seatIndex", 0),
                    "stack": p.get("startingStack", 0),
                    "cards": p.get("holeCards", []),
                    "net": p.get("netChange", 0)
                } for p in players],
                "hero_net": hero.get("netChange", 0) if hero else 0,
                "actions_count": len(h.get("actions", []))
            })
        except Exception:
            pass
    return results

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AgentPoker 2.0 全能可视化控制台</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body { background-color: #0b0f19; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .card-dark { background: #131b2e; border: 1px solid #1e293b; }
    .poker-card {
      display: inline-flex; align-items: center; justify-content: center;
      width: 32px; height: 44px; border-radius: 4px; font-weight: bold; font-size: 14px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.5); margin-right: 4px; background: white;
    }
    .suit-red { color: #dc2626; }
    .suit-black { color: #1e293b; }
  </style>
</head>
<body class="text-slate-200">
  <!-- Top Navbar -->
  <header class="bg-slate-900 border-b border-slate-800 px-6 py-4 flex flex-wrap items-center justify-between shadow-lg">
    <div class="flex items-center space-x-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500 to-red-600 flex items-center justify-center text-xl shadow-md">
        🃏
      </div>
      <div>
        <h1 class="text-xl font-bold text-white tracking-wide flex items-center gap-2">
          AgentPoker <span class="text-xs font-semibold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">2.0 PRO</span>
        </h1>
        <p class="text-xs text-slate-400">德州扑克自适应博弈训练引擎 & 实战云控中心</p>
      </div>
    </div>
    <!-- Quick Status Bar -->
    <div class="flex items-center space-x-4 mt-2 sm:mt-0">
      <div id="trainBadge" class="flex items-center space-x-2 px-3 py-1.5 rounded-full text-xs font-medium bg-slate-800 border border-slate-700 text-slate-400">
        <span class="w-2 h-2 rounded-full bg-slate-500"></span>
        <span>训练: 待命</span>
      </div>
      <div id="liveBadge" class="flex items-center space-x-2 px-3 py-1.5 rounded-full text-xs font-medium bg-slate-800 border border-slate-700 text-slate-400">
        <span class="w-2 h-2 rounded-full bg-slate-500"></span>
        <span>比赛: 未连接</span>
      </div>
      <button onclick="switchTable()" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-600/80 hover:bg-amber-600 text-white flex items-center gap-1.5 transition">
        <i class="fa-solid fa-arrows-rotate"></i> 换桌
      </button>
    </div>
  </header>

  <!-- Main Container -->
  <main class="max-w-7xl mx-auto px-4 py-6">
    <!-- Navigation Tabs -->
    <div class="flex border-b border-slate-800 mb-6 space-x-6 text-sm font-medium">
      <button onclick="switchTab("tabTrain")" id="tabBtnTrain" class="pb-3 border-b-2 border-emerald-500 text-emerald-400 flex items-center gap-2">
        <i class="fa-solid fa-dumbbell"></i> 演化训练控制
      </button>
      <button onclick="switchTab("tabLive")" id="tabBtnLive" class="pb-3 border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center gap-2">
        <i class="fa-solid fa-trophy"></i> 在线赛事实战
      </button>
      <button onclick="switchTab("tabHands")" id="tabBtnHands" class="pb-3 border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center gap-2">
        <i class="fa-solid fa-clock-rotate-left"></i> 对局复盘观战
      </button>
    </div>

    <!-- TAB 1: 训练控制台 -->
    <div id="tabTrain" class="space-y-6">
      <!-- 指标卡片 -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="card-dark rounded-xl p-4 shadow">
          <div class="text-xs text-slate-400 font-medium">当前最高 Fitness</div>
          <div class="text-2xl font-bold text-emerald-400 mt-1" id="statFitness">--</div>
          <div class="text-xs text-slate-500 mt-1">加权适应度评估</div>
        </div>
        <div class="card-dark rounded-xl p-4 shadow">
          <div class="text-xs text-slate-400 font-medium">预赛出线率 (Top 12)</div>
          <div class="text-2xl font-bold text-amber-400 mt-1" id="statTop12">--%</div>
          <div class="text-xs text-slate-500 mt-1">半决赛突围概率</div>
        </div>
        <div class="card-dark rounded-xl p-4 shadow">
          <div class="text-xs text-slate-400 font-medium">冠军夺冠率 (Champion)</div>
          <div class="text-2xl font-bold text-purple-400 mt-1" id="statChamp">--%</div>
          <div class="text-xs text-slate-500 mt-1">决赛第 1 名胜率</div>
        </div>
        <div class="card-dark rounded-xl p-4 shadow">
          <div class="text-xs text-slate-400 font-medium">平均单手收益 BB/100</div>
          <div class="text-2xl font-bold text-blue-400 mt-1" id="statBB">--</div>
          <div class="text-xs text-slate-500 mt-1">大盲/百手盈利能力</div>
        </div>
      </div>

      <!-- 训练参数控制与图表 -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- 控制表单 -->
        <div class="card-dark rounded-xl p-5 shadow space-y-4">
          <h2 class="text-base font-semibold text-white flex items-center gap-2">
            <i class="fa-solid fa-sliders text-emerald-400"></i> 训练参数配置
          </h2>
          <div class="grid grid-cols-2 gap-3 text-xs">
            <div>
              <label class="block text-slate-400 mb-1">训练代数</label>
              <input type="number" id="inpGens" value="10" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white">
            </div>
            <div>
              <label class="block text-slate-400 mb-1">种群大小 (候选数)</label>
              <input type="number" id="inpPop" value="8" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white">
            </div>
            <div>
              <label class="block text-slate-400 mb-1">初评场数 / 候选</label>
              <input type="number" id="inpRuns" value="40" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white">
            </div>
            <div>
              <label class="block text-slate-400 mb-1">并发 Workers (2h2g建议2)</label>
              <input type="number" id="inpWorkers" value="2" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white">
            </div>
          </div>
          <div>
            <label class="block text-slate-400 text-xs mb-1">初始热启动底模</label>
            <select id="selBaseModel" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-white"></select>
          </div>
          <div class="flex items-center space-x-2 text-xs">
            <input type="checkbox" id="chkMixProfiles" checked class="rounded bg-slate-900 border-slate-700 text-emerald-500">
            <label for="chkMixProfiles" class="text-slate-300">混入优质真实玩家画像 (50% 比例)</label>
          </div>
          <div class="pt-2 flex gap-3">
            <button onclick="startTrain()" id="btnStartTrain" class="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white font-medium py-2 rounded-lg text-xs transition flex items-center justify-center gap-1.5">
              <i class="fa-solid fa-play"></i> 启动演化训练
            </button>
            <button onclick="stopTrain()" id="btnStopTrain" class="bg-red-600/80 hover:bg-red-600 text-white font-medium px-4 py-2 rounded-lg text-xs transition flex items-center justify-center gap-1.5">
              <i class="fa-solid fa-stop"></i> 停止
            </button>
          </div>
        </div>

        <!-- 演化趋势折线图 -->
        <div class="card-dark rounded-xl p-5 shadow lg:col-span-2 flex flex-col">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-base font-semibold text-white flex items-center gap-2">
              <i class="fa-solid fa-chart-line text-blue-400"></i> Fitness 与盈利演化曲线
            </h2>
            <span class="text-xs text-slate-400" id="lblGenCount">累计 0 代数据</span>
          </div>
          <div class="flex-1 min-h-[220px]">
            <canvas id="fitnessChart"></canvas>
          </div>
        </div>
      </div>

      <!-- 2.0 参数架构与实时日志 -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- 2.0 基因参数面板 -->
        <div class="card-dark rounded-xl p-5 shadow space-y-3">
          <h2 class="text-base font-semibold text-white flex items-center gap-2">
            <i class="fa-solid fa-dna text-purple-400"></i> 2.0 策略基因指纹 (Champion)
          </h2>
          <div class="space-y-2 text-xs">
            <div class="flex justify-between border-b border-slate-800 pb-1">
              <span class="text-slate-400">入池率 VPIP</span>
              <span class="font-bold text-white" id="valVPIP">--</span>
            </div>
            <div class="flex justify-between border-b border-slate-800 pb-1">
              <span class="text-slate-400">翻牌价值门槛 Flop</span>
              <span class="font-bold text-emerald-400" id="valFlopVal">--</span>
            </div>
            <div class="flex justify-between border-b border-slate-800 pb-1">
              <span class="text-slate-400">转牌价值门槛 Turn</span>
              <span class="font-bold text-amber-400" id="valTurnVal">--</span>
            </div>
            <div class="flex justify-between border-b border-slate-800 pb-1">
              <span class="text-slate-400">河牌价值门槛 River</span>
              <span class="font-bold text-red-400" id="valRiverVal">--</span>
            </div>
            <div class="flex justify-between border-b border-slate-800 pb-1">
              <span class="text-slate-400">干燥板面下注尺寸</span>
              <span class="font-bold text-blue-400" id="valDrySize">--</span>
            </div>
            <div class="flex justify-between pb-1">
              <span class="text-slate-400">潮湿板面下注尺寸</span>
              <span class="font-bold text-purple-400" id="valWetSize">--</span>
            </div>
          </div>
        </div>

        <!-- 训练日志流 -->
        <div class="card-dark rounded-xl p-5 shadow lg:col-span-2 flex flex-col">
          <div class="flex items-center justify-between mb-2">
            <h2 class="text-base font-semibold text-white flex items-center gap-2">
              <i class="fa-solid fa-terminal text-emerald-400"></i> 训练引擎实时日志 (Console)
            </h2>
            <button onclick="refreshLogs()" class="text-xs text-slate-400 hover:text-white transition">
              <i class="fa-solid fa-rotate-right"></i> 刷新日志
            </button>
          </div>
          <pre id="trainLogBox" class="bg-black/80 rounded-lg p-3 text-xs font-mono text-emerald-400/90 overflow-y-auto h-48 border border-slate-800 whitespace-pre-wrap leading-relaxed"></pre>
        </div>
      </div>
    </div>

    <!-- TAB 2: 在线赛事实战 -->
    <div id="tabLive" class="hidden space-y-6">
      <div class="card-dark rounded-xl p-6 shadow space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <h2 class="text-lg font-bold text-white flex items-center gap-2">
              <i class="fa-solid fa-satellite-dish text-blue-400"></i> 赛场接入与桌况调度
            </h2>
            <p class="text-xs text-slate-400 mt-1">自动接入平台比赛，执行自适应决策与对手画像贝叶斯识别</p>
          </div>
          <div class="flex items-center gap-3">
            <button onclick="startLive()" class="bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-4 py-2.5 rounded-lg transition flex items-center gap-2">
              <i class="fa-solid fa-play"></i> 开始比赛
            </button>
            <button onclick="switchTable()" class="bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold px-4 py-2.5 rounded-lg transition flex items-center gap-2">
              <i class="fa-solid fa-arrows-rotate"></i> 立即换桌
            </button>
            <button onclick="stopLive()" class="bg-red-600 hover:bg-red-500 text-white text-xs font-semibold px-4 py-2.5 rounded-lg transition flex items-center gap-2">
              <i class="fa-solid fa-door-open"></i> 安全离桌停止
            </button>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div>
            <label class="block text-slate-400 mb-1">参赛模型选择</label>
            <select id="selLiveModel" class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white"></select>
          </div>
          <div>
            <label class="block text-slate-400 mb-1">换桌策略说明</label>
            <div class="bg-slate-900/60 border border-slate-800 rounded p-2 text-slate-400">
              点击换桌后，Agent 将在本手结算间隙向服务器发送离桌协议，并自动重新排队分配到新桌。
            </div>
          </div>
          <div>
            <label class="block text-slate-400 mb-1">热重载保护</label>
            <div class="bg-slate-900/60 border border-slate-800 rounded p-2 text-emerald-400/80">
              ⚡ 策略热重载激活：比赛进行中若后台训练产出新 Champion，系统将自动热更新参数，无需退桌。
            </div>
          </div>
        </div>
      </div>

      <!-- 实战日志流 -->
      <div class="card-dark rounded-xl p-5 shadow">
        <h2 class="text-base font-semibold text-white mb-3 flex items-center gap-2">
          <i class="fa-solid fa-bolt text-amber-400"></i> 实战比赛实时日志 (Live Stream)
        </h2>
        <pre id="liveLogBox" class="bg-black/80 rounded-lg p-3 text-xs font-mono text-amber-400/90 overflow-y-auto h-72 border border-slate-800 whitespace-pre-wrap leading-relaxed"></pre>
      </div>
    </div>

    <!-- TAB 3: 对局复盘观战 -->
    <div id="tabHands" class="hidden space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-base font-semibold text-white flex items-center gap-2">
          <i class="fa-solid fa-list-check text-emerald-400"></i> 最近对战手牌记录 (Hand Replays)
        </h2>
        <button onclick="loadHands()" class="text-xs bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-1.5 rounded-lg text-slate-300 transition">
          <i class="fa-solid fa-rotate"></i> 刷新对局
        </button>
      </div>
      <div id="handsList" class="space-y-3">
        <div class="text-center py-12 text-slate-500 text-xs">正在加载历史手牌...</div>
      </div>
    </div>
  </main>

  <script>
    let chartInstance = null;
    let currentTab = "tabTrain";

    function switchTab(tabId) {
      currentTab = tabId;
      document.getElementById("tabTrain").classList.add("hidden");
      document.getElementById("tabLive").classList.add("hidden");
      document.getElementById("tabHands").classList.add("hidden");
      document.getElementById(tabId).classList.remove("hidden");

      document.getElementById("tabBtnTrain").className = "pb-3 border-b-2 " + (tabId === "tabTrain" ? "border-emerald-500 text-emerald-400" : "border-transparent text-slate-400");
      document.getElementById("tabBtnLive").className = "pb-3 border-b-2 " + (tabId === "tabLive" ? "border-emerald-500 text-emerald-400" : "border-transparent text-slate-400");
      document.getElementById("tabBtnHands").className = "pb-3 border-b-2 " + (tabId === "tabHands" ? "border-emerald-500 text-emerald-400" : "border-transparent text-slate-400");

      if (tabId === "tabHands") loadHands();
    }

    function renderCard(c) {
      if (!c || c.length < 2) return "";
      const rank = c.slice(0, -1);
      const suit = c.slice(-1).toLowerCase();
      let icon = "";
      let isRed = false;
      if (suit === "h") { icon = "♥"; isRed = true; }
      else if (suit === "d") { icon = "♦"; isRed = true; }
      else if (suit === "s") { icon = "♠"; isRed = false; }
      else if (suit === "c") { icon = "♣"; isRed = false; }
      return `<div class="poker-card ${isRed ? "suit-red" : "suit-black"}">${rank}${icon}</div>`;
    }

    async function fetchStatus() {
      try {
        const res = await fetch("/api/status");
        const data = await res.json();
        
        // Update badges
        const trainBadge = document.getElementById("trainBadge");
        if (data.training.running) {
          trainBadge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full text-xs font-medium bg-emerald-950/80 border border-emerald-600 text-emerald-400";
          trainBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span><span>训练进行中 (PID: ${data.training.pid})</span>`;
        } else {
          trainBadge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full text-xs font-medium bg-slate-800 border border-slate-700 text-slate-400";
          trainBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-500"></span><span>训练: 空闲待命</span>`;
        }

        const liveBadge = document.getElementById("liveBadge");
        if (data.live.running) {
          liveBadge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full text-xs font-medium bg-blue-950/80 border border-blue-600 text-blue-400";
          liveBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-blue-400 animate-pulse"></span><span>比赛对局中 (PID: ${data.live.pid})</span>`;
        } else {
          liveBadge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full text-xs font-medium bg-slate-800 border border-slate-700 text-slate-400";
          liveBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-500"></span><span>比赛: 未连接</span>`;
        }

        // Update archive charts and cards
        if (data.archive && data.archive.length > 0) {
          const last = data.archive[data.archive.length - 1];
          document.getElementById("statFitness").innerText = last.fitness.toFixed(3);
          document.getElementById("statTop12").innerText = last.top12_rate.toFixed(1) + "%";
          document.getElementById("statChamp").innerText = last.champion_rate.toFixed(1) + "%";
          document.getElementById("statBB").innerText = (last.avg_bb100 >= 0 ? "+" : "") + last.avg_bb100.toFixed(1);
          document.getElementById("lblGenCount").innerText = `累计到达 Gen ${last.generation}`;

          if (last.params) {
            document.getElementById("valVPIP").innerText = (last.params.vpip * 100).toFixed(1) + "%";
            document.getElementById("valFlopVal").innerText = last.params.flop_value_threshold.toFixed(2);
            document.getElementById("valTurnVal").innerText = last.params.turn_value_threshold.toFixed(2);
            document.getElementById("valRiverVal").innerText = last.params.river_value_threshold.toFixed(2);
            document.getElementById("valDrySize").innerText = (last.params.dry_board_bet_size * 100).toFixed(0) + "% 底池";
            document.getElementById("valWetSize").innerText = (last.params.wet_board_bet_size * 100).toFixed(0) + "% 底池";
          }
          updateChart(data.archive);
        }
      } catch (e) {
        console.error("Status error:", e);
      }
    }

    function updateChart(archive) {
      const labels = archive.map(a => `Gen ${a.generation}`);
      const fitnessData = archive.map(a => a.fitness);
      const bbData = archive.map(a => a.avg_bb100);

      if (!chartInstance) {
        const ctx = document.getElementById("fitnessChart").getContext("2d");
        chartInstance = new Chart(ctx, {
          type: "line",
          data: {
            labels: labels,
            datasets: [
              {
                label: "Fitness 适应度",
                data: fitnessData,
                borderColor: "#10b981",
                backgroundColor: "rgba(16, 185, 129, 0.15)",
                fill: true,
                tension: 0.3,
                yAxisID: "y"
              },
              {
                label: "BB/100 净收益",
                data: bbData,
                borderColor: "#3b82f6",
                backgroundColor: "transparent",
                borderDash: [4, 4],
                tension: 0.3,
                yAxisID: "y1"
              }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            scales: {
              x: { grid: { color: "#1e293b" }, ticks: { color: "#94a3b8" } },
              y: {
                grid: { color: "#1e293b" }, ticks: { color: "#10b981" },
                title: { display: true, text: "Fitness", color: "#10b981" }
              },
              y1: {
                position: "right",
                grid: { drawOnChartArea: false }, ticks: { color: "#3b82f6" },
                title: { display: true, text: "BB/100", color: "#3b82f6" }
              }
            },
            plugins: { legend: { labels: { color: "#cbd5e1" } } }
          }
        });
      } else {
        chartInstance.data.labels = labels;
        chartInstance.data.datasets[0].data = fitnessData;
        chartInstance.data.datasets[1].data = bbData;
        chartInstance.update();
      }
    }

    async function loadModels() {
      try {
        const res = await fetch("/api/models");
        const list = await res.json();
        const sel1 = document.getElementById("selBaseModel");
        const sel2 = document.getElementById("selLiveModel");
        sel1.innerHTML = "";
        sel2.innerHTML = "";
        list.forEach(m => {
          const opt1 = document.createElement("option");
          opt1.value = m; opt1.innerText = m;
          if (m.includes("champion_optimized")) opt1.selected = true;
          sel1.appendChild(opt1);

          const opt2 = document.createElement("option");
          opt2.value = m; opt2.innerText = m;
          if (m.includes("champion_optimized") || m.includes("champion_v2")) opt2.selected = true;
          sel2.appendChild(opt2);
        });
      } catch (e) {}
    }

    async function loadHands() {
      const container = document.getElementById("handsList");
      try {
        const res = await fetch("/api/hands");
        const hands = await res.json();
        if (!hands || hands.length === 0) {
          container.innerHTML = `<div class="text-center py-10 text-slate-500 text-xs">暂无对战手牌记录，启动实战比赛后即可实时记录。</div>`;
          return;
        }
        let html = "";
        hands.forEach(h => {
          const isWin = h.hero_net > 0;
          const isLoss = h.hero_net < 0;
          const badgeColor = isWin ? "bg-emerald-950 text-emerald-400 border-emerald-800" : (isLoss ? "bg-red-950 text-red-400 border-red-800" : "bg-slate-800 text-slate-400 border-slate-700");
          const netText = (h.hero_net >= 0 ? "+" : "") + h.hero_net;
          
          let cardsHtml = "";
          (h.board || []).forEach(c => { cardsHtml += renderCard(c); });
          if (!cardsHtml) cardsHtml = `<span class="text-slate-500 text-xs italic">翻前决战 (Preflop)</span>`;

          html += `
            <div class="card-dark rounded-xl p-4 shadow border border-slate-800 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
              <div class="flex items-center space-x-3">
                <div class="text-center px-3 py-1 rounded-lg border ${badgeColor}">
                  <div class="text-[10px] uppercase font-bold">HERO</div>
                  <div class="text-sm font-black">${netText}</div>
                </div>
                <div>
                  <div class="text-xs text-slate-400 flex items-center gap-2">
                    <span><i class="fa-regular fa-clock"></i> ${h.time}</span>
                    <span>• 桌号: <span class="font-mono text-slate-300">${h.tableId}</span></span>
                    <span>• 底池: <span class="font-bold text-amber-400">${h.pot}</span></span>
                  </div>
                  <div class="mt-2 flex items-center">
                    <span class="text-xs text-slate-400 mr-2">公牌:</span>
                    <div class="flex">${cardsHtml}</div>
                  </div>
                </div>
              </div>
              <div class="text-xs text-slate-400 flex flex-wrap gap-2">
                ${h.players.map(p => `<span class="px-2 py-1 rounded bg-slate-900 border border-slate-800">${p.name}: ${(p.net>=0?"+":"")+p.net}</span>`).join("")}
              </div>
            </div>
          `;
        });
        container.innerHTML = html;
      } catch (e) {
        container.innerHTML = `<div class="text-red-400 text-xs py-4">加载手牌出错: ${e}</div>`;
      }
    }

    async function refreshLogs() {
      try {
        const r1 = await fetch("/api/train/logs");
        const t1 = await r1.text();
        const b1 = document.getElementById("trainLogBox");
        b1.innerText = t1;
        b1.scrollTop = b1.scrollHeight;

        const r2 = await fetch("/api/live/logs");
        const t2 = await r2.text();
        const b2 = document.getElementById("liveLogBox");
        b2.innerText = t2;
        b2.scrollTop = b2.scrollHeight;
      } catch (e) {}
    }

    async function startTrain() {
      const payload = {
        generations: document.getElementById("inpGens").value,
        population: document.getElementById("inpPop").value,
        runs: document.getElementById("inpRuns").value,
        workers: document.getElementById("inpWorkers").value,
        base_model: document.getElementById("selBaseModel").value,
        mix_profiles: document.getElementById("chkMixProfiles").checked
      };
      const res = await fetch("/api/train/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const d = await res.json();
      alert(d.message);
      fetchStatus();
    }

    async function stopTrain() {
      if (!confirm("确认终止当前正在运行的训练进程？")) return;
      const res = await fetch("/api/train/stop", { method: "POST" });
      const d = await res.json();
      alert(d.message);
      fetchStatus();
    }

    async function startLive() {
      const model = document.getElementById("selLiveModel").value;
      const res = await fetch("/api/live/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ strategy: model }) });
      const d = await res.json();
      alert(d.message);
      fetchStatus();
    }

    async function stopLive() {
      if (!confirm("确认停止比赛并离桌？")) return;
      const res = await fetch("/api/live/stop", { method: "POST" });
      const d = await res.json();
      alert(d.message);
      fetchStatus();
    }

    async function switchTable() {
      const res = await fetch("/api/live/switch_table", { method: "POST" });
      const d = await res.json();
      alert(d.message);
    }

    window.onload = () => {
      loadModels();
      fetchStatus();
      refreshLogs();
      setInterval(fetchStatus, 3000);
      setInterval(refreshLogs, 4000);
    };
  </script>
</body>
</html>"""

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress access logs

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            return

        if path == "/api/status":
            data = {
                "training": {"running": pm.is_training(), "pid": pm.train_proc.pid if pm.train_proc else None},
                "live": {"running": pm.is_live(), "pid": pm.live_proc.pid if pm.live_proc else None},
                "archive": get_archive_data()
            }
            self._send_json(data)
            return

        if path == "/api/models":
            self._send_json(get_models_list())
            return

        if path == "/api/hands":
            self._send_json(get_recent_hands(limit=30))
            return

        if path == "/api/train/logs":
            self._send_text(pm.get_logs("train"))
            return

        if path == "/api/live/logs":
            self._send_text(pm.get_logs("live"))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            params = json.loads(body) if body else {}
        except Exception:
            params = {}

        if path == "/api/train/start":
            self._send_json(pm.start_training(params))
            return
        if path == "/api/train/stop":
            self._send_json(pm.stop_training())
            return
        if path == "/api/live/start":
            strategy = params.get("strategy", "models/champion_optimized.json")
            self._send_json(pm.start_live(strategy))
            return
        if path == "/api/live/stop":
            self._send_json(pm.stop_live())
            return
        if path == "/api/live/switch_table":
            self._send_json(pm.switch_table())
            return

        self.send_response(404)
        self.end_headers()

    def _send_json(self, obj: Any):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _send_text(self, text: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

def run_server(host: str = "0.0.0.0", port: int = 8080):
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"\n" + "="*68)
    print(f" 🃏 AgentPoker 2.0 全能可视化控制台已启动！")
    print(f" • 本地访问: http://127.0.0.1:{port}")
    print(f" • 局域网/公网: http://{host}:{port}")
    print(f" • 功能: 训练启停、比赛启停、一键换桌、折线走势图、实时对局复盘")
    print(f"="*68 + "\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Dashboard] 正在停止控制台...")
        server.server_close()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    run_server(port=port)
