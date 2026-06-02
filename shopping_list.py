import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def generate_shopping_list(recipe_names):
    """Given a list of recipe names, return what you need to buy."""
    
    needs = {}  # ingredient_id -> {name, total_needed, on_hand}

    for recipe_name in recipe_names:
        recipe = supabase.table("recipes")\
            .select("id, name, base_servings")\
            .eq("name", recipe_name).execute()
        
        if not recipe.data:
            print(f"Recipe not found: {recipe_name}")
            continue

        r = recipe.data[0]

        items = supabase.table("recipe_items")\
            .select("qty_required, ingredient_id, ingredients(name)")\
            .eq("recipe_id", r["id"]).execute()

        for item in items.data:
            ing_id = item["ingredient_id"]
            ing_name = item["ingredients"]["name"]
            qty = item["qty_required"]

            if ing_id not in needs:
                needs[ing_id] = {"name": ing_name, "total_needed": 0, "on_hand": 0}
            needs[ing_id]["total_needed"] += qty

    for ing_id in needs:
        pantry = supabase.table("pantry")\
            .select("qty_on_hand")\
            .eq("ingredient_id", ing_id).execute()
        
        if pantry.data:
            needs[ing_id]["on_hand"] = pantry.data[0]["qty_on_hand"]

    print("\n=== SHOPPING LIST ===")
    shopping = []
    for ing_id, data in needs.items():
        to_buy = max(0, data["total_needed"] - data["on_hand"])
        if to_buy > 0:
            print(f"{data['name']}: {to_buy}g")
            shopping.append({"ingredient_id": ing_id, "qty_needed": to_buy})
    
    if not shopping:
        print("You have everything you need!")
    
    return shopping

# Test it
generate_shopping_list(["Chicken & Rice Bowl", "Garlic Pasta with Spinach"])
