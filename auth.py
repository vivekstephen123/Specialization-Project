import uuid
import bcrypt
from supabase_client import supabase

# SIGNUP USER
import uuid
from supabase_client import supabase  # Already initialized

async def signup_user(username: str,email: str ,password: str, preferences: str = None, diet_plan: str = None):
    # Check if username already exists
    existing_user = supabase.table('CustomUsers').select("*").eq('username', username).execute()
    if existing_user.data:
        return {"error": "Username already taken."}

    # Insert new user with random UUID
    new_user_id = str(uuid.uuid4())
    response = supabase.table('CustomUsers').insert({
        "user_id": new_user_id,
        "username": username,
        "email": email,
        "password": password,
        "preferences": preferences,
        "diet_plan": diet_plan
    }).execute()

    if response.data:
        return {
            "message": "Signup successful.",
            "user_id": new_user_id
        }
    else:
        return {"error": "Failed to create user."}


async def login_user(email: str, password: str):
    print("here")
    user = supabase.table('CustomUsers') \
        .select("*") \
        .eq("email", email) \
        .eq("password", password) \
        .limit(1) \
        .execute()

    if user.data:
        return {
            "message": "Login successful.",
            "user": user.data[0],
            "access_token": str(uuid.uuid4())
        }
    else:
        return None

