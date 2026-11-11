# momo.py - GetServiceGH MTN MoMo API
# Works with Merchant SIM - Money goes: Customer -> Your Merchant Wallet -> Worker
# No Paystack, No waiting, No float needed

import os
import uuid
import requests
import base64

# ============ CONFIG - Paste your keys here after MTN office ============
# Get these from MTN office / momodeveloper.mtn.com
API_USER = os.getenv("MTN_API_USER", "YOUR_API_USER_ID")
API_KEY = os.getenv("MTN_API_KEY", "YOUR_API_KEY")
COLLECTION_SUB_KEY = os.getenv("MTN_COLLECTION_KEY", "YOUR_COLLECTION_SUB_KEY")
DISBURSEMENT_SUB_KEY = os.getenv("MTN_DISBURSEMENT_KEY", "YOUR_DISBURSEMENT_SUB_KEY")

# For testing: "sandbox" - For live: "mtn-ghana"
# MTN Ghana live target is "mtn-ghana"
ENVIRONMENT = os.getenv("MTN_ENV", "sandbox")  # change to "mtn-ghana" when live
BASE_URL = "https://sandbox.momodeveloper.mtn.com" if ENVIRONMENT == "sandbox" else "https://proxy.momoapi.mtn.com"

CURRENCY = "GHS"
CALLBACK_URL = os.getenv("MTN_CALLBACK_URL", "https://your-app.onrender.com/momo/callback")

# ============ 1. GET ACCESS TOKEN ============
def get_token(is_disbursement=False):
    """Get token for Collection or Disbursement"""
    sub_key = DISBURSEMENT_SUB_KEY if is_disbursement else COLLECTION_SUB_KEY
    product = "disbursements" if is_disbursement else "collection"
    
    url = f"{BASE_URL}/{product}/token/"
    auth = base64.b64encode(f"{API_USER}:{API_KEY}".encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth}",
        "Ocp-Apim-Subscription-Key": sub_key,
    }
    r = requests.post(url, headers=headers)
    if r.status_code == 200:
        return r.json().get("access_token")
    print(f"Token Error {product}:", r.text)
    return None

# ============ 2. CUSTOMER PAYS YOU (Collection) ============
def request_payment(customer_phone, amount, booking_id, payer_message="Payment for GetServiceGH"):
    """
    Sends MoMo prompt to customer phone.
    Example: request_payment("0541371615", 50, 18)
    Returns: reference_id to check status later
    """
    token = get_token(is_disbursement=False)
    if not token:
        return {"success": False, "error": "Could not get token"}

    reference_id = str(uuid.uuid4())
    # MTN wants phone without +233, just 054...
    phone = customer_phone.replace("+233", "0").strip()

    url = f"{BASE_URL}/collection/v1_0/requesttopay"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Reference-Id": reference_id,
        "X-Target-Environment": ENVIRONMENT,
        "Ocp-Apim-Subscription-Key": COLLECTION_SUB_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "amount": str(amount),
        "currency": CURRENCY,
        "externalId": str(booking_id),
        "payer": {"partyIdType": "MSISDN", "partyId": phone},
        "payerMessage": payer_message,
        "payeeNote": f"Booking #{booking_id} - GetServiceGH"
    }
    r = requests.post(url, json=payload, headers=headers)
    if r.status_code == 202:
        return {"success": True, "reference_id": reference_id, "message": "Prompt sent to customer"}
    return {"success": False, "error": r.text, "reference_id": reference_id}

def check_payment_status(reference_id):
    """Check if customer approved. Returns SUCCESSFUL / PENDING / FAILED"""
    token = get_token(is_disbursement=False)
    url = f"{BASE_URL}/collection/v1_0/requesttopay/{reference_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Target-Environment": ENVIRONMENT,
        "Ocp-Apim-Subscription-Key": COLLECTION_SUB_KEY,
    }
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json()
    return {"status": "ERROR", "detail": r.text}

# ============ 3. PAY WORKER INSTANTLY (Disbursement) ============
def pay_worker(worker_phone, amount, booking_id, message="Payment for completed job"):
    """
    THIS IS THE MAGIC - Takes money from YOUR Merchant Wallet and sends to worker in seconds.
    Example: pay_worker("0541371615", 45, 18)
    """
    token = get_token(is_disbursement=True)
    if not token:
        return {"success": False, "error": "Could not get disbursement token"}

    reference_id = str(uuid.uuid4())
    phone = worker_phone.replace("+233", "0").strip()

    url = f"{BASE_URL}/disbursement/v1_0/transfer"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Reference-Id": reference_id,
        "X-Target-Environment": ENVIRONMENT,
        "Ocp-Apim-Subscription-Key": DISBURSEMENT_SUB_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "amount": str(amount),
        "currency": CURRENCY,
        "externalId": str(booking_id),
        "payee": {"partyIdType": "MSISDN", "partyId": phone},
        "payerMessage": message,
        "payeeNote": f"GetServiceGH - Booking #{booking_id}"
    }
    r = requests.post(url, json=payload, headers=headers)
    if r.status_code == 202:
        return {"success": True, "reference_id": reference_id, "message": "Transfer started - worker will receive in seconds"}
    return {"success": False, "error": r.text, "reference_id": reference_id}

def check_transfer_status(reference_id):
    token = get_token(is_disbursement=True)
    url = f"{BASE_URL}/disbursement/v1_0/transfer/{reference_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Target-Environment": ENVIRONMENT,
        "Ocp-Apim-Subscription-Key": DISBURSEMENT_SUB_KEY,
    }
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json()
    return {"status": "ERROR", "detail": r.text}

# ============ 4. CHECK YOUR MERCHANT BALANCE ============
def get_balance():
    """How much is in your Merchant Wallet right now?"""
    token = get_token(is_disbursement=False)
    url = f"{BASE_URL}/collection/v1_0/account/balance"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Target-Environment": ENVIRONMENT,
        "Ocp-Apim-Subscription-Key": COLLECTION_SUB_KEY,
    }
    r = requests.get(url, headers=headers)
    return r.json() if r.status_code == 200 else {"error": r.text}

# ============ TEST ============
if __name__ == "__main__":
    print("Balance:", get_balance())
