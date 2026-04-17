import json
import hmac
import hashlib
import re
from datetime import datetime
from urllib.parse import quote

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from supabase import create_client

st.set_page_config(page_title="Allocato", layout="wide")

# =========================
# Subscription / Pricing Links
# =========================
STRIPE_BASIC = "https://buy.stripe.com/test_8x2dR37H21WI4sV3gGfjG00"
STRIPE_PRO = "https://buy.stripe.com/test_3cIaERf9udFq2kN04ufjG01"
STRIPE_LIFETIME = "https://buy.stripe.com/test_fZu9AN2mIeJu3oRbNcfjG02"

# =========================
# User / Auth System (Supabase)
# =========================
USER_STATE_VERSION = 1
TIERS = ["Free", "Basic", "Pro", "Lifetime"]
TIER_ICONS = {"Free": "🆓", "Basic": "📘", "Pro": "🚀", "Lifetime": "💎"}

# Supabase Secrets (in Streamlit Secrets hinterlegen)
# SUPABASE_URL = "https://<project-ref>.supabase.co"
# SUPABASE_SERVICE_ROLE_KEY = "..."
# optional fallback:
# SUPABASE_ANON_KEY = "..."
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", st.secrets.get("SUPABASE_ANON_KEY", ""))

# Für Testing kannst du hier Admin-E-Mails hinterlegen.
ADMIN_EMAILS = {
    "admin@allocato.local",
}

# Direkte Test-Freischaltungen pro E-Mail.
# Beispiel:
# TEST_ACCOUNT_TIER_OVERRIDES = {
#     "kev_cone@web.de": "Pro",
#     "zweite@email.de": "Lifetime",
# }
TEST_ACCOUNT_TIER_OVERRIDES = {}

ALLOW_ADMIN_TIER_OVERRIDE = True


def build_checkout_url(base_url: str) -> str:
    email = normalize_email(st.session_state.get("auth_user_email", ""))
    if email:
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}locked_prefilled_email={quote(email)}"
    return base_url


def ensure_auth_session_state():
    auth_defaults = {
        "subscription_tier": "Free",
        "auth_logged_in": False,
        "auth_user_email": "",
        "auth_loaded_for": "",
        "auth_is_admin": False,
    }
    for key, value in auth_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def normalize_email(email: str) -> str:
    return email.strip().lower()

def get_test_override_tier(email: str) -> str | None:
    normalized = normalize_email(email)
    tier = TEST_ACCOUNT_TIER_OVERRIDES.get(normalized)
    return tier if tier in TIERS else None

def resolve_effective_tier(email: str | None, stored_tier: str | None = None) -> str:
    email_normalized = normalize_email(email) if email else ""
    override_tier = get_test_override_tier(email_normalized) if email_normalized else None
    if override_tier:
        return override_tier
    if stored_tier in TIERS:
        return stored_tier
    return "Free"

def is_valid_email(email: str) -> bool:
    pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
    return re.match(pattern, normalize_email(email)) is not None

def hash_password(password: str, salt_hex: str | None = None) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else hashlib.sha256(str(datetime.utcnow().timestamp()).encode("utf-8")).digest()
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
    return f"{salt.hex()}${derived.hex()}"

def verify_password(password: str, stored_value: str) -> bool:
    try:
        salt_hex, stored_hash = stored_value.split("$", 1)
        candidate = hash_password(password, salt_hex).split("$", 1)[1]
        return hmac.compare_digest(candidate, stored_hash)
    except Exception:
        return False

@st.cache_resource
def get_supabase_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "Supabase ist nicht konfiguriert. Bitte SUPABASE_URL und "
            "SUPABASE_SERVICE_ROLE_KEY (oder SUPABASE_ANON_KEY) in Streamlit Secrets setzen."
        )
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def clean_supabase_row(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return row

def get_user_row(email: str):
    normalized = normalize_email(email)
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("users")
            .select("email,password_hash,subscription_tier,state_json,created_at,updated_at")
            .eq("email", normalized)
            .limit(1)
            .execute()
        )
        data = response.data or []
        if not data:
            return None
        return clean_supabase_row(data[0])
    except Exception as e:
        raise RuntimeError(f"Supabase user lookup failed: {e}") from e

def create_user(email: str, password: str) -> tuple[bool, str]:
    normalized = normalize_email(email)
    if not is_valid_email(normalized):
        return False, "Bitte eine gültige E-Mail-Adresse eingeben."
    if len(password) < 8:
        return False, "Das Passwort muss mindestens 8 Zeichen lang sein."
    try:
        if get_user_row(normalized):
            return False, "Diese E-Mail ist bereits registriert."
        now = datetime.utcnow().isoformat()
        initial_state = json.dumps({}, ensure_ascii=False)
        supabase = get_supabase_client()
        supabase.table("users").insert({
            "email": normalized,
            "password_hash": hash_password(password),
            "subscription_tier": "Free",
            "state_json": initial_state,
            "created_at": now,
            "updated_at": now,
        }).execute()
        return True, "Registrierung erfolgreich. Du kannst dich jetzt einloggen."
    except Exception as e:
        return False, f"Registrierung fehlgeschlagen: {e}"

def update_user_tier(email: str, new_tier: str):
    normalized = normalize_email(email)
    if new_tier not in TIERS:
        return
    try:
        now = datetime.utcnow().isoformat()
        supabase = get_supabase_client()
        supabase.table("users").update({
            "subscription_tier": new_tier,
            "updated_at": now,
        }).eq("email", normalized).execute()
    except Exception as e:
        st.error(f"Tier-Update fehlgeschlagen: {e}")

def login_user(email: str, password: str) -> tuple[bool, str]:
    normalized = normalize_email(email)
    try:
        row = get_user_row(normalized)
    except Exception as e:
        return False, f"Login fehlgeschlagen: {e}"
    if row is None:
        return False, "Kein Konto mit dieser E-Mail gefunden."
    if not verify_password(password, row["password_hash"]):
        return False, "Falsches Passwort."
    st.session_state["auth_logged_in"] = True
    st.session_state["auth_user_email"] = normalized
    st.session_state["auth_is_admin"] = normalized in ADMIN_EMAILS
    st.session_state["subscription_tier"] = resolve_effective_tier(normalized, row.get("subscription_tier"))
    st.session_state["auth_loaded_for"] = ""
    return True, "Erfolgreich eingeloggt."

def logout_user():
    save_logged_in_user_state()
    st.session_state["auth_logged_in"] = False
    st.session_state["auth_user_email"] = ""
    st.session_state["auth_loaded_for"] = ""
    st.session_state["auth_is_admin"] = False
    st.session_state["subscription_tier"] = "Free"

def get_auth_texts(lang: str) -> dict:
    if lang == "EN":
        return {
            "account_header": "👤 Account",
            "guest_info": "You are using Allocato as a guest. To save baskets and your plan permanently, please register or log in.",
            "login_tab": "Login",
            "register_tab": "Register",
            "email": "Email",
            "password": "Password",
            "password_repeat": "Repeat password",
            "login_button": "Log in",
            "register_button": "Create account",
            "logout_button": "Log out",
            "logged_in_as": "Logged in as",
            "current_plan": "Current plan",
            "plan_note": "Your plan is loaded from your account.",
            "admin_plan": "Admin plan control",
            "save_plan": "Save plan",
            "plan_saved": "Plan saved.",
            "register_pw_mismatch": "Passwords do not match.",
            "auth_required_export": "Please log in and upgrade to use these exports permanently.",
            "stripe_note": "The Stripe checkout links are included. Automatic plan upgrade after payment still requires a Stripe webhook or a server endpoint.",
        }
    return {
        "account_header": "👤 Konto",
        "guest_info": "Du nutzt Allocato aktuell als Gast. Für dauerhaft gespeicherte Körbe und Abo-Stufen bitte registrieren oder einloggen.",
        "login_tab": "Login",
        "register_tab": "Registrieren",
        "email": "E-Mail",
        "password": "Passwort",
        "password_repeat": "Passwort wiederholen",
        "login_button": "Einloggen",
        "register_button": "Konto erstellen",
        "logout_button": "Ausloggen",
        "logged_in_as": "Eingeloggt als",
        "current_plan": "Aktueller Plan",
        "plan_note": "Dein Plan wird aus deinem Nutzerkonto geladen.",
        "admin_plan": "Admin-Plansteuerung",
        "save_plan": "Plan speichern",
        "plan_saved": "Plan gespeichert.",
        "register_pw_mismatch": "Die Passwörter stimmen nicht überein.",
        "auth_required_export": "Bitte logge dich ein und upgrade deinen Account, um diese Exporte dauerhaft zu nutzen.",
        "stripe_note": "Die Stripe-Checkout-Links sind eingebaut. Für eine automatische Planfreischaltung nach Zahlung brauchst du zusätzlich noch einen Stripe-Webhook oder Server-Endpunkt.",
    }

ensure_auth_session_state()


# =========================
# Hard Limits
# =========================
def get_current_tier() -> str:
    email = st.session_state.get("auth_user_email", "")
    tier = st.session_state.get("subscription_tier", "Free")
    return resolve_effective_tier(email, tier)

def get_max_baskets() -> int:
    return 1 if get_current_tier() == "Free" else 999

def get_max_period() -> str:
    return "3y" if get_current_tier() == "Free" else "5y"

def can_use_asset_search() -> bool:
    return get_current_tier() in ["Basic", "Pro", "Lifetime"]

def can_export_full() -> bool:
    return get_current_tier() != "Free"

# =========================
# Defaults / Session State
# =========================
defaults = {
    "language": "DE",
    "initial_capital": 10000,
    "monthly_savings": 500,
    "period": get_max_period(),
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
    "asset_search_query": "",
    "asset_search_select": None,
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

if "_pending_preset" not in st.session_state:
    st.session_state["_pending_preset"] = None

if "baskets" not in st.session_state:
    st.session_state.baskets = {"Korb 1": defaults["assets_input"]}

if "active_basket" not in st.session_state:
    st.session_state.active_basket = list(st.session_state.baskets.keys())[0]

if "last_loaded_basket" not in st.session_state:
    st.session_state.last_loaded_basket = st.session_state.active_basket

if "new_basket_name" not in st.session_state:
    st.session_state.new_basket_name = ""

if "rename_basket_name" not in st.session_state:
    st.session_state.rename_basket_name = ""

# Sichere Widget-/Sidebar-Helferzustände für Korb-Aktionen
if "new_basket_name_input" not in st.session_state:
    st.session_state.new_basket_name_input = ""

if "rename_basket_name_input" not in st.session_state:
    st.session_state.rename_basket_name_input = ""

if "_pending_active_basket" in st.session_state:
    st.session_state.active_basket = st.session_state["_pending_active_basket"]
    st.session_state.last_loaded_basket = st.session_state["_pending_active_basket"]
    del st.session_state["_pending_active_basket"]

if "_clear_new_basket_name_input" in st.session_state:
    st.session_state.new_basket_name_input = ""
    del st.session_state["_clear_new_basket_name_input"]

if "_clear_rename_basket_name_input" in st.session_state:
    st.session_state.rename_basket_name_input = ""
    del st.session_state["_clear_rename_basket_name_input"]


PERSISTENT_STATE_KEYS = [
    "language",
    "initial_capital",
    "monthly_savings",
    "period",
    "rebalance_freq",
    "fee_pct_input",
    "min_score",
    "max_weight_pct",
    "vol_penalty",
    "cash_interest_pct",
    "use_regime_filter",
    "show_debug",
    "conviction_power",
    "soft_cash_mode",
    "target_cash_floor_pct",
    "target_cash_ceiling_pct",
    "soft_cash_invest_ratio_pct",
    "weight_chart_top_n",
    "top_n",
    "assets_input",
    "asset_search_query",
    "asset_search_select",
    "_pending_preset",
    "baskets",
    "active_basket",
    "last_loaded_basket",
]

def build_user_state_payload() -> dict:
    payload = {"version": USER_STATE_VERSION}
    for key in PERSISTENT_STATE_KEYS:
        payload[key] = st.session_state.get(key)
    return payload

def apply_user_state_payload(payload: dict):
    if not isinstance(payload, dict):
        return
    for key in PERSISTENT_STATE_KEYS:
        if key in payload and payload[key] is not None:
            st.session_state[key] = payload[key]

def load_logged_in_user_state():
    if not st.session_state.get("auth_logged_in") or not st.session_state.get("auth_user_email"):
        return
    email = st.session_state["auth_user_email"]
    if st.session_state.get("auth_loaded_for") == email:
        return
    row = get_user_row(email)
    if row is None:
        logout_user()
        return
    st.session_state["subscription_tier"] = resolve_effective_tier(email, row["subscription_tier"])
    st.session_state["auth_is_admin"] = email in ADMIN_EMAILS
    payload = {}
    if row["state_json"]:
        try:
            payload = json.loads(row["state_json"])
        except Exception:
            payload = {}
    apply_user_state_payload(payload)
    st.session_state["auth_loaded_for"] = email

def save_logged_in_user_state():
    if not st.session_state.get("auth_logged_in") or not st.session_state.get("auth_user_email"):
        return
    email = normalize_email(st.session_state["auth_user_email"])
    payload_json = json.dumps(build_user_state_payload(), ensure_ascii=False)
    now = datetime.utcnow().isoformat()
    try:
        supabase = get_supabase_client()
        supabase.table("users").update({
            "subscription_tier": st.session_state.get("subscription_tier", "Free"),
            "state_json": payload_json,
            "updated_at": now,
        }).eq("email", email).execute()
    except Exception as e:
        st.warning(f"Speichern des Nutzerstatus fehlgeschlagen: {e}")

def enforce_plan_limits():
    tier_now = st.session_state.get("subscription_tier", "Free")
    if tier_now == "Free":
        if len(st.session_state.baskets) > 1:
            first_name = list(st.session_state.baskets.keys())[0]
            st.session_state.baskets = {first_name: st.session_state.baskets[first_name]}
            st.session_state.active_basket = first_name
            st.session_state.last_loaded_basket = first_name
            st.session_state.assets_input = st.session_state.baskets[first_name]
        if st.session_state.get("period") not in ["1y", "2y", "3y"]:
            st.session_state["period"] = "3y"
        if int(st.session_state.get("top_n", 4)) > 4:
            st.session_state["top_n"] = 4

load_logged_in_user_state()
enforce_plan_limits()

# =========================
# Presets
# =========================
PRESETS = {
    "Quality": {
        "assets_input": "AAPL\nSAP.DE\nSIE.DE\nALV.DE\nMUV2.DE\nJNJ\nPG",
        "top_n": 4,
        "conviction_power": 2.0,
        "max_weight_pct": 55,
        "vol_penalty": 0.08,
        "rebalance_freq": "Monatlich",
        "min_score": 0.00,
        "soft_cash_mode": True,
        "target_cash_floor_pct": 5,
        "target_cash_ceiling_pct": 15,
        "soft_cash_invest_ratio_pct": 85,
    },
    "Global": {
        "assets_input": (
            "SPY\nQQQ\nVOO\nVUG\nVTI\nVXUS\nNVDA\nMSFT\nAAPL\nGOOGL\nAMZN\nMETA\nTSLA\nAMD\nAVGO\n"
            "SAP.DE\nSIE.DE\nAIR.DE\nALV.DE\nBMW.DE\nBAS.DE\nDBK.DE\nV\nMA\nJPM\nJNJ\nPG\n"
            "KO\nPEP\nMCD\nASML\nADBE\nCRM\nNOW"
        ),
        "top_n": 5,
        "conviction_power": 2.5,
        "max_weight_pct": 55,
        "vol_penalty": 0.08,
        "rebalance_freq": "Monatlich",
        "min_score": 0.00,
        "soft_cash_mode": True,
        "target_cash_floor_pct": 5,
        "target_cash_ceiling_pct": 15,
        "soft_cash_invest_ratio_pct": 85,
    },
    "Europa": {
        "assets_input": (
            "SAP.DE\nSIE.DE\nAIR.DE\nALV.DE\nMUV2.DE\nBMW.DE\nBAS.DE\nDBK.DE\nRWE.DE\n"
            "DTE.DE\nIFX.DE\nADS.DE\nDPW.DE\nVOW3.DE\nCON.DE\nHEI.DE"
        ),
        "top_n": 5,
        "conviction_power": 2.2,
        "max_weight_pct": 50,
        "vol_penalty": 0.08,
        "rebalance_freq": "Monatlich",
        "min_score": 0.00,
        "soft_cash_mode": True,
        "target_cash_floor_pct": 8,
        "target_cash_ceiling_pct": 18,
        "soft_cash_invest_ratio_pct": 85,
    },
    "Dividend": {
        "assets_input": (
            "JNJ\nPG\nKO\nPEP\nMCD\nMMM\nIBM\nVZ\nT\nMO\nPM\nABBV\nLLY\nMRK\nPFE\nUNH\n"
            "V\nMA\nJPM\nBAC\nGS\nMS\nC\nAXP\nSPY\nQQQ\nSAP.DE\nSIE.DE\nALV.DE\nMUV2.DE"
        ),
        "top_n": 6,
        "conviction_power": 2.0,
        "max_weight_pct": 50,
        "vol_penalty": 0.08,
        "rebalance_freq": "Monatlich",
        "min_score": 0.00,
        "soft_cash_mode": True,
        "target_cash_floor_pct": 7,
        "target_cash_ceiling_pct": 15,
        "soft_cash_invest_ratio_pct": 85,
    },
}

# =========================
# Local Asset Database
# =========================
ASSET_CATALOG = [
    {"ticker": "SPY", "name": "SPDR S&P 500 ETF", "isin": "US78462F1030", "wkn": "A1JULM"},
    {"ticker": "QQQ", "name": "Invesco QQQ Trust", "isin": "US46090E1038", "wkn": "A0F5UF"},
    {"ticker": "VOO", "name": "Vanguard S&P 500 ETF", "isin": "US9229083632", "wkn": "A1JX53"},
    {"ticker": "VUG", "name": "Vanguard Growth ETF", "isin": "US9229087369", "wkn": "A0Q4R2"},
    {"ticker": "VTI", "name": "Vanguard Total Stock Market ETF", "isin": "US9229087690", "wkn": "A0J206"},
    {"ticker": "VXUS", "name": "Vanguard Total International Stock ETF", "isin": "US9219097683", "wkn": "A1JX51"},
    {"ticker": "ARKK", "name": "ARK Innovation ETF", "isin": "US00214Q1040", "wkn": "A14Y8H"},
    {"ticker": "NVDA", "name": "NVIDIA Corp.", "isin": "US67066G1040", "wkn": "918422"},
    {"ticker": "MSFT", "name": "Microsoft Corp.", "isin": "US5949181045", "wkn": "870747"},
    {"ticker": "AAPL", "name": "Apple Inc.", "isin": "US0378331005", "wkn": "865985"},
    {"ticker": "GOOGL", "name": "Alphabet Inc. Class A", "isin": "US02079K3059", "wkn": "A14Y6F"},
    {"ticker": "AMZN", "name": "Amazon.com Inc.", "isin": "US0231351067", "wkn": "906866"},
    {"ticker": "META", "name": "Meta Platforms Inc.", "isin": "US30303M1027", "wkn": "A1JWVX"},
    {"ticker": "TSLA", "name": "Tesla Inc.", "isin": "US88160R1014", "wkn": "A1CX3T"},
    {"ticker": "AMD", "name": "Advanced Micro Devices", "isin": "US0079031078", "wkn": "863186"},
    {"ticker": "AVGO", "name": "Broadcom Inc.", "isin": "US11135F1012", "wkn": "A2JG9Z"},
    {"ticker": "ASML", "name": "ASML Holding", "isin": "USN070592100", "wkn": "A1J4U4"},
    {"ticker": "ADBE", "name": "Adobe Inc.", "isin": "US00724F1012", "wkn": "871981"},
    {"ticker": "CRM", "name": "Salesforce Inc.", "isin": "US79466L3024", "wkn": "A0B87V"},
    {"ticker": "NOW", "name": "ServiceNow Inc.", "isin": "US81762P1021", "wkn": "A1JX4P"},
    {"ticker": "PLTR", "name": "Palantir Technologies", "isin": "US69608A1088", "wkn": "A2QA4J"},
    {"ticker": "ARM", "name": "Arm Holdings ADR", "isin": "US0420682058", "wkn": "A3EUCD"},
    {"ticker": "SMCI", "name": "Super Micro Computer", "isin": "US86800U1043", "wkn": "A0MKJF"},
    {"ticker": "COIN", "name": "Coinbase Global", "isin": "US19260Q1076", "wkn": "A2QP7J"},
    {"ticker": "MSTR", "name": "MicroStrategy Inc.", "isin": "US5949724083", "wkn": "722713"},
    {"ticker": "HOOD", "name": "Robinhood Markets", "isin": "US7707001027", "wkn": "A3CVQC"},
    {"ticker": "MRK", "name": "Merck & Co.", "isin": "US58933Y1055", "wkn": "A0YD8Q"},
    {"ticker": "PFE", "name": "Pfizer Inc.", "isin": "US7170811035", "wkn": "852009"},
    {"ticker": "LLY", "name": "Eli Lilly", "isin": "US5324571083", "wkn": "858560"},
    {"ticker": "JNJ", "name": "Johnson & Johnson", "isin": "US4781601046", "wkn": "853260"},
    {"ticker": "PG", "name": "Procter & Gamble", "isin": "US7427181091", "wkn": "852062"},
    {"ticker": "KO", "name": "Coca-Cola", "isin": "US1912161007", "wkn": "850663"},
    {"ticker": "PEP", "name": "PepsiCo", "isin": "US7134481081", "wkn": "851995"},
    {"ticker": "MCD", "name": "McDonald's", "isin": "US5801351017", "wkn": "856958"},
    {"ticker": "MMM", "name": "3M Co.", "isin": "US88579Y1010", "wkn": "851745"},
    {"ticker": "IBM", "name": "IBM", "isin": "US4592001014", "wkn": "851399"},
    {"ticker": "VZ", "name": "Verizon", "isin": "US92343V1044", "wkn": "868402"},
    {"ticker": "T", "name": "AT&T", "isin": "US00206R1023", "wkn": "A0HL9Z"},
    {"ticker": "MO", "name": "Altria Group", "isin": "US02209S1033", "wkn": "200417"},
    {"ticker": "PM", "name": "Philip Morris", "isin": "US7181721090", "wkn": "A0NDBJ"},
    {"ticker": "ABBV", "name": "AbbVie", "isin": "US00287Y1091", "wkn": "A1J84E"},
    {"ticker": "UNH", "name": "UnitedHealth Group", "isin": "US91324P1021", "wkn": "869561"},
    {"ticker": "V", "name": "Visa Inc.", "isin": "US92826C8394", "wkn": "A0NC7B"},
    {"ticker": "MA", "name": "Mastercard", "isin": "US57636Q1040", "wkn": "A0F602"},
    {"ticker": "JPM", "name": "JPMorgan Chase", "isin": "US46625H1005", "wkn": "850628"},
    {"ticker": "BAC", "name": "Bank of America", "isin": "US0605051046", "wkn": "858388"},
    {"ticker": "GS", "name": "Goldman Sachs", "isin": "US38141G1040", "wkn": "920332"},
    {"ticker": "MS", "name": "Morgan Stanley", "isin": "US6174464486", "wkn": "885836"},
    {"ticker": "C", "name": "Citigroup", "isin": "US1729674242", "wkn": "A1H92V"},
    {"ticker": "AXP", "name": "American Express", "isin": "US0258161092", "wkn": "850226"},
    {"ticker": "SAP.DE", "name": "SAP SE", "isin": "DE0007164600", "wkn": "716460"},
    {"ticker": "SIE.DE", "name": "Siemens AG", "isin": "DE0007236101", "wkn": "723610"},
    {"ticker": "AIR.DE", "name": "Airbus SE", "isin": "NL0000235190", "wkn": "938914"},
    {"ticker": "ALV.DE", "name": "Allianz SE", "isin": "DE0008404005", "wkn": "840400"},
    {"ticker": "MUV2.DE", "name": "Munich Re", "isin": "DE0008430026", "wkn": "843002"},
    {"ticker": "BMW.DE", "name": "BMW AG", "isin": "DE0005190003", "wkn": "519000"},
    {"ticker": "BAS.DE", "name": "BASF SE", "isin": "DE000BASF111", "wkn": "BASF11"},
    {"ticker": "DBK.DE", "name": "Deutsche Bank", "isin": "DE0005140008", "wkn": "514000"},
    {"ticker": "RWE.DE", "name": "RWE AG", "isin": "DE0007037129", "wkn": "703712"},
    {"ticker": "DTE.DE", "name": "Deutsche Telekom", "isin": "DE0005557508", "wkn": "555750"},
    {"ticker": "IFX.DE", "name": "Infineon", "isin": "DE0006231004", "wkn": "623100"},
    {"ticker": "ADS.DE", "name": "Adidas", "isin": "DE000A1EWWW0", "wkn": "A1EWWW"},
    {"ticker": "DPW.DE", "name": "DHL Group", "isin": "DE0005552004", "wkn": "555200"},
    {"ticker": "VOW3.DE", "name": "Volkswagen Vz", "isin": "DE0007664039", "wkn": "766403"},
    {"ticker": "CON.DE", "name": "Continental", "isin": "DE0005439004", "wkn": "543900"},
    {"ticker": "HEI.DE", "name": "Heidelberg Materials", "isin": "DE0006047004", "wkn": "604700"},
]
ASSET_CATALOG_DF = pd.DataFrame(ASSET_CATALOG).drop_duplicates(subset=["ticker"]).reset_index(drop=True)

# =========================
# Translation
# =========================
TRANSLATIONS = {
    "DE": {
        "page_badges": ["Dynamic Allocation", "Direct Equity Ownership", "Buy & Hold Benchmark", "Launch Version 5.2.0"],
        "hero_sub": (
            "Dein smarter Portfolio-Manager für Direktaktien. "
            "Nicht blind kaufen. Nicht unnötig Gebühren zahlen. "
            "Nicht darauf hoffen, dass irgendein Produkt schon irgendwie passt."
            "<br><br>"
            "Allocato hilft dir, ein dynamisch gesteuertes Portfolio aufzubauen, "
            "in dem du <b>Kontrolle, Transparenz und Dividenden direkt selbst</b> behältst."
        ),
        "warning_expander": "⚠️ Wichtiger Hinweis",
        "warning_text": (
            "**Allocato ist kein Anlageberatungstool.** \n"
            "Die dargestellten Ergebnisse sind historische Simulationen und keine Garantie für zukünftige Renditen. \n"
            "Jede Anlageentscheidung triffst du selbst. Vergangene Performance ist kein Indikator für zukünftige Ergebnisse."
        ),
        "why_label": "Warum Allocato?",
        "why_title": "Mehr Kontrolle. Mehr Transparenz. Mehr Eigentum.",
        "why_text": (
            "Viele Anleger stecken ihr Geld in Produkte, deren Regeln sie kaum kennen, "
            "zahlen laufende Gebühren und geben Entscheidungen komplett aus der Hand. "
            "Allocato geht den anderen Weg:"
            "<br><br>"
            "<b>Du definierst den Anlagekorb. Die Engine übernimmt die Logik.</b><br>"
            "Sie bewertet Momentum, Trend und Risiko, gewichtet die stärksten Titel neu "
            "und versucht, Kapital intelligent statt passiv zu allokieren."
            "<br><br>"
            "<span class='small-note'>"
            "Allocato ist kein Versprechen auf sichere Gewinne. "
            "Es ist ein Werkzeug für Anleger, die bewusstere Entscheidungen treffen wollen — "
            "mit mehr Eigentum, mehr Transparenz und weniger Abhängigkeit von Standardlösungen."
            "</span>"
        ),
        "sidebar_language": "Sprache",
        "sidebar_settings": "Einstellungen",
        "subscription_header": "🔑 Mein Abonnement",
        "subscription_label": "Aktuelles Abo",
        "free_warning": "**Free-Version aktiv**\n\n1 Korb • max. 3 Jahre • keine Asset-Suche",
        "basic_active": "📘 Basic aktiv",
        "pro_active": "🚀 Pro aktiv",
        "lifetime_active": "💎 Lifetime aktiv",
        "upgrade_basic": "Jetzt upgraden → Basic (19 €/Monat)",
        "upgrade_pro": "Upgrade → Pro (39 €/Monat)",
        "upgrade_lifetime": "Lifetime sichern (249 €)",
        "basket_header": "🧺 Meine Körbe",
        "basket_select": "Aktiver Korb",
        "basket_new_name": "Neuer Korbname",
        "basket_add": "Korb anlegen",
        "basket_delete": "Aktiven Korb löschen",
        "basket_rename": "Aktiven Korb umbenennen",
        "basket_rename_name": "Neuer Name für aktiven Korb",
        "basket_limit_free": "Weitere Körbe sind ab Basic verfügbar.",
        "basket_created": "Korb erstellt: {name}",
        "basket_deleted": "Korb gelöscht: {name}",
        "basket_renamed": "Korb umbenannt in: {name}",
        "basket_name_exists": "Dieser Korbname existiert bereits.",
        "basket_name_empty": "Bitte einen gültigen Korbnamen eingeben.",
        "basket_delete_blocked": "Der letzte Korb kann nicht gelöscht werden.",
        "start_capital": "Startkapital (€)",
        "start_capital_help": "Einmalige Anfangsinvestition.",
        "monthly_savings": "Monatliche Sparrate (€)",
        "monthly_savings_help": "Zusätzlicher Betrag, der bei Monatswechsel investierbar wird.",
        "period": "Zeitraum",
        "period_help": "Für Momentum-Strategien sind 3 bis 5 Jahre meist am sinnvollsten.",
        "rebalance": "Rebalancing",
        "rebalance_options": ["Monatlich", "Quartalsweise"],
        "fee": "Transaktionskosten pro Trade (%)",
        "fee_help": "Gebühren und Slippage pro Umschichtung.",
        "min_score": "Mindest-Score für Kauf",
        "min_score_help": "Nur Assets mit Score über diesem Wert dürfen gekauft werden.",
        "max_weight": "Max. Gewicht pro Asset (%)",
        "max_weight_help": "Begrenzt die maximale Positionsgröße pro Asset.",
        "vol_penalty": "Volatilitätsstrafe",
        "vol_penalty_help": "Je höher dieser Wert, desto stärker werden schwankungsreiche Assets bestraft.",
        "cash_interest": "Cash-Zins p.a. (%)",
        "cash_interest_help": "Optionaler Zins auf uninvestiertes Cash.",
        "regime_filter": "Marktregime-Filter nutzen (SPY > SMA200)",
        "regime_filter_help": "Wenn aktiv, investiert der Bot nur offensiv, wenn SPY über SMA200 liegt.",
        "show_debug": "Debug-Bereich anzeigen",
        "show_debug_help": "Zeigt Rohdaten und interne Details an.",
        "aggressive_mode": "Aggressiv-Modus",
        "conviction": "Conviction-Stärke",
        "conviction_help": "Je höher, desto stärker werden die besten Assets bevorzugt.",
        "soft_cash_mode": "Soft Cash Mode nutzen",
        "soft_cash_mode_help": "Wenn keine klaren Signale da sind, bleibt der Bot nicht komplett in Cash.",
        "cash_floor": "Ziel-Cash-Untergrenze (%)",
        "cash_floor_help": "Der Bot versucht, im Normalfall mindestens so viel Cash zu halten.",
        "cash_ceiling": "Ziel-Cash-Obergrenze (%)",
        "cash_ceiling_help": "Der Bot versucht, im Normalfall nicht deutlich mehr Cash zu halten.",
        "soft_cash_ratio": "Soft-Cash Investitionsquote (%)",
        "soft_cash_ratio_help": "Wenn Soft Cash Mode aktiv ist und keine starken Signale da sind, bleibt ungefähr dieser Anteil investiert.",
        "visualization": "Visualisierung",
        "weight_chart_top_n": "Anzahl Assets im Gewichts-Chart",
        "weight_chart_top_n_help": "Zeigt im Gewichtungsverlauf nur die größten durchschnittlichen Positionen. Der Rest wird zu 'Sonstige' zusammengefasst.",
        "recommended_setups": "⚡ Empfohlene Setups",
        "asset_search_section": "🔎 Asset-Suche",
        "asset_search_query": "Suche nach Ticker, Name, ISIN oder WKN",
        "asset_search_query_help": "Beispiel: SAP, Apple, DE0007164600 oder 716460",
        "asset_search_result": "Treffer auswählen",
        "add_asset_button": "Zum Korb hinzufügen",
        "add_selected_assets_button": "Alle Treffer hinzufügen",
        "remove_asset_section": "➖ Asset entfernen",
        "remove_asset_select": "Ticker zum Entfernen",
        "remove_asset_button": "Aus Korb entfernen",
        "search_no_results": "Keine Treffer in der integrierten Datenbank gefunden.",
        "search_info": "Tipp: Du kannst weiterhin manuell Ticker in den Asset-Korb schreiben. Die Suche deckt die integrierte Asset-Datenbank ab.",
        "search_locked": "🔒 Asset-Suche nur in Basic & höher verfügbar",
        "asset_basket": "Asset-Korb",
        "tickers_input": "Ticker (ein pro Zeile)",
        "tickers_input_help": "Der Bot wählt aus diesem Korb selbst die stärksten Assets.",
        "top_n": "Top-N Assets halten",
        "top_n_help": "Wie viele der stärksten Assets gleichzeitig gehalten werden.",
        "preset_quality": "Quality",
        "preset_global": "Global",
        "preset_europe": "Europa",
        "preset_dividend": "Dividend",
        "about_expander": "ℹ️ Was ist Allocato?",
        "about_text": (
            "Allocato ist für Anleger gedacht, die mehr Kontrolle über ihr Kapital wollen.\n\n"
            "Nicht blind kaufen. \n"
            "Nicht dauerhaft Gebühren zahlen, ohne zu wissen, was im Produkt eigentlich passiert. \n"
            "Nicht Dividendenströme und Entscheidungen komplett auslagern.\n\n"
            "**Die Idee hinter Allocato:**\n"
            "Du definierst deinen Anlagekorb selbst. \n"
            "Die Engine bewertet Stärke, Trend und Risiko und verteilt das Kapital dynamisch auf die stärksten Assets.\n\n"
            "Damit entsteht ein Portfolio-Manager für Direktaktien und ETFs, der versucht:\n"
            "- Chancen aktiv zu nutzen\n"
            "- Cash bewusst zu steuern\n"
            "- Risiko kontrollierbarer zu halten\n"
            "- und Entscheidungen nachvollziehbar zu machen"
        ),
        "metrics_expander": "🧠 Wie interpretiere ich die Kennzahlen?",
        "metrics_text": (
            "**Bot Endwert** \nEndwert des aktiven Portfolios.\n\n"
            "**Buy & Hold Endwert** \nEndwert eines passiven Vergleichsportfolios mit denselben Assets.\n\n"
            "**Outperformance** \nDifferenz der Gesamtrendite in Prozentpunkten. Positiv = Bot schlägt Buy & Hold.\n\n"
            "**Exposure** \nWie viel Prozent des Portfolios im Durchschnitt investiert waren.\n\n"
            "**Ø Cash-Quote** \nDurchschnittlicher Cash-Anteil.\n\n"
            "**CAGR** \nJährliche durchschnittliche Wachstumsrate.\n\n"
            "**Max Drawdown** \nGrößter historischer Rückgang vom Hochpunkt.\n\n"
            "**Volatilität** \nSchwankungsintensität des Portfolios.\n\n"
            "**Sharpe Ratio** \nRendite im Verhältnis zur Schwankung. Höher ist meist besser."
        ),
        "preset_expander": "⚙️ Empfohlene Start-Setups",
        "preset_text": (
            "**Quality / Direktaktien-Korb**\n"
            "- AAPL\n- SAP.DE\n- SIE.DE\n- ALV.DE\n- MUV2.DE\n- JNJ\n- PG\n\n"
            "Empfehlung:\n"
            "- Top-N: 4\n"
            "- Rebalancing: Monatlich\n"
            "- Max Gewicht: 55\n"
            "- Conviction-Stärke: 2.0\n"
            "- Volatilitätsstrafe: 0.08\n\n"
            "**Großer globaler Korb**\n"
            "- ETFs, Tech, Europa, Dividenden gemischt\n\n"
            "Empfehlung:\n"
            "- Top-N: 5 bis 6\n"
            "- Rebalancing: Monatlich\n"
            "- Max Gewicht: 55\n"
            "- Conviction-Stärke: 2.0 bis 2.5\n\n"
            "**Europa / Deutschland**\n"
            "- SAP.DE\n- SIE.DE\n- AIR.DE\n- ALV.DE\n- MUV2.DE\n- BMW.DE\n- RWE.DE\n- DTE.DE\n\n"
            "Empfehlung:\n"
            "- Top-N: 5\n"
            "- Rebalancing: Monatlich oder Quartalsweise\n"
            "- Cashbereich: 8 bis 18"
        ),
        "calculate": "Portfolio berechnen",
        "spinner": "Berechne aggressives dynamisches Portfolio...",
        "error_min_assets": "Bitte mindestens 2 Ticker eingeben.",
        "warning_skip": "Keine Daten für {ticker} – wird übersprungen.",
        "error_no_data": "Es konnten keine gültigen Kursdaten geladen werden.",
        "error_less_than_2": "Nach dem Laden sind weniger als 2 gültige Assets übrig.",
        "error_too_few_rows": "Zu wenig gültige Daten nach Berechnung der Indikatoren.",
        "warning_spy": "SPY-Daten konnten nicht geladen werden. Regime-Filter wird deaktiviert.",
        "status_success": "✅ Der Bot schlägt Buy & Hold in diesem Test.",
        "status_neutral": "ℹ️ Der Bot liegt nahe an Buy & Hold. Für eine aktive aggressive Strategie ist das bereits ordentlich.",
        "status_bad": "⚠️ Der Bot liegt klar hinter Buy & Hold. Prüfe besonders Cash-Quote, Top-N, Conviction-Stärke und Rebalancing.",
        "cash_high": "💡 Die durchschnittliche Cash-Quote liegt über 15 %. Für einen aggressiven Modus könntest du Soft Cash Mode, niedrigeren Mindest-Score oder höheres Max-Gewicht testen.",
        "cash_low": "💡 Die durchschnittliche Cash-Quote liegt unter 5 %. Das ist offensiv, kann aber Drawdowns erhöhen.",
        "metric_bot_end": "Bot Endwert",
        "metric_bh_end": "Buy & Hold Endwert",
        "metric_outperf": "Outperformance",
        "metric_trades": "Trades",
        "metric_bot_return": "Bot Rendite",
        "metric_bh_return": "Buy & Hold Rendite",
        "metric_exposure": "Exposure",
        "metric_cash": "Ø Cash-Quote",
        "metric_cagr": "Bot CAGR",
        "metric_dd": "Bot Max Drawdown",
        "metric_vol": "Bot Volatilität",
        "metric_sharpe": "Bot Sharpe",
        "end_capital_success": "Endkapital dynamischer Bot: {value}",
        "equity_title": "Dynamischer Portfolio Bot vs Buy & Hold",
        "equity_label_bot": "Dynamischer Bot",
        "equity_label_bh": "Buy & Hold",
        "export_title": "Export",
        "export_caption": "Lade Equity-Verlauf, Rebalancing-Log oder Gewichtshistorie als CSV herunter.",
        "export_equity": "⬇️ Equity Curve CSV",
        "export_rebal": "⬇️ Rebalancing Log CSV",
        "export_weights": "⬇️ Gewichte CSV",
        "export_locked": "🔒 Weitere Exporte sind ab Basic verfügbar",
        "interpret_expander": "📌 Interpretation dieses Ergebnisses",
        "interpret_text": (
            "**Zusammenfassung dieses Testlaufs**\n\n"
            "- **Outperformance:** {outperformance:.2f} Prozentpunkte\n"
            "- **Exposure:** {exposure:.1f} %\n"
            "- **Ø Cash-Quote:** {cash:.1f} %\n"
            "- **Trades:** {trades}\n"
            "- **Conviction-Stärke:** {conviction:.1f}\n"
            "- **Soft Cash Mode:** {soft_cash}\n"
            "- **Ziel-Cashbereich:** {cash_floor}% bis {cash_ceiling}%\n\n"
            "**Interpretation**\n"
            "- Höhere Conviction-Stärke konzentriert das Kapital stärker auf Gewinner.\n"
            "- Eine Cash-Quote zwischen 5% und 15% ist hier das Zielbild.\n"
            "- Ist die Trade-Zahl sehr hoch, kann der Bot zu nervös sein.\n"
            "- Ist die Cash-Quote zu hoch, wird in starken Bullenphasen oft Rendite liegen gelassen.\n"
            "- Ein geringerer Max Drawdown kann den Bot trotz geringerer Rendite strategisch interessant machen."
        ),
        "soft_cash_on": "Aktiv",
        "soft_cash_off": "Aus",
        "current_weights": "Aktuelle Portfolio-Gewichte",
        "active_positions_empty": "Aktuell sind keine aktiven Positionen im Portfolio.",
        "show_all_assets": "Alle Assets inkl. 0%-Gewicht anzeigen",
        "weights_chart_title": "Gewichtungsverlauf im Portfolio",
        "weights_chart_caption": "Angezeigt werden die größten durchschnittlichen Positionen sowie 'Sonstige' und Cash.",
        "weights_chart_inner_title": "Portfolio-Gewichte über die Zeit",
        "weights_chart_ylabel": "Gewicht in %",
        "other_label": "Sonstige",
        "latest_selection": "🎯 Zuletzt ausgewählte Top-Assets",
        "last_selection_date": "Letzte Auswahl am {date}:",
        "last_target_weights": "Letzte Zielgewichte:",
        "no_positions_selected": "Keine Positionen ausgewählt.",
        "no_selection_yet": "Noch keine Auswahl vorhanden.",
        "weights_table": "📊 Gewichtungsverlauf als Tabelle",
        "weights_rebalance": "🔁 Gewichte an den Rebalancing-Zeitpunkten",
        "weights_rebalance_empty": "Keine Rebalancing-Zeitpunkte vorhanden.",
        "rebal_log": "📒 Rebalancing-Log",
        "rebal_log_empty": "Noch kein Rebalancing geloggt.",
        "debug_expander": "🛠 Debug / Daten prüfen",
        "debug_used_tickers": "Verwendete Ticker:",
        "debug_skipped": "Übersprungene Ticker:",
        "debug_top_n": "Top-N gewählt:",
        "debug_top_n_effective": "Top-N effektiv:",
        "debug_max_weight": "Max. Gewicht je Asset (%):",
        "debug_conviction": "Conviction-Stärke:",
        "debug_soft_cash": "Soft Cash Mode:",
        "debug_regime": "Regime-Filter aktiv:",
        "debug_last_prices": "Letzte Preise:",
        "debug_last_scores": "Letzte Scores:",
        "info_start": "👈 Wähle ein Setup oder gib deinen Asset-Korb ein und klicke auf 'Portfolio berechnen'.",
        "date_col": "Datum",
        "regime_ok_col": "Regime OK",
        "selected_assets_col": "Ausgewählte Assets",
        "turnover_col": "Turnover €",
        "fees_col": "Gebühren €",
        "cash_eur_col": "Cash €",
        "portfolio_eur_col": "Portfolio €",
        "weights_ticker_col": "Ticker",
        "weights_current_col": "Aktuelles Gewicht %",
        "weights_target_col": "Zielgewicht %",
        "bh_cash_label": "Cash (€)",
        "invested_label": "Investiert (€)",
        "bot_portfolio_label": "Bot Portfolio",
        "buy_hold_label": "Buy & Hold",
        "search_option_format": "{ticker} | {name} | ISIN: {isin} | WKN: {wkn}",
        "added_asset_msg": "{ticker} wurde zum Asset-Korb hinzugefügt.",
        "added_all_assets_msg": "{count} Assets wurden zum Asset-Korb hinzugefügt.",
        "removed_asset_msg": "{ticker} wurde aus dem Asset-Korb entfernt.",
        "remove_empty_msg": "Es ist kein Asset zum Entfernen vorhanden.",
        "footer_free": "🆓 Free-Version • Upgrade für unbegrenzte Körbe, 5 Jahre Historie und Asset-Suche",
    },
    "EN": {
        "page_badges": ["Dynamic Allocation", "Direct Equity Ownership", "Buy & Hold Benchmark", "Launch Version 5.2.0"],
        "hero_sub": (
            "Your smart portfolio manager for direct equities. "
            "Do not buy blindly. Do not pay unnecessary fees. "
            "Do not just hope that some product somehow fits."
            "<br><br>"
            "Allocato helps you build a dynamically managed portfolio "
            "where you keep <b>control, transparency and dividends directly</b>."
        ),
        "warning_expander": "⚠️ Important notice",
        "warning_text": (
            "**Allocato is not an investment advisory tool.** \n"
            "The results shown are historical simulations and not a guarantee of future returns. \n"
            "Every investment decision is your own. Past performance is not an indicator of future results."
        ),
        "why_label": "Why Allocato?",
        "why_title": "More control. More transparency. More ownership.",
        "why_text": (
            "Many investors put money into products whose rules they barely understand, "
            "pay ongoing fees and hand over decisions completely. "
            "Allocato takes a different path:"
            "<br><br>"
            "<b>You define the asset universe. The engine handles the logic.</b><br>"
            "It evaluates momentum, trend and risk, reweights the strongest assets "
            "and aims to allocate capital intelligently instead of passively."
            "<br><br>"
            "<span class='small-note'>"
            "Allocato is not a promise of guaranteed profits. "
            "It is a tool for investors who want to make more conscious decisions — "
            "with more ownership, more transparency and less dependence on standard solutions."
            "</span>"
        ),
        "sidebar_language": "Language",
        "sidebar_settings": "Settings",
        "subscription_header": "🔑 My subscription",
        "subscription_label": "Current plan",
        "free_warning": "**Free plan active**\n\n1 basket • max. 3 years • no asset search",
        "basic_active": "📘 Basic active",
        "pro_active": "🚀 Pro active",
        "lifetime_active": "💎 Lifetime active",
        "upgrade_basic": "Upgrade now → Basic (€19/month)",
        "upgrade_pro": "Upgrade → Pro (€39/month)",
        "upgrade_lifetime": "Get Lifetime (€249)",
        "basket_header": "🧺 My baskets",
        "basket_select": "Active basket",
        "basket_new_name": "New basket name",
        "basket_add": "Create basket",
        "basket_delete": "Delete active basket",
        "basket_rename": "Rename active basket",
        "basket_rename_name": "New name for active basket",
        "basket_limit_free": "Additional baskets are available from Basic upwards.",
        "basket_created": "Basket created: {name}",
        "basket_deleted": "Basket deleted: {name}",
        "basket_renamed": "Basket renamed to: {name}",
        "basket_name_exists": "This basket name already exists.",
        "basket_name_empty": "Please enter a valid basket name.",
        "basket_delete_blocked": "The last basket cannot be deleted.",
        "start_capital": "Starting capital (€)",
        "start_capital_help": "One-time initial investment.",
        "monthly_savings": "Monthly savings (€)",
        "monthly_savings_help": "Additional amount that becomes investable at each month change.",
        "period": "Period",
        "period_help": "For momentum strategies, 3 to 5 years usually makes the most sense.",
        "rebalance": "Rebalancing",
        "rebalance_options": ["Monthly", "Quarterly"],
        "fee": "Transaction costs per trade (%)",
        "fee_help": "Fees and slippage per rebalance.",
        "min_score": "Minimum score for buying",
        "min_score_help": "Only assets with a score above this threshold may be bought.",
        "max_weight": "Max weight per asset (%)",
        "max_weight_help": "Limits the maximum position size per asset.",
        "vol_penalty": "Volatility penalty",
        "vol_penalty_help": "The higher this value, the more strongly volatile assets are penalized.",
        "cash_interest": "Cash interest p.a. (%)",
        "cash_interest_help": "Optional interest on uninvested cash.",
        "regime_filter": "Use market regime filter (SPY > SMA200)",
        "regime_filter_help": "If enabled, the bot only invests offensively when SPY is above its SMA200.",
        "show_debug": "Show debug section",
        "show_debug_help": "Displays raw data and internal details.",
        "aggressive_mode": "Aggressive mode",
        "conviction": "Conviction strength",
        "conviction_help": "The higher it is, the more strongly the best assets are favored.",
        "soft_cash_mode": "Use soft cash mode",
        "soft_cash_mode_help": "If there are no clear signals, the bot does not stay fully in cash.",
        "cash_floor": "Target cash floor (%)",
        "cash_floor_help": "The bot tries to keep at least this much cash under normal conditions.",
        "cash_ceiling": "Target cash ceiling (%)",
        "cash_ceiling_help": "The bot tries not to keep significantly more cash than this under normal conditions.",
        "soft_cash_ratio": "Soft cash investment ratio (%)",
        "soft_cash_ratio_help": "If soft cash mode is active and there are no strong signals, roughly this share remains invested.",
        "visualization": "Visualization",
        "weight_chart_top_n": "Number of assets in weight chart",
        "weight_chart_top_n_help": "Shows only the largest average positions in the weight history. The rest is grouped into 'Other'.",
        "recommended_setups": "⚡ Recommended setups",
        "asset_search_section": "🔎 Asset search",
        "asset_search_query": "Search by ticker, name, ISIN or WKN",
        "asset_search_query_help": "Example: SAP, Apple, DE0007164600 or 716460",
        "asset_search_result": "Select result",
        "add_asset_button": "Add to basket",
        "add_selected_assets_button": "Add all results",
        "remove_asset_section": "➖ Remove asset",
        "remove_asset_select": "Ticker to remove",
        "remove_asset_button": "Remove from basket",
        "search_no_results": "No results found in the integrated asset database.",
        "search_info": "Tip: You can still type tickers manually into the asset basket. Search currently covers the integrated asset database.",
        "search_locked": "🔒 Asset search only in Basic & higher",
        "asset_basket": "Asset universe",
        "tickers_input": "Tickers (one per line)",
        "tickers_input_help": "The bot selects the strongest assets from this universe.",
        "top_n": "Hold top-N assets",
        "top_n_help": "How many of the strongest assets are held at the same time.",
        "preset_quality": "Quality",
        "preset_global": "Global",
        "preset_europe": "Europe",
        "preset_dividend": "Dividend",
        "about_expander": "ℹ️ What is Allocato?",
        "about_text": (
            "Allocato is built for investors who want more control over their capital.\n\n"
            "Do not buy blindly. \n"
            "Do not keep paying fees without knowing what is actually happening inside the product. \n"
            "Do not outsource dividend streams and decisions completely.\n\n"
            "**The idea behind Allocato:**\n"
            "You define your own asset universe. \n"
            "The engine evaluates strength, trend and risk and dynamically allocates capital to the strongest assets.\n\n"
            "This creates a portfolio manager for direct equities and ETFs that aims to:\n"
            "- actively capture opportunities\n"
            "- manage cash deliberately\n"
            "- keep risk more controllable\n"
            "- and make decisions more transparent"
        ),
        "metrics_expander": "🧠 How do I interpret the metrics?",
        "metrics_text": (
            "**Bot ending value** \nFinal value of the active portfolio.\n\n"
            "**Buy & Hold ending value** \nFinal value of a passive benchmark portfolio with the same assets.\n\n"
            "**Outperformance** \nDifference in total return in percentage points. Positive = bot beats Buy & Hold.\n\n"
            "**Exposure** \nAverage share of the portfolio that was invested.\n\n"
            "**Avg. cash ratio** \nAverage cash share.\n\n"
            "**CAGR** \nAnnualized growth rate.\n\n"
            "**Max drawdown** \nLargest historical decline from a previous peak.\n\n"
            "**Volatility** \nHow strongly the portfolio fluctuates.\n\n"
            "**Sharpe ratio** \nReturn relative to volatility. Higher is usually better."
        ),
        "preset_expander": "⚙️ Recommended starter setups",
        "preset_text": (
            "**Quality / direct equity basket**\n"
            "- AAPL\n- SAP.DE\n- SIE.DE\n- ALV.DE\n- MUV2.DE\n- JNJ\n- PG\n\n"
            "Recommendation:\n"
            "- Top-N: 4\n"
            "- Rebalancing: Monthly\n"
            "- Max weight: 55\n"
            "- Conviction strength: 2.0\n"
            "- Volatility penalty: 0.08\n\n"
            "**Large global basket**\n"
            "- ETFs, tech, Europe, dividend names mixed\n\n"
            "Recommendation:\n"
            "- Top-N: 5 to 6\n"
            "- Rebalancing: Monthly\n"
            "- Max weight: 55\n"
            "- Conviction strength: 2.0 to 2.5\n\n"
            "**Europe / Germany**\n"
            "- SAP.DE\n- SIE.DE\n- AIR.DE\n- ALV.DE\n- MUV2.DE\n- BMW.DE\n- RWE.DE\n- DTE.DE\n\n"
            "Recommendation:\n"
            "- Top-N: 5\n"
            "- Rebalancing: Monthly or Quarterly\n"
            "- Cash range: 8 to 18"
        ),
        "calculate": "Calculate portfolio",
        "spinner": "Calculating aggressive dynamic portfolio...",
        "error_min_assets": "Please enter at least 2 tickers.",
        "warning_skip": "No data for {ticker} – skipping.",
        "error_no_data": "No valid price data could be loaded.",
        "error_less_than_2": "Fewer than 2 valid assets remain after loading.",
        "error_too_few_rows": "Not enough valid data after calculating indicators.",
        "warning_spy": "SPY data could not be loaded. Regime filter will be disabled.",
        "status_success": "✅ The bot beats Buy & Hold in this test.",
        "status_neutral": "ℹ️ The bot is close to Buy & Hold. For an active aggressive strategy, that is already decent.",
        "status_bad": "⚠️ The bot is clearly behind Buy & Hold. Check cash ratio, Top-N, conviction strength and rebalancing.",
        "cash_high": "💡 The average cash ratio is above 15%. For a more aggressive mode, you could test soft cash mode, a lower minimum score or a higher max weight.",
        "cash_low": "💡 The average cash ratio is below 5%. That is offensive, but it can increase drawdowns.",
        "metric_bot_end": "Bot ending value",
        "metric_bh_end": "Buy & Hold ending value",
        "metric_outperf": "Outperformance",
        "metric_trades": "Trades",
        "metric_bot_return": "Bot return",
        "metric_bh_return": "Buy & Hold return",
        "metric_exposure": "Exposure",
        "metric_cash": "Avg. cash ratio",
        "metric_cagr": "Bot CAGR",
        "metric_dd": "Bot max drawdown",
        "metric_vol": "Bot volatility",
        "metric_sharpe": "Bot Sharpe",
        "end_capital_success": "Ending capital dynamic bot: {value}",
        "equity_title": "Dynamic portfolio bot vs Buy & Hold",
        "equity_label_bot": "Dynamic bot",
        "equity_label_bh": "Buy & Hold",
        "export_title": "Export",
        "export_caption": "Download equity history, rebalancing log or weight history as CSV.",
        "export_equity": "⬇️ Equity Curve CSV",
        "export_rebal": "⬇️ Rebalancing Log CSV",
        "export_weights": "⬇️ Weights CSV",
        "export_locked": "🔒 Additional exports are available from Basic upwards",
        "interpret_expander": "📌 Interpretation of this result",
        "interpret_text": (
            "**Summary of this test run**\n\n"
            "- **Outperformance:** {outperformance:.2f} percentage points\n"
            "- **Exposure:** {exposure:.1f}%\n"
            "- **Avg. cash ratio:** {cash:.1f}%\n"
            "- **Trades:** {trades}\n"
            "- **Conviction strength:** {conviction:.1f}\n"
            "- **Soft cash mode:** {soft_cash}\n"
            "- **Target cash range:** {cash_floor}% to {cash_ceiling}%\n\n"
            "**Interpretation**\n"
            "- Higher conviction strength concentrates capital more strongly in winners.\n"
            "- A cash ratio between 5% and 15% is the target picture here.\n"
            "- If the number of trades is very high, the bot may be too nervous.\n"
            "- If the cash ratio is too high, returns may be left on the table during strong bull phases.\n"
            "- A lower max drawdown can still make the bot strategically attractive even with lower return."
        ),
        "soft_cash_on": "On",
        "soft_cash_off": "Off",
        "current_weights": "Current portfolio weights",
        "active_positions_empty": "There are currently no active positions in the portfolio.",
        "show_all_assets": "Show all assets including 0% weights",
        "weights_chart_title": "Portfolio weight history",
        "weights_chart_caption": "Showing the largest average positions as well as 'Other' and cash.",
        "weights_chart_inner_title": "Portfolio weights over time",
        "weights_chart_ylabel": "Weight in %",
        "other_label": "Other",
        "latest_selection": "🎯 Most recently selected top assets",
        "last_selection_date": "Latest selection on {date}:",
        "last_target_weights": "Latest target weights:",
        "no_positions_selected": "No positions selected.",
        "no_selection_yet": "No selection available yet.",
        "weights_table": "📊 Weight history as table",
        "weights_rebalance": "🔁 Weights at rebalancing dates",
        "weights_rebalance_empty": "No rebalancing dates available.",
        "rebal_log": "📒 Rebalancing log",
        "rebal_log_empty": "No rebalancing logged yet.",
        "debug_expander": "🛠 Debug / inspect data",
        "debug_used_tickers": "Used tickers:",
        "debug_skipped": "Skipped tickers:",
        "debug_top_n": "Chosen Top-N:",
        "debug_top_n_effective": "Effective Top-N:",
        "debug_max_weight": "Max weight per asset (%):",
        "debug_conviction": "Conviction strength:",
        "debug_soft_cash": "Soft cash mode:",
        "debug_regime": "Regime filter active:",
        "debug_last_prices": "Latest prices:",
        "debug_last_scores": "Latest scores:",
        "info_start": "👈 Choose a setup or enter your asset basket and click 'Calculate portfolio'.",
        "date_col": "Date",
        "regime_ok_col": "Regime OK",
        "selected_assets_col": "Selected assets",
        "turnover_col": "Turnover €",
        "fees_col": "Fees €",
        "cash_eur_col": "Cash €",
        "portfolio_eur_col": "Portfolio €",
        "weights_ticker_col": "Ticker",
        "weights_current_col": "Current weight %",
        "weights_target_col": "Target weight %",
        "bh_cash_label": "Cash (€)",
        "invested_label": "Invested (€)",
        "bot_portfolio_label": "Bot portfolio",
        "buy_hold_label": "Buy & Hold",
        "search_option_format": "{ticker} | {name} | ISIN: {isin} | WKN: {wkn}",
        "added_asset_msg": "{ticker} was added to the asset basket.",
        "added_all_assets_msg": "{count} assets were added to the asset basket.",
        "removed_asset_msg": "{ticker} was removed from the asset basket.",
        "remove_empty_msg": "There is no asset available to remove.",
        "footer_free": "🆓 Free plan • Upgrade for unlimited baskets, 5 years of history and asset search",
    },
}

# =========================
# Helpers
# =========================
def get_basket_limit() -> int:
    return get_max_baskets()

def queue_preset(name: str):
    st.session_state["_pending_preset"] = name

def apply_pending_preset():
    preset_name = st.session_state.get("_pending_preset")
    if preset_name and preset_name in PRESETS:
        for key, value in PRESETS[preset_name].items():
            st.session_state[key] = value
        st.session_state["_pending_preset"] = None

def get_basket_list() -> list[str]:
    raw = st.session_state.get("assets_input", "")
    return [x.strip() for x in raw.splitlines() if x.strip()]

def set_basket_list(tickers: list[str]):
    cleaned = []
    seen = set()
    for t in tickers:
        t = t.strip()
        if t and t not in seen:
            cleaned.append(t)
            seen.add(t)
    st.session_state["assets_input"] = "\n".join(cleaned)

def add_ticker_to_basket(ticker: str):
    basket = get_basket_list()
    if ticker not in basket:
        basket.append(ticker)
        set_basket_list(basket)

def add_multiple_tickers_to_basket(tickers: list[str]):
    basket = get_basket_list()
    existing = set(basket)
    for t in tickers:
        if t not in existing:
            basket.append(t)
            existing.add(t)
    set_basket_list(basket)

def remove_ticker_from_basket(ticker: str):
    basket = [t for t in get_basket_list() if t != ticker]
    set_basket_list(basket)

def filter_asset_catalog(query: str) -> pd.DataFrame:
    if not query.strip():
        return ASSET_CATALOG_DF.copy()
    q = query.strip().lower()
    df = ASSET_CATALOG_DF.copy()
    mask = (
        df["ticker"].str.lower().str.contains(q, na=False) |
        df["name"].str.lower().str.contains(q, na=False) |
        df["isin"].str.lower().str.contains(q, na=False) |
        df["wkn"].str.lower().str.contains(q, na=False)
    )
    return df.loc[mask].copy()

def format_search_option(row: pd.Series, T: dict) -> str:
    return T["search_option_format"].format(
        ticker=row["ticker"],
        name=row["name"],
        isin=row["isin"],
        wkn=row["wkn"],
    )

def sync_active_basket_from_state():
    active = st.session_state.active_basket
    if active not in st.session_state.baskets:
        st.session_state.active_basket = list(st.session_state.baskets.keys())[0]
        active = st.session_state.active_basket
    if st.session_state.last_loaded_basket != active:
        st.session_state.assets_input = st.session_state.baskets.get(active, "")
        st.session_state.last_loaded_basket = active

def save_active_basket_to_state():
    active = st.session_state.active_basket
    st.session_state.baskets[active] = st.session_state.get("assets_input", "")

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
    if mode in ("Monatlich", "Monthly"):
        return current_date.month != prev_date.month
    if mode in ("Quartalsweise", "Quarterly"):
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

def simplify_weight_chart(weights_with_cash: pd.DataFrame, top_k: int, other_label: str):
    cols_no_cash = [c for c in weights_with_cash.columns if c != "Cash"]
    avg_weights = weights_with_cash[cols_no_cash].mean().sort_values(ascending=False)
    keep = avg_weights.head(top_k).index.tolist()
    other = [c for c in cols_no_cash if c not in keep]
    out = pd.DataFrame(index=weights_with_cash.index)
    for c in keep:
        out[c] = weights_with_cash[c]
    if other:
        out[other_label] = weights_with_cash[other].sum(axis=1)
    if "Cash" in weights_with_cash.columns:
        out["Cash"] = weights_with_cash["Cash"]
    return out

def make_export_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

# =========================
# Apply preset / language
# =========================
apply_pending_preset()
lang = st.session_state.get("language", "DE")
T = TRANSLATIONS[lang]

# =========================
# Styling
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
        background: linear-gradient(135deg, rgba(15,23,42,0.92) 0%, rgba(30,41,59,0.92) 100%);
        border: 1px solid rgba(255,255,255,0.08);
        padding: 1rem 1.1rem;
        border-radius: 16px;
        margin-top: 0.8rem;
        margin-bottom: 0.8rem;
        color: rgba(255,255,255,0.95);
    }
    .small-note {
        color: rgba(255,255,255,0.72);
        font-size: 0.95rem;
        line-height: 1.45;
    }
    .section-label {
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        opacity: 0.7;
        margin-bottom: 0.4rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================
# Header / Branding
# =========================
badges_html = "".join([f"<span class='hero-badge'>{badge}</span>" for badge in T["page_badges"]])
st.markdown(
    f"""
    <div class="hero-box">
        <div class="hero-title">🚀 Allocato</div>
        <div class="hero-sub">{T["hero_sub"]}</div>
        {badges_html}
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander(T["warning_expander"]):
    st.markdown(T["warning_text"])

st.markdown(
    f"""
    <div class="story-box">
        <div class="section-label">{T["why_label"]}</div>
        <b>{T["why_title"]}</b><br><br>
        {T["why_text"]}
    </div>
    """,
    unsafe_allow_html=True,
)

# =========================
# Sidebar
# =========================
st.sidebar.selectbox(
    T["sidebar_language"],
    options=["DE", "EN"],
    key="language",
)

lang = st.session_state.get("language", "DE")
T = TRANSLATIONS[lang]

AUTH_T = get_auth_texts(lang)

st.sidebar.header(AUTH_T["account_header"])

if st.session_state.get("auth_logged_in"):
    st.sidebar.success(f'{AUTH_T["logged_in_as"]}: {st.session_state["auth_user_email"]}')
    st.sidebar.caption(AUTH_T["plan_note"])
    if st.sidebar.button(AUTH_T["logout_button"], use_container_width=True):
        logout_user()
        st.rerun()
else:
    st.sidebar.info(AUTH_T["guest_info"])
    login_tab, register_tab = st.sidebar.tabs([AUTH_T["login_tab"], AUTH_T["register_tab"]])

    with login_tab:
        with st.form("login_form", clear_on_submit=False):
            login_email = st.text_input(AUTH_T["email"], key="login_email")
            login_password = st.text_input(AUTH_T["password"], type="password", key="login_password")
            login_submit = st.form_submit_button(AUTH_T["login_button"], use_container_width=True)
        if login_submit:
            ok, message = login_user(login_email, login_password)
            if ok:
                st.sidebar.success(message)
                st.rerun()
            else:
                st.sidebar.error(message)

    with register_tab:
        with st.form("register_form", clear_on_submit=False):
            reg_email = st.text_input(AUTH_T["email"], key="register_email")
            reg_password = st.text_input(AUTH_T["password"], type="password", key="register_password")
            reg_password_2 = st.text_input(AUTH_T["password_repeat"], type="password", key="register_password_repeat")
            reg_submit = st.form_submit_button(AUTH_T["register_button"], use_container_width=True)
        if reg_submit:
            if reg_password != reg_password_2:
                st.sidebar.error(AUTH_T["register_pw_mismatch"])
            else:
                ok, message = create_user(reg_email, reg_password)
                if ok:
                    st.sidebar.success(message)
                else:
                    st.sidebar.error(message)

st.sidebar.header(T["subscription_header"])
tier = get_current_tier()
stored_tier = st.session_state.get("subscription_tier", "Free")
st.sidebar.markdown(f'**{AUTH_T["current_plan"]}:** {TIER_ICONS.get(tier, "🔑")} {tier}')
override_tier = get_test_override_tier(st.session_state.get("auth_user_email", ""))
if override_tier and st.session_state.get("auth_logged_in"):
    st.sidebar.caption(f"🧪 Test-Override aktiv: {override_tier} für {st.session_state.get('auth_user_email', '')}")

if tier == "Free":
    st.sidebar.warning(T["free_warning"])
    st.sidebar.link_button(T["upgrade_basic"], build_checkout_url(STRIPE_BASIC), use_container_width=True)
elif tier == "Basic":
    st.sidebar.info(T["basic_active"])
    st.sidebar.link_button(T["upgrade_pro"], build_checkout_url(STRIPE_PRO), use_container_width=True)
elif tier == "Pro":
    st.sidebar.success(T["pro_active"])
    st.sidebar.link_button(T["upgrade_lifetime"], build_checkout_url(STRIPE_LIFETIME), use_container_width=True)
else:
    st.sidebar.success(T["lifetime_active"])

st.sidebar.caption(AUTH_T["stripe_note"])

if st.session_state.get("auth_logged_in") and st.session_state.get("auth_is_admin") and ALLOW_ADMIN_TIER_OVERRIDE:
    st.sidebar.subheader(AUTH_T["admin_plan"])
    admin_selected_tier = st.sidebar.selectbox(
        AUTH_T["current_plan"],
        options=TIERS,
        index=TIERS.index(tier) if tier in TIERS else 0,
        key="admin_selected_tier",
    )
    if st.sidebar.button(AUTH_T["save_plan"], use_container_width=True):
        update_user_tier(st.session_state["auth_user_email"], admin_selected_tier)
        st.session_state["subscription_tier"] = admin_selected_tier
        enforce_plan_limits()
        save_logged_in_user_state()
        st.sidebar.success(AUTH_T["plan_saved"])
        st.rerun()

st.sidebar.header(T["basket_header"])
basket_names = list(st.session_state.baskets.keys())

st.sidebar.selectbox(
    T["basket_select"],
    options=basket_names,
    key="active_basket",
)

sync_active_basket_from_state()

if tier != "Free":
    st.sidebar.text_input(T["basket_new_name"], key="new_basket_name_input")

    if st.sidebar.button(T["basket_add"], use_container_width=True):
        name = st.session_state.get("new_basket_name_input", "").strip()
        if not name:
            st.sidebar.error(T["basket_name_empty"])
        elif name in st.session_state.baskets:
            st.sidebar.error(T["basket_name_exists"])
        elif len(st.session_state.baskets) >= get_basket_limit():
            st.sidebar.warning(T["basket_limit_free"])
        else:
            save_active_basket_to_state()
            st.session_state.baskets[name] = defaults["assets_input"]
            st.session_state["_pending_active_basket"] = name
            st.session_state["_clear_new_basket_name_input"] = True
            save_logged_in_user_state()
            st.sidebar.success(T["basket_created"].format(name=name))
            st.rerun()

    rename_name = st.sidebar.text_input(T["basket_rename_name"], key="rename_basket_name_input")

    if st.sidebar.button(T["basket_rename"], use_container_width=True):
        old_name = st.session_state.active_basket
        new_name = rename_name.strip()
        if not new_name:
            st.sidebar.error(T["basket_name_empty"])
        elif new_name in st.session_state.baskets and new_name != old_name:
            st.sidebar.error(T["basket_name_exists"])
        else:
            save_active_basket_to_state()
            st.session_state.baskets[new_name] = st.session_state.baskets.pop(old_name)
            st.session_state["_pending_active_basket"] = new_name
            st.session_state["_clear_rename_basket_name_input"] = True
            save_logged_in_user_state()
            st.sidebar.success(T["basket_renamed"].format(name=new_name))
            st.rerun()

    if st.sidebar.button(T["basket_delete"], use_container_width=True):
        if len(st.session_state.baskets) <= 1:
            st.sidebar.warning(T["basket_delete_blocked"])
        else:
            current = st.session_state.active_basket
            st.session_state.baskets.pop(current, None)
            new_active = list(st.session_state.baskets.keys())[0]
            st.session_state["_pending_active_basket"] = new_active
            save_logged_in_user_state()
            st.sidebar.success(T["basket_deleted"].format(name=current))
            st.rerun()
else:
    st.sidebar.caption(T["basket_limit_free"])

st.sidebar.header(T["sidebar_settings"])

initial_capital = st.sidebar.number_input(
    T["start_capital"],
    min_value=0,
    step=1000,
    key="initial_capital",
    help=T["start_capital_help"],
)

monthly_savings = st.sidebar.number_input(
    T["monthly_savings"],
    min_value=0,
    step=50,
    key="monthly_savings",
    help=T["monthly_savings_help"],
)

rebalance_options = T["rebalance_options"]

period_options = ["1y", "2y", "3y"] if tier == "Free" else ["1y", "2y", "3y", "5y"]
if st.session_state.period not in period_options:
    st.session_state.period = period_options[-1]

period = st.sidebar.selectbox(
    T["period"],
    period_options,
    key="period",
    help=T["period_help"],
)

rebalance_freq = st.sidebar.selectbox(
    T["rebalance"],
    rebalance_options,
    key="rebalance_freq",
)

fee_pct_input = st.sidebar.number_input(
    T["fee"],
    min_value=0.0,
    step=0.01,
    format="%.2f",
    key="fee_pct_input",
    help=T["fee_help"],
)
fee_pct = fee_pct_input / 100.0

min_score = st.sidebar.number_input(
    T["min_score"],
    step=0.01,
    format="%.2f",
    key="min_score",
    help=T["min_score_help"],
)

max_weight_pct = st.sidebar.number_input(
    T["max_weight"],
    min_value=1,
    max_value=100,
    step=5,
    key="max_weight_pct",
    help=T["max_weight_help"],
)

vol_penalty = st.sidebar.number_input(
    T["vol_penalty"],
    min_value=0.0,
    step=0.01,
    format="%.2f",
    key="vol_penalty",
    help=T["vol_penalty_help"],
)

cash_interest_pct = st.sidebar.number_input(
    T["cash_interest"],
    min_value=0.0,
    step=0.10,
    format="%.2f",
    key="cash_interest_pct",
    help=T["cash_interest_help"],
)

use_regime_filter = st.sidebar.checkbox(
    T["regime_filter"],
    key="use_regime_filter",
    help=T["regime_filter_help"],
)

show_debug = st.sidebar.checkbox(
    T["show_debug"],
    key="show_debug",
    help=T["show_debug_help"],
)

st.sidebar.subheader(T["aggressive_mode"])

conviction_power = st.sidebar.slider(
    T["conviction"],
    min_value=1.0,
    max_value=4.0,
    step=0.1,
    key="conviction_power",
    help=T["conviction_help"],
)

soft_cash_mode = st.sidebar.checkbox(
    T["soft_cash_mode"],
    key="soft_cash_mode",
    help=T["soft_cash_mode_help"],
)

target_cash_floor_pct = st.sidebar.slider(
    T["cash_floor"],
    min_value=0,
    max_value=20,
    step=1,
    key="target_cash_floor_pct",
    help=T["cash_floor_help"],
)

target_cash_ceiling_pct = st.sidebar.slider(
    T["cash_ceiling"],
    min_value=5,
    max_value=30,
    step=1,
    key="target_cash_ceiling_pct",
    help=T["cash_ceiling_help"],
)

soft_cash_invest_ratio_pct = st.sidebar.slider(
    T["soft_cash_ratio"],
    min_value=20,
    max_value=95,
    step=5,
    key="soft_cash_invest_ratio_pct",
    help=T["soft_cash_ratio_help"],
)

st.sidebar.subheader(T["visualization"])

weight_chart_top_n = st.sidebar.slider(
    T["weight_chart_top_n"],
    min_value=5,
    max_value=15,
    step=1,
    key="weight_chart_top_n",
    help=T["weight_chart_top_n_help"],
)

st.sidebar.subheader(T["recommended_setups"])
col_a, col_b = st.sidebar.columns(2)
col_a.button(T["preset_quality"], on_click=queue_preset, args=("Quality",))
col_b.button(T["preset_global"], on_click=queue_preset, args=("Global",))
col_c, col_d = st.sidebar.columns(2)
col_c.button(T["preset_europe"], on_click=queue_preset, args=("Europa",))
col_d.button(T["preset_dividend"], on_click=queue_preset, args=("Dividend",))

apply_pending_preset()
save_active_basket_to_state()
enforce_plan_limits()
save_logged_in_user_state()

# =========================
# Asset Search / Basket Builder
# =========================
if can_use_asset_search():
    st.sidebar.subheader(T["asset_search_section"])

    search_query = st.sidebar.text_input(
        T["asset_search_query"],
        key="asset_search_query",
        help=T["asset_search_query_help"],
    )

    filtered_assets = filter_asset_catalog(search_query)
    if filtered_assets.empty:
        st.sidebar.info(T["search_no_results"])
    else:
        filtered_assets = filtered_assets.copy()
        filtered_assets["display"] = filtered_assets.apply(lambda row: format_search_option(row, T), axis=1)
        option_map = dict(zip(filtered_assets["display"], filtered_assets["ticker"]))
        display_options = filtered_assets["display"].tolist()

        selected_display = st.sidebar.selectbox(
            T["asset_search_result"],
            options=display_options,
            key="asset_search_select",
        )

        if st.sidebar.button(T["add_asset_button"]):
            ticker_to_add = option_map[selected_display]
            add_ticker_to_basket(ticker_to_add)
            save_active_basket_to_state()
            save_logged_in_user_state()
            st.sidebar.success(T["added_asset_msg"].format(ticker=ticker_to_add))
            st.rerun()

        if st.sidebar.button(T["add_selected_assets_button"]):
            tickers_to_add = filtered_assets["ticker"].tolist()
            add_multiple_tickers_to_basket(tickers_to_add)
            save_active_basket_to_state()
            save_logged_in_user_state()
            st.sidebar.success(T["added_all_assets_msg"].format(count=len(tickers_to_add)))
            st.rerun()

    st.sidebar.caption(T["search_info"])
else:
    st.sidebar.subheader(T["asset_search_section"])
    st.sidebar.caption(T["search_locked"])

basket_list_for_remove = get_basket_list()

st.sidebar.subheader(T["remove_asset_section"])
if basket_list_for_remove:
    remove_choice = st.sidebar.selectbox(
        T["remove_asset_select"],
        options=basket_list_for_remove,
    )
    if st.sidebar.button(T["remove_asset_button"]):
        remove_ticker_from_basket(remove_choice)
        save_active_basket_to_state()
        save_logged_in_user_state()
        st.sidebar.success(T["removed_asset_msg"].format(ticker=remove_choice))
        st.rerun()
else:
    st.sidebar.caption(T["remove_empty_msg"])

st.sidebar.subheader(T["asset_basket"])
assets_input = st.sidebar.text_area(
    T["tickers_input"],
    height=180,
    key="assets_input",
    help=T["tickers_input_help"],
)
save_active_basket_to_state()
save_logged_in_user_state()

input_tickers = [x.strip() for x in assets_input.splitlines() if x.strip()]
asset_count = len(input_tickers)
max_assets = max(1, asset_count)
current_top_n = int(st.session_state.get("top_n", 1))

max_top_n = 4 if tier == "Free" else max_assets
safe_top_n = max(1, min(current_top_n, max_top_n))

if st.session_state.get("top_n") != safe_top_n:
    st.session_state["top_n"] = safe_top_n

if asset_count >= 2:
    top_n = st.sidebar.slider(
        T["top_n"],
        min_value=1,
        max_value=max_top_n,
        value=safe_top_n,
        key="top_n",
        help=T["top_n_help"],
    )
else:
    st.session_state["top_n"] = 1
    top_n = 1
    st.sidebar.number_input(
        T["top_n"],
        min_value=1,
        max_value=1,
        value=1,
        disabled=True,
        help=T["top_n_help"],
    )
    st.sidebar.caption("⚠️ Bitte mindestens 2 Assets im Korb lassen." if lang == "DE" else "⚠️ Please keep at least 2 assets in the basket.")

# =========================
# Explainers
# =========================
with st.expander(T["about_expander"]):
    st.markdown(T["about_text"])

with st.expander(T["metrics_expander"]):
    st.markdown(T["metrics_text"])

with st.expander(T["preset_expander"]):
    st.markdown(T["preset_text"])

# =========================
# Main
# =========================
if st.sidebar.button(T["calculate"], type="primary"):
    save_active_basket_to_state()

    with st.spinner(T["spinner"]):
        tickers = [x.strip() for x in st.session_state.get("assets_input", "").splitlines() if x.strip()]
        if len(tickers) < 2:
            st.error(T["error_min_assets"])
            st.stop()

        series_map, skipped_tickers = load_close_prices(tickers, period)
        for skipped in skipped_tickers:
            st.warning(T["warning_skip"].format(ticker=skipped))

        prices = align_price_series(series_map)
        if prices.empty:
            st.error(T["error_no_data"])
            st.stop()

        tickers = list(prices.columns)
        if len(tickers) < 2:
            st.error(T["error_less_than_2"])
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
            st.error(T["error_too_few_rows"])
            st.stop()

        regime_ok_series = pd.Series(True, index=prices.index)
        if use_regime_filter:
            spy_close = load_single_close("SPY", period)
            if spy_close.empty:
                st.warning(T["warning_spy"])
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
                        for tkr in weights.index:
                            target_values[tkr] = investable_capital * weights[tkr]

                        target_weights_log[date] = {
                            tkr: (target_values[tkr] / total_equity_before) for tkr in weights.index
                        }
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
                                power=conviction_power,
                            )
                            if len(fallback_selected) > 0:
                                investable_capital = total_equity_before * invest_ratio
                                for tkr in fallback_weights.index:
                                    target_values[tkr] = investable_capital * fallback_weights[tkr]
                                target_weights_log[date] = {
                                    tkr: (target_values[tkr] / total_equity_before) for tkr in fallback_weights.index
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
                            power=max(1.5, conviction_power - 0.5),
                        )
                        if len(fallback_selected) > 0:
                            investable_capital = total_equity_before * invest_ratio
                            for tkr in fallback_weights.index:
                                target_values[tkr] = investable_capital * fallback_weights[tkr]
                            target_weights_log[date] = {
                                tkr: (target_values[tkr] / total_equity_before) for tkr in fallback_weights.index
                            }
                            selected_assets_log[date] = fallback_selected.index.tolist()
                        else:
                            target_weights_log[date] = {}
                            selected_assets_log[date] = []
                    else:
                        target_weights_log[date] = {}
                        selected_assets_log[date] = []

                turnover = sum(abs(target_values[tkr] - current_values[tkr]) for tkr in tickers)
                fees = turnover * fee_pct
                total_equity_after_fees = max(total_equity_before - fees, 0.0)

                if total_equity_before > 0:
                    fee_adjustment = total_equity_after_fees / total_equity_before
                    for tkr in tickers:
                        target_values[tkr] *= fee_adjustment

                for tkr in tickers:
                    price = current_prices[tkr]
                    new_shares = target_values[tkr] / price if price > 0 else 0.0
                    if abs(new_shares - shares[tkr]) > 1e-12:
                        trade_count += 1
                    shares[tkr] = new_shares

                invested_value = sum(shares[tkr] * current_prices[tkr] for tkr in tickers)
                cash = total_equity_after_fees - invested_value

                rebalance_log.append({
                    T["date_col"]: date,
                    T["regime_ok_col"]: regime_today_ok,
                    T["selected_assets_col"]: ", ".join(selected_assets_log.get(date, [])) if selected_assets_log.get(date, []) else "Cash",
                    T["turnover_col"]: float(turnover),
                    T["fees_col"]: float(fees),
                    T["cash_eur_col"]: float(cash),
                    T["portfolio_eur_col"]: float(total_equity_after_fees),
                })

            invested_value = sum(shares[tkr] * current_prices[tkr] for tkr in tickers)
            total_value = invested_value + cash

            equity_bot.loc[date] = total_value
            cash_bot.loc[date] = cash
            invested_bot.loc[date] = invested_value

            if total_value > 0:
                for tkr in tickers:
                    weight_history.loc[date, tkr] = (shares[tkr] * current_prices[tkr]) / total_value * 100
                cash_weight_history.loc[date] = cash / total_value * 100
            else:
                for tkr in tickers:
                    weight_history.loc[date, tkr] = 0.0
                cash_weight_history.loc[date] = 0.0

        # Benchmark
        bh_shares = {tkr: 0.0 for tkr in tickers}
        equity_bh = pd.Series(index=dates, dtype=float)
        first_prices = prices.iloc[0]
        bh_weight = 1.0 / len(tickers)

        for tkr in tickers:
            bh_shares[tkr] = (initial_capital * bh_weight) / first_prices[tkr]

        for i, date in enumerate(dates):
            current_prices = prices.loc[date]
            if i > 0:
                prev_date = dates[i - 1]
                if date.month != prev_date.month:
                    for tkr in tickers:
                        bh_shares[tkr] += (monthly_savings * bh_weight) / current_prices[tkr]

            bh_value = sum(bh_shares[tkr] * current_prices[tkr] for tkr in tickers)
            equity_bh.loc[date] = bh_value

        bot_metrics = compute_metrics(equity_bot)
        bh_metrics = compute_metrics(equity_bh)
        exposure = (invested_bot / equity_bot.replace(0, np.nan)).mean() * 100
        avg_cash_quote = (cash_bot / equity_bot.replace(0, np.nan)).mean() * 100
        outperformance_pp = bot_metrics["total_return"] - bh_metrics["total_return"]

        last_prices = prices.iloc[-1]
        final_equity = equity_bot.iloc[-1]
        current_weights = {}

        for tkr in tickers:
            current_weights[tkr] = (shares[tkr] * last_prices[tkr] / final_equity) * 100 if final_equity > 0 else 0.0

        weights_df = pd.DataFrame({
            T["weights_ticker_col"]: list(current_weights.keys()),
            T["weights_current_col"]: list(current_weights.values()),
        }).sort_values(T["weights_current_col"], ascending=False)

        rebalance_df = pd.DataFrame(rebalance_log)
        weights_with_cash = weight_history.copy()
        weights_with_cash["Cash"] = cash_weight_history
        weights_with_cash = weights_with_cash.fillna(0)

        weights_chart_df = simplify_weight_chart(
            weights_with_cash,
            top_k=weight_chart_top_n,
            other_label=T["other_label"],
        )

        rebalance_dates = [entry[T["date_col"]] for entry in rebalance_log]
        weights_rebalance_only = weights_with_cash.loc[
            weights_with_cash.index.intersection(rebalance_dates)
        ].copy()

        # Status
        if outperformance_pp > 0:
            st.success(T["status_success"])
        elif outperformance_pp > -10:
            st.info(T["status_neutral"])
        else:
            st.warning(T["status_bad"])

        if avg_cash_quote > 15:
            st.info(T["cash_high"])
        elif avg_cash_quote < 5:
            st.info(T["cash_low"])

        # Metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(T["metric_bot_end"], f"{equity_bot.iloc[-1]:,.2f} €")
        c2.metric(T["metric_bh_end"], f"{equity_bh.iloc[-1]:,.2f} €")
        c3.metric(T["metric_outperf"], f"{outperformance_pp:.2f} pp")
        c4.metric(T["metric_trades"], f"{trade_count}")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric(T["metric_bot_return"], f"{bot_metrics['total_return']:.2f}%")
        c6.metric(T["metric_bh_return"], f"{bh_metrics['total_return']:.2f}%")
        c7.metric(T["metric_exposure"], f"{exposure:.1f}%")
        c8.metric(T["metric_cash"], f"{avg_cash_quote:.1f}%")

        c9, c10, c11, c12 = st.columns(4)
        c9.metric(T["metric_cagr"], f"{bot_metrics['cagr']:.2f}%")
        c10.metric(T["metric_dd"], f"{bot_metrics['max_dd']:.2f}%")
        c11.metric(T["metric_vol"], f"{bot_metrics['volatility']:.2f}%")
        c12.metric(T["metric_sharpe"], f"{bot_metrics['sharpe']:.2f}")

        st.success(T["end_capital_success"].format(value=f"{equity_bot.iloc[-1]:,.2f} €"))

        # Equity chart
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(equity_bot.index, equity_bot, label=T["equity_label_bot"], linewidth=2.5, color="lime")
        ax.plot(equity_bh.index, equity_bh, label=T["equity_label_bh"], linewidth=2.0, color="gray")
        ax.set_title(T["equity_title"])
        ax.legend()
        ax.grid(True, alpha=0.25)
        st.pyplot(fig)

        # Export
        st.markdown(f"### {T['export_title']}")
        st.caption(T["export_caption"])

        export_equity_df = pd.DataFrame({
            T["date_col"]: equity_bot.index,
            T["bot_portfolio_label"]: equity_bot.values,
            T["buy_hold_label"]: equity_bh.values,
            T["bh_cash_label"]: cash_bot.values,
            T["invested_label"]: invested_bot.values,
        })

        equity_csv = make_export_csv(export_equity_df)
        rebal_csv = make_export_csv(rebalance_df) if not rebalance_df.empty else b""
        weights_csv = make_export_csv(
            weights_with_cash.reset_index().rename(columns={"index": T["date_col"]})
        )

        col_exp1, col_exp2, col_exp3 = st.columns(3)

        col_exp1.download_button(
            label=T["export_equity"],
            data=equity_csv,
            file_name="allocato_equity_curve.csv",
            mime="text/csv",
            use_container_width=True,
        )

        if tier == "Free":
            col_exp2.caption(T["export_locked"])
            col_exp3.caption(T["export_locked"])
        else:
            col_exp2.download_button(
                label=T["export_rebal"],
                data=rebal_csv,
                file_name="allocato_rebalancing_log.csv",
                mime="text/csv",
                disabled=rebalance_df.empty,
                use_container_width=True,
            )
            col_exp3.download_button(
                label=T["export_weights"],
                data=weights_csv,
                file_name="allocato_weight_history.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with st.expander(T["interpret_expander"]):
            st.markdown(
                T["interpret_text"].format(
                    outperformance=outperformance_pp,
                    exposure=exposure,
                    cash=avg_cash_quote,
                    trades=trade_count,
                    conviction=conviction_power,
                    soft_cash=T["soft_cash_on"] if soft_cash_mode else T["soft_cash_off"],
                    cash_floor=target_cash_floor_pct,
                    cash_ceiling=target_cash_ceiling_pct,
                )
            )

        st.subheader(T["current_weights"])
        active_weights_df = weights_df[weights_df[T["weights_current_col"]] > 0].copy()
        if not active_weights_df.empty:
            st.dataframe(active_weights_df.round(2), use_container_width=True)
        else:
            st.info(T["active_positions_empty"])

        with st.expander(T["show_all_assets"]):
            st.dataframe(weights_df.round(2), use_container_width=True)

        st.subheader(T["weights_chart_title"])
        st.caption(T["weights_chart_caption"])

        chart_cols = list(weights_chart_df.columns)
        base_colors = list(plt.cm.tab20.colors)
        colors = []
        normal_idx = 0

        for col in chart_cols:
            if col == "Cash":
                colors.append((0.50, 0.50, 0.50))
            elif col == T["other_label"]:
                colors.append((0.80, 0.80, 0.80))
            else:
                colors.append(base_colors[normal_idx % len(base_colors)])
                normal_idx += 1

        fig2, ax2 = plt.subplots(figsize=(12, 6))
        ax2.stackplot(
            weights_chart_df.index,
            *[weights_chart_df[col] for col in chart_cols],
            labels=chart_cols,
            colors=colors,
            alpha=0.95,
        )
        ax2.set_title(T["weights_chart_inner_title"])
        ax2.set_ylabel(T["weights_chart_ylabel"])
        ax2.set_ylim(0, 100)
        ax2.legend(loc="upper left", bbox_to_anchor=(1.01, 1))
        ax2.grid(True, alpha=0.25)
        st.pyplot(fig2)

        with st.expander(T["latest_selection"]):
            if selected_assets_log:
                last_selection_date = max(selected_assets_log.keys())
                st.write(T["last_selection_date"].format(date=last_selection_date.date()))
                st.write(selected_assets_log[last_selection_date])

                st.write(T["last_target_weights"])
                last_weights = target_weights_log.get(last_selection_date, {})
                if last_weights:
                    last_weights_df = pd.DataFrame({
                        T["weights_ticker_col"]: list(last_weights.keys()),
                        T["weights_target_col"]: [v * 100 for v in last_weights.values()],
                    }).sort_values(T["weights_target_col"], ascending=False)
                    st.dataframe(last_weights_df.round(2), use_container_width=True)
                else:
                    st.write(T["no_positions_selected"])
            else:
                st.write(T["no_selection_yet"])

        with st.expander(T["weights_table"]):
            st.dataframe(weights_with_cash.round(2), use_container_width=True)

        with st.expander(T["weights_rebalance"]):
            if not weights_rebalance_only.empty:
                st.dataframe(weights_rebalance_only.round(2), use_container_width=True)
            else:
                st.write(T["weights_rebalance_empty"])

        with st.expander(T["rebal_log"]):
            if not rebalance_df.empty:
                st.dataframe(rebalance_df.round(2), use_container_width=True)
            else:
                st.write(T["rebal_log_empty"])

        if show_debug:
            with st.expander(T["debug_expander"]):
                st.write(T["debug_used_tickers"], tickers)
                st.write(T["debug_skipped"], skipped_tickers)
                st.write(T["debug_top_n"], top_n)
                st.write(T["debug_top_n_effective"], effective_top_n)
                st.write(T["debug_max_weight"], max_weight_pct)
                st.write(T["debug_conviction"], conviction_power)
                st.write(T["debug_soft_cash"], soft_cash_mode)
                st.write(T["debug_regime"], use_regime_filter)
                st.write(T["debug_last_prices"])
                st.dataframe(prices.tail(), use_container_width=True)
                st.write(T["debug_last_scores"])
                st.dataframe(raw_score.tail(), use_container_width=True)

        save_logged_in_user_state()

        if tier == "Free":
            st.caption(T["footer_free"])

else:
    st.info(T["info_start"])
    if get_current_tier() == "Free":
        st.caption(T["footer_free"])
