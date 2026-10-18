import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from kiteconnect import KiteConnect
import json as _json

from backend.config import (
    API_KEY,
    API_SECRET,
    SECTOR_INDICES,
    validate_config,
    setup_logging,
    PROJECT_ROOT,
)
from backend.data.kite_client import KiteClient
from backend.data.cache_manager import CacheManager
from backend.data.macro_client import MacroClient
from backend.analysis.regime_detection import RegimeDetector
from backend.analysis.market_signals import MarketSignals
from backend.analysis.leading_signals import LeadingSignalAnalyzer
from backend.analysis.sector_analysis import SectorAnalyzer, compute_recent_momentum, compute_composite_score, compute_exit_signals
from backend.portfolio.allocation import PortfolioAllocator
from backend.data.mf_client import MFClient
from backend.analysis.fund_recommender import FundRecommender
from backend.models.schemas import TokenResponse, HealthResponse, SectorPerformanceMetrics
from backend.api.os_api import router as os_router
from backend.decision.api import router as decide_router
from backend.api.swing_api import router as swing_router
from backend.decision.db import init_db
from backend.decision.runs import persist_run_from_pipeline
from backend.decision.db import SessionLocal
from backend.portfolio.ledger import InvestmentLedger

setup_logging()
logger = logging.getLogger(__name__)

cache = CacheManager()
_ledger = InvestmentLedger()
_access_token: Optional[str] = None
_pipeline_results: Dict[str, Any] = {}
_last_run: Optional[str] = None
_jobs: Dict[str, Dict[str, Any]] = {}

templates = Jinja2Templates(directory=str(PROJECT_ROOT / "backend" / "templates"))
static_dir = PROJECT_ROOT / "backend" / "static"
static_dir.mkdir(parents=True, exist_ok=True)


def _parse_last_run(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%b %d, %Y %H:%M",):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@contextmanager
def _without_proxy():
    """Temporarily clear proxy env vars so Kite API calls aren't blocked by Cursor sandbox proxies."""
    proxy_keys = [k for k in list(os.environ) if "proxy" in k.lower()]
    saved = {k: os.environ.pop(k) for k in proxy_keys}
    try:
        yield
    finally:
        os.environ.update(saved)


def _load_cached_token() -> Optional[str]:
    token_data = cache.get("kite_access_token")
    if token_data and isinstance(token_data, dict):
        return token_data.get("access_token")
    return None


def _persist_token(token: str) -> None:
    cache.set("kite_access_token", {"access_token": token}, ttl_hours=24 * 7, source="oauth")


def _is_kite_connected() -> bool:
    if not _access_token:
        return False
    try:
        with _without_proxy():
            kite = KiteClient(access_token=_access_token, cache=cache)
            kite.get_profile()
        return True
    except Exception:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _access_token, _pipeline_results, _last_run
    # Drop Cursor/sandbox proxy vars — they break Kite and yfinance HTTPS
    for key in [k for k in list(os.environ) if "proxy" in k.lower()]:
        logger.info(f"Clearing proxy env var: {key}")
        os.environ.pop(key, None)
    issues = validate_config()
    if issues:
        for i in issues:
            logger.warning(i)
    _access_token = _load_cached_token()
    if _access_token:
        logger.info("Loaded cached Kite access token")
    cached_results = cache.get("pipeline_results")
    if cached_results:
        _pipeline_results = cached_results
        _last_run = _pipeline_results.get("_last_run")
        logger.info("Loaded cached pipeline results")
    try:
        init_db()
        logger.info("Decision OS database ready")
    except Exception as exc:
        logger.warning("Decision OS DB init failed: %s", exc)
    logger.info("Server started")
    yield


app = FastAPI(title="Pulse Decision OS", version="4.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.include_router(os_router)
app.include_router(decide_router)
app.include_router(swing_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ctx(request: Request, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = {"request": request, "kite_connected": _is_kite_connected()}
    if extra:
        ctx.update(extra)
    return ctx


# ─── PAGES ─────────────────────────────────────────────────

@app.get("/")
def home(request: Request):
    """Primary product is Decision OS Next.js app."""
    return RedirectResponse(url="http://127.0.0.1:3000/analyse")


@app.get("/legacy")
@app.get("/legacy/dashboard")
@app.get("/dashboard")
def dashboard(request: Request):
    """Jinja cycle lab — kept under /legacy; primary UX is Next.js Decision OS."""
    ctx: Dict[str, Any] = {
        "last_run": _last_run,
        "open_position_count": len(_ledger.list_positions()),
    }

    if _pipeline_results:
        ctx["summary"] = _pipeline_results.get("summary", [])
        ctx["current_phase"] = _pipeline_results.get("current_phase", "")
        ctx["sub_phase"] = _pipeline_results.get("sub_phase", "")
        ctx["sub_phase_desc"] = _pipeline_results.get("sub_phase_desc", "")
        ctx["market_story"] = _pipeline_results.get("market_story", "")
        ctx["risk_label"] = _pipeline_results.get("risk_label", "")
        ctx["phase_progress"] = _pipeline_results.get("phase_progress", 0)
        ctx["recommendations"] = _pipeline_results.get("recommendations", [])
        ctx["signals"] = _pipeline_results.get("leading_signals", {})
        ctx["top_sectors"] = _pipeline_results.get("top_sectors", [])
        ctx["fund_picks"] = _pipeline_results.get("fund_picks", {})
        ctx["exit_watch"] = _pipeline_results.get("exit_watch", [])
        ctx["investments"] = _pipeline_results.get("investments", [])
        ctx["sector_matrix"] = _pipeline_results.get("sector_matrix", {})
        ctx["matrix_phases"] = _pipeline_results.get("matrix_phases", [])
        ctx["matrix_labels"] = _pipeline_results.get("matrix_labels", {})
        ctx["cycle_gauge"] = _pipeline_results.get("cycle_gauge", {})
        ctx["phase_history"] = _pipeline_results.get("phase_history", [])
        ctx["market_signals"] = _pipeline_results.get("market_signals", {})

    return templates.TemplateResponse("dashboard.html", _ctx(request, ctx))


@app.get("/sectors")
def sectors(request: Request):
    ctx: Dict[str, Any] = {}

    if _pipeline_results:
        ctx["sector_performance"] = _pipeline_results.get("sector_performance", [])
        ctx["current_regime"] = _pipeline_results.get("current_phase", "expansion")

    if not ctx.get("sector_performance"):
        ctx["error"] = "Run the analysis first."

    return templates.TemplateResponse("sectors.html", _ctx(request, ctx))


@app.get("/loading")
def loading_page(request: Request, job: str = ""):
    return templates.TemplateResponse("loading.html", _ctx(request, {"job_id": job}))


# ─── AUTH ─────────────────────────────────────────────────

@app.get("/login")
def login(next: str = Query("http://127.0.0.1:3000/analyse")):
    try:
        kite = KiteConnect(api_key=API_KEY)
        cache.set("kite_oauth_next", {"next": next}, ttl_hours=1, source="oauth")
        return RedirectResponse(url=kite.login_url())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed: {e}")


@app.get("/callback")
def callback(request: Request, request_token: str = Query(...)):
    global _access_token
    try:
        with _without_proxy():
            kite = KiteConnect(api_key=API_KEY)
            session = kite.generate_session(request_token, api_secret=API_SECRET)
        _access_token = session["access_token"]
        _persist_token(_access_token)
        logger.info("Kite authentication successful")
        nxt = "http://127.0.0.1:3000/analyse"
        stored = cache.get("kite_oauth_next") or {}
        if isinstance(stored, dict) and stored.get("next"):
            nxt = str(stored["next"])
        sep = "&" if "?" in nxt else "?"
        return RedirectResponse(url=f"{nxt}{sep}kite=connected", status_code=303)
    except Exception as e:
        logger.error(f"Auth failed: {e}")
        return RedirectResponse(
            url=f"http://127.0.0.1:3000/analyse?kite=error&detail={str(e)[:120]}",
            status_code=303,
        )


@app.get("/api/kite/status")
def kite_status():
    connected = _is_kite_connected()
    return {
        "connected": connected,
        "login_url": "http://127.0.0.1:8000/login?next=http://127.0.0.1:3000/analyse",
    }


@app.get("/get_token", response_model=TokenResponse)
def get_token():
    if _access_token:
        return TokenResponse(access_token=_access_token)
    raise HTTPException(status_code=401, detail="No access token available.")


# ─── API: PROGRESS POLLING ────────────────────────────────

@app.get("/api/pipeline/status/{job_id}")
def pipeline_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return {"done": True, "error": "Job not found", "step": "", "progress": 0}
    return {
        "done": job.get("done", False),
        "error": job.get("error"),
        "step": job.get("step", ""),
        "progress": job.get("progress", 0),
    }


# ─── API: RUN PIPELINE ────────────────────────────────────

@app.post("/api/run-pipeline")
def run_pipeline():
    global _pipeline_results, _last_run

    if not _access_token:
        raise HTTPException(status_code=401, detail="Connect Kite first")

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"done": False, "step": "Starting...", "progress": 0, "error": None}

    def _run():
        global _pipeline_results, _last_run
        try:
            job = _jobs[job_id]

            job["step"] = "Fetching sector data from Kite..."
            job["progress"] = 0.05
            kite = KiteClient(access_token=_access_token, cache=cache)
            start = "2005-01-01"
            end = datetime.now().strftime("%Y-%m-%d")

            # 1. Fetch sector data (Kite) and global data (yfinance) in parallel
            job["step"] = "Fetching sector & global data..."
            job["progress"] = 0.10
            sector_data = kite.fetch_all_sectors_parallel(start, end)

            macro = MacroClient(cache=cache)
            global_data = {}
            try:
                global_data = macro.fetch_all_global(start, end)
            except Exception as e:
                logger.warning(f"Global data fetch partial: {e}")

            # 2. Market-derived cycle signals (from Kite sector data)
            job["step"] = "Computing market cycle signals..."
            job["progress"] = 0.30
            market = MarketSignals(cache=cache)
            market_signals = market.compute_all(sector_data, kite_client=kite)

            # Sticky phase: use last persisted sub_phase as deadband prior
            prev_sub_phase = None
            sector_history_maps: List[Dict] = []
            try:
                from backend.decision.recommend import build_sector_history_maps
                from backend.decision.runs import list_runs

                with SessionLocal() as db:
                    prior_runs = list_runs(db, limit=4)
                    if prior_runs:
                        prev_sub_phase = (prior_runs[0].sub_phase or "").strip() or None
                        sector_history_maps = build_sector_history_maps(prior_runs)
            except Exception as hist_exc:
                logger.debug("No prior run history for sticky phase/recommend: %s", hist_exc)

            cycle = market.get_cycle_phase(prev_sub_phase=prev_sub_phase)

            # 3. Regime detection from market-derived phase data
            job["step"] = "Detecting economic phase..."
            job["progress"] = 0.40
            phase_df = RegimeDetector.derive_phases_from_cyclical_ratio(sector_data)
            regime_detector = RegimeDetector(cache=cache)
            if not phase_df.empty:
                regime_probs = regime_detector.fit_from_phases(phase_df)
            else:
                regime_probs = regime_detector.fit_from_phases(
                    pd.DataFrame({"phase": ["expansion"], "growth_rate": [1.0]}, index=[pd.Timestamp.now()]))
            current_regime = regime_detector.get_current_regime()
            current_phase = cycle["phase"]
            sub_phase = cycle["sub_phase"]
            # Prefer detector progress (from historical phase durations); fall back to market estimate
            detector_progress = regime_detector.phase_progress
            if not phase_df.empty and detector_progress > 0:
                phase_progress = detector_progress
            else:
                phase_progress = cycle["progress"]

            # 4. Leading signals (global + India VIX)
            job["step"] = "Analyzing leading signals..."
            job["progress"] = 0.50
            india_vix = market_signals.get("india_vix", {})
            signal_analyzer = LeadingSignalAnalyzer(macro=macro)
            try:
                signals = signal_analyzer.analyze_all(
                    start, end,
                    india_vix_value=india_vix.get("value"),
                    india_vix_signal=india_vix.get("signal"),
                )
            except Exception as e:
                logger.warning(f"Signals skipped: {e}")
                signals = {}

            # 5. Sector performance analysis
            job["step"] = "Computing sector performance..."
            job["progress"] = 0.60
            sector_analyzer = SectorAnalyzer(kite=kite, cache=cache)

            results: Dict[str, Any] = {}
            results["current_phase"] = current_phase
            results["sub_phase"] = sub_phase
            results["sub_phase_desc"] = regime_detector.get_sub_phase_description() if not phase_df.empty else ""
            results["phase_progress"] = phase_progress

            # Market signals for display
            results["market_signals"] = {
                "cyclical_defensive": market_signals.get("cyclical_defensive", {}),
                "credit_cycle": market_signals.get("credit_cycle", {}),
                "inflation": market_signals.get("inflation_expectations", {}),
                "growth_value": market_signals.get("growth_value", {}),
                "breadth": market_signals.get("market_breadth", {}),
                "india_vix": india_vix,
                "rotation": market_signals.get("sector_momentum", {}),
                "cycle_score": cycle["score"],
            }

            results["leading_signals"] = {
                name: {
                    "name": s.name,
                    "direction": s.direction,
                    "confidence": s.confidence,
                    "value": s.value,
                }
                for name, s in signals.items()
            }

            # Phase history from cyclical/defensive ratio
            if not phase_df.empty:
                results["phase_history"] = [
                    {"date": str(idx.date()), "phase": row.get("phase", "expansion")}
                    for idx, row in phase_df.iterrows()
                ]

            # Cycle gauge — only regimes the detector actually produces
            results["cycle_gauge"] = {
                "phases": ["Early Exp", "Late Exp", "Contraction"],
                "current_phase": sub_phase,
                "progress_pct": round(phase_progress * 100),
                "note": "Derived from sector relative prices (not official GDP dating).",
            }

            # Market story — honest framing: price-derived tactical tilt, not GDP dating
            consensus = signal_analyzer.get_consensus_score() if signals else 0.0
            risk = "low" if consensus > 0.3 else "elevated" if consensus > -0.1 else "high"
            risk_label = "Low risk" if risk == "low" else "Some caution" if risk == "elevated" else "Be careful"

            if phase_progress > 0.85:
                risk_label = "Late in this price regime — be selective"
                risk = "high"

            breadth = market_signals.get("market_breadth", {}).get("signal", "")
            tilt = {
                "early_expansion": "cyclical tilt (banks, autos, realty)",
                "late_expansion": "mid/late tilt (energy, metals, IT)",
                "contraction": "defensive tilt (pharma, FMCG, IT)",
            }.get(sub_phase, "mixed tilt")
            story = (
                f"Price-regime read: {sub_phase.replace('_', ' ')} "
                f"(sector-relative, not official GDP dating). "
                f"Breadth: {breadth}. {risk_label}. Book tilt: {tilt}. "
                f"Recommendations use enter/exit bands so the list stays sticky."
            )

            results["market_story"] = story
            results["risk_level"] = risk
            results["risk_label"] = risk_label
            results["methodology_note"] = (
                "Cycle labels come from Nifty sector relative performance plus "
                "macro proxies. Sticky recommend bands reduce weekly churn; "
                "hold-until dates are review deadlines, not automatic sells."
            )

            sub_phase_sectors = regime_detector.get_sub_phase_sector_map()

            if sector_data and regime_probs is not None and not regime_probs.empty:
                perf = sector_analyzer.analyze_all_sectors(sector_data, regime_probs)
                all_metrics: List[Dict] = []
                for sector_metrics in perf.values():
                    for m in sector_metrics:
                        all_metrics.append(m.dict())
                results["sector_performance"] = all_metrics

                momentum = compute_recent_momentum(sector_data)

                job["step"] = "Scoring sectors..."
                job["progress"] = 0.75
                summary: List[Dict] = []
                recommendations: List[str] = []
                exit_watch: List[Dict] = []

                from backend.decision.recommend import is_sticky_recommended, prev_scores_for_sector
                from backend.decision.thresholds import SCRAPE_MIN, rating_for_score

                sub_phase_fits = {
                    "early_expansion": float(cycle.get("early_fit") or 0),
                    "late_expansion": float(cycle.get("late_fit") or 0),
                    "contraction": float(cycle.get("contraction_fit") or 0),
                }

                for sector_key in sector_data:
                    exp_metrics = [m for m in all_metrics if m["sector"] == sector_key and m["regime"] == "expansion"]
                    con_metrics = [m for m in all_metrics if m["sector"] == sector_key and m["regime"] == "contraction"]
                    avg_expansion = exp_metrics[0]["mean_return"] / 100 if exp_metrics else 0.0
                    avg_contraction = con_metrics[0]["mean_return"] / 100 if con_metrics else 0.0
                    recent = momentum.get(sector_key, 0.0) / 100

                    signal_bias = signal_analyzer.get_sector_bias(sector_key) if signals else 0.0

                    all_sector_metrics = [
                        SectorPerformanceMetrics(**m) for m in all_metrics if m["sector"] == sector_key
                    ]
                    current_regime_str = current_phase if current_phase in ("expansion", "contraction") else "expansion"

                    score_result = compute_composite_score(
                        sector_key, all_sector_metrics, current_regime_str,
                        momentum.get(sector_key, 0.0), signal_bias,
                        sub_phase_sectors, sub_phase,
                        sub_phase_fits=sub_phase_fits,
                    )

                    is_sub_phase_fit = sector_key in sub_phase_sectors.get(sub_phase, [])
                    exit_signals = compute_exit_signals(
                        sector_key, sector_data.get(sector_key, pd.DataFrame()),
                        all_sector_metrics, current_regime_str, phase_progress,
                        {k: v for k, v in signals.items()},
                        recent_momentum=momentum.get(sector_key, 0.0),
                        composite_score=score_result["score"],
                        sub_phase_fit=is_sub_phase_fit,
                    )

                    prev_scores, was_rec = prev_scores_for_sector(
                        sector_history_maps, sector_key, limit=3
                    )
                    rating = rating_for_score(score_result["score"])
                    is_recommended = is_sticky_recommended(
                        float(score_result["score"]),
                        rating=rating,
                        prev_scores=prev_scores,
                        was_recommended=was_rec,
                    )
                    scrape_eligible = (
                        score_result["score"] >= SCRAPE_MIN or is_recommended
                    )

                    reasons = []
                    if signal_bias > 0.05:
                        reasons.append("macro bias supportive")
                    elif signal_bias < -0.05:
                        reasons.append("pressured by macro")
                    if recent > 0.05:
                        reasons.append("rising now")
                    elif recent < -0.03:
                        reasons.append("pulled back recently")
                    sfit = sub_phase.split("_")[0] + "-cycle" if sector_key in sub_phase_sectors.get(sub_phase, []) else ""
                    if sfit:
                        reasons.append("good for current price regime")
                    if avg_expansion > 0.025:
                        reasons.append("grows well in expansions")
                    why = ", ".join(reasons[:3]) if reasons else "no clear signal"

                    summary.append({
                        "sector": sector_key,
                        "rating": rating,
                        "why": why,
                        "score": int(score_result["score"]),
                        "avg_expansion": avg_expansion,
                        "avg_contraction": avg_contraction,
                        "recent": recent,
                        "recommended": is_recommended,
                        "scrape_eligible": scrape_eligible,
                        "hold_for": exit_signals["hold_for"],
                        "exit_trigger": exit_signals["exit_trigger"],
                        "stop_loss_pct": exit_signals["stop_loss_pct"],
                        "prev_score": prev_scores[0] if prev_scores else None,
                        "sticky": bool(was_rec and is_recommended),
                    })

                    if is_recommended:
                        recommendations.append(sector_key)

                    if is_recommended and (exit_signals["stop_loss_pct"] > 0 or exit_signals["exit_trigger"]):
                        exit_watch.append({
                            "sector": sector_key,
                            "hold_for": exit_signals["hold_for"],
                            "exit_trigger": exit_signals["exit_trigger"],
                            "stop_loss_pct": exit_signals["stop_loss_pct"],
                        })

                summary.sort(key=lambda x: (x["recommended"], x["score"]), reverse=True)
                results["summary"] = summary
                results["recommendations"] = recommendations
                results["exit_watch"] = exit_watch

                results["top_sectors"] = []
                rec_summary = [x for x in summary if x["recommended"]]
                for s in rec_summary[:5]:
                    results["top_sectors"].append({
                        "sector": s["sector"],
                        "final_weight": round(1.0 / max(len(rec_summary), 1), 3),
                        "mean_return": s["avg_expansion"] * 100 if current_phase == "expansion" else s["avg_contraction"] * 100,
                        "score": s["score"],
                    })

                investments: List[Dict] = []
                total_score = sum(s["score"] for s in rec_summary) if rec_summary else 1
                for s in rec_summary[:8]:
                    investments.append({"sector": s["sector"], "pct": round(s["score"] / total_score, 3)})
                results["investments"] = investments

                # Sector phase matrix — only regimes that exist in detector (expansion/contraction)
                def _cell_color(val):
                    if val is None or val == 0:
                        return "transparent"
                    intensity = min(max(abs(val) / 5.0, 0.08), 0.75)
                    if val > 0:
                        return "rgba(34,197,94,%.2f)" % intensity
                    return "rgba(239,68,68,%.2f)" % intensity

                sector_matrix: Dict[str, Dict] = {}
                for sector_key in sector_data:
                    sector_matrix[sector_key] = {}
                    for regime in ["expansion", "contraction"]:
                        matches = [m for m in all_metrics if m["sector"] == sector_key and m["regime"] == regime]
                        val = matches[0]["mean_return"] if matches else 0.0
                        sector_matrix[sector_key][regime] = {"return": val, "color": _cell_color(val)}
                results["sector_matrix"] = sector_matrix
                results["matrix_phases"] = ["expansion", "contraction"]
                results["matrix_labels"] = {"expansion": "Expansion", "contraction": "Contraction"}

            job["step"] = "Finding fund picks..."
            job["progress"] = 0.92
            try:
                from kiteconnect import KiteConnect
                raw_kite = KiteConnect(api_key=API_KEY)
                raw_kite.set_access_token(_access_token)
                mf = MFClient(cache=cache, kite=raw_kite)
                rec = FundRecommender(kite=kite, mf_client=mf)
                scrape_sectors = [
                    x["sector"]
                    for x in summary
                    if x.get("scrape_eligible") or x.get("recommended")
                ]
                results["fund_picks"] = rec.get_picks(
                    scrape_sectors if scrape_sectors else list(sector_data.keys())[:5]
                )
            except Exception as e:
                logger.warning(f"Fund picks skipped: {e}")
                results["fund_picks"] = {}

            _pipeline_results = results
            _last_run = datetime.now().strftime("%b %d, %Y %H:%M")
            results["_last_run"] = _last_run
            cache.set("pipeline_results", results, ttl_hours=24 * 7, source="pipeline")


            try:
                with SessionLocal() as db:
                    persist_run_from_pipeline(db, results)
            except Exception as persist_exc:
                logger.warning("Failed to persist analysis run: %s", persist_exc)

            job["done"] = True
            job["step"] = "Complete"
            job["progress"] = 1.0

        except Exception as e:
            logger.exception("Pipeline failed")
            _jobs[job_id]["done"] = True
            _jobs[job_id]["error"] = str(e)
            _jobs[job_id]["step"] = "Failed"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {"job_id": job_id}


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        kite_connected=_is_kite_connected(),
        last_data_refresh=_parse_last_run(_last_run),
    )




def run():
    import uvicorn

    uvicorn.run("backend.api.server:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
