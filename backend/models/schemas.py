from datetime import date, datetime
from typing import List, Optional, Literal

from pydantic import BaseModel, Field


class RegimeProbabilities(BaseModel):
    record_date: date
    recovery: float = Field(ge=0, le=1)
    expansion: float = Field(ge=0, le=1)
    contraction: float = Field(ge=0, le=1)
    trough: float = Field(ge=0, le=1)

    @property
    def dominant_regime(self) -> str:
        regimes = {
            "recovery": self.recovery,
            "expansion": self.expansion,
            "contraction": self.contraction,
            "trough": self.trough,
        }
        return max(regimes, key=regimes.get)  # type: ignore[arg-type]


class SectorPerformanceMetrics(BaseModel):
    sector: str
    regime: str
    mean_return: float
    std_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    win_rate: float
    beta_to_nifty: Optional[float] = None
    num_quarters: int


class LeadingSignal(BaseModel):
    name: str
    value: float
    direction: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0, le=1)
    lead_months: int


class SectorAllocation(BaseModel):
    sector: str
    strategic_weight: float
    tactical_weight: float
    risk_adjusted_weight: float
    final_weight: float


class PortfolioAllocation(BaseModel):
    effective_date: date = Field(default_factory=date.today)
    allocations: List[SectorAllocation]
    cash_weight: float = 0.0
    regime_probabilities: Optional[RegimeProbabilities] = None


class TokenResponse(BaseModel):
    access_token: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    kite_connected: bool = False
    last_data_refresh: Optional[datetime] = None


class BacktestResult(BaseModel):
    strategy_cagr: float
    strategy_sharpe: float
    strategy_max_drawdown: float
    benchmark_cagr: float
    benchmark_sharpe: float
    benchmark_max_drawdown: float
    alpha: float
    win_rate: float
    num_rebalances: int


class SectorRecommendation(BaseModel):
    sector: str
    score: float = Field(ge=0, le=100)
    avg_expansion: float
    avg_contraction: float
    recent_momentum: float
    recommended: bool
    hold_for: str = ""
    exit_trigger: str = ""
    stop_loss_pct: float = 0.0
    weight_pct: float = 0.0
    fund_etf: str = ""
    fund_mf: str = ""
    fund_nav: float = 0.0
    sub_phase_fit: str = ""
    signal_bias: float = 0.0
