from fastapi import FastAPI
from pydantic import BaseModel

ALLOWED_COMMANDS = {"ADD", "REMOVE", "SET"}

ERRORS = {
    "EMPTY": ("EMPTY_INPUT", "Input is empty"),
    "FORMAT": ("INVALID_FORMAT", "Invalid command format"),
    "COMMAND": ("UNKNOWN_COMMAND", "Unknown command"),
    "ITEM": ("INVALID_ITEM", "Invalid item name"),
    "QUANTITY": ("INVALID_QUANTITY", "Quantity must be a positive integer"),
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

    return {"ok": True, "action": cmd, "item": item, "quantity": int(raw_qty)}

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
