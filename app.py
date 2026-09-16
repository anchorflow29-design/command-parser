from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import uuid
from datetime import datetime, timezone
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
# CORS
# Allow the public Anchorflow onboarding page on GitHub Pages
# to call the backend onboarding endpoints from the browser.
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://anchorflow29-design.github.io"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# ============================================================
# SESSION 7A
# SUPABASE CLIENT REGISTRY
# ============================================================

async def upsert_client_mapping(
    waba_id: str,
    phone_number_id: str,
    business_name: str | None = None
):
    """
    Create or update the persistent Anchorflow client mapping.

    Supabase is accessed only from the backend using the secret key.
    The secret is never returned to the browser.
    """

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_URL is not configured."
        )

    if not supabase_key:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_SERVICE_ROLE_KEY is not configured."
        )

    base_url = supabase_url.rstrip("/")
    clients_url = f"{base_url}/rest/v1/clients"

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    # First try to find an existing client by WABA ID.
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            clients_url,
            headers=headers,
            params={
                "waba_id": f"eq.{waba_id}",
                "select": "*",
                "limit": "1"
            }
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Supabase client lookup failed: {response.text}"
            )

        rows = response.json()

        # If the WABA is not found, also check the phone number.
        if not rows:
            response = await client.get(
                clients_url,
                headers=headers,
                params={
                    "phone_number_id": f"eq.{phone_number_id}",
                    "select": "*",
                    "limit": "1"
                }
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Supabase phone lookup failed: {response.text}"
                )

            rows = response.json()

        # Existing client: update its current connection details.
        if rows:
            existing = rows[0]
            client_id = existing["client_id"]

            update_data = {
                "waba_id": waba_id,
                "phone_number_id": phone_number_id,
                "connection_status": "CONNECTED",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }

            if business_name:
                update_data["business_name"] = business_name

            response = await client.patch(
                clients_url,
                headers={**headers, "Prefer": "return=representation"},
                params={"client_id": f"eq.{client_id}"},
                json=update_data
            )

            if response.status_code not in (200, 204):
                raise HTTPException(
                    status_code=502,
                    detail=f"Supabase client update failed: {response.text}"
                )

            updated_rows = response.json() if response.status_code == 200 else []
            record = updated_rows[0] if updated_rows else {**existing, **update_data}

            return {
                "client_id": client_id,
                "created": False,
                "record": record
            }

        # New client: generate an internal Anchorflow client ID.
        client_id = f"client_{uuid.uuid4().hex[:12]}"

        record = {
            "client_id": client_id,
            "business_name": business_name or "Unnamed Dealership",
            "waba_id": waba_id,
            "phone_number_id": phone_number_id,
            "connection_status": "CONNECTED"
        }

        response = await client.post(
            clients_url,
            headers={**headers, "Prefer": "return=representation"},
            json=record
        )

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=502,
                detail=f"Supabase client creation failed: {response.text}"
            )

        created_rows = response.json()
        return {
            "client_id": client_id,
            "created": True,
            "record": created_rows[0] if created_rows else record
        }



# ============================================================
# SESSION 9A
# STORED CLIENT TOKEN VALIDATION
# ============================================================

class ClientTokenStatusRequest(BaseModel):
    client_id: str


@app.post("/whatsapp/client-token-status")
async def whatsapp_client_token_status(
    payload: ClientTokenStatusRequest
):
    """
    Validate a previously stored client Meta business access token.

    The client_id is supplied by the caller.
    The actual access token is retrieved server-side from Supabase.

    The access token is NEVER returned to the browser.
    """

    app_id = os.getenv("META_APP_ID")
    app_secret = os.getenv("META_APP_SECRET")
    graph_version = os.getenv(
        "META_GRAPH_VERSION",
        "v25.0"
    )

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

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

    if not supabase_url:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_URL is not configured."
        )

    if not supabase_key:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_SERVICE_ROLE_KEY is not configured."
        )

    if not payload.client_id:
        raise HTTPException(
            status_code=400,
            detail="client_id is required."
        )

    # ------------------------------------------------------------
    # STEP 1
    # Retrieve the client credential server-side
    # ------------------------------------------------------------

    credentials_url = (
        f"{supabase_url.rstrip('/')}/rest/v1/"
        f"client_credentials"
    )

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=20.0) as client:

        credential_response = await client.get(
            credentials_url,
            headers=headers,
            params={
                "client_id": f"eq.{payload.client_id}",
                "select": (
                    "client_id,provider,access_token,"
                    "token_type,expires_at,"
                    "data_access_expires_at,"
                    "updated_at"
                ),
                "limit": "1"
            }
        )

    if credential_response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail={
                "message":
                    "Supabase credential lookup failed.",
                "error":
                    credential_response.text
            }
        )

    credential_rows = credential_response.json()

    if not credential_rows:
        return {
            "ok": False,
            "client_id": payload.client_id,
            "token_status": "NOT_FOUND",
            "message":
                "No stored Meta credential exists for this client."
        }

    credential = credential_rows[0]

    access_token = credential.get("access_token")

    if not access_token:
        return {
            "ok": False,
            "client_id": payload.client_id,
            "token_status": "MISSING",
            "message":
                "The client credential exists but contains no access token."
        }

    # ------------------------------------------------------------
    # STEP 2
    # Debug the stored token with Meta
    # ------------------------------------------------------------

    debug_url = (
        f"https://graph.facebook.com/"
        f"{graph_version}/debug_token"
    )

    try:

        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:

            debug_response = await client.get(
                debug_url,
                params={
                    "input_token": access_token,
                    "access_token":
                        f"{app_id}|{app_secret}"
                }
            )

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail={
                "message":
                    "Could not contact Meta while validating the stored client token.",
                "error":
                    str(exc)
            }
        )

    try:
        debug_data = debug_response.json()

    except Exception:

        raise HTTPException(
            status_code=502,
            detail:
                "Meta returned an invalid token-debug response."
        )

    # ------------------------------------------------------------
    # STEP 3
    # Handle invalid/revoked token
    # ------------------------------------------------------------

    if debug_response.status_code != 200:

        return {
            "ok": False,
            "client_id": payload.client_id,
            "token_status": "INVALID",
            "message":
                "Meta rejected the stored client access token.",
            "meta_error": debug_data
        }

    token_info = debug_data.get(
        "data",
        {}
    )

    is_valid = token_info.get(
        "is_valid"
    )

    if is_valid is not True:

        return {
            "ok": False,
            "client_id": payload.client_id,
            "token_status": "INVALID",
            "token": {
                "is_valid": is_valid,
                "app_id":
                    token_info.get("app_id"),
                "user_id":
                    token_info.get("user_id"),
                "scopes":
                    token_info.get("scopes", []),
                "expires_at":
                    token_info.get("expires_at"),
                "data_access_expiration_time":
                    token_info.get(
                        "data_access_expiration_time"
                    )
            }
        }

    # ------------------------------------------------------------
    # STEP 4
    # Return SAFE metadata only
    # ------------------------------------------------------------

    return {
        "ok": True,
        "client_id": payload.client_id,
        "token_status": "VALID",
        "token": {
            "is_valid":
                token_info.get("is_valid"),
            "app_id":
                token_info.get("app_id"),
            "user_id":
                token_info.get("user_id"),
            "scopes":
                token_info.get("scopes", []),
            "expires_at":
                token_info.get("expires_at"),
            "data_access_expiration_time":
                token_info.get(
                    "data_access_expiration_time"
                )
        },
        "stored_credential": {
            "provider":
                credential.get("provider"),
            "token_type":
                credential.get("token_type"),
            "updated_at":
                credential.get("updated_at")
        },
        "message":
            "Stored Meta client access token is valid."
    }


# ============================================================
# SESSION 7E
# CLIENT WHATSAPP TOKEN STORAGE
# ============================================================

class WhatsAppTokenExchangeRequest(BaseModel):
    code: str
    client_id: str
    waba_id: str
    phone_number_id: str


async def store_client_business_token(
    client_id: str,
    waba_id: str,
    phone_number_id: str,
    access_token: str,
    token_type: str | None,
    expires_at: str | None,
    data_access_expires_at: str | None
):
    """
    Store the Meta business access token server-side.

    The token is never returned to the browser.
    This table is accessed using the Supabase service-role key.
    """

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_URL is not configured."
        )

    if not supabase_key:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_SERVICE_ROLE_KEY is not configured."
        )

    clients_url = f"{supabase_url.rstrip('/')}/rest/v1/clients"
    credentials_url = (
        f"{supabase_url.rstrip('/')}/rest/v1/client_credentials"
    )

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    # Verify the supplied client mapping before storing a secret.
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            clients_url,
            headers=headers,
            params={
                "client_id": f"eq.{client_id}",
                "waba_id": f"eq.{waba_id}",
                "phone_number_id": f"eq.{phone_number_id}",
                "select": "client_id",
                "limit": "1"
            }
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Supabase client verification failed: {response.text}"
            )

        rows = response.json()

        if not rows:
            raise HTTPException(
                status_code=404,
                detail="The supplied client_id does not match the WABA and phone number."
            )

        credential_record = {
            "client_id": client_id,
            "provider": "META_WHATSAPP",
            "access_token": access_token,
            "token_type": token_type,
            "expires_at": expires_at,
            "data_access_expires_at": data_access_expires_at,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        response = await client.post(
            credentials_url,
            headers={
                **headers,
                "Prefer": "resolution=merge-duplicates,return=representation"
            },
            params={"on_conflict": "client_id"},
            json=credential_record
        )

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=502,
                detail=f"Supabase credential storage failed: {response.text}"
            )

    return {
        "stored": True,
        "provider": "META_WHATSAPP",
        "expires_at": expires_at,
        "data_access_expires_at": data_access_expires_at
    }


@app.post("/whatsapp/token-exchange")
async def whatsapp_token_exchange(
    payload: WhatsAppTokenExchangeRequest
):
    """
    Exchange the short-lived Embedded Signup authorization code for
    the client's Meta business access token and store it server-side.

    The access token is NEVER returned to the browser.
    """

    app_id = os.getenv("META_APP_ID")
    app_secret = os.getenv("META_APP_SECRET")
    graph_version = os.getenv(
        "META_GRAPH_VERSION",
        "v25.0"
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

    if not payload.code:
        raise HTTPException(
            status_code=400,
            detail="Authorization code is required."
        )

    for field_name, field_value in (
        ("client_id", payload.client_id),
        ("waba_id", payload.waba_id),
        ("phone_number_id", payload.phone_number_id),
    ):
        if not field_value:
            raise HTTPException(
                status_code=400,
                detail=f"{field_name} is required."
            )

    if not payload.waba_id.isdigit():
        raise HTTPException(
            status_code=400,
            detail="WABA ID must contain only digits."
        )

    if not payload.phone_number_id.isdigit():
        raise HTTPException(
            status_code=400,
            detail="Phone Number ID must contain only digits."
        )

    # ------------------------------------------------------------
    # STEP 1
    # Exchange short-lived authorization code server-to-server
    # ------------------------------------------------------------

    token_url = (
        f"https://graph.facebook.com/"
        f"{graph_version}/oauth/access_token"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            token_response = await client.get(
                token_url,
                params={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "code": payload.code
                }
            )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Could not contact Meta during authorization exchange.",
                "error": str(exc)
            }
        )

    try:
        token_data = token_response.json()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Meta returned an invalid authorization response."
        )

    if token_response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Meta rejected the Embedded Signup authorization code.",
                "meta_response": token_data
            }
        )

    business_token = token_data.get("access_token")

    if not business_token:
        raise HTTPException(
            status_code=502,
            detail="Meta did not return an access token."
        )

    # ------------------------------------------------------------
    # STEP 2
    # Debug token metadata without returning the token
    # ------------------------------------------------------------

    debug_url = (
        f"https://graph.facebook.com/"
        f"{graph_version}/debug_token"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            debug_response = await client.get(
                debug_url,
                params={
                    "input_token": business_token,
                    "access_token": f"{app_id}|{app_secret}"
                }
            )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Could not contact Meta while validating the new token.",
                "error": str(exc)
            }
        )

    try:
        debug_data = debug_response.json()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Meta returned an invalid token-debug response."
        )

    if debug_response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Meta rejected the returned business access token during validation.",
                "meta_response": debug_data
            }
        )

    token_info = debug_data.get("data", {})

    if token_info.get("is_valid") is not True:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Meta returned an invalid business access token.",
                "token_info": {
                    "is_valid": token_info.get("is_valid"),
                    "app_id": token_info.get("app_id"),
                    "user_id": token_info.get("user_id"),
                    "scopes": token_info.get("scopes", []),
                    "expires_at": token_info.get("expires_at"),
                    "data_access_expiration_time": token_info.get(
                        "data_access_expiration_time"
                    )
                }
            }
        )

    expires_at = token_info.get("expires_at")
    data_access_expires_at = token_info.get(
        "data_access_expiration_time"
    )
    token_type = token_data.get("token_type")

    # ------------------------------------------------------------
    # STEP 3
    # Store the secret against the verified Anchorflow client
    # ------------------------------------------------------------

    stored = await store_client_business_token(
        client_id=payload.client_id,
        waba_id=payload.waba_id,
        phone_number_id=payload.phone_number_id,
        access_token=business_token,
        token_type=token_type,
        expires_at=(
            str(expires_at)
            if expires_at is not None
            else None
        ),
        data_access_expires_at=(
            str(data_access_expires_at)
            if data_access_expires_at is not None
            else None
        )
    )

    return {
        "ok": True,
        "token_status": "STORED",
        "client_id": payload.client_id,
        "waba_id": payload.waba_id,
        "phone_number_id": payload.phone_number_id,
        "token_type": token_type,
        "expires_at": (
            str(expires_at)
            if expires_at is not None
            else None
        ),
        "data_access_expires_at": (
            str(data_access_expires_at)
            if data_access_expires_at is not None
            else None
        ),
        "message": (
            "Meta business access token exchanged and stored securely "
            "on the Anchorflow backend."
        )
    }


# ============================================================
# SESSION 6
# UNIFIED WHATSAPP ONBOARDING
# ============================================================

class WhatsAppOnboardingRequest(BaseModel):
    waba_id: str
    phone_number_id: str
    business_name: str | None = None


@app.post("/whatsapp/onboard")
async def whatsapp_onboard(
    payload: WhatsAppOnboardingRequest
):
    """
    Unified onboarding operation.

    Receives the WABA ID and phone number ID produced by
    Embedded Signup, subscribes Anchorflow to the WABA,
    verifies the subscription, and returns the onboarding state.

    No access tokens are returned to the browser. The Embedded Signup
    authorization code is exchanged separately by /whatsapp/token-exchange.
    """

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

    if not payload.phone_number_id:
        raise HTTPException(
            status_code=400,
            detail="Phone Number ID is required."
        )

    if not payload.phone_number_id.isdigit():
        raise HTTPException(
            status_code=400,
            detail="Phone Number ID must contain only digits."
        )

    # ------------------------------------------------------------
    # STEP 1
    # Subscribe Anchorflow to the WABA and verify it
    # ------------------------------------------------------------

    subscription = await subscribe_waba(
        payload.waba_id,
        system_user_token,
        app_id,
        graph_version
    )

    # ------------------------------------------------------------
    # STEP 2
    # Persist the WABA -> phone -> Anchorflow client mapping
    # ------------------------------------------------------------

    if not subscription["verified"]:
        return {
            "ok": False,
            "onboarding_status": "SUBSCRIPTION_NOT_VERIFIED",
            "waba_id": payload.waba_id,
            "phone_number_id": payload.phone_number_id,
            "subscription": subscription
        }

    try:
        client_mapping = await upsert_client_mapping(
            payload.waba_id,
            payload.phone_number_id,
            payload.business_name
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to save client mapping: {str(exc)}"
        )

    return {
        "ok": True,
        "onboarding_status": "CONNECTED",
        "message": "WhatsApp Business account connected successfully.",
        "client_id": client_mapping["client_id"],
        "client_created": client_mapping["created"],
        "waba_id": payload.waba_id,
        "phone_number_id": payload.phone_number_id,
        "subscription": {
            "subscribed": subscription["subscribed"],
            "already_subscribed": subscription["already_subscribed"],
            "verified": subscription["verified"]
        }
    }


# ============================================================
# SESSION 7C
# CLIENT RESOLUTION BY PHONE NUMBER ID
# ============================================================

class WhatsAppClientResolutionRequest(BaseModel):
    phone_number_id: str


@app.post("/whatsapp/resolve-client")
async def whatsapp_resolve_client(
    payload: WhatsAppClientResolutionRequest
):
    """
    Resolve an Anchorflow client from a WhatsApp Phone Number ID.

    This endpoint is backend-only and uses the Supabase service-role
    key. It does not expose the key or modify the existing onboarding
    or Meta webhook/subscription logic.
    """

    if not payload.phone_number_id:
        raise HTTPException(
            status_code=400,
            detail="Phone Number ID is required."
        )

    if not payload.phone_number_id.isdigit():
        raise HTTPException(
            status_code=400,
            detail="Phone Number ID must contain only digits."
        )

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_URL is not configured."
        )

    if not supabase_key:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_SERVICE_ROLE_KEY is not configured."
        )

    clients_url = f"{supabase_url.rstrip('/')}/rest/v1/clients"

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            clients_url,
            headers=headers,
            params={
                "phone_number_id": f"eq.{payload.phone_number_id}",
                "select": "client_id,business_name,waba_id,phone_number_id,connection_status",
                "limit": "1"
            }
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Supabase client resolution failed: {response.text}"
        )

    rows = response.json()

    if not rows:
        return {
            "ok": False,
            "client_found": False,
            "phone_number_id": payload.phone_number_id,
            "message": "No Anchorflow client is registered for this phone number."
        }

    record = rows[0]

    return {
        "ok": True,
        "client_found": True,
        "client_id": record["client_id"],
        "business_name": record["business_name"],
        "waba_id": record["waba_id"],
        "phone_number_id": record["phone_number_id"],
        "connection_status": record["connection_status"]
    }
