# Quant Research Lab

Institutional-grade research pipeline that feeds Groww Cloud execution.
CNC/F&O adapters are **deployment surfaces** — not the research ceiling.

## Quality bar (promotion gate)

A candidate graduates to Groww Cloud paper trading only if **all** hold:

1. Written **economic hypothesis** (why the edge exists in India cash/F&O)
2. **Triple-barrier labels** (profit / stop / vertical time)
3. Features with **IC, ICIR, turnover, decay half-life**; orthogonalized where claimed unique
4. **Purged CV or CPCV** with embargo ≥ average hold; never random CV
5. Track trial count \(N\); report **PSR**, **DSR**, **PBO**
6. Costs + capacity model (fees, slippage, ADV cap)
7. Performance sliced by **regime posterior** buckets
8. Stability under parameter perturbation / combinatorial paths

### Anti-patterns (banned)

- Optimize RSI/EMA periods on the full sample
- Promote on win rate alone or synthetic walk-forward
- Stack oscillators “for confluence” without IC evidence
- Ignore multiple-testing when grid/Optuna searching
- Mix decision-at-close and decision-at-open assumptions in one backtest

## Pipeline

```
Hypothesis → Feature store + IC → Triple-barrier labels
  → Primary model (side) → Meta-labeler (size/skip)
  → CPCV + purge/embargo → DSR / PBO gate
  → Vol-target / HRP / CVaR book → Groww dry-run → Live
```

### Phases

| Phase | Deliverable | Exit criterion |
|-------|-------------|----------------|
| R0 | Feature store + IC reports | ≥1 feature OOS ICIR > 0.3 at 10–20d |
| R1 | HMM regime posteriors | Posterior improves MOM vs MR sleeve IC |
| R2 | Triple-barrier + meta-labeler | DSR gate + PBO < 0.5 |
| R3 | Vol-target + corr budget | Beats equal-risk after costs on Calmar/CVaR |
| R4 | Groww-domain replication 2020+ | Edge survives domain shift |
| R5 | Cloud dry-run + IS tracking | Slippage within band |
| R6 | F&O VRP / futures TSMOM paper | ROM + DSR gates |

Synthetic data is for **pipeline CI only**, never for promotion.

## Package layout

```
strategies/research/     # no broker imports
  features/              # feature store, IC reports
  labels/                # triple-barrier
  models/                # primary + meta-labeler, HMM regime
  validation/            # purge, CPCV, PSR/DSR/PBO
  portfolio/             # vol target, HRP, CVaR budget
  reports/               # JSON/markdown report helpers
strategies/groww_swing/  # CNC execution adapter
strategies/groww_fno/    # F&O research + dry-run stubs
```

## Point-in-time discipline

Features at date \(t\) use only information known at India close \(t\).
No future GDP revisions, no same-bar peeking for “next open” fills unless
the backtest explicitly models next-open execution.

## Key references

- López de Prado, *Advances in Financial Machine Learning* (purge, embargo, CPCV, meta-labeling)
- Bailey & López de Prado — Probabilistic / Deflated Sharpe Ratio
- Bailey et al. — Probability of Backtest Overfitting (PBO)
- Jegadeesh–Titman; Moskowitz–Ooi–Pedersen — momentum
- Asness et al. — value/momentum everywhere

## CLI smoke

```bash
python -m strategies.research.reports.run_lab_smoke
```

Runs synthetic panel → features → IC → HMM → labels → meta → CPCV/DSR → portfolio weights.
