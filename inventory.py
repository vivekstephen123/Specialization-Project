# -------------------------
# CODE 1 (UNCHANGED)
# -------------------------
from fastapi import APIRouter, UploadFile, File
from supabase_client import supabase

router = APIRouter()

# Add ingredient - matches SQL schema exactly
from pydantic import BaseModel

class Ingredient(BaseModel):
    user_id: str
    name: str
    quantity: int

@router.post("/add_ingredient/")
async def add_ingredient(ingredient: Ingredient):
    response = supabase.table('Ingredients Inventory').insert({
        "user_id": ingredient.user_id,
        "Name": ingredient.name,
        "Quantity": ingredient.quantity
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
    file_location = f"temp{image.filename}"
    with open(file_location, "wb+") as file_object:
        file_object.write(await image.read())
    # Mocked detection
    detected_ingredient = "Tomato"
    return {"detected_ingredient": detected_ingredient}


# -------------------------
# CODE 2 (MODIFIED TO MATCH SCHEMA)
# -------------------------
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional

class IngredientUpdate(BaseModel):
    name: Optional[str] = None
    quantity: Optional[int] = None

@router.put("/update_ingredient/{ingredient_id}")
async def update_ingredient(ingredient_id: int, ingredient: IngredientUpdate):
    """Update an existing ingredient"""
    try:
        update_data = {}
        if ingredient.name is not None:
            update_data['Name'] = ingredient.name
        if ingredient.quantity is not None:
            update_data['Quantity'] = ingredient.quantity
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        response = supabase.table('Ingredients Inventory').update(update_data).eq('id', ingredient_id).execute()
        if response.data:
            return {"success": True, "message": "Ingredient updated successfully", "ingredient": response.data[0]}
        else:
            raise HTTPException(status_code=404, detail="Ingredient not found")
    except Exception as e:
        print(f"Error updating ingredient: {e}")
        raise HTTPException(status_code=500, detail="Failed to update ingredient")

@router.delete("/delete_ingredient/{ingredient_id}")
async def delete_ingredient(ingredient_id: int):
    """Delete an ingredient"""
    try:
        response = supabase.table('Ingredients Inventory').delete().eq('id', ingredient_id).execute()
        if response.data:
            return {"success": True, "message": "Ingredient deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Ingredient not found")
    except Exception as e:
        print(f"Error deleting ingredient: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete ingredient")

@router.get("/get_ingredient/{ingredient_id}")
async def get_ingredient(ingredient_id: int):
    """Get a specific ingredient"""
    try:
        response = supabase.table('Ingredients Inventory').select("*").eq('id', ingredient_id).execute()
        if response.data:
            return {"success": True, "ingredient": response.data[0]}
        else:
            raise HTTPException(status_code=404, detail="Ingredient not found")
    except Exception as e:
        print(f"Error fetching ingredient: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch ingredient")

@router.put("/update_ingredient_quantity/{ingredient_id}")
async def update_ingredient_quantity(ingredient_id: int, quantity_change: int):
    """Increase or decrease ingredient quantity"""
    try:
        current = supabase.table('Ingredients Inventory').select("*").eq('id', ingredient_id).execute()
        if not current.data:
            raise HTTPException(status_code=404, detail="Ingredient not found")
        
        new_quantity = current.data[0]['Quantity'] + quantity_change
        if new_quantity < 0:
            new_quantity = 0
        
        update = supabase.table('Ingredients Inventory').update({'Quantity': new_quantity}).eq('id', ingredient_id).execute()
        if update.data:
            return {
                "success": True,
                "message": f"Quantity updated to {new_quantity}",
                "ingredient": update.data[0]
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to update quantity")
    except Exception as e:
        print(f"Error updating quantity: {e}")
        raise HTTPException(status_code=500, detail="Failed to update quantity")

@router.get("/search_ingredients/{user_id}")
async def search_ingredients(user_id: str, query: str):
    """Search ingredients by name"""
    try:
        response = supabase.table('Ingredients Inventory').select("*").eq('user_id', user_id).ilike('Name', f'%{query}%').execute()
        return {"success": True, "ingredients": response.data or [], "count": len(response.data) if response.data else 0}
    except Exception as e:
        print(f"Error searching: {e}")
        raise HTTPException(status_code=500, detail="Failed to search ingredients")

@router.post("/bulk_update_ingredients/{user_id}")
async def bulk_update_ingredients(user_id: str, ingredients: list[dict]):
    """Bulk update ingredients"""
    try:
        updated = []
        for data in ingredients:
            if not data.get('id'):
                continue
            update_data = {}
            if 'name' in data:
                update_data['Name'] = data['name']
            if 'quantity' in data:
                update_data['Quantity'] = data['quantity']
            if update_data:
                resp = supabase.table('Ingredients Inventory').update(update_data).eq('id', data['id']).eq('user_id', user_id).execute()
                if resp.data:
                    updated.extend(resp.data)
        return {"success": True, "message": f"Updated {len(updated)} ingredients", "ingredients": updated}
    except Exception as e:
        print(f"Error bulk updating: {e}")
        raise HTTPException(status_code=500, detail="Failed to bulk update")
