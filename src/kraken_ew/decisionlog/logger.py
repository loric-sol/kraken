"""Decision logging: writes a structured JSON record + a human-readable
markdown summary for every signal/trade, answering "why was this taken?"
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from kraken_ew.config import PROJECT_ROOT
from kraken_ew.scoring.composite import ScoreBreakdown

DEFAULT_LOG_DIR = PROJECT_ROOT / "logs" / "decisions"


def _format_markdown(pair: str, breakdown: ScoreBreakdown, action: str, risk_params: dict, ts: datetime) -> str:
    lines = [
        f"# Decision: {action.upper()} {pair}",
        f"_Generated {ts.isoformat()}_",
        "",
        f"**Composite score:** {breakdown.total:.1f} / 100",
        f"**Direction:** {breakdown.direction}",
        "",
        "## Score breakdown",
        "",
        "| Component | Raw (0-100) | Weighted |",
        "|---|---|---|",
    ]
    for component, raw in breakdown.components.items():
        weighted = breakdown.weighted[component]
        lines.append(f"| {component} | {raw:.1f} | {weighted:.2f} |")

    lines += [
        "",
        "## Wave count",
        f"- Label: `{breakdown.metadata.get('wave_label')}`",
        f"- Position: `{breakdown.metadata.get('wave_position')}`",
        f"- Rule violations: {breakdown.metadata.get('wave_rule_violations') or 'none'}",
        f"- Pivots used: {breakdown.metadata.get('num_pivots')}",
        "",
        "## Market context",
        f"- Pair: {breakdown.metadata.get('pair')}",
        f"- Latest close: {breakdown.metadata.get('latest_close')}",
        "",
        "## Risk parameters",
    ]
    for k, v in risk_params.items():
        lines.append(f"- {k}: {v}")

    return "\n".join(lines) + "\n"


def log_decision(pair: str, breakdown: ScoreBreakdown, action: str, risk_params: dict, out_dir: Path | None = None) -> Path:
    """Write `<ts>_<pair>_<action>.json` and `.md` decision records.

    Returns the path to the JSON file.
    """
    out_dir = out_dir or DEFAULT_LOG_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}_{pair}_{action}"

    record = {
        "timestamp": ts.isoformat(),
        "pair": pair,
        "action": action,
        "breakdown": asdict(breakdown),
        "risk_params": risk_params,
    }

    json_path = out_dir / f"{base}.json"
    json_path.write_text(json.dumps(record, indent=2, default=str))

    md_path = out_dir / f"{base}.md"
    md_path.write_text(_format_markdown(pair, breakdown, action, risk_params, ts))

    return json_path
