# Stage 1 Audit & Verification Report: Poker Engine & Tournament Accounting Correctness

> **Status**: **PASS (Gate 1 Evaluated and Passed)**  
> **Evaluation Date**: 2026-09-12  
> **Target Gate**: Gate 1 (Poker Engine & Tournament Accounting Invariants)

---

## 1. Executive Summary

Stage 1 addressed critical flaws in tournament stack persistence, auto-rebuy mechanics, betting round termination under all-in conditions, and accounting ledgers. All poker engine rules and tournament accounting mechanics have been brought into strict compliance with the official 120-player tournament specifications.

### Key Bug Fixes in Stage 1
1. **Continuous Stack Persistence Bug Fixed (`agentpoker/tournament.py`)**:
   - **Problem**: In preliminary rounds, `st[aid]['stack'] = 100 * self.big_blind` was executed at the start of every single round in `_play_group`, resetting accumulated stacks to 100 BB every 20 hands. This destroyed deep-stack dynamics and minted chips for short-stacked players.
   - **Solution**: Removed stack reset between rounds. Stacks now continuously persist across the entire 10 preliminary rounds (200 hands).
2. **Unified Tournament Accounting Ledger Implemented (`agentpoker/tournament.py`)**:
   - **Problem**: Inconsistent formulas for net winnings and lack of rebuy penalty accounting.
   - **Solution**: Implemented standard accounting identity:
     $$\text{net\_bb} = \frac{\text{current\_stack} - \text{initial\_stack}}{\text{bb}} - \text{rebuy\_cost\_bb} = \text{gross\_winnings\_bb} - \text{gross\_losses\_bb}$$
3. **Auto-Rebuy & Non-Elimination Mechanics (`agentpoker/tournament.py`)**:
   - When any agent's stack reaches $\le 0$, they are immediately refilled with 100 BB ($20,000$ chips), `rebuy_count += 1`, and `rebuy_cost_bb += 100.0`. Busted players are not eliminated and participate normally in subsequent hands.
4. **Premature Betting Round Termination Bug Fixed (`agentpoker/engine.py`)**:
   - **Problem**: `NLHEngine` contained `if len(live) <= 1: break` at the start of the betting loop. When all other players went all-in, the lone player holding chips was skipped without being offered the opportunity to call or fold.
   - **Solution**: Corrected condition to check whether the lone live player has already matched `current_bet`:
     ```python
     if not live:
         break
     if len(live) == 1 and live[0].committed_round == current_bet:
         break
     ```
     When facing an uncalled bet, the live player is properly prompted to call or fold.
5. **Final Tiebreaker Logic Corrected (`agentpoker/tournament.py`)**:
   - Removed duplicate `return result` and inverted negative sign in preliminary rank tiebreaker sort order so that Rank 1 beats Rank 2 on tiebreak.

---

## 2. Gate 1 Verification Checklist & Evidence

| Gate ID | Verification Item | Test Function | Result | Evidence |
| :--- | :--- | :--- | :---: | :--- |
| **G1.1** | Chip Conservation ($\sum S_{\text{after}} = \sum S_{\text{before}}$) | `test_chip_conservation` | **PASS** | 100 6-max hands verified, 0 chip leak |
| **G1.2** | Blind Posting & Action Order (HU & 6-Max) | `test_blind_posting` | **PASS** | HU: Dealer SB (100) acts first preflop; 6-max: SB(1), BB(2), UTG(3) acts first |
| **G1.3** | Button Rotation Clockwise | `test_button_rotation` | **PASS** | Button rotates $(d + 1) \pmod n$ across 12 consecutive hands |
| **G1.4** | Multi-All-In Staggered Stack Side Pots | `test_side_pot` | **PASS** | AA (1000 all-in) wins main pot (3000); KK (3000 all-in) wins side pot (4000) over QQ (calls 3000) |
| **G1.5** | Unmatched Raise Return Directly | `test_unmatched_raise` | **PASS** | Uncalled raise (1700) returns directly to raiser, raiser nets folded chips (500) |
| **G1.6** | Auto-Rebuy Mechanics | `test_auto_rebuy` | **PASS** | Busted player stack refilled to 100 BB, `rebuy_count=1`, `rebuy_cost_bb=100.0` |
| **G1.7** | Multiple Rebuys & Accounting Equation | `test_multiple_rebuys` | **PASS** | 3 consecutive busts: `rebuy_cost_bb=300.0`, `net_bb == -300.0 == gross_win - gross_loss` |
| **G1.8** | BB/100 Calculation Consistency | `test_bb100_consistency` | **PASS** | Proportional across arbitrary hands, returns `None` when hands == 0 |
| **G1.9** | Bust Does Not Eliminate | `test_bust_does_not_eliminate` | **PASS** | Player starting round at 0 stack completes all 10 hands in round |
| **G1.10** | Net Ledger Consistency Throughout Transitions | `test_net_result_after_rebuy` | **PASS** | Step 1 (bust -> -100 BB), Step 2 (+150 BB -> +50 BB), Step 3 (bust -> -200 BB) all strictly hold |
| **G1.11** | 1,000+ Randomized Hand Stress Test | `test_1000_randomized_hands_zero_violation`| **PASS** | 1,200 randomized hands (2-6 players, wild policies), 0 chip leaks, 0 negative stacks |

---

## 3. Test Suite Status

```
============================= test session starts ==============================
platform darwin -- Python 3.11.16, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/liang/Downloads/agentpoker_final 2
configfile: pyproject.toml
collected 67 items

tests/test_battle.py ....                                                [  5%]
tests/test_calibration.py ..........                                     [ 20%]
tests/test_engine.py ......                                              [ 29%]
tests/test_live_body.py .                                                [ 31%]
tests/test_live_controller.py ..                                         [ 34%]
tests/test_optimization.py ..........                                    [ 49%]
tests/test_protocol.py .                                                 [ 50%]
tests/test_resumable_training.py ....                                    [ 56%]
tests/test_stage1_accounting.py ...........                              [ 73%]
tests/test_strategy_params_live.py ....                                  [ 79%]
tests/test_tournament.py .                                               [ 80%]
tests/test_training_statistics.py .......                                [ 91%]
tests/test_v2_architecture.py ......                                     [100%]

============================== 67 passed in 9.58s ==============================
```

**Gate 1 Verdict: PASS.** Proceeding to **Stage 2: 120-Player Tournament Consistency (`TournamentConfig`)**.
