from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import httpx


# ============================================================
# EXISTING COMMAND PARSER
# ============================================================

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
    return {
        "ok": False,
        "error_code": code,
        "message": msg
    }


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


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI()


# ============================================================
# EXISTING /parse ENDPOINT
# ============================================================

class CommandInput(BaseModel):
    text: str


@app.post("/parse")
def parse_command(payload: CommandInput):

    return handle(payload.text)


# ============================================================
# WHATSAPP EMBEDDED SIGNUP
# ============================================================

class WhatsAppSignupRequest(BaseModel):
    code: str


async def meta_get(
    url: str,
    params: dict,
    access_token: str
):
    """
    Make a GET request to Meta Graph API.

    The access token is only used server-side.
    """

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    try:

        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:

            response = await client.get(
                url,
                params=params,
                headers=headers
            )

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail=f"Failed to contact Meta: {str(exc)}"
        )

    try:
        data = response.json()

    except Exception:

        raise HTTPException(
            status_code=502,
            detail="Meta returned an invalid response."
        )

    return response, data


# ============================================================
# EMBEDDED SIGNUP AUTHORIZATION
# ============================================================

@app.post("/whatsapp/signup")
async def whatsapp_signup(
    payload: WhatsAppSignupRequest
):

    # --------------------------------------------------------
    # LOAD ENVIRONMENT VARIABLES
    # --------------------------------------------------------

    app_id = os.getenv("META_APP_ID")

    app_secret = os.getenv("META_APP_SECRET")

    graph_version = os.getenv(
        "META_GRAPH_VERSION",
        "v25.0"
    )


    # --------------------------------------------------------
    # VALIDATE SERVER CONFIGURATION
    # --------------------------------------------------------

    if not app_id:

        raise HTTPException(
            status_code=500,
            detail="META_APP_ID is not configured."
        )

    if not app_secret:

        raise HTTPException(
            status_code=500,
            detail="META_APP_SECRET is not configured."
        )

    if not payload.code:

        raise HTTPException(
            status_code=400,
            detail="Authorization code is required."
        )


    # --------------------------------------------------------
    # STEP 1
    # EXCHANGE EMBEDDED SIGNUP CODE FOR ACCESS TOKEN
    # --------------------------------------------------------

    token_url = (
        f"https://graph.facebook.com/"
        f"{graph_version}/oauth/access_token"
    )

    token_params = {

        "client_id": app_id,

        "client_secret": app_secret,

        "code": payload.code

    }


    try:

        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:

            token_response = await client.get(
                token_url,
                params=token_params
            )

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail={
                "message": "Could not contact Meta.",
                "error": str(exc)
            }
        )


    try:

        token_data = token_response.json()

    except Exception:

        raise HTTPException(
            status_code=502,
            detail="Meta returned an invalid token response."
        )


    # --------------------------------------------------------
    # META REJECTED THE CODE
    # --------------------------------------------------------

    if token_response.status_code != 200:

        raise HTTPException(

            status_code=400,

            detail={
                "message":
                    "Meta rejected the Embedded Signup "
                    "authorization code.",

                "meta_response":
                    token_data
            }
        )


    # --------------------------------------------------------
    # EXTRACT ACCESS TOKEN
    # --------------------------------------------------------

    business_token = token_data.get(
        "access_token"
    )


    if not business_token:

        raise HTTPException(

            status_code=502,

            detail=
                "Meta did not return an access token."
        )


    # --------------------------------------------------------
    # IMPORTANT SECURITY RULE
    # --------------------------------------------------------
    #
    # NEVER return business_token to the browser.
    #
    # We keep it server-side.
    #
    # --------------------------------------------------------


    # --------------------------------------------------------
    # STEP 2
    # DEBUG THE TOKEN
    # --------------------------------------------------------
    #
    # Meta's Embedded Signup documentation uses
    # /debug_token after signup to inspect the
    # returned token and its granted scopes.
    #
    # --------------------------------------------------------

    debug_url = (
        f"https://graph.facebook.com/"
        f"{graph_version}/debug_token"
    )

    debug_params = {

        "input_token":
            business_token

    }


    debug_response, debug_data = await meta_get(

        debug_url,

        debug_params,

        business_token

    )


    if debug_response.status_code != 200:

        raise HTTPException(

            status_code=400,

            detail={
                "message":
                    "Meta returned an error while "
                    "debugging the authorization token.",

                "meta_response":
                    debug_data
            }
        )


    token_info = debug_data.get(
        "data",
        {}
    )


    # --------------------------------------------------------
    # CHECK TOKEN VALIDITY
    # --------------------------------------------------------

    if token_info.get("is_valid") is not True:

        raise HTTPException(

            status_code=400,

            detail={
                "message":
                    "The authorization token returned "
                    "by Meta is not valid.",

                "token_info":
                    token_info
            }
        )


    # --------------------------------------------------------
    # EXTRACT SAFE INFORMATION
    # --------------------------------------------------------

    scopes = token_info.get(
        "scopes",
        []
    )

    user_id = token_info.get(
        "user_id"
    )


    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------
    #
    # For now we STOP here.
    #
    # We do NOT yet query the customer's WABA because
    # we need the appropriate business context from
    # the completed onboarding.
    #
    # Session 3 will handle:
    #
    #   Shared WABA discovery
    #   ↓
    #   WABA ID
    #   ↓
    #   Phone numbers
    #
    # --------------------------------------------------------

    print(
        "Meta Embedded Signup authorization successful."
    )

    print(
        f"Meta user ID: {user_id}"
    )

    print(
        f"Granted scopes: {scopes}"
    )


    return {

        "ok": True,

        "message":
            "Meta Embedded Signup authorization "
            "was successfully exchanged and validated.",

        "meta_user_id":
            user_id,

        "scopes":
            scopes

    }
