import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

st.set_page_config(page_title="Allocato", layout="wide")

# =========================
# Branding / Header
# =========================
st.markdown(
    """
    <style>
    .hero-box {
        background: linear-gradient(135deg, #0f172a 0%, #111827 45%, #1f2937 100%);
        padding: 1.4rem 1.6rem;
        border-radius: 18px;
        color: white;
        margin-bottom: 1rem;
        border: 1px solid rgba(255,255,255,0.08);
    }
    .hero-title {
        font-size: 2.0rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
        letter-spacing: -0.02em;
    }
    .hero-sub {
        font-size: 1.05rem;
        opacity: 0.95;
        margin-bottom: 0.8rem;
        line-height: 1.45;
    }
    .hero-badge {
        display: inline-block;
        background: rgba(255,255,255,0.12);
        padding: 0.35rem 0.7rem;
        border-radius: 999px;
        font-size: 0.85rem;
        margin-right: 0.4rem;
        margin-bottom: 0.4rem;
    }
    .story-box {
        background: #f8fafc;
        border: 1px solid #e5e7eb;
        padding: 1rem 1.1rem;
        border-radius: 16px;
        margin-top: 0.8rem;
        margin-bottom: 0.8rem;
    }
    .small-note {
        color: #4b5563;
        font-size: 0.95rem;
        line-height: 1.45;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown(
    """
    <div class="hero-box">
        <div class="hero-title">🚀 Allocato</div>
        <div class="hero-sub">
            Dein smarter Portfolio-Manager für Direktaktien.
            Nicht blind kaufen. Nicht unnötig Gebühren zahlen.
            Nicht darauf hoffen, dass irgendein Produkt schon irgendwie passt.
            <br><br>
            Allocato hilft dir, ein dynamisch gesteuertes Portfolio aufzubauen,
            in dem du <b>Kontrolle, Transparenz und Dividenden direkt selbst</b> behältst.
        </div>
        <span class="hero-badge">Dynamic Allocation</span>
        <span class="hero-badge">Direct Equity Ownership</span>
        <span class="hero-badge">Buy & Hold Benchmark</span>
        <span class="hero-badge">Launch Version 5.0.1</span>
    </div>
    """,
    unsafe_allow_html=True
)

st.markdown(
    """
    <div class="story-box">
        <b>Warum Allocato?</b><br>
        Viele Menschen stecken ihr Geld in Produkte, deren Regeln sie kaum kennen,
        zahlen laufende Gebühren und geben die Steuerung komplett aus der Hand.
        Allocato geht den anderen Weg:
        <br><br>
        <b>Du definierst den Anlagekorb. Die Engine übernimmt die Logik.</b><br>
        Sie bewertet Momentum, Trend und Risiko, gewichtet die stärksten Titel neu
        und versucht, Kapital intelligent statt passiv zu allokieren.
        <br><br>
        <span class="small-note">
        Allocato ist kein Versprechen auf sichere Gewinne. Es ist ein Werkzeug für Anleger,
        die bewusstere Entscheidungen treffen wollen — mit mehr Eigentum, mehr Transparenz
        und weniger Abhängigkeit von Standardlösungen.
        </span>
    </div>
    """,
    unsafe_allow_html=True
)

# =========================
# Defaults / Session State
# =========================
defaults = {
    "initial_capital": 10000,
    "monthly_savings": 500,
    "period": "5y",
    "rebalance_freq": "Monatlich",
    "fee_pct_input": 0.10,
    "min_score": 0.00,
    "max_weight_pct": 55,
    "vol_penalty": 0.08,
    "cash_interest_pct": 0.00,
    "use_regime_filter": False,
    "show_debug": False,
    "conviction_power": 2.0,
    "soft_cash_mode": True,
    "target_cash_floor_pct": 5,
    "target_cash_ceiling_pct": 15,
    "soft_cash_invest_ratio_pct": 85,
    "weight_chart_top_n": 8,
    "top_n": 4,
    "assets_input": "AAPL\nSAP.DE\nSIE.DE\nALV.DE\nMUV2.DE\nJNJ\nPG",
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =========================
# Helper
# =========================
def load_close_prices(tickers, period):
    series_map = {}
    skipped = []

    for t in tickers:
        try:
            raw = yf.download(t, period=period, progress=False, auto_adjust=False)
        except Exception:
            raw = pd.DataFrame()

        if raw.empty:
            skipped.append(t)
            continue

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        if "Close" not in raw.columns:
            skipped.append(t)
            continue

        s = pd.to_numeric(raw["Close"], errors="coerce").dropna().copy()
        if s.empty:
            skipped.append(t)
            continue

        s.name = t
        series_map[t] = s

    return series_map, skipped


def align_price_series(series_map):
    if not series_map:
        return pd.DataFrame()
    return pd.concat(series_map.values(), axis=1, join="inner").dropna()


def load_single_close(ticker, period):
    try:
        raw = yf.download(ticker, period=period, progress=False, auto_adjust=False)
    except Exception:
        return pd.Series(dtype=float)

    if raw.empty:
        return pd.Series(dtype=float)

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    if "Close" not in raw.columns:
        return pd.Series(dtype=float)

    s = pd.to_numeric(raw["Close"], errors="coerce").dropna().copy()
    s.name = ticker
    return s


def compute_metrics(equity: pd.Series):
    returns = equity.pct_change().fillna(0)

    total_return = (equity.iloc[-1] / equity.iloc[0] - 1) * 100

    days = len(equity)
    years = days / 252 if days > 0 else 0
    if years > 0 and equity.iloc[0] > 0:
        cagr = ((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) * 100
    else:
        cagr = 0.0

    rolling_max = equity.cummax()
    drawdown = (equity / rolling_max - 1) * 100
    max_dd = drawdown.min()

    vol = returns.std() * np.sqrt(252) * 100
    sharpe = 0.0
    if returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)

    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "max_dd": float(max_dd),
        "volatility": float(vol),
        "sharpe": float(sharpe),
    }


def is_rebalance_day(current_date, prev_date, mode):
    if mode == "Monatlich":
        return current_date.month != prev_date.month
    if mode == "Quartalsweise":
        prev_q = (prev_date.month - 1) // 3
        curr_q = (current_date.month - 1) // 3
        return (current_date.year != prev_date.year) or (curr_q != prev_q)
    return False


def conviction_weights(score_series: pd.Series, max_weight: float, power: float) -> pd.Series:
    s = score_series.copy().astype(float)
    s = s[s > 0].copy()

    if s.empty:
        return s

    s = s ** power
    s = s / s.sum()

    final = pd.Series(0.0, index=s.index)
    remaining = 1.0
    active = s.copy()

    while len(active) > 0 and remaining > 1e-12:
        active = active / active.sum()
        proposed = active * remaining

        capped_mask = proposed >= max_weight - 1e-12
        if not capped_mask.any():
            final.loc[active.index] += proposed
            remaining = 0.0
            break

        capped_assets = proposed[capped_mask].index.tolist()
        for asset in capped_assets:
            addable = max_weight - final.loc[asset]
            if addable > 0:
                final.loc[asset] += addable
                remaining -= addable

        active = active.drop(index=capped_assets, errors="ignore")

        if remaining <= 1e-12:
            break

    if final.sum() > 0:
        final = final / final.sum()

    return final


def build_soft_cash_selection(score_today, trend_ok, top_n, min_score, invest_ratio, max_weight, power):
    eligible = score_today[(trend_ok) & (score_today > min_score)].sort_values(ascending=False)
    selected = eligible.head(top_n)

    if len(selected) > 0:
        weights = conviction_weights(selected, max_weight=max_weight, power=power)
        return selected, weights, 1.0

    fallback = score_today[trend_ok].sort_values(ascending=False).head(top_n)
    fallback = fallback[fallback > -999]

    if len(fallback) == 0:
        return pd.Series(dtype=float), pd.Series(dtype=float), 0.0

    shifted = fallback - fallback.min() + 1e-6
    weights = conviction_weights(shifted, max_weight=max_weight, power=max(1.0, power - 0.5))

    return fallback, weights, invest_ratio


def simplify_weight_chart(weights_with_cash: pd.DataFrame, top_k: int):
    cols_no_cash = [c for c in weights_with_cash.columns if c != "Cash"]
    avg_weights = weights_with_cash[cols_no_cash].mean().sort_values(ascending=False)

    keep = avg_weights.head(top_k).index.tolist()
    other = [c for c in cols_no_cash if c not in keep]

    out = pd.DataFrame(index=weights_with_cash.index)
    for c in keep:
        out[c] = weights_with_cash[c]

    if other:
        out["Sonstige"] = weights_with_cash[other].sum(axis=1)

    if "Cash" in weights_with_cash.columns:
        out["Cash"] = weights_with_cash["Cash"]

    return out


def make_export_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


# =========================
# Sidebar
# =========================
st.sidebar.header("Einstellungen")

initial_capital = st.sidebar.number_input(
    "Startkapital (€)",
    min_value=0,
    step=1000,
    key="initial_capital",
    help="Einmalige Anfangsinvestition."
)

monthly_savings = st.sidebar.number_input(
    "Monatliche Sparrate (€)",
    min_value=0,
    step=50,
    key="monthly_savings",
    help="Zusätzlicher Betrag, der bei Monatswechsel investierbar wird."
)

period = st.sidebar.selectbox(
    "Zeitraum",
    ["1y", "2y", "3y", "5y"],
    key="period",
    help="Für Momentum-Strategien sind 3 bis 5 Jahre meist am sinnvollsten."
)

rebalance_freq = st.sidebar.selectbox(
    "Rebalancing",
    ["Monatlich", "Quartalsweise"],
    key="rebalance_freq",
    help="Wie oft das Portfolio neu bewertet und angepasst wird."
)

fee_pct_input = st.sidebar.number_input(
    "Transaktionskosten pro Trade (%)",
    min_value=0.0,
    step=0.01,
    format="%.2f",
    key="fee_pct_input",
    help="Gebühren und Slippage pro Umschichtung."
)
fee_pct = fee_pct_input / 100.0

min_score = st.sidebar.number_input(
    "Mindest-Score für Kauf",
    step=0.01,
    format="%.2f",
    key="min_score",
    help="Nur Assets mit Score über diesem Wert dürfen gekauft werden."
)

max_weight_pct = st.sidebar.number_input(
    "Max. Gewicht pro Asset (%)",
    min_value=1,
    max_value=100,
    step=5,
    key="max_weight_pct",
    help="Begrenzt die maximale Positionsgröße pro Asset."
)

vol_penalty = st.sidebar.number_input(
    "Volatilitätsstrafe",
    min_value=0.0,
    step=0.01,
    format="%.2f",
    key="vol_penalty",
    help="Je höher dieser Wert, desto stärker werden schwankungsreiche Assets bestraft."
)

cash_interest_pct = st.sidebar.number_input(
    "Cash-Zins p.a. (%)",
    min_value=0.0,
    step=0.10,
    format="%.2f",
    key="cash_interest_pct",
    help="Optionaler Zins auf uninvestiertes Cash."
)

use_regime_filter = st.sidebar.checkbox(
    "Marktregime-Filter nutzen (SPY > SMA200)",
    key="use_regime_filter",
    help="Wenn aktiv, investiert der Bot nur offensiv, wenn SPY über SMA200 liegt."
)

show_debug = st.sidebar.checkbox(
    "Debug-Bereich anzeigen",
    key="show_debug",
    help="Zeigt Rohdaten und interne Details an."
)

st.sidebar.subheader("Aggressiv-Modus")

conviction_power = st.sidebar.slider(
    "Conviction-Stärke",
    min_value=1.0,
    max_value=4.0,
    step=0.1,
    key="conviction_power",
    help="Je höher, desto stärker werden die besten Assets bevorzugt."
)

soft_cash_mode = st.sidebar.checkbox(
    "Soft Cash Mode nutzen",
    key="soft_cash_mode",
    help="Wenn keine klaren Signale da sind, bleibt der Bot nicht komplett in Cash."
)

target_cash_floor_pct = st.sidebar.slider(
    "Ziel-Cash-Untergrenze (%)",
    min_value=0,
    max_value=20,
    step=1,
    key="target_cash_floor_pct",
    help="Der Bot versucht, im Normalfall mindestens so viel Cash zu halten."
)

target_cash_ceiling_pct = st.sidebar.slider(
    "Ziel-Cash-Obergrenze (%)",
    min_value=5,
    max_value=30,
    step=1,
    key="target_cash_ceiling_pct",
    help="Der Bot versucht, im Normalfall nicht deutlich mehr Cash zu halten."
)

soft_cash_invest_ratio_pct = st.sidebar.slider(
    "Soft-Cash Investitionsquote (%)",
    min_value=20,
    max_value=95,
    step=5,
    key="soft_cash_invest_ratio_pct",
    help="Wenn Soft Cash Mode aktiv ist und keine starken Signale da sind, bleibt ungefähr dieser Anteil investiert."
)

st.sidebar.subheader("Visualisierung")
weight_chart_top_n = st.sidebar.slider(
    "Anzahl Assets im Gewichts-Chart",
    min_value=5,
    max_value=15,
    step=1,
    key="weight_chart_top_n",
    help="Zeigt im Gewichtungsverlauf nur die größten durchschnittlichen Positionen. Der Rest wird zu 'Sonstige' zusammengefasst."
)

st.sidebar.subheader("⚡ Empfohlene Setups")
col_a, col_b = st.sidebar.columns(2)

if col_a.button("Quality"):
    st.session_state["assets_input"] = "AAPL\nSAP.DE\nSIE.DE\nALV.DE\nMUV2.DE\nJNJ\nPG"
    st.session_state["top_n"] = 4
    st.session_state["conviction_power"] = 2.0
    st.session_state["max_weight_pct"] = 55
    st.session_state["vol_penalty"] = 0.08
    st.session_state["rebalance_freq"] = "Monatlich"
    st.session_state["min_score"] = 0.00
    st.session_state["soft_cash_mode"] = True
    st.session_state["target_cash_floor_pct"] = 5
    st.session_state["target_cash_ceiling_pct"] = 15
    st.session_state["soft_cash_invest_ratio_pct"] = 85
    st.rerun()

if col_b.button("Global"):
    st.session_state["assets_input"] = (
        "SPY\nQQQ\nVOO\nVUG\nNVDA\nMSFT\nAAPL\nGOOGL\nAMZN\nMETA\nTSLA\nAMD\nAVGO\n"
        "SAP.DE\nSIE.DE\nAIR.DE\nALV.DE\nBMW.DE\nBAS.DE\nDBK.DE\nV\nMA\nJPM\nJNJ\nPG\n"
        "KO\nPEP\nMCD\nASML\nADBE"
    )
    st.session_state["top_n"] = 5
    st.session_state["conviction_power"] = 2.5
    st.session_state["max_weight_pct"] = 55
    st.session_state["vol_penalty"] = 0.08
    st.session_state["rebalance_freq"] = "Monatlich"
    st.session_state["min_score"] = 0.00
    st.session_state["soft_cash_mode"] = True
    st.session_state["target_cash_floor_pct"] = 5
    st.session_state["target_cash_ceiling_pct"] = 15
    st.session_state["soft_cash_invest_ratio_pct"] = 85
    st.rerun()

col_c, col_d = st.sidebar.columns(2)

if col_c.button("Europa"):
    st.session_state["assets_input"] = (
        "SAP.DE\nSIE.DE\nAIR.DE\nALV.DE\nMUV2.DE\nBMW.DE\nBAS.DE\nDBK.DE\nRWE.DE\n"
        "DTE.DE\nIFX.DE\nADS.DE\nDPW.DE\nVOW3.DE\nCON.DE\nHEI.DE"
    )
    st.session_state["top_n"] = 5
    st.session_state["conviction_power"] = 2.2
    st.session_state["max_weight_pct"] = 50
    st.session_state["vol_penalty"] = 0.08
    st.session_state["rebalance_freq"] = "Monatlich"
    st.session_state["min_score"] = 0.00
    st.session_state["soft_cash_mode"] = True
    st.session_state["target_cash_floor_pct"] = 8
    st.session_state["target_cash_ceiling_pct"] = 18
    st.session_state["soft_cash_invest_ratio_pct"] = 85
    st.rerun()

if col_d.button("Dividend"):
    st.session_state["assets_input"] = (
        "JNJ\nPG\nKO\nPEP\nMCD\nMMM\nIBM\nVZ\nT\nMO\nPM\nABBV\nLLY\nMRK\nPFE\nUNH\n"
        "V\nMA\nJPM\nBAC\nGS\nMS\nC\nAXP\nSPY\nQQQ\nSAP.DE\nSIE.DE\nALV.DE\nMUV2.DE"
    )
    st.session_state["top_n"] = 6
    st.session_state["conviction_power"] = 2.0
    st.session_state["max_weight_pct"] = 50
    st.session_state["vol_penalty"] = 0.08
    st.session_state["rebalance_freq"] = "Monatlich"
    st.session_state["min_score"] = 0.00
    st.session_state["soft_cash_mode"] = True
    st.session_state["target_cash_floor_pct"] = 7
    st.session_state["target_cash_ceiling_pct"] = 15
    st.session_state["soft_cash_invest_ratio_pct"] = 85
    st.rerun()

st.sidebar.subheader("Asset-Korb")
assets_input = st.sidebar.text_area(
    "Ticker (ein pro Zeile)",
    height=180,
    key="assets_input",
    help="Der Bot wählt aus diesem Korb selbst die stärksten Assets."
)

input_tickers = [x.strip() for x in assets_input.splitlines() if x.strip()]
max_assets = max(1, len(input_tickers))

top_n = st.sidebar.slider(
    "Top-N Assets halten",
    min_value=1,
    max_value=max_assets,
    key="top_n",
    help="Wie viele der stärksten Assets gleichzeitig gehalten werden."
)

# =========================
# Erklärungen
# =========================
with st.expander("ℹ️ Was ist Allocato?"):
    st.markdown("""
Allocato ist für Anleger gedacht, die mehr Kontrolle über ihr Kapital wollen.

Nicht blind kaufen.  
Nicht dauerhaft Gebühren zahlen, ohne zu wissen, was im Produkt eigentlich passiert.  
Nicht Dividendenströme und Entscheidungen komplett auslagern.

**Die Idee hinter Allocato:**
Du definierst deinen Anlagekorb selbst.  
Die Engine bewertet Stärke, Trend und Risiko und verteilt das Kapital dynamisch auf die stärksten Titel.

Damit entsteht ein Portfolio-Manager für Direktaktien und ETFs, der versucht:
- Chancen aktiv zu nutzen
- Cash bewusst zu steuern
- Risiko kontrollierbarer zu halten
- und Entscheidungen nachvollziehbar zu machen
""")

with st.expander("🧠 Wie interpretiere ich die Kennzahlen?"):
    st.markdown("""
**Bot Endwert**  
Endwert des aktiven Portfolios.

**Buy & Hold Endwert**  
Endwert eines passiven Vergleichsportfolios mit denselben Assets.

**Outperformance**  
Differenz der Gesamtrendite in Prozentpunkten. Positiv = Bot schlägt Buy & Hold.

**Exposure**  
Wie viel Prozent des Portfolios im Durchschnitt investiert waren.

**Ø Cash-Quote**  
Durchschnittlicher Cash-Anteil.

**CAGR**  
Jährliche durchschnittliche Wachstumsrate.

**Max Drawdown**  
Größter historischer Rückgang vom Hochpunkt.

**Volatilität**  
Schwankungsintensität des Portfolios.

**Sharpe Ratio**  
Rendite im Verhältnis zur Schwankung. Höher ist meist besser.
""")

with st.expander("⚙️ Empfohlene Start-Setups"):
    st.markdown("""
**Quality / Direktaktien-Korb**
- AAPL
- SAP.DE
- SIE.DE
- ALV.DE
- MUV2.DE
- JNJ
- PG

Empfehlung:
- Top-N: 4
- Rebalancing: Monatlich
- Max Gewicht: 55
- Conviction-Stärke: 2.0
- Volatilitätsstrafe: 0.08

**Großer globaler Korb**
- ETFs, Tech, Europa, Dividenden gemischt

Empfehlung:
- Top-N: 5 bis 6
- Rebalancing: Monatlich
- Max Gewicht: 55
- Conviction-Stärke: 2.0 bis 2.5

**Europa / Deutschland**
- SAP.DE
- SIE.DE
- AIR.DE
- ALV.DE
- MUV2.DE
- BMW.DE
- RWE.DE
- DTE.DE

Empfehlung:
- Top-N: 5
- Rebalancing: Monatlich oder Quartalsweise
- Cashbereich: 8 bis 18
""")

# =========================
# Main
# =========================
if st.sidebar.button("Portfolio berechnen", type="primary"):
    with st.spinner("Berechne aggressives dynamisches Portfolio..."):
        tickers = [x.strip() for x in assets_input.splitlines() if x.strip()]

        if len(tickers) < 2:
            st.error("Bitte mindestens 2 Ticker eingeben.")
            st.stop()

        series_map, skipped_tickers = load_close_prices(tickers, period)

        for skipped in skipped_tickers:
            st.warning(f"Keine Daten für {skipped} – wird übersprungen.")

        prices = align_price_series(series_map)

        if prices.empty:
            st.error("Es konnten keine gültigen Kursdaten geladen werden.")
            st.stop()

        tickers = list(prices.columns)

        if len(tickers) < 2:
            st.error("Nach dem Laden sind weniger als 2 gültige Assets übrig.")
            st.stop()

        effective_top_n = min(top_n, len(tickers))
        max_weight = max_weight_pct / 100.0
        daily_cash_rate = (cash_interest_pct / 100.0) / 252.0
        cash_floor = target_cash_floor_pct / 100.0
        cash_ceiling = target_cash_ceiling_pct / 100.0
        soft_invest_ratio = soft_cash_invest_ratio_pct / 100.0

        sma200 = prices.rolling(200).mean()
        mom_63 = prices / prices.shift(63) - 1
        mom_126 = prices / prices.shift(126) - 1
        vol_63 = prices.pct_change().rolling(63).std() * np.sqrt(252)

        raw_score = 0.6 * mom_126 + 0.4 * mom_63 - vol_penalty * vol_63

        valid_mask = sma200.notna().all(axis=1) & raw_score.notna().all(axis=1)
        prices = prices.loc[valid_mask].copy()
        sma200 = sma200.loc[valid_mask].copy()
        raw_score = raw_score.loc[valid_mask].copy()

        if len(prices) < 30:
            st.error("Zu wenig gültige Daten nach Berechnung der Indikatoren.")
            st.stop()

        regime_ok_series = pd.Series(True, index=prices.index)
        if use_regime_filter:
            spy_close = load_single_close("SPY", period)
            if spy_close.empty:
                st.warning("SPY-Daten konnten nicht geladen werden. Regime-Filter wird deaktiviert.")
            else:
                spy_close = spy_close.reindex(prices.index).ffill()
                spy_sma200 = spy_close.rolling(200).mean()
                regime_ok_series = (spy_close > spy_sma200).fillna(False)
                regime_ok_series = regime_ok_series.loc[prices.index]

        dates = prices.index

        shares = {t: 0.0 for t in tickers}
        cash = float(initial_capital)

        equity_bot = pd.Series(index=dates, dtype=float)
        cash_bot = pd.Series(index=dates, dtype=float)
        invested_bot = pd.Series(index=dates, dtype=float)

        weight_history = pd.DataFrame(index=dates, columns=tickers, dtype=float)
        cash_weight_history = pd.Series(index=dates, dtype=float)

        selected_assets_log = {}
        target_weights_log = {}
        rebalance_log = []

        trade_count = 0

        for i, date in enumerate(dates):
            current_prices = prices.loc[date]
            prev_date = None if i == 0 else dates[i - 1]

            if daily_cash_rate > 0:
                cash *= (1 + daily_cash_rate)

            if i > 0 and date.month != prev_date.month:
                cash += monthly_savings

            do_rebalance = False
            if i == 0:
                do_rebalance = True
            elif is_rebalance_day(date, prev_date, rebalance_freq):
                do_rebalance = True

            if do_rebalance:
                regime_today_ok = bool(regime_ok_series.loc[date])
                trend_ok = current_prices > sma200.loc[date]
                score_today = raw_score.loc[date]

                total_equity_before = cash + sum(shares[t] * current_prices[t] for t in tickers)
                current_values = {t: shares[t] * current_prices[t] for t in tickers}
                target_values = {t: 0.0 for t in tickers}

                if regime_today_ok:
                    eligible = score_today[(trend_ok) & (score_today > min_score)].sort_values(ascending=False)
                    selected = eligible.head(effective_top_n)

                    if len(selected) > 0:
                        weights = conviction_weights(selected, max_weight=max_weight, power=conviction_power)

                        target_cash_ratio = cash_floor
                        if len(selected) == 1:
                            target_cash_ratio = min(cash_ceiling, max(cash_floor, 0.10))
                        elif len(selected) == 2:
                            target_cash_ratio = min(cash_ceiling, max(cash_floor, 0.08))

                        investable_capital = total_equity_before * (1 - target_cash_ratio)

                        for t in weights.index:
                            target_values[t] = investable_capital * weights[t]

                        target_weights_log[date] = {t: (target_values[t] / total_equity_before) for t in weights.index}
                        selected_assets_log[date] = selected.index.tolist()

                    else:
                        if soft_cash_mode:
                            fallback_selected, fallback_weights, invest_ratio = build_soft_cash_selection(
                                score_today=score_today,
                                trend_ok=trend_ok,
                                top_n=effective_top_n,
                                min_score=min_score,
                                invest_ratio=soft_invest_ratio,
                                max_weight=max_weight,
                                power=conviction_power
                            )

                            if len(fallback_selected) > 0:
                                investable_capital = total_equity_before * invest_ratio
                                for t in fallback_weights.index:
                                    target_values[t] = investable_capital * fallback_weights[t]

                                target_weights_log[date] = {
                                    t: (target_values[t] / total_equity_before) for t in fallback_weights.index
                                }
                                selected_assets_log[date] = fallback_selected.index.tolist()
                            else:
                                target_weights_log[date] = {}
                                selected_assets_log[date] = []
                        else:
                            target_weights_log[date] = {}
                            selected_assets_log[date] = []
                else:
                    if soft_cash_mode:
                        fallback_selected, fallback_weights, invest_ratio = build_soft_cash_selection(
                            score_today=score_today,
                            trend_ok=trend_ok,
                            top_n=effective_top_n,
                            min_score=min_score,
                            invest_ratio=max(cash_floor, 0.50),
                            max_weight=max_weight,
                            power=max(1.5, conviction_power - 0.5)
                        )

                        if len(fallback_selected) > 0:
                            investable_capital = total_equity_before * invest_ratio
                            for t in fallback_weights.index:
                                target_values[t] = investable_capital * fallback_weights[t]

                            target_weights_log[date] = {
                                t: (target_values[t] / total_equity_before) for t in fallback_weights.index
                            }
                            selected_assets_log[date] = fallback_selected.index.tolist()
                        else:
                            target_weights_log[date] = {}
                            selected_assets_log[date] = []
                    else:
                        target_weights_log[date] = {}
                        selected_assets_log[date] = []

                turnover = sum(abs(target_values[t] - current_values[t]) for t in tickers)
                fees = turnover * fee_pct
                total_equity_after_fees = max(total_equity_before - fees, 0.0)

                if total_equity_before > 0:
                    fee_adjustment = total_equity_after_fees / total_equity_before
                    for t in tickers:
                        target_values[t] *= fee_adjustment

                for t in tickers:
                    price = current_prices[t]
                    new_shares = target_values[t] / price if price > 0 else 0.0
                    if abs(new_shares - shares[t]) > 1e-12:
                        trade_count += 1
                    shares[t] = new_shares

                invested_value = sum(shares[t] * current_prices[t] for t in tickers)
                cash = total_equity_after_fees - invested_value

                rebalance_log.append({
                    "Datum": date,
                    "Regime OK": regime_today_ok,
                    "Ausgewählte Assets": ", ".join(selected_assets_log.get(date, [])) if selected_assets_log.get(date, []) else "Cash",
                    "Turnover €": float(turnover),
                    "Gebühren €": float(fees),
                    "Cash €": float(cash),
                    "Portfolio €": float(total_equity_after_fees),
                })

            invested_value = sum(shares[t] * current_prices[t] for t in tickers)
            total_value = invested_value + cash

            equity_bot.loc[date] = total_value
            cash_bot.loc[date] = cash
            invested_bot.loc[date] = invested_value

            if total_value > 0:
                for t in tickers:
                    weight_history.loc[date, t] = (shares[t] * current_prices[t]) / total_value * 100
                cash_weight_history.loc[date] = cash / total_value * 100
            else:
                for t in tickers:
                    weight_history.loc[date, t] = 0.0
                cash_weight_history.loc[date] = 0.0

        # Benchmark
        bh_shares = {t: 0.0 for t in tickers}
        equity_bh = pd.Series(index=dates, dtype=float)

        first_prices = prices.iloc[0]
        bh_weight = 1.0 / len(tickers)

        for t in tickers:
            bh_shares[t] = (initial_capital * bh_weight) / first_prices[t]

        for i, date in enumerate(dates):
            current_prices = prices.loc[date]

            if i > 0:
                prev_date = dates[i - 1]
                if date.month != prev_date.month:
                    for t in tickers:
                        bh_shares[t] += (monthly_savings * bh_weight) / current_prices[t]

            bh_value = sum(bh_shares[t] * current_prices[t] for t in tickers)
            equity_bh.loc[date] = bh_value

        bot_metrics = compute_metrics(equity_bot)
        bh_metrics = compute_metrics(equity_bh)

        exposure = (invested_bot / equity_bot.replace(0, np.nan)).mean() * 100
        avg_cash_quote = (cash_bot / equity_bot.replace(0, np.nan)).mean() * 100
        outperformance_pp = bot_metrics["total_return"] - bh_metrics["total_return"]

        last_prices = prices.iloc[-1]
        final_equity = equity_bot.iloc[-1]

        current_weights = {}
        for t in tickers:
            current_weights[t] = (shares[t] * last_prices[t] / final_equity) * 100 if final_equity > 0 else 0.0

        weights_df = pd.DataFrame({
            "Ticker": list(current_weights.keys()),
            "Aktuelles Gewicht %": list(current_weights.values())
        }).sort_values("Aktuelles Gewicht %", ascending=False)

        rebalance_df = pd.DataFrame(rebalance_log)

        weights_with_cash = weight_history.copy()
        weights_with_cash["Cash"] = cash_weight_history
        weights_with_cash = weights_with_cash.fillna(0)

        weights_chart_df = simplify_weight_chart(weights_with_cash, top_k=weight_chart_top_n)

        rebalance_dates = [entry["Datum"] for entry in rebalance_log]
        weights_rebalance_only = weights_with_cash.loc[
            weights_with_cash.index.intersection(rebalance_dates)
        ].copy()

        # Hinweise
        if outperformance_pp > 0:
            st.success("✅ Der Bot schlägt Buy & Hold in diesem Test.")
        elif outperformance_pp > -10:
            st.info("ℹ️ Der Bot liegt nahe an Buy & Hold. Für eine aktive aggressive Strategie ist das bereits ordentlich.")
        else:
            st.warning("⚠️ Der Bot liegt klar hinter Buy & Hold. Prüfe besonders Cash-Quote, Top-N, Conviction-Stärke und Rebalancing.")

        if avg_cash_quote > 15:
            st.info("💡 Die durchschnittliche Cash-Quote liegt über 15 %. Für einen aggressiven Modus könntest du Soft Cash Mode, niedrigeren Mindest-Score oder höheres Max-Gewicht testen.")
        elif avg_cash_quote < 5:
            st.info("💡 Die durchschnittliche Cash-Quote liegt unter 5 %. Das ist offensiv, kann aber Drawdowns erhöhen.")

        # Metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Bot Endwert", f"{equity_bot.iloc[-1]:,.2f} €")
        c2.metric("Buy & Hold Endwert", f"{equity_bh.iloc[-1]:,.2f} €")
        c3.metric("Outperformance", f"{outperformance_pp:.2f} pp")
        c4.metric("Trades", f"{trade_count}")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Bot Rendite", f"{bot_metrics['total_return']:.2f}%")
        c6.metric("Buy & Hold Rendite", f"{bh_metrics['total_return']:.2f}%")
        c7.metric("Exposure", f"{exposure:.1f}%")
        c8.metric("Ø Cash-Quote", f"{avg_cash_quote:.1f}%")

        c9, c10, c11, c12 = st.columns(4)
        c9.metric("Bot CAGR", f"{bot_metrics['cagr']:.2f}%")
        c10.metric("Bot Max Drawdown", f"{bot_metrics['max_dd']:.2f}%")
        c11.metric("Bot Volatilität", f"{bot_metrics['volatility']:.2f}%")
        c12.metric("Bot Sharpe", f"{bot_metrics['sharpe']:.2f}")

        st.success(f"Endkapital dynamischer Bot: {equity_bot.iloc[-1]:,.2f} €")

        # Equity Chart
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(equity_bot.index, equity_bot, label="Dynamischer Bot", linewidth=2.5, color="lime")
        ax.plot(equity_bh.index, equity_bh, label="Buy & Hold", linewidth=2, color="gray")
        ax.set_title("Dynamischer Portfolio Bot vs Buy & Hold")
        ax.legend()
        ax.grid(True)
        st.pyplot(fig)

        # Export
        st.subheader("📥 Export")

        export_equity_df = pd.DataFrame({
            "Datum": equity_bot.index,
            "Bot Portfolio": equity_bot.values,
            "Buy & Hold": equity_bh.values,
            "Cash (€)": cash_bot.values,
            "Investiert (€)": invested_bot.values
        })

        equity_csv = make_export_csv(export_equity_df)
        rebal_csv = make_export_csv(rebalance_df) if not rebalance_df.empty else b""
        weights_csv = make_export_csv(weights_with_cash.reset_index().rename(columns={"index": "Datum"}))

        col_exp1, col_exp2, col_exp3 = st.columns(3)

        col_exp1.download_button(
            label="⬇️ Equity Curve CSV",
            data=equity_csv,
            file_name="allocato_equity_curve.csv",
            mime="text/csv"
        )

        col_exp2.download_button(
            label="⬇️ Rebalancing Log CSV",
            data=rebal_csv,
            file_name="allocato_rebalancing_log.csv",
            mime="text/csv",
            disabled=rebalance_df.empty
        )

        col_exp3.download_button(
            label="⬇️ Gewichte CSV",
            data=weights_csv,
            file_name="allocato_weight_history.csv",
            mime="text/csv"
        )

        with st.expander("📌 Interpretation dieses Ergebnisses"):
            st.markdown(f"""
**Zusammenfassung dieses Testlaufs**

- **Outperformance:** {outperformance_pp:.2f} Prozentpunkte
- **Exposure:** {exposure:.1f} %
- **Ø Cash-Quote:** {avg_cash_quote:.1f} %
- **Trades:** {trade_count}
- **Conviction-Stärke:** {conviction_power:.1f}
- **Soft Cash Mode:** {"Aktiv" if soft_cash_mode else "Aus"}
- **Ziel-Cashbereich:** {target_cash_floor_pct}% bis {target_cash_ceiling_pct}%

**Interpretation**
- Höhere Conviction-Stärke konzentriert das Kapital stärker auf Gewinner.
- Eine Cash-Quote zwischen 5% und 15% ist hier das Zielbild.
- Ist die Trade-Zahl sehr hoch, kann der Bot zu nervös sein.
- Ist die Cash-Quote zu hoch, wird in starken Bullenphasen oft Rendite liegen gelassen.
- Ein geringerer Max Drawdown kann den Bot trotz geringerer Rendite strategisch interessant machen.
""")

        st.subheader("Aktuelle Portfolio-Gewichte")
        st.dataframe(weights_df.round(2), use_container_width=True)

        st.subheader("Gewichtungsverlauf im Portfolio (%)")
        chart_cols = list(weights_chart_df.columns)
        base_colors = list(plt.cm.tab20.colors)
        colors = []

        normal_idx = 0
        for col in chart_cols:
            if col == "Cash":
                colors.append((0.55, 0.55, 0.55))
            elif col == "Sonstige":
                colors.append((0.82, 0.82, 0.82))
            else:
                colors.append(base_colors[normal_idx % len(base_colors)])
                normal_idx += 1

        fig2, ax2 = plt.subplots(figsize=(12, 6))
        ax2.stackplot(
            weights_chart_df.index,
            *[weights_chart_df[col] for col in chart_cols],
            labels=chart_cols,
            colors=colors
        )
        ax2.set_title("Portfolio-Gewichte über die Zeit")
        ax2.set_ylabel("Gewicht in %")
        ax2.set_ylim(0, 100)
        ax2.legend(loc="upper left", bbox_to_anchor=(1.01, 1))
        ax2.grid(True, alpha=0.3)
        st.pyplot(fig2)

        with st.expander("🎯 Zuletzt ausgewählte Top-Assets"):
            if selected_assets_log:
                last_selection_date = max(selected_assets_log.keys())
                st.write(f"Letzte Auswahl am {last_selection_date.date()}:")
                st.write(selected_assets_log[last_selection_date])

                st.write("Letzte Zielgewichte:")
                last_weights = target_weights_log.get(last_selection_date, {})
                if last_weights:
                    last_weights_df = pd.DataFrame({
                        "Ticker": list(last_weights.keys()),
                        "Zielgewicht %": [v * 100 for v in last_weights.values()]
                    }).sort_values("Zielgewicht %", ascending=False)
                    st.dataframe(last_weights_df.round(2), use_container_width=True)
                else:
                    st.write("Keine Positionen ausgewählt.")
            else:
                st.write("Noch keine Auswahl vorhanden.")

        with st.expander("📊 Gewichtungsverlauf als Tabelle"):
            st.dataframe(weights_with_cash.round(2), use_container_width=True)

        with st.expander("🔁 Gewichte an den Rebalancing-Zeitpunkten"):
            if not weights_rebalance_only.empty:
                st.dataframe(weights_rebalance_only.round(2), use_container_width=True)
            else:
                st.write("Keine Rebalancing-Zeitpunkte vorhanden.")

        with st.expander("📒 Rebalancing-Log"):
            if not rebalance_df.empty:
                st.dataframe(rebalance_df.round(2), use_container_width=True)
            else:
                st.write("Noch kein Rebalancing geloggt.")

        if show_debug:
            with st.expander("🛠 Debug / Daten prüfen"):
                st.write("Verwendete Ticker:", tickers)
                st.write("Übersprungene Ticker:", skipped_tickers)
                st.write("Top-N gewählt:", top_n)
                st.write("Top-N effektiv:", effective_top_n)
                st.write("Max. Gewicht je Asset (%):", max_weight_pct)
                st.write("Conviction-Stärke:", conviction_power)
                st.write("Soft Cash Mode:", soft_cash_mode)
                st.write("Regime-Filter aktiv:", use_regime_filter)
                st.write("Letzte Preise:")
                st.dataframe(prices.tail(), use_container_width=True)
                st.write("Letzte Scores:")
                st.dataframe(raw_score.tail(), use_container_width=True)

else:
    st.info("👈 Wähle ein Setup oder gib deinen Asset-Korb ein und klicke auf 'Portfolio berechnen'.")