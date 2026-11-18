import uuid, requests

COLLECTION_KEY = "paste-your-collection-primary-key-here"
API_USER_ID = str(uuid.uuid4())  # this will be your MTN_API_USER

print("Your API_USER_ID is:", API_USER_ID)

# 1. Create user
r = requests.post(
    "https://sandbox.momodeveloper.mtn.com/v1_0/apiuser",
    headers={
        "X-Reference-Id": API_USER_ID,
        "Ocp-Apim-Subscription-Key": COLLECTION_KEY,
        "Content-Type": "application/json"
    },
    json={"providerCallbackHost": "getservicegh.com"}
)
print("Create user:", r.status_code, r.text)

# 2. Create API Key
r2 = requests.post(
    f"https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/{API_USER_ID}/apikey",
    headers={"Ocp-Apim-Subscription-Key": COLLECTION_KEY}
)
print("API Key result:", r2.text)
print("Save this as MTN_API_KEY")
