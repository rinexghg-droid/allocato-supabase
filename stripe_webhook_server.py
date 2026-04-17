import os
import sqlite3
from datetime import datetime

import stripe
from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI(title="Allocato Stripe Webhook")

# =========================
# ENV
# =========================
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
DB_PATH = os.getenv("ALLOCATO_DB_PATH", "allocato_users.db")

# Diese Preis-IDs musst du in Stripe nachschauen und eintragen.
# Beispiel:
# STRIPE_PRICE_BASIC = "price_123"
# STRIPE_PRICE_PRO = "price_456"
# STRIPE_PRICE_LIFETIME = "price_789"
STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_LIFETIME = os.getenv("STRIPE_PRICE_LIFETIME", "")

stripe.api_key = STRIPE_SECRET_KEY

PRICE_TO_TIER = {
    STRIPE_PRICE_BASIC: "Basic",
    STRIPE_PRICE_PRO: "Pro",
    STRIPE_PRICE_LIFETIME: "Lifetime",
}

VALID_TIERS = {"Free", "Basic", "Pro", "Lifetime"}


# =========================
# DB HELPERS
# =========================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_user_exists(email: str):
    now = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT email FROM users WHERE email = ?",
            (email.lower().strip(),)
        ).fetchone()

        if row is None:
            conn.execute(
                """
                INSERT INTO users (email, password_hash, subscription_tier, state_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    email.lower().strip(),
                    "__STRIPE_CREATED_NO_PASSWORD__",
                    "Free",
                    "{}",
                    now,
                    now,
                ),
            )
            conn.commit()


def update_user_tier(email: str, tier: str):
    if tier not in VALID_TIERS:
        raise ValueError(f"Ungültiger Tier: {tier}")

    ensure_user_exists(email)
    now = datetime.utcnow().isoformat()

    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET subscription_tier = ?, updated_at = ?
            WHERE email = ?
            """,
            (tier, now, email.lower().strip()),
        )
        conn.commit()


def get_line_item_tier(session_id: str) -> str | None:
    line_items = stripe.checkout.Session.list_line_items(session_id, limit=10)
    for item in line_items.data:
        price = getattr(item, "price", None)
        if not price:
            continue
        price_id = getattr(price, "id", "")
        tier = PRICE_TO_TIER.get(price_id)
        if tier:
            return tier
    return None


# =========================
# ROUTES
# =========================
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret fehlt")

    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiger Payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Ungültige Stripe-Signatur")

    event_type = event["type"]
    obj = event["data"]["object"]

    # Einmalige Käufe / Payment Link / Checkout
    if event_type == "checkout.session.completed":
        email = (
            obj.get("customer_details", {}).get("email")
            or obj.get("customer_email")
            or obj.get("metadata", {}).get("user_email")
        )

        if not email:
            return {"received": True, "note": "Keine E-Mail im Checkout gefunden"}

        tier = get_line_item_tier(obj["id"])
        if not tier:
            return {"received": True, "note": "Keine passende Preis-ID gemappt"}

        update_user_tier(email, tier)
        return {"received": True, "email": email, "tier": tier}

    # Optional: wieder auf Free setzen, wenn Abo endet
    if event_type in {
        "customer.subscription.deleted",
        "customer.subscription.updated",
    }:
        status = obj.get("status", "")
        customer_id = obj.get("customer")

        if not customer_id:
            return {"received": True, "note": "Kein customer_id"}

        customer = stripe.Customer.retrieve(customer_id)
        email = customer.get("email")
        if not email:
            return {"received": True, "note": "Kein customer email"}

        # Nur wenn wirklich beendet / inaktiv
        if status in {"canceled", "unpaid", "incomplete_expired"}:
            update_user_tier(email, "Free")
            return {"received": True, "email": email, "tier": "Free"}

    return {"received": True, "ignored": event_type}
