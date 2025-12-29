### stripe_fastapi_receiver/main.py

import os
import hmac
import hashlib
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Header, HTTPException
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# Optional: ensure fallback if ssl is missing
try:
    import ssl
except ModuleNotFoundError:
    raise ImportError("Missing 'ssl' module. Ensure your Python environment includes SSL support.")

from stripe_service import create_stripe_payout
from database import init_db, record_transaction

load_dotenv()

app = FastAPI()

SHARED_SECRET = os.getenv("FIMSHAREDSECRET")
if not SHARED_SECRET:
    raise ValueError("FIMSHAREDSECRET not set in environment variables.")
SHARED_SECRET = SHARED_SECRET.encode()

init_db()

SUPPORTED_CURRENCIES = ["USD", "EUR", "GBP"]

class Amount(BaseModel):
    Ccy: str
    value: str

class CreditTransfer(BaseModel):
    Amt: dict
    Cdtr: dict
    CdtrAcct: dict
    RmtInf: dict

class ISO20022Webhook(BaseModel):
    Document: dict

@app.post("/webhook")
async def receive_webhook(
    request: Request,
    x_fim_signature: str = Header(None)
):
    # Verify signature
    raw_body = await request.body()
    expected_sig = hmac.new(SHARED_SECRET, raw_body, hashlib.sha256).hexdigest()
    if x_fim_signature != expected_sig:
        logger.warning("Invalid signature detected.")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON payload
    data = await request.json()
    try:
        message = ISO20022Webhook(**data)
        transfers = message.Document["CstmrCdtTrfInitn"]["PmtInf"]["CdtTrfTxInf"]
        logger.info(f"Received {len(transfers)} transaction(s).")
    except Exception as e:
        logger.error(f"Error parsing webhook payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid data format: {e}")

    results = []
    for tx in transfers:
        amount = float(tx["Amt"]["InstdAmt"]["value"])
        currency = tx["Amt"]["InstdAmt"]["Ccy"].upper()
        reference = tx["RmtInf"]["Ustrd"]
        recipient = tx["Cdtr"]["Nm"]

        logger.info(f"Processing transaction: Ref={reference}, Amount={amount} {currency}, Recipient={recipient}")

        # Save raw transaction before payout
        record_transaction(reference, recipient, amount, currency)
        logger.info("Transaction recorded in database.")

        # Handle only supported currencies
        if currency in SUPPORTED_CURRENCIES:
            # Log USD inflow for tracking
            if currency == "USD":
                logger.info(f"USD inflow detected. Will auto-convert to EUR before payout.")

            payout_response = create_stripe_payout(amount, currency)
            logger.info(f"Payout initiated for {amount} {currency}. Response: {payout_response}")

            results.append({
                "reference": reference,
                "recipient": recipient,
                "original_currency": currency,
                "payout_result": payout_response
            })
        else:
            logger.warning(f"Unsupported currency received: {currency}. Transaction ignored.")
            results.append({
                "reference": reference,
                "recipient": recipient,
                "currency": currency,
                "status": "ignored",
                "reason": f"Unsupported currency: {currency}"
            })

    return {"status": "processed", "results": results}

