# Deploy CNC multi-approach swing on Groww Cloud

Portable package: `strategies/groww_swing/` (no Pulse/FastAPI imports required).

## What it trades

Named approaches in `params.json` → `enabled_approaches`:

| ID | Idea | Default |
|----|------|---------|
| `trend_pullback` | EMA20 pullback + RSI reclaim (expansion) | on |
| `trend_breakout` | N-day high break + volume (expansion) | on |
| `rs_momentum` | Top RS vs Nifty in uptrend (expansion) | **off** (weak sample E[R]) |
| `defensive_mean_reversion` | Oversold bounce in defensives (contraction sleeve) | on |
| `vol_compression_break` | BB/ATR squeeze → upside break (non-fear) | on |

Cycle filter + `regime_router.py` decide **which approaches run today**. Risk-off / VIX fear → no new entries.

Trend approaches require **RS vs Nifty ≥ 0** (not just “not lagging hard”).

## Data limits (important)

- Groww equity/index candles: available **from ~2020**, not 20 years (vendor limit).
- Daily requests: **180 days max** per call — we chunk from 2020-01-01 → now for full cache.
- **15-minute is not the primary swing timeframe** (hold horizon is multi-day). Optional later as entry-timing overlay only.

Refresh full daily cache (background):

```bash
# via API
curl -X POST 'http://127.0.0.1:8000/api/swing/cache/refresh?full_history=true'
```

Full eval (CLI, after cache ready):

```bash
python -m strategies.groww_swing.eval
# writes data/groww_cache/last_eval.json
```

Or Pulse UI → **Full eval** (async job). Quick backtest is smoke only.

## Credentials

Set one of:

- `GROWW_API_KEY` + `GROWW_TOTP_SECRET` (preferred for schedules)
- `GROWW_API_KEY` + `GROWW_API_SECRET`
- `GROWW_ACCESS_TOKEN`

Optional: `SWING_CAPITAL=100000`

## Dry-run (default)

`params.json` has `"dry_run": true`. Orders and GTTs are logged only; candles still hit Groww.

```bash
python -m strategies.groww_swing
```

## Go live

1. Full daily eval on Groww cache looks acceptable (baseline + per-approach).
2. Confirm dry-run scans look sane for several sessions.
3. Set `"dry_run": false` **or** `SWING_LIVE=1`.
4. Keep `"place_target_gtt": false` unless you accept dual full-qty GTTs. Protective **stop GTT only** is default.
5. Schedule once per day near cash close (e.g. **15:20 IST**).

## State file

`positions_state.json` tracks entry date / stop for portfolio heat and `max_hold_days` time exits.

## Promote checklist

- [ ] Full-history cache (~2020→now) ready (`manifest.json` has `history_start` / `history_end`)
- [ ] `python -m strategies.groww_swing.eval` (or UI Full eval) — not quick smoke
- [ ] Per-approach `approach_stats` / `recommended_disable` reviewed
- [ ] Losers off in `enabled_approaches`
- [ ] Dry-run scan matches router
- [ ] `dry_run: false` only after stop GTT path verified
