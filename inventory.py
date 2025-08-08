# ---------- inventory.py ----------
from fastapi import APIRouter, UploadFile, File
from supabase_client import supabase

router = APIRouter()

# Add ingredient - matches SQL schema exactly
@router.post("/add_ingredient/")
async def add_ingredient(user_id: str, name: str, quantity: int):
    response = supabase.table('Ingredients Inventory').insert({
        "user_id": user_id,
        "Name": name,
        "Quantity": quantity
    }).execute()

    if response.data:
        return {"message": "Ingredient added successfully", "data": response.data}
    else:
        return {"message": "Failed to add ingredient"}

# Get all ingredients by user_id
@router.get("/get_ingredients/{user_id}")
async def get_ingredients(user_id: str):
    print("HERE")
    response = supabase.table('Ingredients Inventory').select("*").eq('user_id', user_id).execute()

    if response.data:
        print(response.data)
        return {"ingredients": response.data}
    else:
        return {"message": "No ingredients found"}

# Get user profile
@router.get("/get_profile/{user_id}")
async def get_profile(user_id: str):
    response = supabase.table('CustomUsers').select("*").eq('user_id', user_id).execute()

    if response.data:
        return {"profile": response.data[0]}
    else:
        return {"message": "Profile not found."}

# Detect ingredient (mocked)
@router.post("/detect_ingredient/")
async def detect_ingredient(image: UploadFile = File(...)):
    file_location = f"temp_{image.filename}"
    with open(file_location, "wb+") as file_object:
        file_object.write(await image.read())

    # Mocked detection
    detected_ingredient = "Tomato"

    return {"detected_ingredient": detected_ingredient}
