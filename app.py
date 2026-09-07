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
# SESSION 5
# REUSABLE WABA SUBSCRIPTION FUNCTION
# ============================================================

async def subscribe_waba(
    waba_id: str,
    system_user_token: str,
    app_id: str,
    graph_version: str
):
    """
    Ensure Anchorflow is subscribed to a WABA.

    This function:
    1. Checks the existing subscriptions.
    2. Detects Anchorflow using the nested Meta response.
    3. If already subscribed, does nothing.
    4. Otherwise sends POST /subscribed_apps.
    5. Verifies the resulting subscription.

    It is intentionally reusable by multiple endpoints.
    """

    url = (
        f"https://graph.facebook.com/"
        f"{graph_version}/"
        f"{waba_id}/"
        f"subscribed_apps"
    )

    headers = {
        "Authorization":
            f"Bearer {system_user_token}"
    }

    try:

        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:

            # =================================================
            # STEP 1
            # Check current subscriptions
            # =================================================

            status_response = await client.get(
                url,
                headers=headers
            )

            try:

                status_data = status_response.json()

            except Exception:

                raise HTTPException(
                    status_code=502,
                    detail=
                        "Meta returned an invalid "
                        "subscription status response."
                )

            if status_response.status_code != 200:

                raise HTTPException(
                    status_code=
                        status_response.status_code,

                    detail={
                        "message":
                            "Meta rejected the WABA "
                            "subscription status request.",

                        "waba_id":
                            waba_id,

                        "meta_response":
                            status_data
                    }
                )

            current_apps = status_data.get(
                "data",
                []
            )

            # =================================================
            # STEP 2
            # Check for Anchorflow
            # =================================================

            already_subscribed = False

            for app in current_apps:

                app_data = app.get(
                    "whatsapp_business_api_data",
                    {}
                )

                if str(
                    app_data.get("id")
                ) == str(app_id):

                    already_subscribed = True
                    break

            # =================================================
            # STEP 3
            # Already subscribed
            # =================================================

            if already_subscribed:

                return {
                    "subscribed": True,
                    "already_subscribed": True,
                    "verified": True,
                    "subscription_request": None,
                    "subscribed_apps": current_apps
                }

            # =================================================
            # STEP 4
            # Subscribe Anchorflow
            # =================================================

            subscribe_response = await client.post(
                url,
                headers=headers
            )

            try:

                subscribe_data = (
                    subscribe_response.json()
                )

            except Exception:

                raise HTTPException(
                    status_code=502,
                    detail=
                        "Meta returned an invalid "
                        "subscription response."
                )

            if subscribe_response.status_code not in (
                200,
                201
            ):

                raise HTTPException(
                    status_code=
                        subscribe_response.status_code,

                    detail={
                        "message":
                            "Meta rejected the WABA "
                            "subscription request.",

                        "waba_id":
                            waba_id,

                        "meta_response":
                            subscribe_data
                    }
                )

            # =================================================
            # STEP 5
            # Verify
            # =================================================

            verify_response = await client.get(
                url,
                headers=headers
            )

            try:

                verify_data = verify_response.json()

            except Exception:

                raise HTTPException(
                    status_code=502,
                    detail=
                        "Meta returned an invalid "
                        "verification response."
                )

            if verify_response.status_code != 200:

                raise HTTPException(
                    status_code=
                        verify_response.status_code,

                    detail={
                        "message":
                            "Subscription request succeeded, "
                            "but verification failed.",

                        "waba_id":
                            waba_id,

                        "meta_response":
                            verify_data
                    }
                )

            final_apps = verify_data.get(
                "data",
                []
            )

            verified = False

            for app in final_apps:

                app_data = app.get(
                    "whatsapp_business_api_data",
                    {}
                )

                if str(
                    app_data.get("id")
                ) == str(app_id):

                    verified = True
                    break

            return {
                "subscribed": verified,
                "already_subscribed": False,
                "verified": verified,
                "subscription_request": subscribe_data,
                "subscribed_apps": final_apps
            }

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail={
                "message":
                    "Failed to communicate with Meta "
                    "during WABA subscription.",

                "error":
                    str(exc)
            }
        )


# ============================================================
# SESSION 5
# READ WABA SUBSCRIPTION STATUS
# ============================================================

async def get_waba_subscription_status(
    waba_id: str,
    system_user_token: str,
    app_id: str,
    graph_version: str
):
    """
    Read-only subscription check.

    This is deliberately separate from subscribe_waba()
    because discovery should not automatically subscribe
    an ambiguous WABA yet.
    """

    url = (
        f"https://graph.facebook.com/"
        f"{graph_version}/"
        f"{waba_id}/"
        f"subscribed_apps"
    )

    headers = {
        "Authorization":
            f"Bearer {system_user_token}"
    }

    try:

        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:

            response = await client.get(
                url,
                headers=headers
            )

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail={
                "message":
                    "Failed to contact Meta.",

                "error":
                    str(exc)
            }
        )

    try:

        data = response.json()

    except Exception:

        raise HTTPException(
            status_code=502,
            detail=
                "Meta returned an invalid subscription response."
        )

    if response.status_code != 200:

        raise HTTPException(
            status_code=response.status_code,
            detail={
                "message":
                    "Meta rejected the WABA subscription "
                    "status request.",

                "waba_id":
                    waba_id,

                "meta_response":
                    data
            }
        )

    subscribed_apps = data.get(
        "data",
        []
    )

    subscribed = False

    for app in subscribed_apps:

        app_data = app.get(
            "whatsapp_business_api_data",
            {}
        )

        if str(
            app_data.get("id")
        ) == str(app_id):

            subscribed = True
            break

    return {
        "subscribed": subscribed,
        "subscribed_apps": subscribed_apps
    }


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

    app_id = os.getenv("META_APP_ID")
    app_secret = os.getenv("META_APP_SECRET")

    graph_version = os.getenv(
        "META_GRAPH_VERSION",
        "v25.0"
    )

    business_id = os.getenv(
        "META_BUSINESS_ID"
    )

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

                "error":
                    str(exc)
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
    # DEBUG TOKEN
    # ========================================================

    debug_url = (
        f"https://graph.facebook.com/"
        f"{graph_version}/debug_token"
    )

    debug_response, debug_data = await meta_get(
        debug_url,
        {
            "input_token":
                business_token
        },
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

    if token_info.get(
        "is_valid"
    ) is not True:

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

    if shared_wabas_response.status_code != 200:

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Authorization succeeded, but Meta "
                    "did not allow Anchorflow to retrieve "
                    "shared WABAs.",

                "meta_response":
                    shared_wabas_data
            }
        )

    wabas = shared_wabas_data.get(
        "data",
        []
    )

    # ========================================================
    # SAFE WABA INFORMATION
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

    phone_numbers = []

    selected_waba_id = None

    # We retain the existing behavior of only selecting a WABA
    # when exactly one is discovered.
    #
    # IMPORTANT:
    # We do NOT automatically subscribe here yet.
    # We only inspect the subscription status.

    subscription = None

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
                        "did not allow Anchorflow to "
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

        # ----------------------------------------------------
        # Read-only subscription status
        # ----------------------------------------------------

        system_user_token = os.getenv(
            "META_SYSTEM_USER_TOKEN"
        )

        if system_user_token:

            subscription = await get_waba_subscription_status(
                selected_waba_id,
                system_user_token,
                app_id,
                graph_version
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

        if subscription:

            print(
                "Anchorflow WABA subscription status: "
                f"{subscription.get('subscribed')}"
            )

    # ========================================================
    # RETURN SAFE RESPONSE
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
            phone_numbers,

        "subscription":
            subscription
    }


# ============================================================
# SESSION 4 - TEST WABA ACCESS
# ============================================================

@app.get("/whatsapp/test-assets")
async def test_whatsapp_assets():

    system_user_token = os.getenv(
        "META_SYSTEM_USER_TOKEN"
    )

    graph_version = os.getenv(
        "META_GRAPH_VERSION",
        "v25.0"
    )

    waba_id = "2328538700984791"

    phone_number_id = "1000053203193157"

    business_id = os.getenv(
        "META_BUSINESS_ID"
    )

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
        "Authorization":
            f"Bearer {system_user_token}"
    }

    results = {}

    try:

        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:

            # ------------------------------------------------
            # 1. Get WABA details
            # ------------------------------------------------

            waba_response = await client.get(
                f"https://graph.facebook.com/"
                f"{graph_version}/{waba_id}",
                params={
                    "fields":
                        "id,name,currency,timezone_id"
                },
                headers=headers
            )

            results["waba"] = {
                "status_code":
                    waba_response.status_code,

                "response":
                    waba_response.json()
            }

            # ------------------------------------------------
            # 2. Get phone numbers
            # ------------------------------------------------

            phones_response = await client.get(
                f"https://graph.facebook.com/"
                f"{graph_version}/"
                f"{waba_id}/phone_numbers",
                headers=headers
            )

            results["phone_numbers"] = {
                "status_code":
                    phones_response.status_code,

                "response":
                    phones_response.json()
            }

            # ------------------------------------------------
            # 3. Verify assigned users
            # ------------------------------------------------

            assigned_users_response = await client.get(
                f"https://graph.facebook.com/"
                f"{graph_version}/"
                f"{waba_id}/assigned_users",
                params={
                    "business":
                        business_id
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
                f"{graph_version}/"
                f"{phone_number_id}",
                params={
                    "fields":
                        "id,display_phone_number,"
                        "verified_name,quality_rating,"
                        "code_verification_status"
                },
                headers=headers
            )

            results["specific_phone"] = {
                "status_code":
                    phone_response.status_code,

                "response":
                    phone_response.json()
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


# ============================================================
# SESSION 4 - DYNAMIC WABA DISCOVERY
# ============================================================

@app.post("/whatsapp/discover")
async def discover_whatsapp_waba(
    payload: WhatsAppSignupRequest
):

    app_id = os.getenv(
        "META_APP_ID"
    )

    app_secret = os.getenv(
        "META_APP_SECRET"
    )

    system_user_token = os.getenv(
        "META_SYSTEM_USER_TOKEN"
    )

    business_id = os.getenv(
        "META_BUSINESS_ID"
    )

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

    graph_version = os.getenv(
        "META_GRAPH_VERSION",
        "v25.0"
    )

    graph_base = (
        f"https://graph.facebook.com/"
        f"{graph_version}"
    )

    try:

        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:

            # ====================================================
            # STEP 1
            # Exchange Embedded Signup authorization code
            # ====================================================

            token_response = await client.get(
                f"{graph_base}/oauth/access_token",
                params={
                    "client_id":
                        app_id,

                    "client_secret":
                        app_secret,

                    "code":
                        payload.code
                }
            )

            token_data = token_response.json()

            if token_response.status_code != 200:

                raise HTTPException(
                    status_code=
                        token_response.status_code,

                    detail={
                        "message":
                            "Meta rejected the authorization code.",

                        "meta_response":
                            token_data
                    }
                )

            oauth_access_token = token_data.get(
                "access_token"
            )

            if not oauth_access_token:

                raise HTTPException(
                    status_code=502,
                    detail=
                        "Meta did not return an access token."
                )

            # ====================================================
            # STEP 2
            # Debug OAuth token
            # ====================================================

            debug_response = await client.get(
                f"{graph_base}/debug_token",
                params={
                    "input_token":
                        oauth_access_token
                },
                headers={
                    "Authorization":
                        f"Bearer {system_user_token}"
                }
            )

            debug_data = debug_response.json()

            if debug_response.status_code != 200:

                raise HTTPException(
                    status_code=
                        debug_response.status_code,

                    detail={
                        "message":
                            "Meta could not debug the "
                            "Embedded Signup token.",

                        "meta_response":
                            debug_data
                    }
                )

            token_info = debug_data.get(
                "data",
                {}
            )

            if not token_info.get(
                "is_valid"
            ):

                raise HTTPException(
                    status_code=400,
                    detail={
                        "message":
                            "The Embedded Signup token "
                            "is not valid.",

                        "token_info":
                            token_info
                    }
                )

            # ====================================================
            # STEP 3
            # Fetch WABAs shared with Anchorflow
            # ====================================================

            waba_response = await client.get(
                f"{graph_base}/"
                f"{business_id}/"
                f"client_whatsapp_business_accounts",

                headers={
                    "Authorization":
                        f"Bearer {system_user_token}"
                }
            )

            waba_data = waba_response.json()

            if waba_response.status_code not in (
                200,
                201
            ):

                raise HTTPException(
                    status_code=
                        waba_response.status_code,

                    detail={
                        "message":
                            "Meta could not retrieve "
                            "shared WABAs.",

                        "meta_response":
                            waba_data
                    }
                )

    except HTTPException:

        raise

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

    # ============================================================
    # NEVER RETURN oauth_access_token
    # ============================================================

    return {

        "ok": True,

        "message":
            "Embedded Signup token validated and "
            "shared WABAs retrieved.",

        "token": {

            "is_valid":
                token_info.get("is_valid"),

            "app_id":
                token_info.get("app_id"),

            "user_id":
                token_info.get("user_id"),

            "scopes":
                token_info.get("scopes"),

            "expires_at":
                token_info.get("expires_at")
        },

        "wabas":
            waba_data.get(
                "data",
                []
            )
    }


# ============================================================
# SESSION 5
# TEST WABA SUBSCRIPTION STATUS
# ============================================================

@app.get("/whatsapp/subscription-status")
async def whatsapp_subscription_status():

    system_user_token = os.getenv(
        "META_SYSTEM_USER_TOKEN"
    )

    graph_version = os.getenv(
        "META_GRAPH_VERSION",
        "v25.0"
    )

    waba_id = "2328538700984791"

    app_id = os.getenv(
        "META_APP_ID"
    )

    if not system_user_token:

        raise HTTPException(
            status_code=500,
            detail="META_SYSTEM_USER_TOKEN is not configured."
        )

    if not app_id:

        raise HTTPException(
            status_code=500,
            detail="META_APP_ID is not configured."
        )

    result = await get_waba_subscription_status(
        waba_id,
        system_user_token,
        app_id,
        graph_version
    )

    return {

        "ok": True,

        "waba_id":
            waba_id,

        "subscribed":
            result["subscribed"],

        "subscribed_apps":
            result["subscribed_apps"]
    }


# ============================================================
# SESSION 5
# MANUAL WABA SUBSCRIPTION
# ============================================================

class WABASubscriptionRequest(BaseModel):
    waba_id: str


@app.post("/whatsapp/subscribe")
async def whatsapp_subscribe(
    payload: WABASubscriptionRequest
):

    system_user_token = os.getenv(
        "META_SYSTEM_USER_TOKEN"
    )

    graph_version = os.getenv(
        "META_GRAPH_VERSION",
        "v25.0"
    )

    app_id = os.getenv(
        "META_APP_ID"
    )

    if not system_user_token:

        raise HTTPException(
            status_code=500,
            detail="META_SYSTEM_USER_TOKEN is not configured."
        )

    if not app_id:

        raise HTTPException(
            status_code=500,
            detail="META_APP_ID is not configured."
        )

    if not payload.waba_id:

        raise HTTPException(
            status_code=400,
            detail="WABA ID is required."
        )

    if not payload.waba_id.isdigit():

        raise HTTPException(
            status_code=400,
            detail="WABA ID must contain only digits."
        )

    result = await subscribe_waba(
        payload.waba_id,
        system_user_token,
        app_id,
        graph_version
    )

    return {

        "ok":
            result["subscribed"],

        "waba_id":
            payload.waba_id,

        "already_subscribed":
            result["already_subscribed"],

        "verified":
            result["verified"],

        "subscription_request":
            result["subscription_request"],

        "subscribed_apps":
            result["subscribed_apps"]
    }
