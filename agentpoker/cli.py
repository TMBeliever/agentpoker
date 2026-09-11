from __future__ import annotations
import argparse, os, json
from pathlib import Path
from .strategy import StrategyAgent
from .training import StrategyTrainer, ArenaEvaluator, ARCHETYPES
from .tournament import LeagueSimulator, SimAgent
from .protocol import AgentPokerClient, Config
from .live import LiveRunner
from .collector import JSONLCollector, ReplayBuilder
from .profiler import OpponentProfiler

def run_connect(base_url: str = "https://poker.bang.sohu.com") -> None:
    import http.server, urllib.parse, secrets, webbrowser
    state = secrets.token_urlsafe(16)
    auth_code = None

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/callback":
                qs = urllib.parse.parse_qs(parsed.query)
                ret_state = qs.get("state", [""])[0]
                code = qs.get("code", [""])[0]
                if ret_state == state and code:
                    auth_code = code
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<h1>Agent Connected Successfully!</h1><p>Credentials received. You may close this tab now.</p>")
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Invalid state or missing authorization code.")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), CallbackHandler)
    port = server.server_address[1]
    url = f"{base_url.rstrip('/')}/cli/connect?port={port}&state={state}"
    print(f"\n[Connect] Starting temporary authorization listener on http://127.0.0.1:{port}...")
    print(f"[Connect] Opening browser for Agent authorization:\n  {url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    server.handle_request()
    server.server_close()

    if not auth_code:
        print("[Connect] Authorization cancelled or no code received.")
        return

    print("[Connect] Exchanging code for Agent secretKey...")
    client = AgentPokerClient(Config(base_url=base_url))
    resp = client.exchange_code(auth_code)
    sk = resp.get("secretKey")
    agent_id = resp.get("agent_id")
    agent_name = resp.get("name", "Unnamed")

    if not sk:
        print(f"[Connect] Failed to receive secretKey: {resp}")
        return

    active_cid = ""
    try:
        disc = client.discover("active")
        comps = disc.get("competitions", [])
        if comps:
            active_cid = comps[0]["id"]
            print(f"[Connect] Discovered active competition: {comps[0].get('name')} ({active_cid})")
    except Exception:
        pass

    env_content = f"AGENTPOKER_APP={base_url.rstrip('/')}\nAGENTPOKER_KEY={sk}\nAGENTPOKER_COMPETITION_ID={active_cid}\nAGENTPOKER_TIMEOUT=10\n"
    p = Path(".env")
    p.write_text(env_content, encoding="utf-8")
    try:
        os.chmod(".env", 0o600)
    except Exception:
        pass

    masked_sk = sk[:6] + "..." + sk[-4:] if len(sk) > 10 else "[PROTECTED]"
    print(f"\n[Connect] Success! Connected as Agent '{agent_name}' (ID: {agent_id})")
    print(f"[Connect] Saved credentials to .env (mode 0600, key: {masked_sk})")
    print(f"[Connect] Start playing with: python -m agentpoker.cli live")

def main():
    p=argparse.ArgumentParser(prog='agentpoker'); sub=p.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('simulate'); s.add_argument('--agents',type=int,default=36); s.add_argument('--runs',type=int,default=10); s.add_argument('--seed',type=int,default=7)
    t=sub.add_parser('train')
    t.add_argument('--track',choices=['universal','targeted'],default=None,help='Training track: universal (general robust GTO) or targeted (real opponent profiling)')
    t.add_argument('--generations',type=int,default=10)
    t.add_argument('--population',type=int,default=16)
    t.add_argument('--runs',type=int,default=30)
    t.add_argument('--final-race',type=int,default=200)
    t.add_argument('--agents',type=int,default=36)
    t.add_argument('--equity-samples',type=int,default=0)
    t.add_argument('--workers',type=int,default=0)
    t.add_argument('--profiles',default=None,help='Opponent profiles for targeted training')
    t.add_argument('--save',default=None,help='Output model path')
    t.add_argument('--archive',default=None,help='Generations archive directory')
    t.add_argument('--no-resume',dest='resume',action='store_false',default=True,help='Disable resuming from existing archive checkpoints')
    t.add_argument('--reeval-runs',type=int,default=40,help='Fresh-seed tournaments used to re-score the generation shortlist before crowning a champion')
    t.add_argument('--holdout-frac',type=float,default=0.25,help='Fraction of real opponent profiles held out of training and used only for final validation')
    e=sub.add_parser('evaluate'); e.add_argument('--strategy',default='models/champion.json'); e.add_argument('--runs',type=int,default=500); e.add_argument('--agents',type=int,default=36); e.add_argument('--equity-samples',type=int,default=0); e.add_argument('--profiles',default=None); e.add_argument('--workers',type=int,default=0)
    l=sub.add_parser('live')
    l.add_argument('--competition-id',default=os.getenv('AGENTPOKER_COMPETITION_ID'))
    l.add_argument('--key',default=os.getenv('AGENTPOKER_KEY'))
    l.add_argument('--app',default=os.getenv('AGENTPOKER_APP','https://poker.bang.sohu.com'))
    l.add_argument('--strategy',default='models/champion.json')
    l.add_argument('--max-steps',type=int,default=0)
    l.add_argument('--max-hands',type=int,default=0,help='Max hands to play before stopping (0 for infinite)')
    l.add_argument('--round-hands',type=int,default=20,help='Number of hands per round (default: 20)')
    l.add_argument('--cycle-hands',type=int,default=200,help='Number of hands per tournament cycle (default: 200)')
    l.add_argument('--no-auto-profile',dest='auto_profile',action='store_false',default=True,help='Disable automatic in-memory profile hot-reloading')
    l.add_argument('--profiles',default='models/opponent_profiles.json')
    r=sub.add_parser('replay-export'); r.add_argument('--raw',default='data/raw/events.jsonl'); r.add_argument('--out',default='data/processed/hands.jsonl')
    sub.add_parser('discover')
    conn=sub.add_parser('connect')
    conn.add_argument('--app',default=os.getenv('AGENTPOKER_APP','https://poker.bang.sohu.com'))
    pr=sub.add_parser('profile')
    pr.add_argument('--input',default='data/processed/hands.jsonl')
    pr.add_argument('--out',default='models/opponent_profiles.json')
    pr.add_argument('--prior-weight',type=float,default=8.0)
    pr.add_argument('--min-hands',type=int,default=30,help='Minimum hands required to keep in profile')
    pr.add_argument('--no-filter-afk',dest='filter_afk',action='store_false',default=True,help='Disable filtering AFK/zombie agents')
    pr.add_argument('--competition-id',default=os.getenv('AGENTPOKER_COMPETITION_ID'))
    pr.add_argument('--pull',action='store_true',help='Pull hands directly from competition API')
    pr.add_argument('--max-hands',type=int,default=None)
    args=p.parse_args()
    if args.cmd=='simulate':
        names=list(ARCHETYPES); agents=[]
        for i in range(args.agents):
            base=ARCHETYPES[names[i%len(names)]]
            agents.append(SimAgent(f'agent_{i+1:03d}',StrategyAgent(base,seed=args.seed+i,name=f'agent_{i+1:03d}')))
        for run in range(args.runs):
            sim=LeagueSimulator(agents,seed=args.seed+run*10007); r=sim.run_event(); print(f'run={run+1} top12={[x.agent_id for x in r["qualified"][:12]]} champion={r["final"][0].agent_id if r["final"] else None}')
    elif args.cmd=='train':
        track = args.track
        if track is None:
            track = 'targeted' if args.profiles else 'universal'

        if track == 'targeted':
            save_path = args.save or 'models/champion_targeted.json'
            archive_dir = args.archive or 'models/archive_targeted'
            profiles_src = args.profiles or 'models/opponent_profiles.json'
            print(f"[Train] === 启动【赛场特训收割轨 (Targeted)】===")
            print(f"[Train] 挂载对手画像: {profiles_src} | 模型保存: {save_path} | 归档: {archive_dir}")
        else:
            save_path = args.save or 'models/champion_universal.json'
            archive_dir = args.archive or 'models/archive_universal'
            profiles_src = None
            print(f"[Train] === 启动【通用自演化基石轨 (Universal)】===")
            print(f"[Train] 无特定画像偏见 | 模型保存: {save_path} | 归档: {archive_dir}")

        trainer = StrategyTrainer(seed=7, pool_size=args.agents, equity_samples=args.equity_samples, workers=args.workers, profiles=profiles_src, holdout_frac=args.holdout_frac)
        champ, report = trainer.fit(args.generations, args.population, args.runs, save=save_path, archive=archive_dir, final_race=args.final_race, resume=args.resume, reeval_runs=args.reeval_runs)
        
        if track == 'universal' and save_path == 'models/champion_universal.json':
            try:
                Path('models/champion.json').write_text(Path(save_path).read_text(encoding='utf-8'), encoding='utf-8')
            except Exception:
                pass
        print(f"[Train] 训练完成！已成功保存到 {save_path}")
    elif args.cmd=='evaluate':
        pth=StrategyAgent.load(args.strategy).params
        r=ArenaEvaluator(pool_size=args.agents,equity_samples=args.equity_samples,profiles=args.profiles,workers=args.workers).evaluate(pth,runs=args.runs,seed_offset=9911,verbose=True)
        print(json.dumps(r,ensure_ascii=False,indent=2))
    elif args.cmd=='discover': print(AgentPokerClient(Config()).discover())
    elif args.cmd=='connect': run_connect(base_url=args.app)
    elif args.cmd=='replay-export': print(f'exported {ReplayBuilder(args.raw).export(args.out)} hands -> {args.out}')
    elif args.cmd=='profile':
        profiler=OpponentProfiler()
        cid=args.competition_id or os.getenv('AGENTPOKER_COMPETITION_ID')
        if args.pull or not os.path.exists(args.input):
            if not cid: raise SystemExit('AGENTPOKER_COMPETITION_ID is required to pull hand history.')
            client=AgentPokerClient(Config(competition_id=cid))
            print(f"[Profile] Pulling hand history from competition {cid}...")
            count=profiler.pull_competition_hands(client,cid,max_hands=args.max_hands,save_hands_path=args.input)
            print(f"[Profile] Fetched and saved {count} hands to {args.input}")
        else:
            count=profiler.ingest_file(args.input)
            print(f"[Profile] Ingested {count} hands from local file {args.input}")
        res=profiler.export(args.out,prior_weight=args.prior_weight,min_hands=args.min_hands,filter_afk=args.filter_afk)
        print(f"[Profile] Generated clean profiles for {len(res)} agents -> {args.out}")
    elif args.cmd=='live':
        key = args.key or os.getenv('AGENTPOKER_KEY')
        if not key:
            raise SystemExit('Error: AGENTPOKER_KEY is required.\nRun `python -m agentpoker.cli connect` to login, or export AGENTPOKER_KEY in .env')
        cid = args.competition_id or os.getenv('AGENTPOKER_COMPETITION_ID')
        if not cid:
            # Try auto-discovery of active competition
            client_temp = AgentPokerClient(Config(base_url=args.app, key=key))
            try:
                cs = client_temp.discover('active').get('competitions', [])
                if cs:
                    cid = cs[0]['id']
                    print(f"[Live] Auto-selected active competition: {cs[0].get('name')} ({cid})")
            except Exception:
                pass
        if not cid:
            raise SystemExit('Error: AGENTPOKER_COMPETITION_ID is required.')
        prof_file=args.profiles if args.profiles and os.path.exists(args.profiles) else None
        st=StrategyAgent.load(args.strategy,profiles=prof_file) if os.path.exists(args.strategy) else StrategyAgent(profiles=prof_file)
        client=AgentPokerClient(Config(base_url=args.app, key=key, competition_id=cid))
        runner = LiveRunner(
            client,
            st,
            competition_id=cid,
            collector=JSONLCollector(),
            round_hands=args.round_hands,
            cycle_hands=args.cycle_hands,
            auto_profile=args.auto_profile,
            profiles_path=args.profiles or 'models/opponent_profiles.json',
        )
        runner.run(max_steps=args.max_steps or None, max_hands=args.max_hands or None)
if __name__=='__main__': main()
