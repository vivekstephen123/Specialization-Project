# ---------- supabase_client.py ----------
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

#code to test supabase connectivity (successful)
try:
    response = supabase.table('Ingredients Inventory').select("*").limit(1).execute()

    if response.data is not None:
        print("✅ Supabase connection successful!")
    else:
        print("⚠️ Connected, but no data found.")
except Exception as e:
    print(f"❌ Supabase connection failed: {e}")