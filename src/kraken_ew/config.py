"""Loads YAML configs from the project's config/ directory into dataclasses."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


def load_dotenv(path: Path | str = PROJECT_ROOT / ".env") -> None:
    """Minimal .env loader: populate os.environ from KEY=VALUE lines without
    overriding variables already set in the environment. No external dep.
    Called on import so MASSIVE_API_KEY etc. are available to standalone
    scripts, the CLI, and scheduled tasks."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# Load .env once at import time.
load_dotenv()


@dataclass
class PairConfig:
    market_symbol: str
    kraken_pair: str


@dataclass
class PairsConfig:
    default_interval: int
    pairs: dict[str, PairConfig]

    def kraken_pair(self, market_symbol: str) -> str:
        return self.pairs[market_symbol].kraken_pair


@dataclass
class ScoringConfig:
    weights: dict[str, float]
    pivots: dict
    fibonacci: dict
    indicators: dict


@dataclass
class RiskConfig:
    position_sizing: dict
    stop_loss: dict
    take_profit: dict
    score_thresholds: dict
    circuit_breakers: dict


@dataclass
class AppConfig:
    pairs: PairsConfig
    scoring: ScoringConfig
    risk: RiskConfig


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    with open(path) as f:
        return yaml.safe_load(f)


def load_pairs_config() -> PairsConfig:
    raw = _load_yaml("pairs.yaml")
    pairs = {
        symbol: PairConfig(market_symbol=symbol, kraken_pair=data["kraken_pair"])
        for symbol, data in raw["pairs"].items()
    }
    return PairsConfig(default_interval=raw["default_interval"], pairs=pairs)


def load_scoring_config() -> ScoringConfig:
    raw = _load_yaml("scoring_weights.yaml")
    weights = raw["weights"]
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"scoring weights must sum to 1.0, got {total}")
    return ScoringConfig(
        weights=weights,
        pivots=raw["pivots"],
        fibonacci=raw["fibonacci"],
        indicators=raw["indicators"],
    )


def load_risk_config() -> RiskConfig:
    raw = _load_yaml("risk.yaml")
    return RiskConfig(
        position_sizing=raw["position_sizing"],
        stop_loss=raw["stop_loss"],
        take_profit=raw["take_profit"],
        score_thresholds=raw["score_thresholds"],
        circuit_breakers=raw["circuit_breakers"],
    )


def load_config() -> AppConfig:
    return AppConfig(
        pairs=load_pairs_config(),
        scoring=load_scoring_config(),
        risk=load_risk_config(),
    )
