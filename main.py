from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from auth import signup_user, login_user
from inventory import router as inventory_router
import re
import json
import logging
import google.generativeai as genai
from supabase_client import supabase
from recipe_generator import update_ingredients_inventory

app = FastAPI()
app.include_router(inventory_router)

# Gemini API configuration
genai.configure(api_key="AIzaSyDGKB4D6OEaQNiqUFdGtljNobAFXPi4omw")
model = genai.GenerativeModel("gemini-1.5-flash")

class SignupRequest(BaseModel):
    username: str
    password: str
    preferences: str = None
    diet_plan: str = None

class LoginRequest(BaseModel):
    username: str
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

# Existing routes
@app.post("/signup/")
async def signup(request: SignupRequest):
    result = await signup_user(
        username=request.username,
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
    user = await login_user(username=request.username, password=request.password)
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
        if "error" in recipe:
            raise HTTPException(status_code=400, detail=recipe["error"])
        if "post meal inventory change" in recipe:
            inventory_changes = recipe["post meal inventory change"]
            if isinstance(inventory_changes, str):
                inventory_changes = json.loads(inventory_changes)
            update_ingredients_inventory(request.user_id, inventory_changes)
        return {
            "success": True,
            "recipe": recipe
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate recipe: {str(e)}")

# Optional: GET route for recipe generation (if you prefer GET with query params)
@app.get("/generate-recipe/{user_id}")
async def generate_recipe_get(user_id: str, meal_type: MealType = MealType.lunch):
    try:
        recipe = generate_recipe(user_id, meal_type)
        
        if "error" in recipe:
            raise HTTPException(status_code=400, detail=recipe["error"])
        
        # Update inventory if recipe contains ingredients
        if "ingredients" in recipe:
            update_ingredients_inventory(user_id, recipe["ingredients"])
        
        # Update inventory based on post meal inventory change
        if "post meal inventory change" in recipe:
            inventory_changes = recipe["post meal inventory change"]
            if isinstance(inventory_changes, str):
                import json
                inventory_changes = json.loads(inventory_changes)
            update_ingredients_inventory(user_id, inventory_changes)
        
        return {
            "success": True,
            "recipe": recipe
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate recipe: {str(e)}")