import re
import json
import logging
import google.generativeai as genai
from supabase_client import supabase
import os 

# Gemini API configuration
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key="")
model = genai.GenerativeModel("gemini-1.5-flash")

# Recipe generator function
def clean_json_response(text):
    clean_text = re.sub(r'```(?:json)?', '', text).strip()
    clean_text = re.sub(r'```$', '', clean_text).strip()
    return clean_text

def fetch_ingredients_for_user(user_id):
    response = supabase.table('Ingredients Inventory').select("*").eq('user_id', user_id).execute()

    ingredients_list = []
    for item in response.data:
        ingredient = f"{item['Quantity']}g of {item['Name']}"
        ingredients_list.append(ingredient)

    return ", ".join(ingredients_list)

def fetch_user_profile(user_id):
    response = supabase.table('UserProfiles').select("*").eq('user_id', user_id).execute()
    if response.data:
        return response.data[0]
    return {}

def generate_recipe(user_id):
    print("HERE")
    ingredients_string = fetch_ingredients_for_user(user_id)
    user_profile = fetch_user_profile(user_id)
    preferences = user_profile.get("preferences", "")
    diet_plan = user_profile.get("diet_plan", "")

    if not ingredients_string:
        return {"error": "No ingredients available in inventory."}

    prompt = f"""
You are a smart cooking assistant.

Here are the available ingredients:
{ingredients_string}

User preferences: {preferences}
User diet plan: {diet_plan}

Please suggest a healthy recipe using these ingredients, following the user's preferences and diet plan.
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
  "prep_time": "string"
}}
"""

    response = model.generate_content(prompt)

    try:
        clean_text = clean_json_response(response.text)
        recipe_json = json.loads(clean_text)
        print(recipe_json)
        # Update inventory after recipe is generated
        if "post meal inventory change" in recipe_json:
            inventory_changes = recipe_json["post meal inventory change"]
            if isinstance(inventory_changes, str):
                inventory_changes = json.loads(inventory_changes)
            update_ingredients_inventory(user_id, inventory_changes)
        return recipe_json
    except json.JSONDecodeError:
        return {"error": "Invalid JSON returned by Gemini", "raw_response": response.text}

def update_ingredients_inventory(user_id, inventory_changes):
    """
    Updates the Ingredients Inventory table to match the new quantities after cooking.
    Deletes the ingredient if quantity becomes 0.
    inventory_changes: list of dicts like {"ingredient": "Carrot", "quantity": 2}
    """
    if not isinstance(inventory_changes, list):
        print("inventory_changes is not a list:", inventory_changes)
        return
    for change in inventory_changes:
        print("CHANGE ITEM:", change)
        if not isinstance(change, dict) or "ingredient" not in change or "quantity" not in change:
            print("Skipping invalid change item:", change)
            continue
        name = change["ingredient"].strip().title()
        try:
            new_qty = int(change["quantity"])
        except Exception as e:
            print(f"Invalid quantity for {name}: {change['quantity']}. Error: {e}")
            continue
        print(f"Setting {name} for user {user_id} to quantity {new_qty}")  # Debug print
        if new_qty > 0:
            response = supabase.table('Ingredients Inventory') \
                .update({'Quantity': new_qty}) \
                .eq('user_id', user_id) \
                .eq('Name', name) \
                .execute()
            print("Update response:", response)
        else:
            response = supabase.table('Ingredients Inventory') \
                .delete() \
                .eq('user_id', user_id) \
                .eq('Name', name) \
                .execute()
            print(f"Deleted {name} for user {user_id}")
            print("Delete response:", response)
