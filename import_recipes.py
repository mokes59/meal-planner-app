"""
Import recipes from recipes_final.json into Supabase.

Usage:
    py -3.11 import_recipes.py

Make sure:
1. recipes_final.json is in the same folder as this script
2. .env file has your SUPABASE_URL and SUPABASE_KEY
"""

import os
import json
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def import_recipes(json_path="recipes_final.json"):
    with open(json_path, encoding="utf-8") as f:
        recipes = json.load(f)

    imported = 0
    skipped = 0

    for r in recipes:
        try:
            # Insert recipe
            result = supabase.table("recipes").insert({
                "name": r["name"],
                "category": r["category"],
                "base_servings": r["base_servings"],
                "instructions": r.get("instructions", ""),
            }).execute()

            recipe_id = result.data[0]["id"]

            # Insert each ingredient and link to recipe
            for ing_text in r.get("ingredients", []):
                ing_text = ing_text.strip()
                if not ing_text or len(ing_text) < 2:
                    continue

                # Check if ingredient already exists (case insensitive)
                existing = supabase.table("ingredients")\
                    .select("id")\
                    .ilike("name", ing_text[:255])\
                    .execute()

                if existing.data:
                    ing_id = existing.data[0]["id"]
                else:
                    new_ing = supabase.table("ingredients").insert({
                        "name": ing_text[:255],
                        "calories": 0,
                        "protein": 0,
                        "carbs": 0,
                        "fat": 0,
                        "fiber": 0,
                        "unit": "oz",
                        "source": "cookbook",
                    }).execute()
                    ing_id = new_ing.data[0]["id"]

                # Link ingredient to recipe (qty=1 placeholder, units stored as-is in name)
                supabase.table("recipe_items").insert({
                    "recipe_id": recipe_id,
                    "ingredient_id": ing_id,
                    "qty_required": 1,
                }).execute()

            print(f"  OK  {r['name']} ({r['category']}) - {len(r.get('ingredients',[]))} ingredients | Cal:{r['calories_per_serving']} Pro:{r['protein_per_serving']}")
            imported += 1

        except Exception as e:
            print(f"  ERR {r['name']}: {e}")
            skipped += 1

    print(f"\n{'='*50}")
    print(f"DONE: {imported} imported, {skipped} skipped")

if __name__ == "__main__":
    print(f"=== Importing recipes to Supabase ===\n")
    import_recipes()
