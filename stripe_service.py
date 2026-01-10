import os
import stripe
import logging
from decimal import Decimal, ROUND_HALF_UP

logger = logging.getLogger("stripe_service")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

EUR_DAILY_LIMIT = Decimal("5000.00")

def to_cents(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def create_stripe_payout(amount: float, currency: str):
    if not stripe.api_key:
        return {"error": "STRIPE_SECRET_KEY is not set"}

    currency = currency.upper()
    amt = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Only enforce limit for EUR payouts (still in EUR only)
    if currency == "EUR":
        eur_bank_id = os.getenv("EUR_BANK_ID")
        if not eur_bank_id:
            return {"error": "EUR_BANK_ID is not set"}

        if amt <= EUR_DAILY_LIMIT:
            return _payout(amt, "eur", eur_bank_id)

        # Split into two EUR payouts (same currency) if you really want to cap daily
        first = _payout(EUR_DAILY_LIMIT, "eur", eur_bank_id)
        second = _payout(amt - EUR_DAILY_LIMIT, "eur", eur_bank_id)
        return [first, second]

    # Other currencies payout to their configured destination (same currency)
    dest = os.getenv(f"{currency}_BANK_ID")
    return _payout(amt, currency.lower(), dest)

def _payout(amount: Decimal, currency: str, destination=None):
    payout_data = {
        "amount": to_cents(amount),
        "currency": currency,
        "method": "standard",
        "statement_descriptor": "Payouts",
    }
    if destination:
        payout_data["destination"] = destination

    payout = stripe.Payout.create(**payout_data)
    return {
        "id": payout.id,
        "status": payout.status,
        "amount": payout.amount,
        "currency": payout.currency,
    }
