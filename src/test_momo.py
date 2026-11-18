from momo import request_payment, check_payment_status, get_balance

print("Balance:", get_balance())

# In sandbox, MTN uses this test number
result = request_payment("46733123454", 1, 999)
print("Payment request:", result)

if result.get("success"):
    ref = result["reference_id"]
    print("Reference:", ref)
    print("Now check status:", check_payment_status(ref))
