import requests
import mwparserfromhell
import os

API_URL = "https://test.wikipedia.org/w/api.php"

# Environment variables for GitHub Actions or local testing
BOT_USER = os.environ.get("BOT_USER")
BOT_PASSWORD = os.environ.get("BOT_PASSWORD")

PROBLEM_CATEGORY = "Category:Articles with hatnote templates targeting a nonexistent page"
HATNOTE_CATEGORY = "Category:Hatnote templates"

MAX_ARTICLES = int(os.environ.get("MAX_ARTICLES", 20))
DRY_RUN = os.environ.get("DRY_RUN", "True").lower() in ["true", "1", "yes"]

session = requests.Session()

def login():
    r = session.get(API_URL, params={
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    }).json()
    login_token = r["query"]["tokens"]["logintoken"]

    r2 = session.post(API_URL, data={
        "action": "login",
        "lgname": BOT_USER,
        "lgpassword": BOT_PASSWORD,
        "lgtoken": login_token,
        "format": "json"
    }).json()
    if r2.get("login", {}).get("result") != "Success":
        raise Exception("Login failed: " + str(r2))
    print("[+] Logged in successfully.")

    r3 = session.get(API_URL, params={"action": "query", "meta": "tokens", "format": "json"}).json()
    return r3["query"]["tokens"]["csrftoken"]

def get_category_members(category, namespace=0):
    """Return list of page titles in a category, ignoring subcategories."""
    members = []
    cmcontinue = ""
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmlimit": "max",
            "cmnamespace": namespace,  # 0=articles, 10=templates
            "format": "json"
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        r = session.get(API_URL, params=params).json()
        members.extend([m["title"] for m in r["query"]["categorymembers"]])
        if "continue" in r:
            cmcontinue = r["continue"]["cmcontinue"]
        else:
            break
    return members

def page_exists(title):
    r = session.get(API_URL, params={
        "action": "query",
        "titles": title,
        "format": "json"
    }).json()
    page = next(iter(r["query"]["pages"].values()))
    return "missing" not in page

def get_page_text(title):
    r = session.get(API_URL, params={
        "action": "query",
        "prop": "revisions",
        "titles": title,
        "rvprop": "content",
        "format": "json"
    }).json()
    page = next(iter(r["query"]["pages"].values()))
    return page["revisions"][0]["*"] if "revisions" in page else ""

def edit_page(title, new_text, summary):
    if DRY_RUN:
        print(f"[DRY RUN] Would save {title}: {summary}")
        return
    r = session.post(API_URL, data={
        "action": "edit",
        "title": title,
        "text": new_text,
        "token": csrf_token,
        "format": "json",
        "summary": summary,
        "bot": True
    }).json()
    if "edit" in r and r["edit"].get("result") == "Success":
        print(f"[+] Edited {title}")
    else:
        print(f"[!] Failed to edit {title}: {r}")

def main():
    global csrf_token
    csrf_token = login()

    # Load hatnote templates (namespace 10)
    print("[~] Loading hatnote templates...")
    hatnote_templates = get_category_members(HATNOTE_CATEGORY, namespace=10)
    hatnote_templates = [t.replace("Template:", "") for t in hatnote_templates]
    print(f"[+] Loaded {len(hatnote_templates)} hatnote templates.")

    # Load problem articles (namespace 0)
    print("[~] Loading problem pages...")
    problem_pages = get_category_members(PROBLEM_CATEGORY, namespace=0)
    print(f"[+] Found {len(problem_pages)} problem pages.")

    # Apply max articles limit
    if MAX_ARTICLES is not None:
        problem_pages = problem_pages[:MAX_ARTICLES]
        print(f"[+] Limiting to {len(problem_pages)} articles for this run.")

    # Process each article
    for page_title in problem_pages:
        print(f"\n[~] Processing {page_title}")
        text = get_page_text(page_title)
        wikicode = mwparserfromhell.parse(text)
        modified = False

        for template in wikicode.filter_templates():
            name = template.name.strip()
            if name in hatnote_templates:
                links = template.filter_wikilinks()
                remove_template = False
                for link in links:
                    target_title = str(link.title).split("|")[0]
                    if not page_exists(target_title):
                        remove_template = True
                        print(f"    [-] Template {name} points to missing page {target_title}")
                        break
                if remove_template:
                    wikicode.remove(template)
                    modified = True

        if modified:
            edit_page(page_title, str(wikicode), "Bot: Removed hatnote pointing to nonexistent page")

# Run main() only if executed directly
if __name__ == "__main__":
    main()
