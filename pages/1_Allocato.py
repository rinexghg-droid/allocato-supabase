# WICHTIG: Für diesen Code muss `plotly` in requirements.txt ergänzt werden, z. B. mit: plotly
import json
import hmac
import hashlib
import re
from datetime import datetime, timedelta
from urllib.parse import quote
from urllib import request as urllib_request, error as urllib_error

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from supabase import create_client

st.set_page_config(page_title="Allocato", layout="wide")

# =========================
# Subscription / Pricing Links
# =========================
STRIPE_BASIC = "https://buy.stripe.com/fZu9AN2mIeJu3oRbNcfjG02"
STRIPE_PRO = "https://buy.stripe.com/3cIaERf9udFq2kN04ufjG01"
STRIPE_LIFETIME = "https://buy.stripe.com/8x2dR37H21WI4sV3gGfjG00"

APP_BASE_URL = "https://allocato-finance.streamlit.app"
LANDING_PUBLIC_URL = APP_BASE_URL
BOT_PUBLIC_URL = f"{APP_BASE_URL}/Allocato"

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
TEST_ACCOUNT_TIER_OVERRIDES = {
    "rinexghg@gmail.com": "Lifetime",
}

ALLOW_ADMIN_TIER_OVERRIDE = True


def build_checkout_url(base_url: str) -> str:
    email = normalize_email(st.session_state.get("auth_user_email", ""))
    if email:
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}locked_prefilled_email={quote(email)}"
    return base_url

def get_checkout_login_required_text(lang: str) -> str:
    if lang == "EN":
        return "🚀 Almost there — please log in or register first so your upgrade lands on the right Allocato account."
    return "🚀 Fast da – logge dich bitte erst ein oder registriere dich, damit dein Upgrade sauber beim richtigen Allocato-Account landet."

def get_login_redirect_button_text(lang: str) -> str:
    return "✨ Log in / register now" if lang == "EN" else "✨ Jetzt einloggen / registrieren"


def get_subscription_summary_text(tier: str, lang: str) -> str:
    summaries = {
        "DE": {
            "Free": "1 Korb, bis zu 3 Jahre Historie und ein kompakter Einstieg in Allocato.",
            "Basic": "Unbegrenzte Körbe, 5 Jahre Historie, CSV-Exports und globale Asset-Suche.",
            "Pro": "Alles aus Basic plus mehr Komfort, priorisierte Updates und mehr Premium-Feeling.",
            "Lifetime": "Einmal freischalten und dauerhaft alle starken Allocato-Vorteile genießen.",
        },
        "EN": {
            "Free": "1 basket, up to 3 years of history and a compact entry into Allocato.",
            "Basic": "Unlimited baskets, 5 years of history, CSV exports and global asset search.",
            "Pro": "Everything from Basic plus more comfort, prioritized updates and extra premium vibes.",
            "Lifetime": "Unlock once and keep enjoying the full Allocato experience for the long run.",
        },
    }
    return summaries.get(lang, summaries["DE"]).get(tier, "")

def get_default_subscription_expiry(tier: str) -> str:
    if tier == "Lifetime":
        return "Lifetime"
    if tier == "Free":
        return ""
    return (datetime.utcnow() + timedelta(days=30)).date().isoformat()

def ensure_subscription_expiry_for_tier(tier: str):
    current_value = str(st.session_state.get("subscription_expires_at", "") or "").strip()
    if tier == "Lifetime":
        st.session_state["subscription_expires_at"] = "Lifetime"
        return
    if tier == "Free":
        st.session_state["subscription_expires_at"] = ""
        return
    if not current_value or current_value.lower() == "lifetime":
        st.session_state["subscription_expires_at"] = get_default_subscription_expiry(tier)

def format_subscription_expires_at(value: str | None, lang: str) -> str:
    if not value:
        return "—"
    value_str = str(value).strip()
    if value_str.lower() == "lifetime":
        return "Lifetime Access" if lang == "EN" else "Lifetime-Zugang"
    try:
        dt = datetime.fromisoformat(value_str.replace("Z", ""))
    except Exception:
        try:
            dt = datetime.strptime(value_str, "%Y-%m-%d")
        except Exception:
            return value_str
    if lang == "EN":
        return dt.strftime("%B %d, %Y")
    months = [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember"
    ]
    return f"{dt.day}. {months[dt.month - 1]} {dt.year}"

def ensure_auth_session_state():
    auth_defaults = {
        "subscription_tier": "Free",
        "subscription_expires_at": "",
        "auth_logged_in": False,
        "auth_user_email": "",
        "auth_loaded_for": "",
        "auth_is_admin": False,
        "cancel_subscription_confirmed": False,
        "last_calc_results": None,
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
            .select("email,password_hash,subscription_tier,subscription_expires_at,state_json,created_at,updated_at")
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
        st.session_state["auth_logged_in"] = True
        st.session_state["auth_user_email"] = normalized
        st.session_state["auth_is_admin"] = normalized in ADMIN_EMAILS
        st.session_state["subscription_tier"] = "Free"
        st.session_state["subscription_expires_at"] = ""
        st.session_state["auth_loaded_for"] = ""
        return True, "Registrierung erfolgreich."
    except Exception as e:
        return False, f"Registrierung fehlgeschlagen: {e}"

def update_user_tier(email: str, new_tier: str):
    normalized = normalize_email(email)
    if new_tier not in TIERS:
        return
    try:
        now = datetime.utcnow().isoformat()
        expires_at = get_default_subscription_expiry(new_tier)
        supabase = get_supabase_client()
        update_payload = {
            "subscription_tier": new_tier,
            "updated_at": now,
        }
        try:
            update_payload["subscription_expires_at"] = expires_at
        except Exception:
            pass
        supabase.table("users").update(update_payload).eq("email", normalized).execute()
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
    st.session_state["subscription_expires_at"] = row.get("subscription_expires_at") or get_default_subscription_expiry(st.session_state["subscription_tier"])
    ensure_subscription_expiry_for_tier(st.session_state["subscription_tier"])
    st.session_state["auth_loaded_for"] = ""
    return True, "Erfolgreich eingeloggt."

def logout_user():
    save_logged_in_user_state()
    st.session_state["auth_logged_in"] = False
    st.session_state["auth_user_email"] = ""
    st.session_state["auth_loaded_for"] = ""
    st.session_state["auth_is_admin"] = False
    st.session_state["subscription_tier"] = "Free"
    st.session_state["subscription_expires_at"] = ""

def update_user_password(email: str, current_password: str, new_password: str) -> tuple[bool, str]:
    normalized = normalize_email(email)
    if len(new_password) < 8:
        return False, "Das neue Passwort muss mindestens 8 Zeichen lang sein."
    try:
        row = get_user_row(normalized)
    except Exception as e:
        return False, f"Passwort-Update fehlgeschlagen: {e}"
    if row is None:
        return False, "Kein Konto mit dieser E-Mail gefunden."
    if not verify_password(current_password, row["password_hash"]):
        return False, "Das aktuelle Passwort ist nicht korrekt."
    try:
        now = datetime.utcnow().isoformat()
        supabase = get_supabase_client()
        supabase.table("users").update({
            "password_hash": hash_password(new_password),
            "updated_at": now,
        }).eq("email", normalized).execute()
        return True, "✨ Passwort erfolgreich aktualisiert."
    except Exception as e:
        return False, f"Passwort-Update fehlgeschlagen: {e}"

def update_user_email(current_email: str, password: str, new_email: str) -> tuple[bool, str]:
    normalized_current = normalize_email(current_email)
    normalized_new = normalize_email(new_email)

    if normalized_current == normalized_new:
        return False, "Die neue E-Mail ist identisch mit der aktuellen."
    if not is_valid_email(normalized_new):
        return False, "Bitte eine gültige neue E-Mail-Adresse eingeben."

    try:
        current_row = get_user_row(normalized_current)
    except Exception as e:
        return False, f"E-Mail-Update fehlgeschlagen: {e}"

    if current_row is None:
        return False, "Kein Konto mit dieser E-Mail gefunden."
    if not verify_password(password, current_row["password_hash"]):
        return False, "Das Passwort ist nicht korrekt."

    try:
        existing_target = get_user_row(normalized_new)
        if existing_target:
            return False, "Diese neue E-Mail ist bereits registriert."
    except Exception as e:
        return False, f"E-Mail-Update fehlgeschlagen: {e}"

    try:
        now = datetime.utcnow().isoformat()
        supabase = get_supabase_client()
        supabase.table("users").update({
            "email": normalized_new,
            "updated_at": now,
        }).eq("email", normalized_current).execute()
        st.session_state["auth_user_email"] = normalized_new
        st.session_state["auth_loaded_for"] = ""
        st.session_state["auth_is_admin"] = normalized_new in ADMIN_EMAILS
        return True, "✨ E-Mail erfolgreich aktualisiert."
    except Exception as e:
        return False, f"E-Mail-Update fehlgeschlagen: {e}"

def get_auth_texts(lang: str) -> dict:
    if lang == "EN":
        return {
            "account_header": "👤 Account",
            "guest_info": "You are cruising through Allocato as a guest right now. Log in or register to save baskets, upgrades and your setup permanently.",
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
            "account_magic_title": "✨ Your Allocato cockpit",
            "account_guest_title": "🌟 Ready for your account?",
            "upgrade_title": "🚀 Upgrade your setup",
            "upgrade_hint": "Choose your pace — Basic, Pro or Lifetime.",
            "password_change_title": "🔐 Change password",
            "password_current": "Current password",
            "password_new": "New password",
            "password_new_repeat": "Repeat new password",
            "password_change_button": "Save new password",
            "password_change_mismatch": "The new passwords do not match.",
            "email_change_title": "📬 Change email",
            "email_new": "New email address",
            "email_change_button": "Save new email",
            "security_note": "Your account area is where plan, login and security stay in sync.",
            "login_gate_caption": "Log in once and your upgrade will be attached to the right account instantly.",
            "plan_free_badge": "🆓 Free mode",
            "plan_basic_badge": "📘 Basic active",
            "plan_pro_badge": "🚀 Pro active",
            "plan_lifetime_badge": "💎 Lifetime active",
            "manage_subscription_title": "💳 Manage subscription",
            "subscription_spotlight": "Your plan cockpit",
            "upgrade_microcopy": "Upgrade buttons stay ready — unlock them with your login.",
            "lifetime_access": "Lifetime Access",
            "cancel_subscription_final": "Cancel now and return to Free",
            "active_until": "Active until",
            "plan_includes": "What's included",
            "cancel_subscription_button": "🛑 Cancel subscription",
            "cancel_subscription_confirm": "Yes, I really want to cancel this subscription.",
            "cancel_subscription_warning": "Careful: canceling sends your plan back to Free in this demo flow.",
            "cancel_subscription_success": "All set — your subscription was canceled and your account is now back on Free.",
            "cancel_subscription_need_confirm": "Please confirm the cancellation first.",
            "admin_plan": "Admin plan control",
            "save_plan": "Save plan",
            "plan_saved": "Plan saved.",
            "register_pw_mismatch": "Passwords do not match.",
            "auth_required_export": "Please log in and upgrade to use these exports permanently.",
            "stripe_note": "💳 Checkout is ready. Payments are linked to your account automatically once the webhook gives the green light.",
        }
    return {
        "account_header": "👤 Konto",
        "guest_info": "Du surfst gerade als Gast durch Allocato. Logge dich ein oder registriere dich, damit Körbe, Upgrades und dein Setup dauerhaft gespeichert bleiben.",
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
        "account_magic_title": "✨ Dein Allocato-Cockpit",
        "account_guest_title": "🌟 Bereit für deinen Account?",
        "upgrade_title": "🚀 Upgrade dein Setup",
        "upgrade_hint": "Wähle dein Tempo — Basic, Pro oder Lifetime.",
        "password_change_title": "🔐 Passwort ändern",
        "password_current": "Aktuelles Passwort",
        "password_new": "Neues Passwort",
        "password_new_repeat": "Neues Passwort wiederholen",
        "password_change_button": "Neues Passwort speichern",
        "password_change_mismatch": "Die neuen Passwörter stimmen nicht überein.",
        "email_change_title": "📬 E-Mail ändern",
        "email_new": "Neue E-Mail-Adresse",
        "email_change_button": "Neue E-Mail speichern",
        "security_note": "Hier bleiben Plan, Login und Sicherheit sauber auf einer Spur.",
        "login_gate_caption": "Einmal kurz einloggen — dann hängt sich dein Upgrade direkt an den richtigen Account.",
        "plan_free_badge": "🆓 Free-Modus",
        "plan_basic_badge": "📘 Basic aktiv",
        "plan_pro_badge": "🚀 Pro aktiv",
        "plan_lifetime_badge": "💎 Lifetime aktiv",
        "manage_subscription_title": "💳 Mein Abo verwalten",
        "subscription_spotlight": "Dein Plan-Cockpit",
        "upgrade_microcopy": "Die Upgrade-Buttons sind immer sichtbar — mit Login werden sie direkt scharf.",
        "lifetime_access": "Lifetime-Zugang",
        "cancel_subscription_final": "Jetzt kündigen und auf Free zurückfallen",
        "active_until": "Aktiv bis",
        "plan_includes": "Was enthalten ist",
        "cancel_subscription_button": "🛑 Abo kündigen",
        "cancel_subscription_confirm": "Ja, ich möchte dieses Abo wirklich kündigen.",
        "cancel_subscription_warning": "Achtung: In diesem Demo-Flow wird dein Plan bei Kündigung direkt auf Free zurückgesetzt.",
        "cancel_subscription_success": "Alles klar — dein Abo wurde beendet und dein Account ist jetzt wieder auf Free gesetzt.",
        "cancel_subscription_need_confirm": "Bitte bestätige die Kündigung zuerst.",
        "admin_plan": "Admin-Plansteuerung",
        "save_plan": "Plan speichern",
        "plan_saved": "Plan gespeichert.",
        "register_pw_mismatch": "Die Passwörter stimmen nicht überein.",
        "auth_required_export": "Bitte logge dich ein und upgrade deinen Account, um diese Exporte dauerhaft zu nutzen.",
        "stripe_note": "💳 Checkout ist bereit. Zahlungen werden deinem Account automatisch sauber zugeordnet, sobald der Webhook grünes Licht gibt.",
    }

ensure_auth_session_state()

def maybe_handle_payment_query(lang: str):
    payment_status = str(st.query_params.get("payment", "")).strip().lower()
    marker = f"{payment_status}:{st.session_state.get('auth_user_email', 'guest')}"
    if not payment_status or st.session_state.get("_last_payment_marker") == marker:
        return

    if payment_status == "success":
        if st.session_state.get("auth_logged_in"):
            st.session_state["auth_loaded_for"] = ""
            load_logged_in_user_state()
            enforce_plan_limits()
        st.success(
            "🎉 Zahlung erfolgreich! Dein Upgrade wurde zurück in Allocato eskortiert."
            if lang == "DE"
            else "🎉 Payment successful! Your upgrade has been escorted back into Allocato."
        )
    elif payment_status == "cancel":
        st.info(
            "😌 Checkout abgebrochen. Alles gut — dein Depot wartet geduldig auf die nächste Runde."
            if lang == "DE"
            else "😌 Checkout canceled. No worries — your portfolio is patiently waiting for the next round."
        )

    st.session_state["_last_payment_marker"] = marker


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
    return "3y" if get_current_tier() == "Free" else "max"

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
    "max_weight_pct": 40,
    "vol_penalty": 0.08,
    "cash_interest_pct": 0.00,
    "use_regime_filter": False,
    "show_debug": False,
    "conviction_power": 2.0,
    "soft_cash_mode": True,
    "target_cash_floor_pct": 1,
    "target_cash_ceiling_pct": 8,
    "soft_cash_invest_ratio_pct": 95,
    "weight_chart_top_n": 8,
    "top_n": 8,
    "assets_input": "AAPL\nSAP.DE\nSIE.DE\nALV.DE\nMUV2.DE\nJNJ\nPG",
    "asset_search_query": "",
    "asset_search_select": None,
    "benchmark_etfs_input": "SPY\nQQQ",
    "simulate_taxes_de": False,
    "enable_ki_explanations": False,
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
    "benchmark_etfs_input",
    "simulate_taxes_de",
    "enable_ki_explanations",
    "subscription_expires_at",
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
    st.session_state["subscription_expires_at"] = row.get("subscription_expires_at") or get_default_subscription_expiry(st.session_state["subscription_tier"])
    ensure_subscription_expiry_for_tier(st.session_state["subscription_tier"])
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
ensure_subscription_expiry_for_tier(st.session_state.get("subscription_tier", "Free"))
maybe_handle_payment_query(st.session_state.get("language", "DE"))

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
        "page_badges": ["Dynamic Allocation ⚡", "Direct Equity Ownership 💎", "Buy & Hold Benchmark 📊", "Launch Version 5.2.0 🚀"],
        "hero_sub": (
            "Dein smarter Portfolio-Manager für Direktaktien. "
            "Nicht blind kaufen. Nicht unnötig Gebühren zahlen. "
            "Nicht darauf hoffen, dass irgendein Produkt schon irgendwie passt."
            "<br><br>"
            "Allocato hilft dir, ein dynamisch gesteuertes Portfolio aufzubauen, "
            "in dem du <b>Kontrolle, Transparenz und Dividenden direkt selbst</b> behältst — mit etwas mehr Biss und deutlich weniger Excel-Müdigkeit."
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
        "rebalance_options": ["Aus", "Jährlich", "Quartalsweise", "Monatlich", "Alle 2 Jahre", "Alle 5 Jahre"],
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
        "warning_partial_history": "{ticker} hat nur begrenzte Historie, wird aber trotzdem verwendet.",
        "warning_removed_after_align": "{ticker} wurde wegen zu vieler Datenlücken nach der Bereinigung entfernt.",
        "warning_align_reduced": "Die gemeinsame Historie wurde automatisch bereinigt, damit der Vergleich stabil bleibt.",
        "metric_paid_in": "Kumulative Einzahlungen",
        "equity_label_paid_in": "Kumulative Einzahlungen",
        "benchmark_section": "📊 Benchmark-ETFs hinzufügen",
        "benchmark_input": "Benchmark-ETF Ticker (einer pro Zeile)",
        "benchmark_input_help": "Beispiele: SPY, QQQ, VWCE.DE, URTH, IWDA.AS",
        "benchmark_added_title": "Zusätzliche ETF-Benchmarks",
        "simulate_taxes_de": "Steuern DE simulieren (26,375 %)",
        "simulate_taxes_de_help": "Simuliert Abgeltungsteuer auf realisierte Gewinne mit 1.000 € Freistellungsbetrag pro Jahr und Average-Cost-Methode.",
        "enable_ki_explanations": "KI-Erklärungen aktivieren",
        "enable_ki_explanations_help": "Zeigt kurze Dummy-Erklärungen zu den zuletzt ausgewählten Top-Assets an.",
        "ki_explanations_title": "🤖 KI-Erklärungen zu den Top-Assets",
        "ki_explanations_missing_key": "Es werden lokale Dummy-Erklärungen verwendet – keine API-Kosten.",
        "taxes_col": "Steuern €",
        "tax_note_title": "Steuern & Realismus",
        "tax_note_text": "- Aktivierte Steuern belasten realisierte Gewinne des Bots sofort über Cash.\n- Verwendet wird die Average-Cost-Methode für Einstandspreise.\n- Pro Kalenderjahr werden automatisch 1.000 € Freistellungsbetrag berücksichtigt.\n- Buy & Hold realisiert in dieser Simulation kaum Gewinne, weil Positionen fast nie verkauft werden. Dadurch wird der Vergleich realistischer und der Bot weniger künstlich bevorzugt.",
        "buy_hold_action_col": "Buy & Hold Aktion",
        "annual_returns_title": "📅 Jährliche Renditen",
        "annual_returns_year": "Jahr",
        "annual_returns_bot": "Bot %",
        "annual_returns_bh": "Buy & Hold %",
        "rebal_buys_col": "Käufe",
        "rebal_sells_col": "Verkäufe",
        "rebal_reason_col": "Logik",
        "interpret_why_title": "Warum der Bot besser sein kann",
        "interpret_why_text": "- **Cash-Management:** In schwächeren Marktphasen wird nicht stumpf immer voll investiert.\n- **Rebalancing-Logik:** Gewinner können nach festen Regeln neu gewichtet werden, statt ewig zufällig groß zu bleiben.\n- **Conviction-Weighting:** Stärkere Signale bekommen mehr Kapital, schwächere weniger.\n- **Trend-Filter:** Aktien unter ihrem Trend verlieren an Priorität.\n- **Verlustbegrenzung durch Auswahl:** Der Bot hält nicht automatisch den ganzen Korb gleichgewichtet wie Buy & Hold.\n- **Buy & Hold investiert jeden Monat die Sparrate gleichmäßig auf alle verfügbaren Titel – daher bei großen Körben stark verdünnt.",
        "load_status_start": "Lade Kursdaten für {count} Assets ...",
        "load_status_done": "{loaded} Assets geladen • {partial} mit begrenzter Historie • {skipped} übersprungen.",
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
        "metric_net_bot": "Netto nach Steuern (Bot)",
        "metric_net_bh": "Netto nach Steuern (Buy & Hold)",
        "tax_gross_net_text": ("- **Brutto vs. Netto:** Ohne Steuern wirkt aktive Umschichtung oft zu stark. Sobald reale Steuerabflüsse auf realisierte Gewinne berücksichtigt werden, sinkt der frei verfügbare Cash-Puffer des Bots.\n"
                                "- **Warum Buy & Hold meist näher an Brutto bleibt:** Buy & Hold verkauft in dieser Simulation fast nichts. Dadurch werden Gewinne meist nicht laufend versteuert, sondern bleiben investiert.\n"
                                "- **Warum der Bot trotzdem vorn bleiben kann:** Der Bot versucht trotz Steuerabzügen, durch Selektion, Cash-Management und Rebalancing effizientere Kapitalpfade zu finden."),
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
        "info_start": "👈 Wähle ein Setup oder wirf deinen Asset-Korb rein — dann einmal auf 'Portfolio berechnen' und Allocato legt los.",
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
        "footer_free": "🆓 Free-Version • Upgrade für unbegrenzte Körbe, 5 Jahre Historie und Asset-Suche — wenn dein Depot nach mehr Power ruft.",
    },
    "EN": {
        "page_badges": ["Dynamic Allocation ⚡", "Direct Equity Ownership 💎", "Buy & Hold Benchmark 📊", "Launch Version 5.2.0 🚀"],
        "hero_sub": (
            "Your smart portfolio manager for direct equities. "
            "Do not buy blindly. Do not pay unnecessary fees. "
            "Do not just hope that some product somehow fits."
            "<br><br>"
            "Allocato helps you build a dynamically managed portfolio "
            "where you keep <b>control, transparency and dividends directly</b> — with more edge and a lot less spreadsheet fatigue."
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
        "rebalance_options": ["Off", "Yearly", "Quarterly", "Monthly", "Every 2 Years", "Every 5 Years"],
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
        "warning_partial_history": "{ticker} has only limited history but will still be used.",
        "warning_removed_after_align": "{ticker} was removed after cleanup due to too many data gaps.",
        "warning_align_reduced": "The common history was cleaned automatically to keep the comparison stable.",
        "metric_paid_in": "Cumulative contributions",
        "equity_label_paid_in": "Cumulative contributions",
        "benchmark_section": "📊 Add benchmark ETFs",
        "benchmark_input": "Benchmark ETF tickers (one per line)",
        "benchmark_input_help": "Examples: SPY, QQQ, VWCE.DE, URTH, IWDA.AS",
        "benchmark_added_title": "Additional ETF benchmarks",
        "simulate_taxes_de": "Simulate German taxes (26.375%)",
        "simulate_taxes_de_help": "Simulates capital gains tax on realized profits with a €1,000 annual allowance and average-cost accounting.",
        "enable_ki_explanations": "Enable AI explanations",
        "enable_ki_explanations_help": "Show short local placeholder explanations for the most recently selected top assets.",
        "ki_explanations_title": "🤖 AI explanations for the top assets",
        "ki_explanations_missing_key": "Local placeholder explanations are used – no API cost.",
        "taxes_col": "Taxes €",
        "tax_note_title": "Taxes & realism",
        "tax_note_text": "- Enabled taxes reduce bot cash immediately when gains are realized.\n- The simulation uses an average-cost basis.\n- A €1,000 yearly allowance is applied automatically.\n- Buy & Hold realizes very few gains in this setup because positions are rarely sold. That makes the comparison more realistic and prevents an artificial bot advantage.",
        "buy_hold_action_col": "Buy & Hold Action",
        "annual_returns_title": "📅 Annual returns",
        "annual_returns_year": "Year",
        "annual_returns_bot": "Bot %",
        "annual_returns_bh": "Buy & Hold %",
        "rebal_buys_col": "Buys",
        "rebal_sells_col": "Sells",
        "rebal_reason_col": "Logic",
        "interpret_why_title": "Why the bot can outperform",
        "interpret_why_text": "- **Cash management:** In weaker market phases, the bot does not blindly stay fully invested.\n- **Rebalancing logic:** Winners can be reweighted on clear rules instead of drifting forever.\n- **Conviction weighting:** Stronger signals get more capital, weaker signals get less.\n- **Trend filter:** Assets below trend lose priority.\n- **Selection effect:** The bot does not automatically hold the full basket equally weighted like Buy & Hold.\n- **Buy & Hold invests the monthly savings evenly across all available names – therefore it gets heavily diluted in large baskets.",
        "load_status_start": "Loading price data for {count} assets ...",
        "load_status_done": "{loaded} assets loaded • {partial} with limited history • {skipped} skipped.",
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
        "metric_net_bot": "Net after taxes (Bot)",
        "metric_net_bh": "Net after taxes (Buy & Hold)",
        "tax_gross_net_text": ("- **Gross vs. net:** Without taxes, active rebalancing can look too strong. Once real tax drag on realized gains is included, the bot loses part of its free cash buffer.\n"
                                "- **Why Buy & Hold often stays closer to gross:** Buy & Hold rarely sells in this simulation. Gains therefore remain mostly untaxed during the run and continue compounding.\n"
                                "- **Why the bot can still stay ahead:** Even after taxes, the bot may still benefit from selection, cash management and rebalancing discipline."),
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
        "info_start": "👈 Pick a setup or drop in your asset basket — then hit 'Calculate portfolio' and let Allocato cook.",
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
        "footer_free": "🆓 Free plan • Upgrade for unlimited baskets, 5 years of history and asset search — when your portfolio wants more firepower.",
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


def get_benchmark_list() -> list[str]:
    raw = st.session_state.get("benchmark_etfs_input", "")
    cleaned = []
    seen = set()
    for item in raw.splitlines():
        ticker = str(item).strip().upper()
        if ticker and ticker not in seen:
            cleaned.append(ticker)
            seen.add(ticker)
    return cleaned

def build_benchmark_equity_series(benchmark_tickers: list[str], period: str, dates: pd.Index, initial_capital: float, monthly_savings: float) -> dict:
    benchmark_map = {}
    if len(dates) == 0:
        return benchmark_map

    dates = pd.Index(dates).sort_values()
    requested_start = dates.min()

    for bench in benchmark_tickers:
        series = _download_with_fallbacks(bench, get_period_metadata(period)["yf_period"])
        if series.empty:
            continue

        series = series.sort_index()
        floor_start = get_backtest_floor_date(period)
        if floor_start is not None:
            series = series.loc[series.index >= floor_start]
        if series.empty:
            continue

        series = series.reindex(dates).ffill(limit=7)
        first_live_idx = series.first_valid_index()
        if first_live_idx is None:
            continue

        equity = pd.Series(index=dates, dtype=float)
        shares = 0.0
        cash = 0.0

        for i, date in enumerate(dates):
            if i > 0:
                prev_date = dates[i - 1]
                if date.month != prev_date.month or date.year != prev_date.year:
                    cash += monthly_savings

            price = series.loc[date]
            if pd.isna(price):
                equity.loc[date] = cash
                continue

            if shares == 0.0 and cash == 0.0 and date >= first_live_idx:
                cash += initial_capital

            if cash > 0 and price > 0:
                shares += cash / float(price)
                cash = 0.0

            equity.loc[date] = shares * float(price) + cash

        equity = equity.ffill().fillna(0.0)
        if (equity > 0).sum() >= 20:
            benchmark_map[bench] = equity

    return benchmark_map


def init_tax_lot_state(tickers: list[str]) -> dict:
    return {
        t: {"shares": 0.0, "cost_total": 0.0}
        for t in tickers
    }

def apply_trade_with_tax(
    ticker: str,
    current_shares: float,
    target_shares: float,
    price: float,
    lots_state: dict,
    taxes_enabled: bool,
    tax_state: dict,
    tax_rate: float,
) -> tuple[float, float, float]:
    if price <= 0:
        return current_shares, 0.0, 0.0

    lot = lots_state.setdefault(ticker, {"shares": 0.0, "cost_total": 0.0})
    current_value = current_shares * price
    target_value = target_shares * price
    tax_due = 0.0

    if target_shares > current_shares + 1e-12:
        buy_shares = target_shares - current_shares
        buy_cost = buy_shares * price
        lot["shares"] += buy_shares
        lot["cost_total"] += buy_cost
        return target_shares, target_value - current_value, 0.0

    if target_shares < current_shares - 1e-12:
        sell_shares = current_shares - target_shares
        avg_cost = (lot["cost_total"] / lot["shares"]) if lot["shares"] > 1e-12 else price
        realized_gain = max(0.0, (price - avg_cost) * sell_shares)
        if taxes_enabled and realized_gain > 0:
            remaining_allowance = max(0.0, 1000.0 - tax_state["used_allowance"])
            allowance_applied = min(remaining_allowance, realized_gain)
            taxable_gain = max(0.0, realized_gain - allowance_applied)
            tax_state["used_allowance"] += allowance_applied
            tax_due = taxable_gain * tax_rate
        lot["shares"] = max(0.0, lot["shares"] - sell_shares)
        lot["cost_total"] = max(0.0, lot["cost_total"] - avg_cost * sell_shares)
        if lot["shares"] <= 1e-12:
            lot["shares"] = 0.0
            lot["cost_total"] = 0.0
        return target_shares, target_value - current_value, tax_due

    return current_shares, 0.0, 0.0


BACKTEST_FIXED_START_DEFAULT = pd.Timestamp("2014-01-01")
BACKTEST_FIXED_START_BY_PERIOD = {
    "1y": None,
    "2y": None,
    "3y": None,
    "5y": pd.Timestamp("2014-01-01"),
    "10y": pd.Timestamp("2014-01-01"),
    "15y": pd.Timestamp("2012-01-01"),
    "20y": pd.Timestamp("2012-01-01"),
    "max": pd.Timestamp("2012-01-01"),
}

def get_period_metadata(period: str) -> dict:
    period = str(period).strip().lower()
    mapping = {
        "1y": {"yf_period": "1y", "preferred_points": 180},
        "2y": {"yf_period": "2y", "preferred_points": 300},
        "3y": {"yf_period": "3y", "preferred_points": 420},
        "5y": {"yf_period": "10y", "preferred_points": 700},
        "10y": {"yf_period": "15y", "preferred_points": 1200},
        "15y": {"yf_period": "max", "preferred_points": 1800},
        "20y": {"yf_period": "max", "preferred_points": 2400},
        "max": {"yf_period": "max", "preferred_points": 700},
    }
    return mapping.get(period, mapping["3y"])

def get_backtest_floor_date(period: str) -> pd.Timestamp | None:
    period = str(period).strip().lower()
    return BACKTEST_FIXED_START_BY_PERIOD.get(period, BACKTEST_FIXED_START_DEFAULT)

def _safe_series_history_stats(series_map: dict) -> pd.DataFrame:
    rows = []
    for ticker, series in series_map.items():
        s = pd.to_numeric(series, errors="coerce").dropna()
        if s.empty:
            continue
        rows.append({
            "ticker": ticker,
            "first_valid": pd.Timestamp(s.index.min()),
            "last_valid": pd.Timestamp(s.index.max()),
            "observations": int(len(s)),
        })
    if not rows:
        return pd.DataFrame(columns=["ticker", "first_valid", "last_valid", "observations"])
    return pd.DataFrame(rows).sort_values(["first_valid", "ticker"]).reset_index(drop=True)


def _extract_close_series(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    preferred_cols = ["Close", "Adj Close"]
    close_col = next((col for col in preferred_cols if col in raw.columns), None)
    if close_col is None:
        return pd.Series(dtype=float)
    s = pd.to_numeric(raw[close_col], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().copy()
    if s.empty:
        return pd.Series(dtype=float)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.name = ticker
    return s

def _download_with_fallbacks(ticker: str, period: str) -> pd.Series:
    candidates = [
        {"period": period, "auto_adjust": True},
        {"period": period, "auto_adjust": False},
    ]
    if period == "max":
        candidates.extend([
            {"period": "20y", "auto_adjust": True},
            {"period": "10y", "auto_adjust": True},
            {"period": "5y", "auto_adjust": True},
        ])
    else:
        candidates.extend([
            {"period": "max", "auto_adjust": True},
            {"period": "max", "auto_adjust": False},
        ])

    best = pd.Series(dtype=float)
    for cfg in candidates:
        try:
            raw = yf.download(
                ticker,
                period=cfg["period"],
                progress=False,
                auto_adjust=cfg["auto_adjust"],
                actions=False,
                threads=False,
            )
        except Exception:
            raw = pd.DataFrame()
        s = _extract_close_series(raw, ticker)
        if len(s) > len(best):
            best = s
        if len(best) >= 180:
            break
    return best

def load_close_prices(tickers, period, progress_bar=None, status_box=None):
    tickers = [str(t).strip() for t in tickers if str(t).strip()]
    meta = get_period_metadata(period)
    yf_period = meta["yf_period"]
    preferred_points = meta["preferred_points"]
    floor_start = get_backtest_floor_date(period)

    series_map = {}
    skipped = []
    partial_history = []
    loaded = []

    total = max(len(tickers), 1)
    if status_box is not None:
        status_box.info(T["load_status_start"].format(count=len(tickers)))

    for i, t in enumerate(tickers, start=1):
        if status_box is not None:
            status_box.info(
                f"📦 Lade {i}/{total}: {t}" if st.session_state.get("language", "DE") == "DE"
                else f"📦 Loading {i}/{total}: {t}"
            )
        if progress_bar is not None:
            progress_bar.progress(i / total, text=f"{i}/{total} • {t}")

        s = _download_with_fallbacks(t, yf_period)

        if s.empty:
            skipped.append(t)
            continue

        s = s.sort_index()
        if floor_start is not None:
            floor_observations = int((s.index >= floor_start).sum())
            if floor_observations < preferred_points:
                partial_history.append(t)
        elif len(s) < preferred_points:
            partial_history.append(t)

        series_map[t] = s
        loaded.append(t)

    if progress_bar is not None:
        progress_bar.empty()
    if status_box is not None:
        status_box.success(
            T["load_status_done"].format(
                loaded=len(loaded),
                partial=len(partial_history),
                skipped=len(skipped),
            )
        )

    return series_map, skipped, partial_history


def align_price_series(series_map, period: str, min_live_assets: int = 2, ff_limit: int = 7):
    if not series_map:
        return pd.DataFrame(), [], {
            "requested_floor_start": None,
            "actual_common_start": None,
            "first_full_coverage_start": None,
            "asset_history_df": pd.DataFrame(),
            "live_assets_by_day": pd.Series(dtype=float),
        }

    prices_raw = pd.concat(series_map.values(), axis=1, join="outer").sort_index()
    prices_raw = prices_raw[~prices_raw.index.duplicated(keep="last")]
    prices_raw = prices_raw.replace([np.inf, -np.inf], np.nan)

    keep_cols = []
    dropped_cols = []
    for col in prices_raw.columns:
        s = pd.to_numeric(prices_raw[col], errors="coerce").dropna()
        if len(s) < 5:
            dropped_cols.append(col)
            continue
        keep_cols.append(col)

    if not keep_cols:
        return pd.DataFrame(), sorted(set(dropped_cols)), {
            "requested_floor_start": get_backtest_floor_date(period),
            "actual_common_start": None,
            "first_full_coverage_start": None,
            "asset_history_df": pd.DataFrame(),
            "live_assets_by_day": pd.Series(dtype=float),
        }

    prices = prices_raw[keep_cols].copy()
    floor_start = get_backtest_floor_date(period)
    if floor_start is not None:
        prices = prices.loc[prices.index >= floor_start].copy()
        if prices.empty:
            prices = prices_raw[keep_cols].copy()

    asset_history_df = _safe_series_history_stats(series_map)
    live_assets_by_day = prices.notna().sum(axis=1)

    enough_live_mask = live_assets_by_day >= max(1, min_live_assets)
    if enough_live_mask.any():
        actual_common_start = prices.index[enough_live_mask.argmax()]
        prices = prices.loc[prices.index >= actual_common_start].copy()
        live_assets_by_day = prices.notna().sum(axis=1)
    else:
        actual_common_start = prices.index.min()

    prices = prices.ffill(limit=ff_limit)
    prices = prices.loc[prices.notna().sum(axis=1) >= max(1, min_live_assets)].copy()

    if prices.empty:
        return pd.DataFrame(), sorted(set(dropped_cols)), {
            "requested_floor_start": floor_start,
            "actual_common_start": pd.Timestamp(actual_common_start) if actual_common_start is not None else None,
            "first_full_coverage_start": None,
            "asset_history_df": asset_history_df,
            "live_assets_by_day": live_assets_by_day,
        }

    full_coverage_mask = prices.notna().all(axis=1)
    first_full_coverage_start = prices.index[full_coverage_mask.argmax()] if full_coverage_mask.any() else None

    return prices, sorted(set(dropped_cols)), {
        "requested_floor_start": floor_start,
        "actual_common_start": pd.Timestamp(actual_common_start) if actual_common_start is not None else None,
        "first_full_coverage_start": pd.Timestamp(first_full_coverage_start) if first_full_coverage_start is not None else None,
        "asset_history_df": asset_history_df,
        "live_assets_by_day": live_assets_by_day,
    }


def load_single_close(ticker, period):
    s = _download_with_fallbacks(ticker, get_period_metadata(period)["yf_period"])
    return s

def compute_metrics(equity: pd.Series):
    eq = pd.to_numeric(equity, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().copy()
    eq = eq[eq > 0]
    if eq.empty or len(eq) < 2:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "max_dd": 0.0,
            "volatility": 0.0,
            "sharpe": 0.0,
        }

    returns = eq.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    start_val = float(eq.iloc[0])
    end_val = float(eq.iloc[-1])
    total_return = ((end_val / start_val) - 1.0) * 100.0 if start_val > 0 else 0.0
    days = len(eq)
    years = max(days / 252.0, 1 / 252.0)
    cagr = (((end_val / start_val) ** (1.0 / years)) - 1.0) * 100.0 if start_val > 0 and end_val > 0 else 0.0
    rolling_max = eq.cummax().replace(0, np.nan)
    drawdown = ((eq / rolling_max) - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0) * 100.0
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0
    vol = float(returns.std() * np.sqrt(252) * 100.0) if len(returns) > 1 else 0.0
    sharpe = float((returns.mean() / returns.std()) * np.sqrt(252)) if returns.std() and returns.std() > 0 else 0.0
    return {
        "total_return": float(np.nan_to_num(total_return, nan=0.0, posinf=0.0, neginf=0.0)),
        "cagr": float(np.nan_to_num(cagr, nan=0.0, posinf=0.0, neginf=0.0)),
        "max_dd": float(np.nan_to_num(max_dd, nan=0.0, posinf=0.0, neginf=0.0)),
        "volatility": float(np.nan_to_num(vol, nan=0.0, posinf=0.0, neginf=0.0)),
        "sharpe": float(np.nan_to_num(sharpe, nan=0.0, posinf=0.0, neginf=0.0)),
    }

def is_rebalance_day(current_date, prev_date, mode):
    if mode in ("Aus", "Off"):
        return False
    if mode in ("Monatlich", "Monthly"):
        return current_date.month != prev_date.month or current_date.year != prev_date.year
    if mode in ("Quartalsweise", "Quarterly"):
        prev_q = (prev_date.month - 1) // 3
        curr_q = (current_date.month - 1) // 3
        return (current_date.year != prev_date.year) or (curr_q != prev_q)
    if mode in ("Jährlich", "Yearly"):
        return current_date.year != prev_date.year
    if mode in ("Alle 2 Jahre", "Every 2 Years"):
        return current_date.year != prev_date.year and current_date.year % 2 == 0
    if mode in ("Alle 5 Jahre", "Every 5 Years"):
        return current_date.year != prev_date.year and current_date.year % 5 == 0
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

def compute_annual_returns(bot_equity: pd.Series, bh_equity: pd.Series, T: dict) -> pd.DataFrame:
    annual_bot = bot_equity.resample("YE").last().pct_change() * 100
    annual_bh = bh_equity.resample("YE").last().pct_change() * 100
    df = pd.DataFrame({
        T["annual_returns_year"]: annual_bot.index.year,
        T["annual_returns_bot"]: annual_bot.values,
        T["annual_returns_bh"]: annual_bh.reindex(annual_bot.index).values,
    }).dropna(how="all")
    return df.reset_index(drop=True)

def style_rebalance_log(df: pd.DataFrame, buys_col: str, sells_col: str):
    def _cell_color(val: str, positive: bool):
        if not isinstance(val, str) or val.strip() in {"", "—"}:
            return ""
        bg = "rgba(34,197,94,0.16)" if positive else "rgba(239,68,68,0.16)"
        border = "#22c55e" if positive else "#ef4444"
        color = "#dcfce7" if positive else "#fee2e2"
        return f"background-color: {bg}; color: {color}; border-left: 3px solid {border};"

    styler = df.style
    if buys_col in df.columns:
        styler = styler.map(lambda v: _cell_color(v, True), subset=[buys_col])
    if sells_col in df.columns:
        styler = styler.map(lambda v: _cell_color(v, False), subset=[sells_col])
    return styler

def render_net_tax_badge(label: str, value: float, paid_in: float):
    positive = value >= paid_in
    bg = "rgba(34,197,94,0.14)" if positive else "rgba(239,68,68,0.14)"
    border = "rgba(34,197,94,0.40)" if positive else "rgba(239,68,68,0.40)"
    color = "#dcfce7" if positive else "#fecaca"
    st.markdown(
        f"""
        <div style="padding:0.95rem 1rem;border-radius:16px;background:{bg};border:1px solid {border};margin:.15rem 0 .4rem 0;">
            <div style="font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;font-weight:800;color:rgba(248,250,252,.72);">{label}</div>
            <div style="font-size:1.35rem;font-weight:800;color:{color};margin-top:.15rem;">{value:,.2f} €</div>
        </div>
        """,
        unsafe_allow_html=True,
    )




def _safe_pct_rank(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if s.dropna().empty:
        return pd.Series(50.0, index=s.index)
    ranks = s.rank(pct=True)
    return (ranks * 100).fillna(50.0)

def clamp_series(series: pd.Series, low: float = 0.0, high: float = 100.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0).clip(lower=low, upper=high)

def load_regime_reference_series(period: str, dates: pd.Index) -> pd.Series:
    spy_close = load_single_close("SPY", period)
    if spy_close.empty:
        return pd.Series(index=dates, data=np.nan)
    return spy_close.reindex(dates).ffill()

def compute_market_regime(prices: pd.DataFrame, period: str, lang: str) -> tuple[pd.DataFrame, pd.Series]:
    dates = prices.index
    spy_close = load_regime_reference_series(period, dates)
    spy_sma200 = spy_close.rolling(200).mean()
    spy_mom_63 = spy_close / spy_close.shift(63) - 1.0
    market_vol_63 = prices.pct_change().mean(axis=1).rolling(63).std() * np.sqrt(252)
    breadth = (prices / prices.shift(63) - 1.0 > 0).mean(axis=1)

    regime_names_de = {
        "BULL": "Bull Regime",
        "TRANSITION": "Transition / Unsicher",
        "BEAR": "Bear Regime",
        "RECOVERY": "Recovery Regime",
    }
    regime_names_en = {
        "BULL": "Bull Regime",
        "TRANSITION": "Transition / Uncertain",
        "BEAR": "Bear Regime",
        "RECOVERY": "Recovery Regime",
    }
    regime_names = regime_names_en if lang == "EN" else regime_names_de

    regime_codes = []
    for dt in dates:
        price = spy_close.loc[dt]
        sma = spy_sma200.loc[dt]
        mom = spy_mom_63.loc[dt]
        vol = market_vol_63.loc[dt]
        br = breadth.loc[dt]

        if pd.isna(price) or pd.isna(sma) or pd.isna(mom) or pd.isna(vol) or pd.isna(br):
            regime_codes.append("TRANSITION")
            continue

        above_sma = price > sma
        strong_mom = mom > 0.04
        weak_mom = mom < -0.04
        high_vol = vol > 0.28
        low_vol = vol < 0.18
        strong_breadth = br > 0.62
        weak_breadth = br < 0.42

        if above_sma and strong_mom and strong_breadth and not high_vol:
            regime_codes.append("BULL")
        elif (not above_sma) and weak_mom and weak_breadth:
            regime_codes.append("BEAR")
        elif above_sma and mom > 0 and br > 0.48:
            regime_codes.append("RECOVERY" if (high_vol or not low_vol) else "BULL")
        elif (not above_sma) and mom > -0.02 and br >= 0.45:
            regime_codes.append("RECOVERY")
        else:
            regime_codes.append("TRANSITION")

    regime_code_series = pd.Series(regime_codes, index=dates, name="regime_code")
    regime_label_series = regime_code_series.map(regime_names).rename("regime")
    regime_df = pd.DataFrame({
        "spy_close": spy_close,
        "spy_sma200": spy_sma200,
        "spy_mom_63": spy_mom_63,
        "market_vol_63": market_vol_63,
        "breadth": breadth,
        "regime_code": regime_code_series,
        "regime": regime_label_series,
    }, index=dates)
    return regime_df, regime_label_series

def get_regime_profile(regime_code: str) -> dict:
    profiles = {
        "BULL": {
            "score_weights": {"trend": 0.24, "momentum": 0.34, "quality": 0.10, "risk": 0.12, "regime_fit": 0.20},
            "cash_target": 0.00,
            "min_score": 32.0,
            "invest_ratio": 1.00,
            "strategy": "Trend + Breakout Momentum",
        },
        "TRANSITION": {
            "score_weights": {"trend": 0.24, "momentum": 0.20, "quality": 0.22, "risk": 0.18, "regime_fit": 0.16},
            "cash_target": 0.02,
            "min_score": 36.0,
            "invest_ratio": 0.99,
            "strategy": "Quality + Momentum",
        },
        "BEAR": {
            "score_weights": {"trend": 0.18, "momentum": 0.12, "quality": 0.24, "risk": 0.28, "regime_fit": 0.18},
            "cash_target": 0.06,
            "min_score": 38.0,
            "invest_ratio": 0.94,
            "strategy": "Defensive Rotation",
        },
        "RECOVERY": {
            "score_weights": {"trend": 0.26, "momentum": 0.26, "quality": 0.14, "risk": 0.12, "regime_fit": 0.22},
            "cash_target": 0.00,
            "min_score": 34.0,
            "invest_ratio": 1.00,
            "strategy": "Recovery Re-Entry",
        },
    }
    return profiles.get(regime_code, profiles["TRANSITION"])

def compute_component_score_table(prices: pd.DataFrame, regime_df: pd.DataFrame, vol_penalty: float) -> dict:
    ret_21 = prices / prices.shift(21) - 1.0
    ret_63 = prices / prices.shift(63) - 1.0
    ret_126 = prices / prices.shift(126) - 1.0
    ret_252 = prices / prices.shift(252) - 1.0
    sma50 = prices.rolling(50, min_periods=20).mean()
    sma200 = prices.rolling(200, min_periods=60).mean()
    vol_63 = prices.pct_change().rolling(63, min_periods=20).std() * np.sqrt(252)
    dd_126 = prices / prices.rolling(126, min_periods=30).max() - 1.0
    pos_days_63 = (prices.pct_change() > 0).rolling(63, min_periods=20).mean()

    trend_raw = 0.45 * ((prices / sma50) - 1.0) + 0.55 * ((prices / sma200) - 1.0)
    momentum_raw = 0.20 * ret_21 + 0.35 * ret_63 + 0.30 * ret_126 + 0.15 * ret_252
    quality_raw = 0.35 * pos_days_63 + 0.35 * (ret_252 - vol_penalty * vol_63) + 0.30 * (1.0 + dd_126)
    risk_raw = -0.55 * vol_63 + 0.45 * dd_126

    trend_score = trend_raw.rank(axis=1, pct=True) * 100
    momentum_score = momentum_raw.rank(axis=1, pct=True) * 100
    quality_score = quality_raw.rank(axis=1, pct=True) * 100
    risk_score = risk_raw.rank(axis=1, pct=True) * 100

    regime_fit_score = pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    for dt in prices.index:
        regime_code = regime_df.loc[dt, "regime_code"]
        if regime_code == "BULL":
            fit_raw = 0.60 * momentum_raw.loc[dt] + 0.40 * trend_raw.loc[dt]
        elif regime_code == "BEAR":
            fit_raw = 0.60 * risk_raw.loc[dt] + 0.40 * quality_raw.loc[dt]
        elif regime_code == "RECOVERY":
            fit_raw = 0.50 * trend_raw.loc[dt] + 0.30 * momentum_raw.loc[dt] + 0.20 * quality_raw.loc[dt]
        else:
            fit_raw = 0.40 * quality_raw.loc[dt] + 0.30 * momentum_raw.loc[dt] + 0.30 * risk_raw.loc[dt]
        regime_fit_score.loc[dt] = _safe_pct_rank(fit_raw)

    return {
        "trend": clamp_series(trend_score.stack()).unstack(),
        "momentum": clamp_series(momentum_score.stack()).unstack(),
        "quality": clamp_series(quality_score.stack()).unstack(),
        "risk": clamp_series(risk_score.stack()).unstack(),
        "regime_fit": clamp_series(regime_fit_score.stack()).unstack(),
        "sma50": sma50,
        "sma200": sma200,
        "vol_63": vol_63,
        "ret_21": ret_21,
        "ret_63": ret_63,
        "ret_126": ret_126,
        "ret_252": ret_252,
    }

def compute_ai_overlay_scores(prices: pd.DataFrame, component_scores: dict, lang: str) -> tuple[pd.DataFrame, dict]:
    overlay = pd.DataFrame(0.0, index=prices.index, columns=prices.columns, dtype=float)
    explanations = {}
    trend = component_scores["trend"]
    momentum = component_scores["momentum"]
    quality = component_scores["quality"]
    risk = component_scores["risk"]

    for dt in prices.index:
        explanations[dt] = {}
        for ticker in prices.columns:
            boost = 0.0
            reasons = []
            tr = float(trend.loc[dt, ticker])
            mo = float(momentum.loc[dt, ticker])
            qu = float(quality.loc[dt, ticker])
            ri = float(risk.loc[dt, ticker])

            if tr > 75 and mo > 75:
                boost += 10
                reasons.append("Trend + Momentum stark" if lang == "DE" else "Strong trend + momentum")
            if qu > 70:
                boost += 4
                reasons.append("stabile Qualitätsmerkmale" if lang == "DE" else "stable quality profile")
            if ri < 30:
                boost -= 8
                reasons.append("erhöhtes Risiko / Drawdown" if lang == "DE" else "elevated risk / drawdown")
            if mo < 25:
                boost -= 7
                reasons.append("schwaches relatives Momentum" if lang == "DE" else "weak relative momentum")

            boost = float(np.clip(boost, -15, 15))
            overlay.loc[dt, ticker] = boost
            if not reasons:
                reasons.append("neutraler KI-Overlay" if lang == "DE" else "neutral AI overlay")
            explanations[dt][ticker] = "; ".join(reasons)
    return overlay, explanations


def compute_total_score_by_regime(prices: pd.DataFrame, regime_df: pd.DataFrame, component_scores: dict, ai_overlay: pd.DataFrame) -> pd.DataFrame:
    total = pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    for dt in prices.index:
        regime_code = regime_df.loc[dt, "regime_code"]
        profile = get_regime_profile(regime_code)
        w = profile["score_weights"]
        base_score = (
            component_scores["trend"].loc[dt] * w["trend"] +
            component_scores["momentum"].loc[dt] * w["momentum"] +
            component_scores["quality"].loc[dt] * w["quality"] +
            component_scores["risk"].loc[dt] * w["risk"] +
            component_scores["regime_fit"].loc[dt] * w["regime_fit"] +
            ai_overlay.loc[dt]
        )
        if regime_code in {"BULL", "RECOVERY"}:
            for ticker in prices.columns:
                if is_crypto_or_high_beta_ticker(ticker):
                    momentum_boost = float(component_scores["momentum"].loc[dt, ticker] >= 65) * 6.0
                    trend_boost = float(component_scores["trend"].loc[dt, ticker] >= 60) * 4.0
                    base_score.loc[ticker] += momentum_boost + trend_boost
        total.loc[dt] = base_score
    return total.clip(lower=0, upper=100)

def should_threshold_rebalance(date, regime_code: str, held_assets: list[str], selected_assets: list[str], current_weight_map: dict, target_weight_map: dict, score_today: pd.Series, component_scores: dict, last_regime_code: str | None) -> tuple[bool, str]:
    if last_regime_code is not None and regime_code != last_regime_code:
        return True, "Regimewechsel"
    for ticker in selected_assets:
        drift = abs(target_weight_map.get(ticker, 0.0) - current_weight_map.get(ticker, 0.0))
        if drift > 0.08:
            return True, "Gewichtsdrift > 8%"
    if held_assets:
        held_score = score_today.reindex(held_assets).dropna().mean() if any(t in score_today.index for t in held_assets) else 0.0
        selected_score = score_today.reindex(selected_assets).dropna().mean() if any(t in score_today.index for t in selected_assets) else 0.0
        if selected_score - held_score > 10:
            return True, "neues Top-Asset deutlich besser"
    for ticker in held_assets:
        try:
            if component_scores["trend"].loc[date, ticker] < 35:
                return True, f"Trendbruch {ticker}"
        except Exception:
            pass
    return False, "Kein Schwellen-Trigger"
def should_skip_sale_for_tax(ticker: str, current_shares: float, target_shares: float, price: float, lots_state: dict, taxes_enabled: bool, regime_code: str, trend_score: float, score_gap: float) -> bool:
    if not taxes_enabled or target_shares >= current_shares or current_shares <= 0 or price <= 0:
        return False
    if regime_code in {"BEAR"} or trend_score < 35 or score_gap > 12:
        return False
    lot = lots_state.get(ticker, {"shares": 0.0, "cost_total": 0.0})
    avg_cost = (lot["cost_total"] / lot["shares"]) if lot.get("shares", 0.0) > 1e-12 else price
    unrealized_gain_pct = ((price / avg_cost) - 1.0) * 100.0 if avg_cost > 0 else 0.0
    reduction_ratio = (current_shares - target_shares) / current_shares if current_shares > 0 else 0.0
    estimated_tax_drag_pct = max(unrealized_gain_pct, 0.0) * 0.26375 * reduction_ratio
    return estimated_tax_drag_pct > 4.0 and regime_code in {"BULL", "RECOVERY", "TRANSITION"}

    if last_regime_code is not None and regime_code != last_regime_code:
        return True, "Regimewechsel"
    for ticker in selected_assets:
        drift = abs(target_weight_map.get(ticker, 0.0) - current_weight_map.get(ticker, 0.0))
        if drift > 0.08:
            return True, "Gewichtsdrift > 8%"
    if held_assets:
        held_score = score_today.reindex(held_assets).dropna().mean() if any(t in score_today.index for t in held_assets) else 0.0
        selected_score = score_today.reindex(selected_assets).dropna().mean() if any(t in score_today.index for t in selected_assets) else 0.0
        if selected_score - held_score > 10:
            return True, "neues Top-Asset deutlich besser"
    for ticker in held_assets:
        try:
            if component_scores["trend"].loc[date, ticker] < 35:
                return True, f"Trendbruch {ticker}"
        except Exception:
            pass
    return False, "Kein Schwellen-Trigger"


def build_target_portfolio_for_date(date, current_prices: pd.Series, total_score: pd.DataFrame, regime_df: pd.DataFrame, component_scores: dict, effective_top_n: int, max_weight: float, soft_cash_mode: bool, cash_floor: float, cash_ceiling: float, soft_invest_ratio: float, min_score_user: float, conviction_power: float) -> dict:
    regime_code = regime_df.loc[date, "regime_code"]
    profile = get_regime_profile(regime_code)
    available = current_prices.dropna().index.tolist()
    score_today = total_score.loc[date].reindex(available).dropna().sort_values(ascending=False)
    trend_today = component_scores["trend"].loc[date].reindex(available).fillna(50)
    risk_today = component_scores["risk"].loc[date].reindex(available).fillna(50)
    quality_today = component_scores["quality"].loc[date].reindex(available).fillna(50)
    momentum_today = component_scores["momentum"].loc[date].reindex(available).fillna(50)
    regime_fit_today = component_scores["regime_fit"].loc[date].reindex(available).fillna(50)

    dynamic_floor = max(min_score_user * 100, profile["min_score"] - 8.0)

    if regime_code == "BULL":
        eligible = score_today[(trend_today.reindex(score_today.index) >= 42) & (momentum_today.reindex(score_today.index) >= 45)]
        eligible = eligible + regime_fit_today.reindex(eligible.index).fillna(50) * 0.03
    elif regime_code == "TRANSITION":
        eligible = score_today[(quality_today.reindex(score_today.index) >= 38) & (risk_today.reindex(score_today.index) >= 35)]
    elif regime_code == "BEAR":
        eligible = score_today[(risk_today.reindex(score_today.index) >= 32) & (quality_today.reindex(score_today.index) >= 35)]
    else:
        eligible = score_today[(trend_today.reindex(score_today.index) >= 38) & (momentum_today.reindex(score_today.index) >= 40)]

    eligible = eligible[eligible >= dynamic_floor]

    if regime_code in {"BULL", "RECOVERY"}:
        for ticker in list(score_today.index):
            if is_crypto_or_high_beta_ticker(ticker):
                eligible.loc[ticker] = max(float(eligible.get(ticker, np.nan)) if ticker in eligible.index else np.nan, float(score_today.loc[ticker]))

    selected = eligible.sort_values(ascending=False).head(effective_top_n)

    if len(selected) == 0:
        fallback = score_today.head(effective_top_n)
        if len(fallback) == 0:
            return {
                "selected": pd.Series(dtype=float),
                "weights": pd.Series(dtype=float),
                "invest_ratio": 0.0,
                "regime_code": regime_code,
                "strategy_name": profile["strategy"] + " / Cash",
                "cash_target": min(max(cash_floor, profile["cash_target"]), cash_ceiling),
            }
        shifted = fallback - fallback.min() + 1e-6
        weights = conviction_weights(shifted, max_weight=max_weight, power=max(1.1, conviction_power - 0.2))
        invest_ratio = profile["invest_ratio"] if regime_code in {"BULL", "RECOVERY"} else min(profile["invest_ratio"], soft_invest_ratio if soft_cash_mode else profile["invest_ratio"])
        return {
            "selected": fallback,
            "weights": weights,
            "invest_ratio": invest_ratio,
            "regime_code": regime_code,
            "strategy_name": profile["strategy"] + " / Flexible Fallback",
            "cash_target": min(max(cash_floor, profile["cash_target"]), cash_ceiling),
        }

    shifted = selected - selected.min() + 1e-6
    weights = conviction_weights(shifted, max_weight=max_weight, power=max(1.2, conviction_power))
    return {
        "selected": selected,
        "weights": weights,
        "invest_ratio": profile["invest_ratio"],
        "regime_code": regime_code,
        "strategy_name": profile["strategy"],
        "cash_target": min(max(cash_floor, profile["cash_target"]), cash_ceiling),
    }

def simulate_allocato_v2(prices: pd.DataFrame, period: str, lang: str, initial_capital: float, monthly_savings: float, rebalance_freq: str, fee_pct: float, min_score: float, max_weight_pct: int, vol_penalty: float, cash_interest_pct: float, show_debug: bool, conviction_power: float, soft_cash_mode: bool, target_cash_floor_pct: int, target_cash_ceiling_pct: int, soft_cash_invest_ratio_pct: int, top_n: int, simulate_taxes_de: bool, alignment_info: dict | None = None):
    prices = prices.sort_index().copy()
    tickers = list(prices.columns)
    effective_top_n = min(top_n, len(tickers))
    max_weight = max_weight_pct / 100.0
    daily_cash_rate = (cash_interest_pct / 100.0) / 252.0
    cash_floor = target_cash_floor_pct / 100.0
    cash_ceiling = target_cash_ceiling_pct / 100.0
    soft_invest_ratio = soft_cash_invest_ratio_pct / 100.0
    tax_rate = 0.26375
    bot_tax_state = {"year": None, "used_allowance": 0.0, "taxes_paid_total": 0.0}
    bh_tax_state = {"year": None, "used_allowance": 0.0, "taxes_paid_total": 0.0}

    regime_df, _ = compute_market_regime(prices, period, lang)
    component_scores = compute_component_score_table(prices, regime_df, vol_penalty)
    ai_overlay_scores, ai_explanations = compute_ai_overlay_scores(prices, component_scores, lang)
    total_score = compute_total_score_by_regime(prices, regime_df, component_scores, ai_overlay_scores)

    row_valid_assets = total_score.notna().sum(axis=1)
    valid_mask = row_valid_assets >= 2
    prices = prices.loc[valid_mask].copy()
    regime_df = regime_df.loc[valid_mask].copy()
    total_score = total_score.loc[valid_mask].copy()
    for key in ["trend", "momentum", "quality", "risk", "regime_fit", "sma50", "sma200", "vol_63", "ret_21", "ret_63", "ret_126", "ret_252"]:
        component_scores[key] = component_scores[key].loc[valid_mask].copy()

    dates = prices.index
    if len(dates) < 30:
        raise ValueError("too_few_rows")

    valuation_prices = prices.ffill(limit=7)

    shares = {t: 0.0 for t in tickers}
    bot_lots_state = init_tax_lot_state(tickers)
    cash = float(initial_capital)

    equity_bot = pd.Series(index=dates, dtype=float)
    cash_bot = pd.Series(index=dates, dtype=float)
    invested_bot = pd.Series(index=dates, dtype=float)
    weight_history = pd.DataFrame(index=dates, columns=tickers, dtype=float)
    cash_weight_history = pd.Series(index=dates, dtype=float)
    cumulative_contributions = pd.Series(index=dates, dtype=float)

    selected_assets_log = {}
    target_weights_log = {}
    rebalance_log = []
    trade_count = 0
    last_regime_code = None
    estimated_tax_drag_pct_map = {}

    for i, date in enumerate(dates):
        tradable_prices = prices.loc[date]
        current_prices = valuation_prices.loc[date]
        prev_date = None if i == 0 else dates[i - 1]
        current_year = int(date.year)
        if bot_tax_state["year"] != current_year:
            bot_tax_state["year"] = current_year
            bot_tax_state["used_allowance"] = 0.0

        if daily_cash_rate > 0:
            cash *= (1 + daily_cash_rate)

        monthly_contribution_added = False
        if i > 0 and (date.month != prev_date.month or date.year != prev_date.year):
            cash += monthly_savings
            monthly_contribution_added = True

        current_values = {}
        for t in tickers:
            px = float(current_prices[t]) if pd.notna(current_prices[t]) else np.nan
            current_values[t] = shares[t] * px if pd.notna(px) else 0.0

        total_equity_before = cash + float(np.nansum(list(current_values.values())))
        current_weight_map = {t: (current_values[t] / total_equity_before if total_equity_before > 0 else 0.0) for t in tickers}

        strategy_payload = build_target_portfolio_for_date(
            date=date,
            current_prices=tradable_prices,
            total_score=total_score,
            regime_df=regime_df,
            component_scores=component_scores,
            effective_top_n=effective_top_n,
            max_weight=max_weight,
            soft_cash_mode=soft_cash_mode,
            cash_floor=cash_floor,
            cash_ceiling=cash_ceiling,
            soft_invest_ratio=soft_invest_ratio,
            min_score_user=min_score,
            conviction_power=conviction_power,
        )
        selected = strategy_payload["selected"]
        weights = strategy_payload["weights"]
        regime_code = strategy_payload["regime_code"]
        invest_ratio = strategy_payload["invest_ratio"]
        strategy_name = strategy_payload["strategy_name"]

        target_values = {t: 0.0 for t in tickers}
        investable_capital = total_equity_before * min(max(invest_ratio, 0.0), 1.0)
        for tkr in weights.index:
            if pd.notna(tradable_prices.get(tkr, np.nan)):
                target_values[tkr] = investable_capital * float(weights[tkr])

        target_weight_map = {t: (target_values[t] / total_equity_before if total_equity_before > 0 else 0.0) for t in tickers}
        held_assets = [t for t, s in shares.items() if s > 1e-12]
        threshold_trigger, threshold_reason = should_threshold_rebalance(
            date=date,
            regime_code=regime_code,
            held_assets=held_assets,
            selected_assets=list(selected.index),
            current_weight_map=current_weight_map,
            target_weight_map=target_weight_map,
            score_today=total_score.loc[date],
            component_scores=component_scores,
            last_regime_code=last_regime_code,
        )
        scheduled_rebalance = i == 0 or (prev_date is not None and is_rebalance_day(date, prev_date, rebalance_freq))
        do_rebalance = scheduled_rebalance or threshold_trigger

        if do_rebalance:
            turnover = float(np.nansum([abs(target_values[t] - current_values[t]) for t in tickers]))
            fees = turnover * fee_pct
            total_equity_after_fees = max(total_equity_before - fees, 0.0)

            if total_equity_before > 0:
                fee_adjustment = total_equity_after_fees / total_equity_before
                for t in tickers:
                    target_values[t] *= fee_adjustment

            buy_actions = []
            sell_actions = []
            taxes_due_total = 0.0

            for tkr in tickers:
                price = float(tradable_prices[tkr]) if pd.notna(tradable_prices[tkr]) else np.nan
                old_shares = shares[tkr]

                if pd.isna(price) or price <= 0:
                    continue

                new_shares = target_values[tkr] / price if price > 0 else 0.0
                lot = bot_lots_state.get(tkr, {"shares": 0.0, "cost_total": 0.0})
                avg_cost = (lot["cost_total"] / lot["shares"]) if lot.get("shares", 0.0) > 1e-12 else price
                unrealized_gain_pct = ((price / avg_cost) - 1.0) * 100.0 if avg_cost > 0 else 0.0
                reduction_ratio = ((old_shares - new_shares) / old_shares) if old_shares > 0 and new_shares < old_shares else 0.0
                estimated_tax_drag_pct_map[tkr] = max(unrealized_gain_pct, 0.0) * 0.26375 * max(reduction_ratio, 0.0)
                score_gap = float(total_score.loc[date].max() - total_score.loc[date].get(tkr, 0.0))
                if should_skip_sale_for_tax(
                    ticker=tkr,
                    current_shares=old_shares,
                    target_shares=new_shares,
                    price=price,
                    lots_state=bot_lots_state,
                    taxes_enabled=simulate_taxes_de,
                    regime_code=regime_code,
                    trend_score=float(component_scores["trend"].loc[date].get(tkr, 50.0)),
                    score_gap=score_gap,
                ):
                    new_shares = old_shares

                updated_shares, delta_value, tax_due = apply_trade_with_tax(
                    ticker=tkr,
                    current_shares=old_shares,
                    target_shares=new_shares,
                    price=price,
                    lots_state=bot_lots_state,
                    taxes_enabled=simulate_taxes_de,
                    tax_state=bot_tax_state,
                    tax_rate=tax_rate,
                )
                delta_shares = updated_shares - old_shares
                if abs(delta_shares) > 1e-12:
                    trade_count += 1
                    if delta_value > 1e-6:
                        buy_actions.append(f"{tkr} (+{delta_value:,.0f}€)")
                    elif delta_value < -1e-6:
                        sell_actions.append(f"{tkr} ({delta_value:,.0f}€)")
                taxes_due_total += tax_due
                shares[tkr] = updated_shares

            bot_tax_state["taxes_paid_total"] += taxes_due_total
            invested_value = float(np.nansum([
                shares[t] * (float(current_prices[t]) if pd.notna(current_prices[t]) else 0.0) for t in tickers
            ]))
            cash = max(0.0, total_equity_after_fees - invested_value - taxes_due_total)

            target_weights_log[date] = {tkr: (target_values[tkr] / total_equity_before) for tkr in weights.index} if total_equity_before > 0 else {}
            selected_assets_log[date] = list(selected.index)

            bh_monthly_action = "—"
            live_bh_assets = int(prices.loc[date].notna().sum())
            if monthly_contribution_added and live_bh_assets > 0:
                per_asset_bh = monthly_savings / live_bh_assets
                bh_monthly_action = (
                    f"{monthly_savings:,.0f}€ gleichmäßig auf {live_bh_assets} verfügbare Titel ({per_asset_bh:,.2f}€ je Titel)"
                    if lang == "DE"
                    else f"{monthly_savings:,.0f}€ spread across {live_bh_assets} available names ({per_asset_bh:,.2f}€ each)"
                )

            reason_parts = [strategy_name]
            if scheduled_rebalance:
                reason_parts.append("Zeit-Trigger" if lang == "DE" else "time trigger")
            if threshold_trigger:
                reason_parts.append(threshold_reason)
            reason_parts.append(regime_df.loc[date, "regime"])

            rebalance_log.append({
                T["date_col"]: date,
                T["regime_ok_col"]: regime_df.loc[date, "regime"],
                T["selected_assets_col"]: ", ".join(list(selected.index)) if len(selected) else "Cash",
                T["buy_hold_action_col"]: bh_monthly_action,
                T["rebal_buys_col"]: ", ".join(buy_actions) if buy_actions else "—",
                T["rebal_sells_col"]: ", ".join(sell_actions) if sell_actions else "—",
                T["rebal_reason_col"]: " | ".join(reason_parts),
                T["turnover_col"]: float(turnover),
                T["fees_col"]: float(fees),
                T["taxes_col"]: float(taxes_due_total),
                T["cash_eur_col"]: float(cash),
                T["portfolio_eur_col"]: float(total_equity_after_fees),
            })

            last_regime_code = regime_code

        invested_value = float(np.nansum([
            shares[t] * (float(current_prices[t]) if pd.notna(current_prices[t]) else 0.0) for t in tickers
        ]))
        total_value = max(0.0, invested_value + cash)
        equity_bot.loc[date] = total_value
        cash_bot.loc[date] = cash
        invested_bot.loc[date] = invested_value
        months_elapsed = (date.year - dates[0].year) * 12 + (date.month - dates[0].month)
        cumulative_contributions.loc[date] = float(initial_capital + max(0, months_elapsed) * monthly_savings)

        if total_value > 0:
            for t in tickers:
                px = float(current_prices[t]) if pd.notna(current_prices[t]) else np.nan
                weight_history.loc[date, t] = ((shares[t] * px) / total_value * 100) if pd.notna(px) else 0.0
            cash_weight_history.loc[date] = cash / total_value * 100
        else:
            weight_history.loc[date] = 0.0
            cash_weight_history.loc[date] = 0.0

    bh_shares = {t: 0.0 for t in tickers}
    bh_lots_state = init_tax_lot_state(tickers)
    bh_cash = float(initial_capital)
    equity_bh = pd.Series(index=dates, dtype=float)

    for i, date in enumerate(dates):
        current_prices = valuation_prices.loc[date]
        live_mask = prices.loc[date].notna()
        live_tickers = [t for t in tickers if live_mask.get(t, False)]
        current_year = int(date.year)
        if bh_tax_state["year"] != current_year:
            bh_tax_state["year"] = current_year
            bh_tax_state["used_allowance"] = 0.0

        if i > 0:
            prev_date = dates[i - 1]
            if date.month != prev_date.month or date.year != prev_date.year:
                bh_cash += monthly_savings

        if live_tickers and bh_cash > 0:
            per_asset_bh = bh_cash / len(live_tickers)
            for t in live_tickers:
                price_now = float(current_prices[t]) if pd.notna(current_prices[t]) else np.nan
                if pd.isna(price_now) or price_now <= 0:
                    continue
                add_shares = per_asset_bh / price_now
                bh_shares[t] += add_shares
                bh_lots_state[t]["shares"] += add_shares
                bh_lots_state[t]["cost_total"] += add_shares * price_now
            bh_cash = 0.0

        bh_value = float(np.nansum([
            max(0.0, bh_shares[t]) * (float(current_prices[t]) if pd.notna(current_prices[t]) else 0.0) for t in tickers
        ])) + max(0.0, bh_cash)
        equity_bh.loc[date] = max(0.0, bh_value)

    bot_metrics = compute_metrics(equity_bot)
    bh_metrics = compute_metrics(equity_bh)
    exposure = (invested_bot / equity_bot.replace(0, np.nan)).mean() * 100
    avg_cash_quote = (cash_bot / equity_bot.replace(0, np.nan)).mean() * 100
    outperformance_pp = bot_metrics["total_return"] - bh_metrics["total_return"]

    last_prices = valuation_prices.iloc[-1]
    final_equity = equity_bot.iloc[-1]
    current_weights = {t: ((shares[t] * float(last_prices[t]) / final_equity) * 100 if final_equity > 0 and pd.notna(last_prices[t]) else 0.0) for t in tickers}
    weights_df = pd.DataFrame({
        T["weights_ticker_col"]: list(current_weights.keys()),
        T["weights_current_col"]: list(current_weights.values()),
    }).sort_values(T["weights_current_col"], ascending=False)

    rebalance_df = pd.DataFrame(rebalance_log)
    weights_with_cash = weight_history.copy()
    weights_with_cash["Cash"] = cash_weight_history
    weights_with_cash = weights_with_cash.fillna(0.0)
    weights_chart_df = simplify_weight_chart(weights_with_cash, top_k=weight_chart_top_n, other_label=T["other_label"])
    rebalance_dates = [entry[T["date_col"]] for entry in rebalance_log]
    weights_rebalance_only = weights_with_cash.loc[weights_with_cash.index.intersection(rebalance_dates)].copy()

    benchmark_equities = build_benchmark_equity_series(get_benchmark_list(), period, dates, float(initial_capital), float(monthly_savings))

    latest_dt = dates[-1]
    latest_score_breakdown_df = pd.DataFrame({
        "Ticker": tickers,
        "Trend Score": component_scores["trend"].loc[latest_dt].values,
        "Momentum Score": component_scores["momentum"].loc[latest_dt].values,
        "Quality Score": component_scores["quality"].loc[latest_dt].values,
        "Risk Score": component_scores["risk"].loc[latest_dt].values,
        "Regime-Fit Score": component_scores["regime_fit"].loc[latest_dt].values,
        "KI Overlay": ai_overlay_scores.loc[latest_dt].values,
        "Gesamtscore": total_score.loc[latest_dt].values,
    }).sort_values("Gesamtscore", ascending=False).reset_index(drop=True)

    ki_explanations_df = pd.DataFrame({
        "Ticker": tickers,
        "KI Erklärung": [ai_explanations.get(latest_dt, {}).get(t, "") for t in tickers],
    }).sort_values("Ticker").reset_index(drop=True)

    regime_summary_df = (
        regime_df[["regime"]]
        .assign(count=1)
        .groupby("regime", as_index=False)["count"]
        .sum()
        .rename(columns={"count": "Tage"})
    )

    latest_top_asset_explanations = []
    return {
        "bot_metrics": bot_metrics,
        "bh_metrics": bh_metrics,
        "exposure": exposure,
        "avg_cash_quote": avg_cash_quote,
        "outperformance_pp": outperformance_pp,
        "trade_count": trade_count,
        "conviction_power": conviction_power,
        "soft_cash_mode": soft_cash_mode,
        "target_cash_floor_pct": target_cash_floor_pct,
        "target_cash_ceiling_pct": target_cash_ceiling_pct,
        "equity_bot": equity_bot,
        "equity_bh": equity_bh,
        "cumulative_contributions": cumulative_contributions,
        "cash_bot": cash_bot,
        "invested_bot": invested_bot,
        "rebalance_df": rebalance_df,
        "weights_with_cash": weights_with_cash,
        "weights_chart_df": weights_chart_df,
        "weights_df": weights_df,
        "selected_assets_log": selected_assets_log,
        "target_weights_log": target_weights_log,
        "weights_rebalance_only": weights_rebalance_only,
        "show_debug": show_debug,
        "tickers": tickers,
        "skipped_tickers": [],
        "top_n": top_n,
        "effective_top_n": effective_top_n,
        "max_weight_pct": max_weight_pct,
        "use_regime_filter": use_regime_filter,
        "prices": prices,
        "raw_score": total_score,
        "benchmark_equities": benchmark_equities,
        "simulate_taxes_de": simulate_taxes_de,
        "bot_taxes_paid": bot_tax_state["taxes_paid_total"],
        "bh_taxes_paid": bh_tax_state["taxes_paid_total"],
        "regime_df": regime_df,
        "regime_summary_df": regime_summary_df,
        "latest_score_breakdown_df": latest_score_breakdown_df,
        "ki_explanations_df": ki_explanations_df,
        "latest_top_asset_explanations": latest_top_asset_explanations,
        "enable_ki_explanations": bool(st.session_state.get("enable_ki_explanations", False)),
        "estimated_tax_drag_pct_map": estimated_tax_drag_pct_map,
        "alignment_info": alignment_info or {},
    }


def is_crypto_or_high_beta_ticker(ticker: str) -> bool:
    t = str(ticker).upper()
    crypto_tokens = ["BTC", "ETH", "SOL", "MSTR", "COIN", "IBIT", "BITX", "ARKK", "HOOD"]
    return any(token in t for token in crypto_tokens)

def get_ki_explanation(ticker: str, context: dict) -> str:
    lang = context.get("lang", "DE")
    trend = float(context.get("trend_score", 50.0) or 50.0)
    momentum = float(context.get("momentum_score", 50.0) or 50.0)
    quality = float(context.get("quality_score", 50.0) or 50.0)
    risk = float(context.get("risk_score", 50.0) or 50.0)
    regime = str(context.get("regime", "Transition"))
    tax_drag = float(context.get("estimated_tax_drag_pct", 0.0) or 0.0)

    if lang == "DE":
        lead = f"{ticker} bleibt interessant, weil Trend ({trend:.0f}) und Momentum ({momentum:.0f}) aktuell tragfähig wirken." if (trend >= 60 or momentum >= 60) else f"{ticker} ist eher eine Beimischung, weil die Signale aktuell gemischt sind."
        tail = f"Im Regime '{regime}' passt der Titel gut zur aktuellen Auswahl." if quality >= 55 else f"Das Risiko ({risk:.0f}) ist höher, deshalb wird die Position nur dosiert gewichtet."
        if tax_drag > 3:
            tail += " Ein Verkauf wird zusätzlich gegen die geschätzte Steuerlast abgewogen."
        return " ".join([lead, tail])[:260]
    lead = f"{ticker} stays interesting because trend ({trend:.0f}) and momentum ({momentum:.0f}) still look constructive." if (trend >= 60 or momentum >= 60) else f"{ticker} is more of a smaller allocation because the signals are currently mixed."
    tail = f"In the '{regime}' regime the asset still fits the active selection." if quality >= 55 else f"Risk ({risk:.0f}) is higher, so the position is sized more carefully."
    if tax_drag > 3:
        tail += " A sale is also weighed against the estimated tax drag."
    return " ".join([lead, tail])[:260]

def build_latest_top_asset_explanations(context: dict, lang: str) -> list[dict]:
    selected_assets_log = context.get("selected_assets_log", {})
    if not selected_assets_log:
        return []
    last_dt = max(selected_assets_log.keys())
    selected = selected_assets_log.get(last_dt, []) or []
    if not selected:
        return []

    score_df = context.get("latest_score_breakdown_df")
    regime_df = context.get("regime_df")
    rebal_df = context.get("rebalance_df", pd.DataFrame())
    strategy = ""
    if not rebal_df.empty:
        latest_row = rebal_df.iloc[-1]
        strategy = str(latest_row.get(T["rebal_reason_col"], ""))

    explanations = []
    for ticker in selected:
        row = None
        if isinstance(score_df, pd.DataFrame) and not score_df.empty and "Ticker" in score_df.columns:
            matched = score_df[score_df["Ticker"] == ticker]
            if not matched.empty:
                row = matched.iloc[0]
        context_payload = {
            "lang": lang,
            "regime": str(regime_df.loc[last_dt, "regime"]) if regime_df is not None and last_dt in regime_df.index else "",
            "strategy": strategy,
            "trend_score": float(row["Trend Score"]) if row is not None else 50.0,
            "momentum_score": float(row["Momentum Score"]) if row is not None else 50.0,
            "quality_score": float(row["Quality Score"]) if row is not None else 50.0,
            "risk_score": float(row["Risk Score"]) if row is not None else 50.0,
            "regime_fit_score": float(row["Regime-Fit Score"]) if row is not None else 50.0,
            "ai_overlay": float(row["KI Overlay"]) if row is not None else 0.0,
            "total_score": float(row["Gesamtscore"]) if row is not None else 50.0,
            "estimated_tax_drag_pct": float(context.get("estimated_tax_drag_pct_map", {}).get(ticker, 0.0)),
        }
        explanations.append({
            "ticker": ticker,
            "text": get_ki_explanation(ticker, context_payload),
        })
    return explanations

def render_calculation_results(context, T, lang, tier):
    bot_metrics = context["bot_metrics"]
    bh_metrics = context["bh_metrics"]
    exposure = context["exposure"]
    avg_cash_quote = context["avg_cash_quote"]
    outperformance_pp = context["outperformance_pp"]
    trade_count = context["trade_count"]
    conviction_power = context["conviction_power"]
    soft_cash_mode = context["soft_cash_mode"]
    target_cash_floor_pct = context["target_cash_floor_pct"]
    target_cash_ceiling_pct = context["target_cash_ceiling_pct"]
    equity_bot = context["equity_bot"]
    equity_bh = context["equity_bh"]
    cumulative_contributions = context["cumulative_contributions"]
    cash_bot = context["cash_bot"]
    invested_bot = context["invested_bot"]
    rebalance_df = context["rebalance_df"]
    weights_with_cash = context["weights_with_cash"]
    weights_chart_df = context["weights_chart_df"]
    weights_df = context["weights_df"]
    selected_assets_log = context["selected_assets_log"]
    target_weights_log = context["target_weights_log"]
    weights_rebalance_only = context["weights_rebalance_only"]
    show_debug = context["show_debug"]
    tickers = context["tickers"]
    skipped_tickers = context["skipped_tickers"]
    top_n = context["top_n"]
    effective_top_n = context["effective_top_n"]
    max_weight_pct = context["max_weight_pct"]
    use_regime_filter = context["use_regime_filter"]
    prices = context["prices"]
    raw_score = context["raw_score"]
    annual_returns_df = compute_annual_returns(equity_bot, equity_bh, T)
    benchmark_equities = context.get("benchmark_equities", {})
    simulate_taxes_de = context.get("simulate_taxes_de", False)
    bot_taxes_paid = context.get("bot_taxes_paid", 0.0)
    bh_taxes_paid = context.get("bh_taxes_paid", 0.0)
    alignment_info = context.get("alignment_info", {})

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
    c5.metric(T["metric_paid_in"], f"{cumulative_contributions.iloc[-1]:,.2f} €")
    c6.metric(T["metric_bh_return"], f"{bh_metrics['total_return']:.2f}%")
    c7.metric(T["metric_exposure"], f"{exposure:.1f}%")
    c8.metric(T["metric_cash"], f"{avg_cash_quote:.1f}%")
    
    c9, c10, c11, c12, c13 = st.columns(5)
    c9.metric(T["metric_bot_return"], f"{bot_metrics['total_return']:.2f}%")
    c10.metric(T["metric_cagr"], f"{bot_metrics['cagr']:.2f}%")
    c11.metric(T["metric_dd"], f"{bot_metrics['max_dd']:.2f}%")
    c12.metric(T["metric_vol"], f"{bot_metrics['volatility']:.2f}%")
    c13.metric(T["metric_sharpe"], f"{bot_metrics['sharpe']:.2f}")
    
    requested_floor_start = alignment_info.get("requested_floor_start")
    actual_common_start = alignment_info.get("actual_common_start")
    first_full_coverage_start = alignment_info.get("first_full_coverage_start")
    asset_history_df = alignment_info.get("asset_history_df", pd.DataFrame())

    def _fmt_dt(dt_value):
        if dt_value is None or pd.isna(dt_value):
            return "—"
        try:
            return pd.Timestamp(dt_value).strftime("%Y-%m-%d")
        except Exception:
            return str(dt_value)

    if requested_floor_start is not None or actual_common_start is not None:
        late_assets = []
        if isinstance(asset_history_df, pd.DataFrame) and not asset_history_df.empty and actual_common_start is not None:
            late_assets = asset_history_df.loc[
                asset_history_df["first_valid"] > pd.Timestamp(actual_common_start), "ticker"
            ].tolist()
        st.info(
            (
                f"📅 Angeforderter Fix-Start: {_fmt_dt(requested_floor_start)} | Tatsächlicher Simulationsstart: {_fmt_dt(actual_common_start)} | Volle Abdeckung ab: {_fmt_dt(first_full_coverage_start)}"
                if lang == "DE"
                else f"📅 Requested fixed start: {_fmt_dt(requested_floor_start)} | Actual simulation start: {_fmt_dt(actual_common_start)} | Full coverage from: {_fmt_dt(first_full_coverage_start)}"
            )
        )
        if late_assets:
            preview = ", ".join(late_assets[:12]) + (" ..." if len(late_assets) > 12 else "")
            st.warning(
                (
                    f"Diese Assets starten später und werden ab ihrer ersten verfügbaren Historie eingeblendet: {preview}"
                    if lang == "DE"
                    else f"These assets start later and are introduced from their first available history onward: {preview}"
                )
            )
    
    st.success(T["end_capital_success"].format(value=f"{equity_bot.iloc[-1]:,.2f} €"))
    if simulate_taxes_de:
        net_col_1, net_col_2 = st.columns(2)
        with net_col_1:
            render_net_tax_badge(T["metric_net_bot"], float(equity_bot.iloc[-1]), float(cumulative_contributions.iloc[-1]))
        with net_col_2:
            render_net_tax_badge(T["metric_net_bh"], float(equity_bh.iloc[-1]), float(cumulative_contributions.iloc[-1]))
        st.caption(f"🇩🇪 {T['taxes_col']}: Bot {bot_taxes_paid:,.2f} € | Buy & Hold {bh_taxes_paid:,.2f} €")
    st.markdown(
        f"""
        <div style="margin:.35rem 0 1rem 0;padding:.9rem 1rem;border-radius:16px;
        background:linear-gradient(135deg, rgba(15,23,42,0.94) 0%, rgba(30,41,59,0.94) 100%);
        border:1px solid rgba(255,255,255,0.08);">
            <div style="font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;color:rgba(147,197,253,.92);font-weight:800;">CAGR Spotlight</div>
            <div style="font-size:1.2rem;font-weight:800;color:#f8fafc;margin-top:.15rem;">{T["metric_cagr"]}: {bot_metrics['cagr']:.2f}%</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    
    st.markdown("### 📈 Equity & Einzahlungen" if lang == "DE" else "### 📈 Equity & Contributions")
    # Equity chart
    equity_fig = go.Figure()
    equity_fig.add_trace(
        go.Scatter(
            x=equity_bot.index,
            y=equity_bot.values,
            mode="lines",
            name=T["equity_label_bot"],
            line=dict(width=3),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.2f} €<extra>" + T["equity_label_bot"] + "</extra>",
        )
    )
    equity_fig.add_trace(
        go.Scatter(
            x=equity_bh.index,
            y=equity_bh.values,
            mode="lines",
            name=T["equity_label_bh"],
            line=dict(width=2, dash="dash"),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.2f} €<extra>" + T["equity_label_bh"] + "</extra>",
        )
    )
    for bench_name, bench_equity in benchmark_equities.items():
        equity_fig.add_trace(
            go.Scatter(
                x=bench_equity.index,
                y=bench_equity.values,
                mode="lines",
                name=bench_name,
                line=dict(width=1.4),
                opacity=0.9,
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.2f} €<extra>" + bench_name + "</extra>",
            )
        )
    equity_fig.add_trace(
        go.Scatter(
            x=cumulative_contributions.index,
            y=cumulative_contributions.values,
            mode="lines",
            name=T["equity_label_paid_in"],
            line=dict(width=2, dash="dot", color="gray"),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.2f} €<extra>" + T["equity_label_paid_in"] + "</extra>",
        )
    )
    equity_fig.update_layout(
        title=T["equity_title"],
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=20, r=20, t=60, b=20),
        xaxis_title="",
        yaxis_title="€",
    )
    st.plotly_chart(equity_fig, use_container_width=True)
    if benchmark_equities:
        st.caption((T["benchmark_added_title"] + ": " + ", ".join(benchmark_equities.keys())))
    
    # Export
    st.markdown(f"### {T['export_title']}")
    st.caption(T["export_caption"])
    st.caption("💾 Downloads behalten die aktuelle Berechnung sichtbar." if lang == "DE" else "💾 Downloads keep the current calculation visible.")
    
    export_equity_df = pd.DataFrame({
        T["date_col"]: equity_bot.index,
        T["bot_portfolio_label"]: equity_bot.values,
        T["buy_hold_label"]: equity_bh.values,
        T["equity_label_paid_in"]: cumulative_contributions.values,
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
        st.markdown(f"### {T['interpret_why_title']}")
        st.markdown(T["interpret_why_text"])
        if simulate_taxes_de:
            st.markdown(f"### {T['tax_note_title']}")
            st.markdown(T["tax_note_text"])
            st.markdown(T["tax_gross_net_text"])

        if context.get("regime_summary_df") is not None:
            st.markdown("### Regime Engine")
            st.dataframe(context["regime_summary_df"], use_container_width=True)
        if context.get("latest_score_breakdown_df") is not None:
            st.markdown("### Score-Breakdown")
            st.dataframe(context["latest_score_breakdown_df"].round(2), use_container_width=True)
        if context.get("ki_explanations_df") is not None:
            st.markdown("### KI-Overlay Erklärungen" if lang == "DE" else "### AI Overlay Explanations")
            st.dataframe(context["ki_explanations_df"], use_container_width=True)
    
    with st.expander(T["annual_returns_title"], expanded=True):
        if not annual_returns_df.empty:
            annual_display_df = annual_returns_df.copy()
            st.dataframe(
                annual_display_df.style.format({
                    T["annual_returns_bot"]: "{:.2f}",
                    T["annual_returns_bh"]: "{:.2f}",
                }),
                use_container_width=True,
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
    
    weights_plot_df = weights_chart_df.copy()
    weights_fig = go.Figure()
    
    for col in weights_plot_df.columns:
        weights_fig.add_trace(
            go.Scatter(
                x=weights_plot_df.index,
                y=weights_plot_df[col],
                mode="lines",
                name=col,
                stackgroup="one",
                groupnorm="",
                hovertemplate="%{x|%Y-%m-%d}<br>" + col + ": %{y:.2f}%<extra></extra>",
            )
        )
    
    weights_fig.update_layout(
        title=T["weights_chart_inner_title"],
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=20, r=20, t=60, b=20),
        xaxis_title="",
        yaxis_title=T["weights_chart_ylabel"],
    )
    weights_fig.update_yaxes(range=[0, 100], ticksuffix="%")
    st.plotly_chart(weights_fig, use_container_width=True)
    
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
    
    st.markdown("### 🔁 Rebalancing-Log" if lang == "DE" else "### 🔁 Rebalancing Log")
    with st.expander(T["rebal_log"], expanded=True):
        if not rebalance_df.empty:
            display_rebal_df = rebalance_df.copy()
            preferred_cols = [
                T["date_col"],
                T["regime_ok_col"],
                T["selected_assets_col"],
                T["buy_hold_action_col"],
                T["rebal_buys_col"],
                T["rebal_sells_col"],
                T["rebal_reason_col"],
                T["turnover_col"],
                T["fees_col"],
                T["taxes_col"],
                T["cash_eur_col"],
                T["portfolio_eur_col"],
            ]
            display_rebal_df = display_rebal_df[[c for c in preferred_cols if c in display_rebal_df.columns]]
            numeric_cols = display_rebal_df.select_dtypes(include=[np.number]).columns
            display_rebal_df[numeric_cols] = display_rebal_df[numeric_cols].round(2)
            styled_rebal_df = style_rebalance_log(display_rebal_df, T["rebal_buys_col"], T["rebal_sells_col"])
            st.dataframe(styled_rebal_df, use_container_width=True)
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
            if isinstance(alignment_info.get("asset_history_df"), pd.DataFrame) and not alignment_info.get("asset_history_df").empty:
                history_df = alignment_info["asset_history_df"].copy()
                st.write("Asset-Historie / Startdaten" if lang == "DE" else "Asset history / start dates")
                st.dataframe(history_df, use_container_width=True)
    
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
    .sidebar-account-card {
        background: linear-gradient(135deg, rgba(15,23,42,0.96) 0%, rgba(30,41,59,0.96) 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 18px;
        padding: 0.95rem 1rem;
        margin-bottom: 0.8rem;
        color: rgba(255,255,255,0.95);
        box-shadow: 0 14px 28px rgba(0,0,0,0.18);
    }
    .sidebar-account-kicker {
        font-size: 0.74rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: rgba(147,197,253,0.92);
        margin-bottom: 0.35rem;
        font-weight: 800;
    }
    .sidebar-account-title {
        font-size: 1.05rem;
        font-weight: 800;
        margin-bottom: 0.25rem;
        color: #f8fafc;
    }
    .sidebar-account-text {
        font-size: 0.92rem;
        line-height: 1.5;
        color: rgba(248,250,252,0.80);
    }
    .sidebar-plan-badge {
        display: inline-block;
        padding: 0.42rem 0.72rem;
        border-radius: 999px;
        font-size: 0.84rem;
        font-weight: 800;
        margin-top: 0.45rem;
        background: rgba(34,197,94,0.16);
        border: 1px solid rgba(34,197,94,0.30);
        color: #ecfccb;
    }
    .sidebar-subscription-panel {
        background: linear-gradient(135deg, rgba(15,23,42,0.98) 0%, rgba(30,41,59,0.98) 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 18px;
        padding: 0.95rem 1rem;
        margin: 0.25rem 0 0.85rem 0;
        color: rgba(248,250,252,0.95);
        box-shadow: 0 14px 28px rgba(0,0,0,0.18);
    }
    .sidebar-subscription-title {
        font-size: 1rem;
        font-weight: 800;
        color: #f8fafc;
        margin-bottom: 0.35rem;
    }
    .sidebar-subscription-meta {
        font-size: 0.92rem;
        color: rgba(248,250,252,0.78);
        line-height: 1.55;
        margin-top: 0.35rem;
    }
    .sidebar-upgrade-note {
        font-size: 0.86rem;
        color: rgba(191,219,254,0.92);
        line-height: 1.5;
        margin: 0.15rem 0 0.55rem 0;
    }
    div[data-testid="stButton"] button[kind="secondary"] {
        border-radius: 12px;
    }
    div[data-testid="stButton"] button[kind="secondary"][data-baseweb="button"] {
        min-height: 2.6rem;
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

tier = get_current_tier()
override_tier = get_test_override_tier(st.session_state.get("auth_user_email", ""))

plan_badge_map = {
    "Free": AUTH_T["plan_free_badge"],
    "Basic": AUTH_T["plan_basic_badge"],
    "Pro": AUTH_T["plan_pro_badge"],
    "Lifetime": AUTH_T["plan_lifetime_badge"],
}
plan_state_text_map = {
    "Free": T["free_warning"],
    "Basic": T["basic_active"],
    "Pro": T["pro_active"],
    "Lifetime": T["lifetime_active"],
}

if st.session_state.get("auth_logged_in"):
    st.sidebar.markdown(
        f"""
        <div class="sidebar-account-card">
            <div class="sidebar-account-kicker">{AUTH_T["account_magic_title"]}</div>
            <div class="sidebar-account-title">{AUTH_T["logged_in_as"]}</div>
            <div class="sidebar-account-text">{st.session_state["auth_user_email"]}</div>
            <div class="sidebar-plan-badge">{TIER_ICONS.get(tier, "🔑")} {plan_badge_map.get(tier, tier)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.caption(AUTH_T["plan_note"])
    st.sidebar.info(plan_state_text_map.get(tier, tier))
    if override_tier:
        st.sidebar.caption(f"🧪 Test-Override aktiv: {override_tier} für {st.session_state.get('auth_user_email', '')}")
else:
    st.sidebar.markdown(
        f"""
        <div class="sidebar-account-card">
            <div class="sidebar-account-kicker">{AUTH_T["account_guest_title"]}</div>
            <div class="sidebar-account-title">{AUTH_T["guest_info"]}</div>
            <div class="sidebar-account-text">{AUTH_T["security_note"]}</div>
            <div class="sidebar-plan-badge">{TIER_ICONS.get("Free", "🆓")} {plan_badge_map.get("Free", "Free")}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
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
                    st.rerun()
                else:
                    st.sidebar.error(message)

st.sidebar.subheader(AUTH_T["upgrade_title"])
st.sidebar.caption(AUTH_T["upgrade_hint"])
st.sidebar.markdown(f"<div class='sidebar-upgrade-note'>{AUTH_T['upgrade_microcopy']}</div>", unsafe_allow_html=True)

upgrade_col_1, upgrade_col_2, upgrade_col_3 = st.sidebar.columns(3)

with upgrade_col_1:
    if st.session_state.get("auth_logged_in", False):
        st.link_button("Basic", build_checkout_url(STRIPE_BASIC), use_container_width=True)
    else:
        if st.button("Basic", key="upgrade_basic_gate", use_container_width=True):
            st.session_state["sidebar_upgrade_prompt_plan"] = "Basic"

with upgrade_col_2:
    if st.session_state.get("auth_logged_in", False):
        st.link_button("Pro", build_checkout_url(STRIPE_PRO), use_container_width=True)
    else:
        if st.button("Pro", key="upgrade_pro_gate", use_container_width=True):
            st.session_state["sidebar_upgrade_prompt_plan"] = "Pro"

with upgrade_col_3:
    if st.session_state.get("auth_logged_in", False):
        st.link_button("Lifetime", build_checkout_url(STRIPE_LIFETIME), use_container_width=True)
    else:
        if st.button("Lifetime", key="upgrade_lifetime_gate", use_container_width=True):
            st.session_state["sidebar_upgrade_prompt_plan"] = "Lifetime"

if (not st.session_state.get("auth_logged_in", False)) and st.session_state.get("sidebar_upgrade_prompt_plan"):
    chosen_plan = st.session_state.get("sidebar_upgrade_prompt_plan")
    st.sidebar.warning(get_checkout_login_required_text(lang))
    st.sidebar.caption(
        f"✨ {chosen_plan} wartet schon auf dich — einmal kurz einloggen, dann geht’s direkt weiter zum Checkout."
        if lang == "DE"
        else f"✨ {chosen_plan} is already waiting for you — quick login first, then it’s straight to checkout."
    )
    st.sidebar.caption(AUTH_T["login_gate_caption"])
    if st.sidebar.button(get_login_redirect_button_text(lang), key="sidebar_login_redirect", use_container_width=True):
        st.switch_page("pages/1_Allocato.py")

st.sidebar.caption(AUTH_T["stripe_note"])

if st.session_state.get("auth_logged_in"):
    with st.sidebar.expander(AUTH_T["password_change_title"], expanded=False):
        with st.form("change_password_form", clear_on_submit=False):
            current_pw = st.text_input(AUTH_T["password_current"], type="password", key="current_password_input")
            new_pw = st.text_input(AUTH_T["password_new"], type="password", key="new_password_input")
            new_pw_repeat = st.text_input(AUTH_T["password_new_repeat"], type="password", key="new_password_repeat_input")
            pw_submit = st.form_submit_button(AUTH_T["password_change_button"], use_container_width=True)
        if pw_submit:
            if new_pw != new_pw_repeat:
                st.sidebar.error(AUTH_T["password_change_mismatch"])
            else:
                ok, message = update_user_password(st.session_state["auth_user_email"], current_pw, new_pw)
                if ok:
                    st.sidebar.success(message)
                else:
                    st.sidebar.error(message)

    with st.sidebar.expander(AUTH_T["email_change_title"], expanded=False):
        with st.form("change_email_form", clear_on_submit=False):
            new_email_value = st.text_input(AUTH_T["email_new"], key="new_email_input")
            email_password = st.text_input(AUTH_T["password"], type="password", key="change_email_password_input")
            email_submit = st.form_submit_button(AUTH_T["email_change_button"], use_container_width=True)
        if email_submit:
            ok, message = update_user_email(st.session_state["auth_user_email"], email_password, new_email_value)
            if ok:
                st.sidebar.success(message)
                st.rerun()
            else:
                st.sidebar.error(message)

    with st.sidebar.expander(AUTH_T["manage_subscription_title"], expanded=True):
        expiry_text = format_subscription_expires_at(st.session_state.get("subscription_expires_at"), lang)
        st.markdown(
            f"""
            <div class="sidebar-subscription-panel">
                <div class="sidebar-account-kicker">{AUTH_T["subscription_spotlight"]}</div>
                <div class="sidebar-subscription-title">{TIER_ICONS.get(tier, "🔑")} {plan_badge_map.get(tier, tier)}</div>
                <div class="sidebar-subscription-meta"><strong>{AUTH_T["active_until"]}:</strong> {expiry_text}</div>
                <div class="sidebar-subscription-meta"><strong>{AUTH_T["plan_includes"]}:</strong> {get_subscription_summary_text(tier, lang)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.caption(
            "💡 Lifetime wird dauerhaft freigeschaltet und bleibt ohne Ablauf einfach entspannt aktiv."
            if lang == "DE"
            else "💡 Lifetime stays unlocked for good and remains active without an expiry date."
        )

        sub_col_1, sub_col_2, sub_col_3 = st.columns(3)
        with sub_col_1:
            st.link_button("Basic", build_checkout_url(STRIPE_BASIC), use_container_width=True)
        with sub_col_2:
            st.link_button("Pro", build_checkout_url(STRIPE_PRO), use_container_width=True)
        with sub_col_3:
            st.link_button("Lifetime", build_checkout_url(STRIPE_LIFETIME), use_container_width=True)

        if tier != "Free":
            st.warning(AUTH_T["cancel_subscription_warning"])
            st.checkbox(
                AUTH_T["cancel_subscription_confirm"],
                key="cancel_subscription_confirmed",
            )
            if st.button(
                AUTH_T["cancel_subscription_final"],
                key="cancel_subscription_button",
                use_container_width=True,
                type="secondary",
            ):
                if not st.session_state.get("cancel_subscription_confirmed", False):
                    st.sidebar.error(AUTH_T["cancel_subscription_need_confirm"])
                else:
                    update_user_tier(st.session_state["auth_user_email"], "Free")
                    st.session_state["subscription_tier"] = "Free"
                    st.session_state["subscription_expires_at"] = ""
                    st.session_state["cancel_subscription_confirmed"] = False
                    enforce_plan_limits()
                    save_logged_in_user_state()
                    st.sidebar.success(AUTH_T["cancel_subscription_success"])
                    st.rerun()
        else:
            st.info(
                "🆓 Du bist aktuell im Free-Modus unterwegs — sobald du upgraden willst, sind die Buttons direkt startklar."
                if lang == "DE"
                else "🆓 You are currently cruising on Free — whenever you want to upgrade, the buttons are ready."
            )

    if st.sidebar.button(AUTH_T["logout_button"], use_container_width=True):
        logout_user()
        st.rerun()

st.sidebar.header(T["subscription_header"])
st.sidebar.markdown(f'**{AUTH_T["current_plan"]}:** {TIER_ICONS.get(tier, "🔑")} {tier}')
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

period_options = ["1y", "2y", "3y"] if tier == "Free" else ["1y", "2y", "3y", "5y", "10y", "15y", "20y", "max"]
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

st.sidebar.subheader(T["benchmark_section"])
st.sidebar.text_area(
    T["benchmark_input"],
    key="benchmark_etfs_input",
    height=90,
    help=T["benchmark_input_help"],
)

simulate_taxes_de = st.sidebar.checkbox(
    T["simulate_taxes_de"],
    key="simulate_taxes_de",
    help=T["simulate_taxes_de_help"],
)

enable_ki_explanations = st.sidebar.checkbox(
    T["enable_ki_explanations"],
    key="enable_ki_explanations",
    help=T["enable_ki_explanations_help"],
)
if enable_ki_explanations and not st.secrets.get("GROK_API_KEY", ""):
    st.sidebar.caption(T["ki_explanations_missing_key"])

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
calculate_clicked = st.sidebar.button(T["calculate"], type="primary")
if calculate_clicked:
    save_active_basket_to_state()

    with st.spinner(T["spinner"]):
        tickers = [x.strip() for x in st.session_state.get("assets_input", "").splitlines() if x.strip()]
        if len(tickers) < 2:
            st.error(T["error_min_assets"])
            st.stop()

        load_progress = st.progress(0, text="0%")
        load_status = st.empty()

        series_map, skipped_tickers, partial_history_tickers = load_close_prices(
            tickers,
            period,
            progress_bar=load_progress,
            status_box=load_status,
        )

        for skipped in skipped_tickers:
            st.warning(T["warning_skip"].format(ticker=skipped))
        for partial_ticker in partial_history_tickers:
            st.info(T["warning_partial_history"].format(ticker=partial_ticker))

        prices, dropped_after_align, alignment_info = align_price_series(series_map, period)
        if dropped_after_align:
            st.info(T["warning_align_reduced"])
        for skipped in dropped_after_align:
            if skipped not in skipped_tickers:
                st.warning(T["warning_removed_after_align"].format(ticker=skipped))

        requested_floor_start = alignment_info.get("requested_floor_start")
        actual_common_start = alignment_info.get("actual_common_start")
        if requested_floor_start is not None or actual_common_start is not None:
            def _fmt_start(dt_value):
                if dt_value is None or pd.isna(dt_value):
                    return "—"
                return pd.Timestamp(dt_value).strftime("%Y-%m-%d")
            st.info(
                (
                    f"📅 Fixer Analyse-Start: {_fmt_start(requested_floor_start)} | Tatsächlicher Simulationsstart: {_fmt_start(actual_common_start)}"
                    if lang == "DE"
                    else f"📅 Fixed analysis start: {_fmt_start(requested_floor_start)} | Actual simulation start: {_fmt_start(actual_common_start)}"
                )
            )

        asset_history_df = alignment_info.get("asset_history_df", pd.DataFrame())
        if isinstance(asset_history_df, pd.DataFrame) and not asset_history_df.empty and requested_floor_start is not None:
            late_assets = asset_history_df.loc[
                asset_history_df["first_valid"] > pd.Timestamp(requested_floor_start), "ticker"
            ].tolist()
            for late_ticker in late_assets:
                if late_ticker in prices.columns:
                    st.info(T["warning_partial_history"].format(ticker=late_ticker))

        if prices.empty:
            st.error(T["error_no_data"])
            st.stop()

        tickers = list(prices.columns)
        if len(tickers) < 2:
            st.error(T["error_less_than_2"])
            st.stop()

        try:
            context = simulate_allocato_v2(
                prices=prices,
                period=period,
                lang=lang,
                initial_capital=float(initial_capital),
                monthly_savings=float(monthly_savings),
                rebalance_freq=rebalance_freq,
                fee_pct=float(fee_pct),
                min_score=float(min_score),
                max_weight_pct=int(max_weight_pct),
                vol_penalty=float(vol_penalty),
                cash_interest_pct=float(cash_interest_pct),
                show_debug=bool(show_debug),
                conviction_power=float(conviction_power),
                soft_cash_mode=bool(soft_cash_mode),
                target_cash_floor_pct=int(target_cash_floor_pct),
                target_cash_ceiling_pct=int(target_cash_ceiling_pct),
                soft_cash_invest_ratio_pct=int(soft_cash_invest_ratio_pct),
                top_n=int(top_n),
                simulate_taxes_de=bool(simulate_taxes_de),
                alignment_info=alignment_info,
            )
        except ValueError:
            st.error(T["error_too_few_rows"])
            st.stop()

        context["skipped_tickers"] = skipped_tickers + [t for t in dropped_after_align if t not in skipped_tickers]
        context["latest_top_asset_explanations"] = build_latest_top_asset_explanations(context, lang)
        st.session_state["last_calc_results"] = context
        render_calculation_results(context, T, lang, tier)
        save_logged_in_user_state()

elif st.session_state.get("last_calc_results") is not None:
    cached_context = st.session_state["last_calc_results"]
    cached_context["latest_top_asset_explanations"] = build_latest_top_asset_explanations(cached_context, lang)
    render_calculation_results(cached_context, T, lang, tier)
else:
    st.info(T["info_start"])
    if get_current_tier() == "Free":
        st.caption(T["footer_free"])
