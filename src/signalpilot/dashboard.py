from __future__ import annotations

from pathlib import Path

import pandas as pd

from signalpilot.journal import load_signal_rows


DEFAULT_JOURNAL_PATH = "data/signals.sqlite3"


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="SignalPilot Journal", layout="wide")
    st.title("SignalPilot Journal")

    journal_path = st.sidebar.text_input("Journal path", DEFAULT_JOURNAL_PATH)
    row_limit = st.sidebar.number_input("Rows", min_value=50, max_value=5000, value=500, step=50)

    rows = load_signal_rows(Path(journal_path), limit=int(row_limit))
    if not rows:
        st.info("No signals found.")
        return

    frame = pd.DataFrame(rows)
    filtered = _apply_filters(st, frame)

    _render_metrics(st, filtered)
    _render_latest_signal(st, filtered)
    _render_outcome_chart(st, filtered)
    _render_table(st, filtered)


def _apply_filters(st, frame: pd.DataFrame) -> pd.DataFrame:
    symbols = _options(frame, "symbol")
    directions = _options(frame, "direction")
    outcomes = _options(frame.fillna({"outcome": "pending"}), "outcome")

    selected_symbols = st.sidebar.multiselect("Symbols", symbols, default=symbols)
    selected_directions = st.sidebar.multiselect("Directions", directions, default=directions)
    selected_outcomes = st.sidebar.multiselect("Outcomes", outcomes, default=outcomes)

    filtered = frame.copy()
    filtered["outcome"] = filtered["outcome"].fillna("pending")
    return filtered[
        filtered["symbol"].isin(selected_symbols)
        & filtered["direction"].isin(selected_directions)
        & filtered["outcome"].isin(selected_outcomes)
    ]


def _render_metrics(st, frame: pd.DataFrame) -> None:
    total = len(frame)
    directional = int(frame["direction"].isin(["LONG", "SHORT"]).sum()) if total else 0
    no_trade = int((frame["direction"] == "NO TRADE").sum()) if total else 0
    resolved = frame[frame["outcome"].isin(["target_hit", "stop_hit"])] if total else frame
    wins = int((resolved["outcome"] == "target_hit").sum()) if len(resolved) else 0
    win_rate = wins / len(resolved) if len(resolved) else None

    columns = st.columns(4)
    columns[0].metric("Signals", total)
    columns[1].metric("Directional", directional)
    columns[2].metric("NO TRADE", no_trade)
    columns[3].metric("Win rate", "-" if win_rate is None else f"{win_rate:.1%}")


def _render_latest_signal(st, frame: pd.DataFrame) -> None:
    if frame.empty:
        st.warning("No rows match the selected filters.")
        return

    latest = frame.iloc[0]
    st.subheader("Latest Signal")
    columns = st.columns(4)
    columns[0].metric("Symbol", latest["symbol"])
    columns[1].metric("Direction", latest["direction"])
    columns[2].metric("Confidence", latest["confidence"])
    columns[3].metric("Risk/reward", _format_risk_reward(latest["risk_reward"]))

    st.write(
        {
            "created_at": latest["created_at"],
            "interval": latest["interval"],
            "regime": latest["market_regime"],
            "entry_zone": latest["entry_zone"] or "-",
            "stop": latest["stop"],
            "targets": _format_targets(latest["targets"]),
            "outcome": latest["outcome"],
            "invalidation": latest["invalidation"],
        }
    )
    st.markdown("\n".join(f"- {reason}" for reason in latest["reasons"]))


def _render_outcome_chart(st, frame: pd.DataFrame) -> None:
    if frame.empty:
        return

    counts = frame["outcome"].value_counts().rename_axis("outcome").reset_index(name="signals")
    st.subheader("Outcomes")
    st.bar_chart(counts, x="outcome", y="signals")


def _render_table(st, frame: pd.DataFrame) -> None:
    table = frame.copy()
    table["targets"] = table["targets"].map(_format_targets)
    table["reasons"] = table["reasons"].map(lambda values: " | ".join(values[:3]))
    st.subheader("Journal")
    st.dataframe(
        table[
            [
                "created_at",
                "symbol",
                "interval",
                "direction",
                "market_regime",
                "close_price",
                "entry_zone",
                "stop",
                "targets",
                "risk_reward",
                "confidence",
                "outcome",
                "reasons",
            ]
        ],
        hide_index=True,
        width="stretch",
    )


def _options(frame: pd.DataFrame, column: str) -> list[str]:
    return sorted(str(value) for value in frame[column].dropna().unique())


def _format_targets(targets: list[float]) -> str:
    return " / ".join(f"{target:.2f}" for target in targets) if targets else "-"


def _format_risk_reward(value: float | None) -> str:
    return "-" if value is None or pd.isna(value) else f"1:{value:.1f}"


if __name__ == "__main__":
    main()
