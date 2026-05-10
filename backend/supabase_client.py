import os
from supabase import create_client, Client
from dotenv import load_dotenv

import httpx
from supabase.client import ClientOptions

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variables")

# Disable HTTP/2 to prevent connection drops (error_code:1) during rapid requests
http_client = httpx.Client(http2=False)

supabase: Client = create_client(
    SUPABASE_URL, 
    SUPABASE_KEY, 
    options=ClientOptions(httpx_client=http_client)
)
