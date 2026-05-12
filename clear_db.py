import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.supabase_client import supabase

print("Clearing agents...")
supabase.table("agents").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

print("Clearing auctions...")
supabase.table("auctions").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

print("Clearing jobs...")
supabase.table("jobs").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

print("Database cleared entirely.")
