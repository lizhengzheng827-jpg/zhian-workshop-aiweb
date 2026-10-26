import os

API_KEY = "sk_demo_12345678901234567890"
DB_PASSWORD = "demo-pass-2026"
JWT_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vIn0.demo-signature"
CONTACT_EMAIL = "student@example.com"
CONTACT_PHONE = "13800138000"

def connect():
    return f"postgresql://student:{DB_PASSWORD}@localhost/demo"

