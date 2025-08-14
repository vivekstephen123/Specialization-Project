from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional, Dict
from pydantic import BaseModel
import re
import json
import os
import tempfile
import logging
import pathlib
import torch
import numpy as np
from PIL import Image
import io
import google.generativeai as genai
from dotenv import load_dotenv
from enum import Enum

from auth import signup_user, login_user
from inventory import router as inventory_router
from supabase_client import supabase
from bill_extract import BillItemExtractor

# ---------------- YOLO MODEL LOAD ----------------
pathlib.PosixPath = pathlib.WindowsPath
yolo_model = torch.hub.load('./yolov5', 'custom', path='new_weights/best.pt', source='local')
print("✅ YOLO model loaded")

# ---------------- FASTAPI APP ----------------
load_dotenv()
app = FastAPI()
app.include_router(inventory_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

class MealType(str, Enum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"

class RecipeRequest(BaseModel):
    user_id: str
    meal_type: MealType

class InventoryUpdateItem(BaseModel):
    quantity: float
    units: str

class UpdateInventoryRequest(BaseModel):
    user_id: str
    updated_inventory: Dict[str, InventoryUpdateItem]  # {"ingredient_name": {"quantity": new_quantity, "units": "g"}}

# Recipe generator functions
def clean_json_response(text):
    clean_text = re.sub(r'```(?:json)?', '', text).strip()
    clean_text = re.sub(r'```$', '', clean_text).strip()
    return clean_text

def fetch_ingredients_for_user(user_id):
    response = supabase.table('Ingredients Inventory').select("*").eq('user_id', user_id).execute()
    ingredients_list = []
    for item in response.data:
        # Format: "Quantity Units of Name"
        ingredient = f"{item['Quantity']} {item['Units']} of {item['Name']}"
        ingredients_list.append(ingredient)
    return ", ".join(ingredients_list)

def fetch_user_profile(user_id):
    response = supabase.table('CustomUsers').select("*").eq('user_id', user_id).execute()
    if response.data:
        return response.data[0]
    return {}

def generate_recipe(user_id, meal_type="lunch"):
    print(f"Generating {meal_type} recipe for user {user_id}")
    ingredients_string = fetch_ingredients_for_user(user_id)
    print("ING - Ingredients string", ingredients_string)
    user_profile = fetch_user_profile(user_id)
    print(user_profile)
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
- Macronutrients breakdown
- Suggested inventory updates after cooking

Respond in valid JSON format like:
{{
  "recipe_name": "string",
  "ingredients": ["ingredient and Quantity", "..."],
  "instructions": "string",
  "prep_time": "string",
  "macros": {{
    "carbs": "number (only the number in grams)",
    "fat": "number (only the number in grams)",
    "protein": "number (only the number in grams)"
  }},
  "meal_type": "{meal_type}",
  "suggested_inventory_update": {{
    "ingredient_name": new_quantity_after_cooking,
    "ingredient_name_2": new_quantity_after_cooking
  }}
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

def update_ingredients_inventory(user_id: str, updated_inventory: Dict[str, InventoryUpdateItem]):
    """
    Updates the Ingredients Inventory table with new quantities and units.
    Only updates ingredients that exist in the user's current inventory.
    Will NOT delete ingredients when quantity is 0 — instead, keeps them with 0 quantity.
    Args:
        user_id: User ID
        updated_inventory: Dict with ingredient names as keys and InventoryUpdateItem as values
    """
    current_inventory_response = supabase.table('Ingredients Inventory').select("*").eq('user_id', user_id).execute()
    
    if not current_inventory_response.data:
        print(f"No current inventory found for user {user_id}")
        return {"updated": 0, "skipped": len(updated_inventory), "errors": []}
    
    current_ingredients = {}
    for item in current_inventory_response.data:
        current_ingredients[item['Name'].lower()] = item['Name']
    
    updated_count = 0
    skipped_count = 0
    errors = []
    
    for ingredient_name, update_info in updated_inventory.items():
        ingredient_name_lower = ingredient_name.strip().lower()
        if ingredient_name_lower not in current_ingredients:
            print(f"Ingredient '{ingredient_name}' not found in user's inventory. Skipping.")
            skipped_count += 1
            continue
        
        actual_ingredient_name = current_ingredients[ingredient_name_lower]
        
        try:
            new_qty = float(update_info.quantity)
            new_units = update_info.units
            response = supabase.table('Ingredients Inventory') \
                .update({'Quantity': new_qty, 'Units': new_units}) \
                .eq('user_id', user_id) \
                .eq('Name', actual_ingredient_name) \
                .execute()
            
            if response.data:
                print(f"Updated {actual_ingredient_name} for user {user_id} to quantity {new_qty} {new_units}")
                updated_count += 1
            else:
                error_msg = f"Failed to update {actual_ingredient_name}"
                print(error_msg)
                errors.append(error_msg)

        except ValueError as e:
            error_msg = f"Invalid quantity for {ingredient_name}: {update_info.quantity}. Error: {e}"
            print(error_msg)
            errors.append(error_msg)
        except Exception as e:
            error_msg = f"Error updating {ingredient_name}: {str(e)}"
            print(error_msg)
            errors.append(error_msg)
    
    return {
        "updated": updated_count,
        "skipped": skipped_count,
        "errors": errors
    }


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

# Updated recipe generation route (no automatic inventory update)
@app.post("/generate-recipe/")
async def generate_recipe_endpoint(request: RecipeRequest):
    try:
        recipe = generate_recipe(request.user_id, request.meal_type)
        print("RECIPE:", recipe)
        if "error" in recipe:
            raise HTTPException(status_code=400, detail=recipe["error"])
        
        return {
            "success": True,
            "recipe": recipe
        }
    except Exception as e:
        print("ERROR:", e)
        raise HTTPException(status_code=500, detail=f"Failed to generate recipe: {str(e)}")

# New separate inventory update endpoint
@app.post("/update-inventory/")
async def update_inventory_endpoint(request: UpdateInventoryRequest):
    try:
        if not request.updated_inventory:
            raise HTTPException(status_code=400, detail="No inventory updates provided")
        
        result = update_ingredients_inventory(request.user_id, request.updated_inventory)
        
        return {
            "success": True,
            "message": f"Inventory update completed. Updated: {result['updated']}, Skipped: {result['skipped']}",
            "details": result
        }
    except Exception as e:
        print("ERROR:", e)
        raise HTTPException(status_code=500, detail=f"Failed to update inventory: {str(e)}")

# Optional: GET route for recipe generation (if you prefer GET with query params)
@app.get("/generate-recipe/{user_id}")
async def generate_recipe_get(user_id: str, meal_type: MealType = MealType.lunch):
    try:
        recipe = generate_recipe(user_id, meal_type)
        if "error" in recipe:
            raise HTTPException(status_code=400, detail=recipe["error"])
        
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


@app.post("/detect-items/")
async def detect_items(file: UploadFile = File(...)):
    print("HERE")
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Upload an image.")

    image_bytes = await file.read()
    img = Image.open(io.BytesIO(image_bytes))
    results = yolo_model(img)
    detections = results.pandas().xyxy[0].to_dict(orient="records")

    item_counts = {}
    for det in detections:
        name = det["name"].title()  # Capitalize each word
        item_counts[name] = item_counts.get(name, 0) + 1

    return {"items": item_counts}