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
# META HELPERS
# ============================================================

async def meta_get(
    url: str,
    params: dict,
    access_token: str
):

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
            detail={
                "message": "Failed to contact Meta.",
                "error": str(exc)
            }
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
# WHATSAPP EMBEDDED SIGNUP REQUEST
# ============================================================

class WhatsAppSignupRequest(BaseModel):
    code: str


# ============================================================
# WHATSAPP EMBEDDED SIGNUP
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

    business_id = os.getenv(
        "META_BUSINESS_ID"
    )


    # --------------------------------------------------------
    # VALIDATE CONFIGURATION
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

    if not business_id:

        raise HTTPException(
            status_code=500,
            detail="META_BUSINESS_ID is not configured."
        )

    if not payload.code:

        raise HTTPException(
            status_code=400,
            detail="Authorization code is required."
        )


    # ========================================================
    # STEP 1
    # EXCHANGE AUTHORIZATION CODE
    # ========================================================

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
                "message":
                    "Could not contact Meta during "
                    "authorization exchange.",

                "error": str(exc)
            }
        )


    try:

        token_data = token_response.json()

    except Exception:

        raise HTTPException(
            status_code=502,
            detail=
                "Meta returned an invalid authorization response."
        )


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


    business_token = token_data.get(
        "access_token"
    )


    if not business_token:

        raise HTTPException(
            status_code=502,
            detail=
                "Meta did not return an access token."
        )


    # ========================================================
    # STEP 2
    # DEBUG THE TOKEN
    # ========================================================

    debug_url = (
        f"https://graph.facebook.com/"
        f"{graph_version}/debug_token"
    )

    debug_params = {
        "input_token": business_token
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
    # Extract safe token information
    # --------------------------------------------------------

    scopes = token_info.get(
        "scopes",
        []
    )

    meta_user_id = token_info.get(
        "user_id"
    )


    # ========================================================
    # STEP 3
    # DISCOVER SHARED WABAs
    # ========================================================
    #
    # Meta's Embedded Signup documentation uses:
    #
    # /{Business-ID}/client_whatsapp_business_accounts
    #
    # to retrieve WABAs assigned/shared with the
    # Tech Provider's Business Manager after signup.
    #
    # The system-user token is used for this operation.
    #
    # ========================================================

    shared_wabas_url = (
        f"https://graph.facebook.com/"
        f"{graph_version}/"
        f"{business_id}/"
        f"client_whatsapp_business_accounts"
    )


    shared_wabas_response, shared_wabas_data = await meta_get(

        shared_wabas_url,

        {},

        business_token

    )


    # --------------------------------------------------------
    # Handle Meta error
    # --------------------------------------------------------

    if shared_wabas_response.status_code != 200:

        raise HTTPException(

            status_code=400,

            detail={
                "message":
                    "Authorization succeeded, but Meta "
                    "did not allow AnchorFlow to retrieve "
                    "shared WABAs.",

                "meta_response":
                    shared_wabas_data
            }
        )


    # --------------------------------------------------------
    # Extract WABAs
    # --------------------------------------------------------

    wabas = shared_wabas_data.get(
        "data",
        []
    )


    # ========================================================
    # IMPORTANT
    # ========================================================
    #
    # It is possible to have:
    #
    #   - zero WABAs
    #   - one WABA
    #   - multiple WABAs
    #
    # We should NOT blindly select the first WABA.
    #
    # For now we return the discovered WABAs.
    #
    # In the production onboarding system, we'll correlate
    # the newly onboarded client with the correct WABA.
    #
    # ========================================================


    safe_wabas = []

    for waba in wabas:

        safe_wabas.append({

            "id":
                waba.get("id"),

            "name":
                waba.get("name"),

            "currency":
                waba.get("currency"),

            "timezone_id":
                waba.get("timezone_id"),

            "message_template_namespace":
                waba.get(
                    "message_template_namespace"
                )

        })


    # ========================================================
    # STEP 4
    # GET PHONE NUMBERS
    # ========================================================
    #
    # We only query phone numbers when exactly one WABA
    # has been discovered.
    #
    # This avoids accidentally selecting the wrong WABA
    # when multiple client WABAs exist.
    #
    # ========================================================

    phone_numbers = []

    selected_waba_id = None


    if len(safe_wabas) == 1:

        selected_waba_id = safe_wabas[0]["id"]

        phone_numbers_url = (
            f"https://graph.facebook.com/"
            f"{graph_version}/"
            f"{selected_waba_id}/"
            f"phone_numbers"
        )


        phone_response, phone_data = await meta_get(

            phone_numbers_url,

            {},

            business_token

        )


        if phone_response.status_code != 200:

            raise HTTPException(

                status_code=400,

                detail={
                    "message":
                        "WABA was discovered, but Meta "
                        "did not allow AnchorFlow to "
                        "retrieve its phone numbers.",

                    "waba_id":
                        selected_waba_id,

                    "meta_response":
                        phone_data
                }
            )


        phone_numbers = phone_data.get(
            "data",
            []
        )


    # ========================================================
    # LOG SAFE INFORMATION
    # ========================================================

    print(
        "Meta Embedded Signup authorization successful."
    )

    print(
        f"Meta user ID: {meta_user_id}"
    )

    print(
        f"Granted scopes: {scopes}"
    )

    print(
        f"Discovered WABAs: {len(safe_wabas)}"
    )

    if selected_waba_id:

        print(
            f"Selected WABA ID: {selected_waba_id}"
        )

        print(
            f"Phone numbers found: "
            f"{len(phone_numbers)}"
        )


    # ========================================================
    # RETURN SAFE RESPONSE
    # ========================================================
    #
    # NEVER return the access token.
    #
    # ========================================================

    return {

        "ok": True,

        "message":
            "Embedded Signup authorization succeeded "
            "and WABA discovery completed.",

        "meta_user_id":
            meta_user_id,

        "scopes":
            scopes,

        "waba_count":
            len(safe_wabas),

        "wabas":
            safe_wabas,

        "selected_waba_id":
            selected_waba_id,

        "phone_numbers":
            phone_numbers

    }
# ============================================================
# SESSION 4 - TEST WABA ACCESS
# ============================================================

@app.get("/whatsapp/test-assets")
async def test_whatsapp_assets():

    system_user_token = os.getenv("META_SYSTEM_USER_TOKEN")
    graph_version = os.getenv("META_GRAPH_VERSION", "v25.0")

    waba_id = "2328538700984791"
    phone_number_id = "1000053203193157"
    business_id = os.getenv("META_BUSINESS_ID")

    if not system_user_token:
        raise HTTPException(
            status_code=500,
            detail="META_SYSTEM_USER_TOKEN is not configured."
        )

    if not business_id:
        raise HTTPException(
            status_code=500,
            detail="META_BUSINESS_ID is not configured."
        )

    headers = {
        "Authorization": f"Bearer {system_user_token}"
    }

    results = {}

    try:

        async with httpx.AsyncClient(timeout=30.0) as client:

            # ------------------------------------------------
            # 1. Get WABA details
            # ------------------------------------------------

            waba_response = await client.get(
                f"https://graph.facebook.com/"
                f"{graph_version}/{waba_id}",
                params={
                    "fields": "id,name,currency,timezone_id"
                },
                headers=headers
            )

            results["waba"] = {
                "status_code": waba_response.status_code,
                "response": waba_response.json()
            }


            # ------------------------------------------------
            # 2. Get phone numbers belonging to WABA
            # ------------------------------------------------

            phones_response = await client.get(
                f"https://graph.facebook.com/"
                f"{graph_version}/{waba_id}/phone_numbers",
                headers=headers
            )

            results["phone_numbers"] = {
                "status_code": phones_response.status_code,
                "response": phones_response.json()
            }


            # ------------------------------------------------
            # 3. Verify assigned users
            # ------------------------------------------------

            assigned_users_response = await client.get(
                f"https://graph.facebook.com/"
                f"{graph_version}/{waba_id}/assigned_users",
                params={
                    "business": business_id
                },
                headers=headers
            )

            results["assigned_users"] = {
                "status_code":
                    assigned_users_response.status_code,

                "response":
                    assigned_users_response.json()
            }


            # ------------------------------------------------
            # 4. Get specific phone number details
            # ------------------------------------------------

            phone_response = await client.get(
                f"https://graph.facebook.com/"
                f"{graph_version}/{phone_number_id}",
                params={
                    "fields":
                        "id,display_phone_number,"
                        "verified_name,quality_rating,"
                        "code_verification_status"
                },
                headers=headers
            )

            results["specific_phone"] = {
                "status_code": phone_response.status_code,
                "response": phone_response.json()
            }


    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail={
                "message":
                    "Failed to communicate with Meta.",

                "error":
                    str(exc)
            }
        )


    return {
        "ok": True,
        "message":
            "Session 4 WABA access test completed.",

        "business_id":
            business_id,

        "system_user_id":
            "61593436147926",

        "waba_id":
            waba_id,

        "phone_number_id":
            phone_number_id,

        "results":
            results
    }
