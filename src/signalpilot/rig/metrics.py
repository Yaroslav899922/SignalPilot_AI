"""Turn closed trades into the metrics the spec + reviews ask for.

Main metric: net expectancy in R. For the *decision* we look at the difference
pullback - baseline with a CI (trade-level and monthly-block, because BTC/ETH/SOL
move together and i.i.d. trade resampling understates the error bar).
"""

from __future__ import annotations

import collections

import numpy as np

RESOLVED = ("target", "stop", "timeout")


def _safe_mean(values):
    return float(np.mean(values)) if len(values) else 0.0


def summarize(trades, plans_created=0, plans_blocked=0, pending_expired=0, missed_move=0,
              n_boot=5000, seed=0):
    resolved = [t for t in trades if t.outcome in RESOLVED]
    n = len(resolved)
    out = {
        "plans_created": plans_created,
        "plans_blocked": plans_blocked,
        "trades_filled": len(trades),
        "trades_resolved": n,
        "fill_rate": (len(trades) / plans_created) if plans_created else 0.0,
        "pending_expired": pending_expired,
        "missed_move": missed_move,
        "missed_move_rate": (missed_move / pending_expired) if pending_expired else 0.0,
    }
    if n == 0:
        out.update({k: 0.0 for k in (
            "win_rate", "avg_win_R", "avg_loss_R", "expectancy_R", "profit_factor",
            "tp_rate", "stop_rate", "timeout_rate", "avg_hold_bars", "net_after_fees",
            "zone_pierce_rate", "ci_low", "ci_high")})
        return out

    net = np.array([t.net_R for t in resolved], dtype=float)
    wins = net[net > 0]
    losses = net[net <= 0]
    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())
    lo, hi = bootstrap_ci(net, n_boot=n_boot, seed=seed)
    out.update({
        "win_rate": len(wins) / n,
        "avg_win_R": _safe_mean(wins),
        "avg_loss_R": _safe_mean(losses),
        "expectancy_R": float(net.mean()),
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "tp_rate": sum(t.outcome == "target" for t in resolved) / n,
        "stop_rate": sum(t.outcome == "stop" for t in resolved) / n,
        "timeout_rate": sum(t.outcome == "timeout" for t in resolved) / n,
        "avg_hold_bars": _safe_mean([t.hold_bars_4h for t in resolved]),
        "net_after_fees": float(net.sum()),
        "zone_pierce_rate": sum(t.zone_pierce for t in resolved) / n,
        "ci_low": lo, "ci_high": hi,
    })
    return out


def bootstrap_ci(net, n_boot=5000, seed=0, alpha=0.05):
    net = np.asarray(net, dtype=float)
    if len(net) < 2:
        return (float(net.mean()) if len(net) else 0.0,) * 2
    rng = np.random.default_rng(seed)
    means = rng.choice(net, size=(n_boot, len(net)), replace=True).mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def difference_ci(trades_a, trades_b, n_boot=5000, seed=0, alpha=0.05):
    """CI for mean(net_R of A) - mean(net_R of B), trade-level and monthly-block."""
    a = [(t.net_R, t.month) for t in trades_a if t.outcome in RESOLVED]
    b = [(t.net_R, t.month) for t in trades_b if t.outcome in RESOLVED]
    zero = {"point": 0.0, "trade_ci": (0.0, 0.0), "month_ci": (0.0, 0.0), "n_a": len(a), "n_b": len(b)}
    if not a or not b:
        return zero
    na = np.array([x[0] for x in a]); nb = np.array([x[0] for x in b])
    point = float(na.mean() - nb.mean())
    rng = np.random.default_rng(seed)
    trade = [rng.choice(na, len(na), True).mean() - rng.choice(nb, len(nb), True).mean()
             for _ in range(n_boot)]

    ma, mb = collections.defaultdict(list), collections.defaultdict(list)
    for v, m in a:
        ma[m].append(v)
    for v, m in b:
        mb[m].append(v)
    months = sorted(set(ma) | set(mb))
    month = []
    for _ in range(n_boot):
        samp = rng.choice(months, len(months), True)
        va = [v for m in samp for v in ma.get(m, [])]
        vb = [v for m in samp for v in mb.get(m, [])]
        if va and vb:
            month.append(np.mean(va) - np.mean(vb))

    def ci(arr):
        return (float(np.quantile(arr, alpha / 2)), float(np.quantile(arr, 1 - alpha / 2)))
    return {"point": point, "trade_ci": ci(trade),
            "month_ci": ci(month) if month else (0.0, 0.0), "n_a": len(na), "n_b": len(nb)}


def by_age(trades, max_bucket=3):
    """Expectancy split by how many 4h-bars after creation the fill happened."""
    resolved = [t for t in trades if t.outcome in RESOLVED]
    rows = []
    for k in range(max_bucket + 1):
        sel = [t.net_R for t in resolved if int(t.fill_age_4h) == k]
        rows.append({"age": str(k), "trades": len(sel), "expectancy_R": _safe_mean(sel)})
    sel = [t.net_R for t in resolved if int(t.fill_age_4h) > max_bucket]
    rows.append({"age": f">{max_bucket}", "trades": len(sel), "expectancy_R": _safe_mean(sel)})
    return rows


def by_symbol(trades):
    resolved = [t for t in trades if t.outcome in RESOLVED]
    rows = []
    for s in sorted({t.symbol for t in resolved}):
        net = [t.net_R for t in resolved if t.symbol == s]
        rows.append({"symbol": s, "trades": len(net), "expectancy_R": _safe_mean(net)})
    return rows
