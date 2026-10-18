# F&O research notes (Phase R6)

## Programs

1. **Index futures TSMOM** — vol-scaled sign of lagged excess return on continuous Nifty/BankNifty; CPCV on roll-aware series.
2. **Variance risk premium** — trade defined-risk premium when `IV − RV` and IV rank support it; never naked short.
3. **Defined-risk expression** — map CNC primary signal to debit/credit verticals; compare **return on margin** vs CNC.
4. **Hedge overlay** — buy puts when `P(stress)` / late-expansion posterior rises; measure CVaR reduction of CNC book.

## Implementation stubs

See `strategies/groww_fno/vrp.py`. Wire Groww `get_expiries` / `get_contracts` / option chain only after CNC R4–R5 gates pass.

## Gates

- DSR / PBO same as equity lab
- Greek budgets (`greek_budget_ok`)
- Bid–ask and DTE bucket reporting mandatory for options
