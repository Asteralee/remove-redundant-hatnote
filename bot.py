import requests
import mwparserfromhell
import os
import sys

API_URL = "https://test.wikipedia.org/w/api.php"

PROBLEM_CATEGORY = "Category:Articles with hatnote templates targeting a nonexistent page"
HATNOTE_CATEGORY = "Category:Hatnote templates"

# ==============================
# Environment Handling
# ==============================

def get_required_env(name):
    value = os.environ.get(name)
    if not value or not value.strip():
        print(f"[FATAL] Missing required environment variable: {name}")
        sys.exit(1)
    return value.strip()

def get_int_env(name, default):
    value = os.environ.get(name)
    if value and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            print(f"[WARNING] Invalid integer for {name}, using default {default}")
    return default

def get_bool_env(name, default=True):
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip().lower() in ["true", "1", "yes"]
    return default


BOT_USER = get_required_env("BOT_USER")
BOT_PASSWORD = get_required_env("BOT_PASSWORD")

MAX_ARTICLES = get_int_env("MAX_ARTICLES", 20)
DRY_RUN = get_bool_env("DRY_RUN", True)

# ==============================
# Session Setup (User-Agent FIX)
# ==============================

session = requests.Session()
session.headers.update({
    "User-Agent": f"{BOT_USER} (TestWiki hatnote cleanup bot; GitHub Actions)"
})

csrf_token = None


# ==============================
# API Helpers
# ==============================

def api_get(params):
    try:
        r = session.get(API_URL, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("[ERROR] API GET failed:", e)
        sys.exit(1)

def api_post(data):
    try:
        r = session.post(API_URL, data=data, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("[ERROR] API POST failed:", e)
        sys.exit(1)


# ==============================
# Login
# ==============================

def login():
    print("[~] Logging in...")

    token_data = api_get({
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    })

    login_token = token_data["query"]["tokens"]["logintoken"]

    login_result = api_post({
        "action": "login",
        "lgname": BOT_USER,
        "lgpassword": BOT_PASSWORD,
        "lgtoken": login_token,
        "format": "json"
    })

    if login_result.get("login", {}).get("result") != "Success":
        print("[FATAL] Login failed:", login_result)
        sys.exit(1)

    csrf_data = api_get({
        "action": "query",
        "meta": "tokens",
        "format": "json"
    })

    print("[+] Login successful.")
    return csrf_data["query"]["tokens"]["csrftoken"]


# ==============================
# Category Fetching (No Subcats)
# ==============================

def get_category_members(category, namespace):
    members = []
    cmcontinue = None

    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmlimit": "max",
            "cmnamespace": namespace,
            "format": "json"
        }

        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        data = api_get(params)

        members.extend([m["title"] for m in data["query"]["categorymembers"]])

        if "continue" in data:
            cmcontinue = data["continue"]["cmcontinue"]
        else:
            break

    return members


# ==============================
# Page Utilities
# ==============================

def get_page_text(title):
    data = api_get({
        "action": "query",
        "prop": "revisions",
        "titles": title,
        "rvprop": "content",
        "format": "json"
    })

    page = next(iter(data["query"]["pages"].values()))
    if "revisions" not in page:
        return None

    return page["revisions"][0]["*"]


def edit_page(title, text, summary):
    if DRY_RUN:
        print(f"[DRY RUN] Would edit: {title}")
        return

    result = api_post({
        "action": "edit",
        "title": title,
        "text": text,
        "token": csrf_token,
        "format": "json",
        "summary": summary,
        "bot": True
    })

    if result.get("edit", {}).get("result") == "Success":
        print(f"[+] Edited {title}")
    else:
        print("[ERROR] Edit failed:", result)


# ==============================
# Batch Existence Check (FAST)
# ==============================

def get_pages_existence(titles):
    existence = {}
    batch_size = 50  # MediaWiki limit

    for i in range(0, len(titles), batch_size):
        batch = titles[i:i+batch_size]

        data = api_get({
            "action": "query",
            "titles": "|".join(batch),
            "format": "json"
        })

        pages = data["query"]["pages"]

        for page in pages.values():
            title = page["title"]
            existence[title] = "missing" not in page

    return existence


# ==============================
# Processing Logic (Optimized)
# ==============================

def process_pages(problem_pages, hatnote_templates):
    edits_made = 0
    existence_cache = {}

    for page_title in problem_pages:
        print(f"\n[~] Checking {page_title}")

        text = get_page_text(page_title)
        if not text:
            continue

        wikicode = mwparserfromhell.parse(text)
        modified = False

        targets_to_check = set()

        # Collect all link targets first
        for template in wikicode.filter_templates():
            name = template.name.strip()

            if name in hatnote_templates:
                for param in template.params:
                    param_code = mwparserfromhell.parse(str(param.value))
                    for link in param_code.filter_wikilinks():
                        target = str(link.title).split("|")[0]
                        if target not in existence_cache:
                            targets_to_check.add(target)

        # Batch check new targets
        if targets_to_check:
            print(f"    [~] Checking {len(targets_to_check)} targets (batch)")
            results = get_pages_existence(list(targets_to_check))
            existence_cache.update(results)

        # Remove broken hatnotes
        for template in wikicode.filter_templates():
            name = template.name.strip()

            if name in hatnote_templates:
                remove_template = False

                for param in template.params:
                    param_code = mwparserfromhell.parse(str(param.value))
                    for link in param_code.filter_wikilinks():
                        target = str(link.title).split("|")[0]

                        if not existence_cache.get(target, False):
                            print(f"    [-] Removing '{name}' (red link: {target})")
                            remove_template = True
                            break
                    if remove_template:
                        break

                if remove_template:
                    wikicode.remove(template)
                    modified = True

        if modified:
            edit_page(
                page_title,
                str(wikicode),
                "Bot: Removed hatnote pointing to nonexistent page"
            )
            edits_made += 1

    return edits_made


# ==============================
# Main
# ==============================

def main():
    global csrf_token
    csrf_token = login()

    print("[~] Loading hatnote templates...")
    hatnote_templates = get_category_members(HATNOTE_CATEGORY, namespace=10)
    hatnote_templates = [t.replace("Template:", "") for t in hatnote_templates]
    print(f"[+] Loaded {len(hatnote_templates)} templates.")

    print("[~] Loading problem pages...")
    problem_pages = get_category_members(PROBLEM_CATEGORY, namespace=0)
    print(f"[+] Found {len(problem_pages)} pages.")

    problem_pages = problem_pages[:MAX_ARTICLES]
    print(f"[~] Processing {len(problem_pages)} pages (limit={MAX_ARTICLES})")

    edits_made = process_pages(problem_pages, hatnote_templates)

    print("\n==============================")
    print("Run complete.")
    print(f"Pages processed: {len(problem_pages)}")
    print(f"Edits made: {edits_made}")
    print("==============================")


if __name__ == "__main__":
    main()
