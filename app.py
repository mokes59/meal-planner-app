import os
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client
from datetime import date, timedelta

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

st.set_page_config(page_title="Meal Planner", page_icon="🍽️", layout="wide")
st.title("🍽️ Meal Planner")

page = st.sidebar.radio("Menu", ["Meal Planner", "Shopping List", "Pantry", "Recipes"])

@st.cache_data(ttl=60)
def get_recipes():
    return supabase.table("recipes").select("id, name, category, base_servings, instructions").order("category").execute().data

@st.cache_data(ttl=60)
def get_pantry():
    return supabase.table("pantry").select("id, qty_on_hand, ingredient_id, ingredients(name, unit)").execute().data

def get_shopping_list(week_start):
    return supabase.table("shopping_list").select("id, qty_needed, purchased, ingredient_id, ingredients(name)").eq("week_start_date", str(week_start)).execute().data

@st.cache_data(ttl=60)
def get_all_recipe_items():
    """Load all recipe ingredients in one query to avoid per-recipe calls."""
    return supabase.table("recipe_items").select("recipe_id, qty_required, ingredient_id, ingredients(name, unit)").execute().data

def check_recipe_availability(recipe_id, recipe_items_all, pantry_map):
    """
    Returns (can_make: bool, missing: list of str).
    missing contains human-readable strings for each ingredient that is short.
    """
    items = [i for i in recipe_items_all if i["recipe_id"] == recipe_id]
    missing = []
    for item in items:
        ing_id = item["ingredient_id"]
        ing_name = item["ingredients"]["name"]
        unit = item["ingredients"].get("unit", "")
        needed = item["qty_required"]
        on_hand = pantry_map.get(ing_id, 0)
        if on_hand < needed:
            short = needed - on_hand
            missing.append(f"{ing_name} (need {short} more {unit})")
    return len(missing) == 0, missing

def decrement_pantry(recipe_id, recipe_items_all, pantry_map):
    """Subtract recipe ingredient quantities from pantry, flooring at 0."""
    items = [i for i in recipe_items_all if i["recipe_id"] == recipe_id]
    for item in items:
        ing_id = item["ingredient_id"]
        current = pantry_map.get(ing_id, 0)
        new_qty = max(0, current - item["qty_required"])
        supabase.table("pantry").update({"qty_on_hand": new_qty}).eq("ingredient_id", ing_id).execute()

if page == "Meal Planner":
    st.header("Plan Your Week")
    recipes = get_recipes()
    recipe_items_all = get_all_recipe_items()
    pantry_data = supabase.table("pantry").select("ingredient_id, qty_on_hand").execute().data
    pantry_map = {p["ingredient_id"]: p["qty_on_hand"] for p in pantry_data}

    categories = sorted(set(r["category"] for r in recipes))
    st.subheader("Select recipes to cook")
    st.caption("Only recipes with all ingredients on hand can be selected. Grayed-out recipes show what's missing.")

    selected_ids = []
    for cat in categories:
        st.markdown(f"**{cat}**")
        cat_recipes = [r for r in recipes if r["category"] == cat]
        cols = st.columns(3)
        for i, r in enumerate(cat_recipes):
            can_make, missing = check_recipe_availability(r["id"], recipe_items_all, pantry_map)
            with cols[i % 3]:
                if can_make:
                    # Selectable recipe
                    if st.checkbox(r["name"], key=f"sel_{r['id']}"):
                        selected_ids.append(r["id"])
                else:
                    # Grayed-out recipe with missing ingredients shown
                    st.markdown(
                        f"<span style='color: #999; font-size: 0.95em;'>⬜ <b>{r['name']}</b></span>",
                        unsafe_allow_html=True
                    )
                    with st.expander("Missing ingredients", expanded=False):
                        for m in missing:
                            st.caption(f"• {m}")

    if selected_ids:
        st.divider()
        st.subheader(f"{len(selected_ids)} recipes selected")

        col_shop, col_cook = st.columns(2)

        with col_shop:
            if st.button("Generate Shopping List", type="primary"):
                week_start = date.today() - timedelta(days=date.today().weekday())
                needs = {}
                for recipe_id in selected_ids:
                    items = [i for i in recipe_items_all if i["recipe_id"] == recipe_id]
                    for item in items:
                        ing_id = item["ingredient_id"]
                        ing_name = item["ingredients"]["name"]
                        qty = item["qty_required"]
                        if ing_id not in needs:
                            needs[ing_id] = {"name": ing_name, "total_needed": 0, "on_hand": 0}
                        needs[ing_id]["total_needed"] += qty
                for ing_id in needs:
                    needs[ing_id]["on_hand"] = pantry_map.get(ing_id, 0)
                to_buy = []
                for ing_id, data in needs.items():
                    shortage = max(0, data["total_needed"] - data["on_hand"])
                    if shortage > 0:
                        to_buy.append({"ingredient_id": ing_id, "name": data["name"], "qty": shortage})
                        supabase.table("shopping_list").upsert({
                            "ingredient_id": ing_id,
                            "qty_needed": shortage,
                            "week_start_date": str(week_start),
                            "purchased": False,
                        }).execute()
                if to_buy:
                    st.success(f"Shopping list generated — {len(to_buy)} items to buy")
                    for item in to_buy:
                        st.write(f"• {item['name']}: {item['qty']}")
                else:
                    st.success("You have everything you need!")

        with col_cook:
            st.markdown("**Mark a recipe as cooked:**")
            selected_recipes = [r for r in recipes if r["id"] in selected_ids]
            recipe_to_cook = st.selectbox(
                "Choose recipe",
                options=[r["name"] for r in selected_recipes],
                key="cook_select"
            )
            if st.button("✅ Mark as Cooked", type="secondary"):
                recipe_id = next(r["id"] for r in selected_recipes if r["name"] == recipe_to_cook)
                decrement_pantry(recipe_id, recipe_items_all, pantry_map)
                st.cache_data.clear()
                st.success(f"'{recipe_to_cook}' marked as cooked — pantry updated!")
                st.rerun()

        st.divider()
        st.subheader("Recipes Selected")
        for r in selected_recipes:
            st.write(f"• {r['name']} ({r['category']})")

elif page == "Shopping List":
    st.header("Shopping List")
    week_start = date.today() - timedelta(days=date.today().weekday())
    st.caption(f"Week of {week_start.strftime('%B %d, %Y')}")
    items = get_shopping_list(week_start)
    if not items:
        st.info("No shopping list yet. Go to Meal Planner and select recipes.")
    else:
        st.write(f"{len([i for i in items if not i['purchased']])} items remaining")
        for item in items:
            col1, col2 = st.columns([4, 1])
            with col1:
                label = f"~~{item['ingredients']['name']}~~" if item["purchased"] else item["ingredients"]["name"]
                st.write(label)
            with col2:
                if not item["purchased"]:
                    if st.button("Got it", key=f"buy_{item['id']}"):
                        supabase.table("shopping_list").update({"purchased": True}).eq("id", item["id"]).execute()
                        st.rerun()

elif page == "Pantry":
    st.header("Pantry")
    pantry = get_pantry()
    if not pantry:
        st.info("Your pantry is empty.")
    else:
        st.write(f"{len(pantry)} ingredients on hand")
        for item in pantry:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(item["ingredients"]["name"])
            with col2:
                st.write(f"{item['qty_on_hand']} {item['ingredients']['unit']}")
    st.divider()
    st.subheader("Add to Pantry")
    ingredients = supabase.table("ingredients").select("id, name, unit").order("name").execute().data
    ing_names = [i["name"] for i in ingredients]
    selected_ing = st.selectbox("Ingredient", ing_names)
    qty = st.number_input("Quantity", min_value=0.0, step=0.5)
    exp_date = st.date_input("Expiration Date (optional)", value=None)
    if st.button("Add to Pantry"):
        ing_id = next(i["id"] for i in ingredients if i["name"] == selected_ing)
        supabase.table("pantry").upsert({
            "ingredient_id": ing_id,
            "qty_on_hand": qty,
            "expiration_date": str(exp_date) if exp_date else None,
        }).execute()
        st.success(f"Added {selected_ing} to pantry")
        st.cache_data.clear()
        st.rerun()

elif page == "Recipes":
    st.header("Recipe Browser")
    recipes = get_recipes()
    search = st.text_input("Search recipes", placeholder="e.g. chicken, soup, breakfast...")
    category_filter = st.selectbox("Category", ["All"] + sorted(set(r["category"] for r in recipes)))
    filtered = recipes
    if search:
        filtered = [r for r in filtered if search.lower() in r["name"].lower()]
    if category_filter != "All":
        filtered = [r for r in filtered if r["category"] == category_filter]
    st.write(f"{len(filtered)} recipes found")
    for r in filtered:
        with st.expander(f"{r['name']} ({r['category']}) — {r['base_servings']} servings"):
            if r.get("instructions"):
                st.write(r["instructions"])
            else:
                st.caption("No instructions stored")
            items = supabase.table("recipe_items")\
                .select("qty_required, ingredients(name, unit)")\
                .eq("recipe_id", r["id"]).execute().data
            if items:
                st.markdown("**Ingredients:**")
                for item in items:
                    st.write(f"• {item['ingredients']['name']}")
