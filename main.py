from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from auth import signup_user, login_user
from inventory import router as inventory_router
import re
import json
import logging
import google.generativeai as genai
from supabase_client import supabase
import os
from bill_extract import BillItemExtractor
from dotenv import load_dotenv
import tempfile


# Load environment variables from .env
load_dotenv()



app = FastAPI()
app.include_router(inventory_router)
API_KEY = os.getenv('GEMINI_API')
if not API_KEY:
    raise RuntimeError("❌ GEMINI_API_KEY not found in .env")
# Gemini API configuration
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

class SignupRequest(BaseModel):
    username: str
    password: str
    email: str
    preferences: str = None
    diet_plan: str = None

class LoginRequest(BaseModel):
    email: str
    password: str

from enum import Enum

class MealType(str, Enum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"

class RecipeRequest(BaseModel):
    user_id: str
    meal_type: MealType

# Recipe generator functions
def clean_json_response(text):
    clean_text = re.sub(r'```(?:json)?', '', text).strip()
    clean_text = re.sub(r'```$', '', clean_text).strip()
    return clean_text

def fetch_ingredients_for_user(user_id):
    response = supabase.table('Ingredients Inventory').select("*").eq('user_id', user_id).execute()
    ingredients_list = []
    for item in response.data:
        ingredient = f"{item['Quantity']} of {item['Name']}"
        ingredients_list.append(ingredient)
    return ", ".join(ingredients_list)

def fetch_user_profile(user_id):
    response = supabase.table('UserProfiles').select("*").eq('user_id', user_id).execute()
    if response.data:
        return response.data[0]
    return {}

def generate_recipe(user_id, meal_type="lunch"):
    print(f"Generating {meal_type} recipe for user {user_id}")
    ingredients_string = fetch_ingredients_for_user(user_id)
    print("ING - Ingredients string", ingredients_string)
    user_profile = fetch_user_profile(user_id)
    preferences = user_profile.get("preferences", "")
    diet_plan = user_profile.get("diet_plan", "")
    
    if not ingredients_string:
        return {"error": "No ingredients available in inventory."}
    
    # Meal-specific guidance
    meal_guidance = {
        "breakfast": "Focus on energizing and nutritious ingredients suitable for starting the day. Consider lighter, easily digestible options.",
        "lunch": "Create a balanced meal that provides sustained energy for the afternoon. Include a good mix of proteins and vegetables.",
        "dinner": "Design a satisfying meal that's not too heavy before bedtime. Consider comfort food elements while maintaining nutritional balance."
    }
    
    prompt = f"""
You are a smart cooking assistant.
Here are the available ingredients:
{ingredients_string}
User preferences: {preferences}
User diet plan: {diet_plan}
Meal type: {meal_type}
Meal guidance: {meal_guidance.get(meal_type, "")}

Please suggest a healthy {meal_type} recipe using these ingredients, following the user's preferences and diet plan.
Make sure the recipe is appropriate for {meal_type} time.
Include:
- Recipe name
- Ingredients list with quantities
- Step-by-step instructions
- Preparation time
Respond in valid JSON format like:
{{
  "recipe_name": "string",
  "ingredients": ["ingredient and Quantity", "..."],
  "instructions": "string",
  "prep_time": "string",
  "meal_type": "{meal_type}",
  "post meal inventory change": "in this column specify how  much the inventory will change after cooking this meal, make sure it is a valid json with the fields - ingredient and quantity (here the quanity will specify what it will be after the cooking, when you're subracting the values from the inventory do not use grams or other measurements use whole items for example even if a recipe says it will take only 10gms of carot you will subtract an entire carot from the inventory)",
}}
"""
    
    response = model.generate_content(prompt)
    try:
        clean_text = clean_json_response(response.text)
        recipe_json = json.loads(clean_text)
        print(recipe_json)
        return recipe_json
    except json.JSONDecodeError:
        return {"error": "Invalid JSON returned by Gemini", "raw_response": response.text}

def parse_inventory_changes(inventory_changes):
    # If it's a string, try to parse as JSON (possibly double-encoded)
    if isinstance(inventory_changes, str):
        try:
            inventory_changes = json.loads(inventory_changes)
            if isinstance(inventory_changes, str):
                inventory_changes = json.loads(inventory_changes)
        except Exception as e:
            print("JSON decode error:", e)
            raise HTTPException(status_code=500, detail=f"Could not parse inventory changes: {str(e)}")
    # If it's a dict, wrap in a list
    if isinstance(inventory_changes, dict):
        inventory_changes = [inventory_changes]
    # Must be a list now
    if not isinstance(inventory_changes, list):
        print("inventory_changes is not a list:", inventory_changes)
        raise HTTPException(status_code=500, detail="Inventory changes is not a list!")
    return inventory_changes

# Existing routes
@app.post("/signup/")
async def signup(request: SignupRequest):
    result = await signup_user(
        username=request.username,
        email=request.email,
        password=request.password,
        preferences=request.preferences,
        diet_plan=request.diet_plan
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return {
        "message": result["message"],
        "user_id": result["user_id"]
    }

@app.post("/login/")
async def login(request: LoginRequest):
    user = await login_user(email=request.email, password=request.password)
    if user:
        return {
            "access_token": user["access_token"],
            "user_id": user["user"]["user_id"]
        }
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

# New recipe generation route
@app.post("/generate-recipe/")
async def generate_recipe_endpoint(request: RecipeRequest):
    try:
        recipe = generate_recipe(request.user_id, request.meal_type)
        print("RECIPE:", recipe)
        if "error" in recipe:
            raise HTTPException(status_code=400, detail=recipe["error"])
        if "post_meal_inventory_change" in recipe:
            inventory_changes_raw = recipe["post_meal_inventory_change"]
            print("RAW INVENTORY CHANGES:", inventory_changes_raw)
            # If it's a dict with 'ingredients', extract the list
            if isinstance(inventory_changes_raw, dict) and "ingredients" in inventory_changes_raw:
                inventory_changes = inventory_changes_raw["ingredients"]
            else:
                inventory_changes = parse_inventory_changes(inventory_changes_raw)
            print("PARSED INVENTORY CHANGES:", inventory_changes)
            update_ingredients_inventory(request.user_id, inventory_changes)
        return {
            "success": True,
            "recipe": recipe
        }
    except Exception as e:
        print("ERROR:", e)
        raise HTTPException(status_code=500, detail=f"Failed to generate recipe: {str(e)}")

# Optional: GET route for recipe generation (if you prefer GET with query params)
@app.get("/generate-recipe/{user_id}")
async def generate_recipe_get(user_id: str, meal_type: MealType = MealType.lunch):
    try:
        recipe = generate_recipe(user_id, meal_type)
        if "error" in recipe:
            raise HTTPException(status_code=400, detail=recipe["error"])
        if "post_meal_inventory_change" in recipe:
            inventory_changes = parse_inventory_changes(recipe["post_meal_inventory_change"])
            print("PARSED INVENTORY CHANGES:", inventory_changes)
            update_ingredients_inventory(user_id, inventory_changes)
        return {
            "success": True,
            "recipe": recipe
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate recipe: {str(e)}")

@app.get("/fetch-user/{user_id}")
async def fetch_user(user_id: str):
    response = supabase.table('CustomUsers').select("*").eq('user_id', user_id).execute()

    if response.data:
        return {"user": response.data[0]}
    else:
        return {"message": "User not found."}
    
# Initialize extractor
bill_extractor = BillItemExtractor(API_KEY)

def extract_bill_items(image_path: str, user_id: Optional[str] = None):
    """
    Extract items from a bill image and return parsed result.
    """
    try:
        json_result = bill_extractor.extract_and_format(image_path)
        return json.loads(json_result)
    except Exception as e:
        return {
            "success": False,
            "error": f"Extraction error: {str(e)}",
            "items": [],
            "total_items": 0
        }

@app.post("/extract-bill-upload/")
async def extract_bill_upload_endpoint(
    file: UploadFile = File(...),
    user_id: Optional[str] = None
):
    try:
        # Validate file type
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid file type. Upload an image.")

        # Save the uploaded image to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            temp_file.write(await file.read())
            temp_file_path = temp_file.name

        try:
            # Extract bill items
            result = extract_bill_items(temp_file_path, user_id)

            if not result.get("success"):
                raise HTTPException(status_code=400, detail=result.get("error", "Extraction failed"))

            return result

        finally:
            # Delete temp file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process bill: {str(e)}")
