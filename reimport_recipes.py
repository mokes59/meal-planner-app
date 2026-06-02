"""
reimport_recipes.py
Clears existing recipe/ingredient data and re-imports from the PDF
with clean individual ingredients and macro data.
"""
import os, re, fitz
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

PDF_PATH = os.path.join(os.path.dirname(__file__), "good food mood__240904_202002.pdf")

# ── helpers ──────────────────────────────────────────────────────────────────

UNITS = r'(?:TBS|tbsp|tsp|cups?|oz|lbs?|g|pkg|cans?|slices?|pieces?|cloves?|scoops?|patties|patty|eggs?|handful|pinch|dash|ounces?|pounds?|tablespoons?|teaspoons?)'

def join_wrapped_lines(lines):
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        while (i + 1 < len(lines) and
               len(lines[i+1]) > 0 and
               (lines[i+1][0].islower() or lines[i+1].startswith('(')) and
               not re.match(r'^\d+\.', lines[i+1]) and
               len(line) < 60):
            i += 1
            line = line.rstrip() + ' ' + lines[i].lstrip()
        result.append(line)
        i += 1
    return result

def parse_ingredient_line(ing):
    m = re.match(r'^([\d\s½¼¾⅓⅔/.]+)\s+(' + UNITS + r')\s+(.+)$', ing, re.IGNORECASE)
    if m:
        qty_str, unit = m.group(1).strip(), m.group(2).lower()
        name = m.group(3).strip()
        num_m = re.search(r'[\d.]+', qty_str)
        qty = float(num_m.group()) if num_m else 1.0
    else:
        m2 = re.match(r'^([\d½¼¾⅓⅔/.]+)\s+(.+)$', ing)
        if m2:
            num_m = re.search(r'[\d.]+', m2.group(1))
            qty = float(num_m.group()) if num_m else 1.0
            name = m2.group(2).strip()
            unit = 'unit'
        else:
            name, qty, unit = ing, 1.0, 'unit'

    name = re.sub(r'\s*\(I (?:use|like|get)[^)]*\)', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s*\(my favorite\)', '', name, flags=re.IGNORECASE).strip()
    name = name.rstrip(',').strip()
    return name, qty, unit

def parse_recipe_page(text):
    if 'MACROS (PER SERVING)' not in text:
        return None
    ll = text.split('\n')

    cal   = re.search(r'Calories:\s*([\d.]+)', text)
    fat   = re.search(r'Fat:\s*([\d.]+)', text)
    prot  = re.search(r'Protein:\s*([\d.]+)', text)
    carbs = re.search(r'Carbs:\s*([\d.]+)', text)
    if not all([cal, fat, prot, carbs]):
        return None

    servings_m = re.search(r'Yield[^:]*:\s*([^\n]+)', text, re.IGNORECASE)
    snum = re.search(r'(\d+)', servings_m.group(1)) if servings_m else None
    servings_num = int(snum.group(1)) if snum else 1

    approx_idx = next((i for i, l in enumerate(ll) if '(approximate)' in l.lower()), None)
    if approx_idx is None:
        return None

    content_raw = [l.strip() for l in ll[approx_idx+1:] if l.strip()]
    content = join_wrapped_lines(content_raw)

    ing_start_pat = re.compile(r'^[\d½¼¾⅓⅔]|^\(micro|^each bowl|^sauce:|^for the|^per bowl', re.IGNORECASE)
    dir_pat = re.compile(r'^\d+\.\s|^prepare|^place|^cook|^add |^mix |^combine|^heat|^bake|^air fry|^assemble|^in a |^these dir|^follow|^make|^bring|^brown|^season|^drain|^dice|^slice|^spray|^layer|^top |^serve', re.IGNORECASE)
    skip_pat = re.compile(r'^optional|^toppings?:|^\*recipe|^served with|^i like|^if meal|^can also|^feel free|^note:|^for drizzl|^each bowl:$|^sauce:$', re.IGNORECASE)

    name_lines = []
    ing_start = 0
    for i, line in enumerate(content):
        if ing_start_pat.match(line) or dir_pat.match(line) or len(line) > 60:
            ing_start = i
            break
        name_lines.append(line)
        ing_start = i + 1

    name = ' '.join(name_lines).strip()
    name = re.sub(r'\*recipe.*', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+', ' ', name).strip()

    # Reject bad names (optional toppings etc picked up as recipe names)
    if re.match(r'^optional|^lime|^for garnish', name, re.IGNORECASE):
        return None

    if not name:
        for line in reversed(ll[:approx_idx]):
            line = line.strip()
            if line and len(line) > 3 and not re.match(
                r'^\d+$|\(approximate\)|MACROS|Calories|Fat:|Protein|Carbs|Yield|ingredients|directions',
                line, re.IGNORECASE):
                name = line
                break

    if not name:
        return None

    # Title-case cleanup
    name = name.strip()

    ingredients = []
    for line in content[ing_start:]:
        if dir_pat.match(line):
            break
        if skip_pat.match(line):
            continue
        if line and len(line) > 3 and len(line) < 120:
            # Skip lines that are clearly continuations from prev or disclaimer
            if re.match(r'^your needs|^amounts to fit|^modify amounts', line, re.IGNORECASE):
                continue
            ing_name, qty, unit = parse_ingredient_line(line)
            if ing_name and len(ing_name) > 1:
                ingredients.append({'name': ing_name, 'qty': qty, 'unit': unit})

    return {
        'name': name,
        'calories': float(cal.group(1)),
        'fat': float(fat.group(1)),
        'protein': float(prot.group(1)),
        'carbs': float(carbs.group(1)),
        'servings': servings_num,
        'ingredients': ingredients,
    }

# ── determine category from page position ────────────────────────────────────
def get_category(page_num):
    # Based on table of contents page ranges
    if page_num <= 32:
        return 'Breakfast'
    elif page_num <= 50:
        return 'Meal Prep'
    elif page_num <= 75:
        return 'Bowls'
    elif page_num <= 90:
        return 'Quickies'
    elif page_num <= 110:
        return 'Meal Time'
    elif page_num <= 135:
        return 'Crockpot'
    elif page_num <= 150:
        return 'Sides + Snacks'
    else:
        return 'Sweets + Treats'

# ── parse PDF ─────────────────────────────────────────────────────────────────
print("Parsing PDF...")
doc = fitz.open(PDF_PATH)
recipes = []
for i in range(len(doc)):
    text = doc[i].get_text()
    result = parse_recipe_page(text)
    if result and result['name']:
        result['category'] = get_category(i + 1)
        recipes.append(result)

print(f"Parsed {len(recipes)} recipes from PDF")

# ── wipe existing data ────────────────────────────────────────────────────────
print("\nClearing existing data...")
supabase.table("recipe_items").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
supabase.table("shopping_list").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
supabase.table("meal_plan").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
supabase.table("recipes").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
supabase.table("ingredients").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
print("Cleared.")

# ── import recipes + ingredients ──────────────────────────────────────────────
print("\nImporting recipes...")
imported = 0
skipped = 0

for r in recipes:
    # Insert recipe
    recipe_row = supabase.table("recipes").insert({
        "name": r['name'],
        "category": r['category'],
        "base_servings": r['servings'],
        "calories": r['calories'],
        "protein": r['protein'],
        "fat": r['fat'],
        "carbs": r['carbs'],
    }).execute()

    if not recipe_row.data:
        print(f"  SKIP (insert failed): {r['name']}")
        skipped += 1
        continue

    recipe_id = recipe_row.data[0]['id']

    # Insert each ingredient + recipe_item link
    for ing in r['ingredients']:
        ing_name = ing['name'][:200]  # cap length

        # Upsert ingredient (by name)
        existing = supabase.table("ingredients").select("id").eq("name", ing_name).execute()
        if existing.data:
            ing_id = existing.data[0]['id']
        else:
            new_ing = supabase.table("ingredients").insert({
                "name": ing_name,
                "unit": ing['unit'],
            }).execute()
            if not new_ing.data:
                continue
            ing_id = new_ing.data[0]['id']

        # Insert recipe_item
        supabase.table("recipe_items").insert({
            "recipe_id": recipe_id,
            "ingredient_id": ing_id,
            "qty_required": ing['qty'],
        }).execute()

    print(f"  ✓ {r['name']} ({r['category']}) — {len(r['ingredients'])} ingredients")
    imported += 1

print(f"\nDone. {imported} recipes imported, {skipped} skipped.")
