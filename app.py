from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import httpx


ALLOWED_COMMANDS = {"ADD", "REMOVE", "SET"}

ERRORS = {
    "EMPTY": ("EMPTY_INPUT", "Input is empty"),
    "FORMAT": ("INVALID_FORMAT", "Invalid command format"),
    "COMMAND": ("UNKNOWN_COMMAND", "Unknown command"),
    "ITEM": ("INVALID_ITEM", "Invalid item name"),
    "QUANTITY": ("INVALID_QUANTITY", "Quantity must be a positive number"),
}


def error(key):
    code, msg = ERRORS[key]
    return {"ok": False, "error_code": code, "message": msg}


def normalize(raw: str) -> str:
    if not raw or not raw.strip():
        raise ValueError("EMPTY")
    return " ".join(raw.strip().split())


def parse(normalized: str) -> dict:
    parts = normalized.split(" ")

    if len(parts) != 3:
        raise ValueError("FORMAT")

    raw_cmd, raw_item, raw_qty = parts

    cmd = raw_cmd.upper()
    item = raw_item.lower()

    if cmd not in ALLOWED_COMMANDS:
        raise ValueError("COMMAND")

    if not item.isalpha():
        raise ValueError("ITEM")

    if not raw_qty.isdigit() or int(raw_qty) <= 0:
        raise ValueError("QUANTITY")

    return {
        "ok": True,
        "action": cmd,
        "item": item,
        "quantity": int(raw_qty)
    }


def handle(user_input: str) -> dict:
    try:
        return parse(normalize(user_input))
    except ValueError as e:
        return error(str(e))


# ---------------- HTTP PART ----------------

app = FastAPI()


class CommandInput(BaseModel):
    text: str


@app.post("/parse")
def parse_command(payload: CommandInput):
    return handle(payload.text)


# ---------------- META WHATSAPP EMBEDDED SIGNUP ----------------

class WhatsAppSignupRequest(BaseModel):
    code: str


@app.post("/whatsapp/signup")
async def whatsapp_signup(payload: WhatsAppSignupRequest):

    app_id = os.getenv("META_APP_ID")
    app_secret = os.getenv("META_APP_SECRET")

    if not app_id or not app_secret:
        raise HTTPException(
            status_code=500,
            detail="Meta credentials are not configured on the server."
        )

    graph_version = "v25.0"

    url = f"https://graph.facebook.com/{graph_version}/oauth/access_token"

    params = {
        "client_id": app_id,
        "client_secret": app_secret,
        "code": payload.code,
    }

    try:

        async with httpx.AsyncClient(timeout=30.0) as client:

            response = await client.get(
                url,
                params=params
            )

        data = response.json()

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail=f"Failed to contact Meta: {str(exc)}"
        )

    if response.status_code != 200:

        raise HTTPException(
            status_code=response.status_code,
            detail={
                "message": "Meta rejected the authorization code.",
                "meta_response": data
            }
        )

    business_token = data.get("access_token")

    if not business_token:

        raise HTTPException(
            status_code=502,
            detail="Meta response did not contain an access token."
        )

    # IMPORTANT:
    # Do NOT return the business token to the browser.
    # For this first test, we only confirm that the exchange succeeded.
    #
    # Later we will securely store the token and use it to:
    # - identify the customer's WABA
    # - retrieve phone numbers
    # - subscribe the WABA to webhooks
    # - complete onboarding

    print("Meta Embedded Signup token exchange successful.")

    return {
        "ok": True,
        "message": "Meta authorization code exchanged successfully."
    }
