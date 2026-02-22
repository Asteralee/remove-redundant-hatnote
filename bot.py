import os
import requests
import mwparserfromhell

# --- Configuration ---
API_URL = "https://test.wikipedia.org/w/api.php"
BOT_USER = os.getenv("BOT_USER")
BOT_PASSWORD = os.getenv("BOT_PASSWORD")
MAX_ARTICLES = int(os.getenv("MAX_ARTICLES", 15))
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"

HEADERS = {"User-Agent": "SimpleWikiHatnoteBot/1.0"}

if not BOT_USER or not BOT_PASSWORD:
    raise ValueError("BOT_USER and BOT_PASSWORD must be set as environment variables.")

# --- Login & token ---
def login_and_get_session(username, password):
    session = requests.Session()
    session.headers.update(HEADERS)

    r1 = session.get(API_URL, params={'action':'query','meta':'tokens','type':'login','format':'json'})
    r1.raise_for_status()
    login_token = r1.json()['query']['tokens']['logintoken']

    r2 = session.post(API_URL, data={
        'action':'login',
        'lgname': username,
        'lgpassword': password,
        'lgtoken': login_token,
        'format':'json'
    })
    r2.raise_for_status()
    if r2.json()['login']['result'] != 'Success':
        raise Exception("Login failed!")

    logged_in_user = session.get(API_URL, params={'action':'query','meta':'userinfo','format':'json'}).json()['query']['userinfo']['name']
    print(f"[INFO] Logged in as {logged_in_user}")
    return session

def get_csrf_token(session):
    r = session.get(API_URL, params={'action':'query','meta':'tokens','format':'json'})
    r.raise_for_status()
    return r.json()['query']['tokens']['csrftoken']

# --- Helpers ---
def fetch_category_pages(session, category_title, limit):
    r = session.get(API_URL, params={
        "action":"query",
        "list":"categorymembers",
        "cmtitle":category_title,
        "cmlimit":limit,
        "format":"json"
    })
    r.raise_for_status()
    return r.json()['query']['categorymembers']

def fetch_page_content(session, title):
    r = session.get(API_URL, params={
        "action":"query",
        "prop":"revisions",
        "rvprop":"content",
        "titles":title,
        "format":"json"
    })
    r.raise_for_status()
    page_data = next(iter(r.json()['query']['pages'].values()))
    if 'revisions' not in page_data:
        return None
    return page_data['revisions'][0]['*']

def edit_page(session, title, new_text, csrf_token):
    response = session.post(API_URL, data={
        "action":"edit",
        "title":title,
        "text":new_text,
        "token":csrf_token,
        "summary":"Bot - Removing redlinked hatnote template ([[en:WP:HNR|read more!]])",
        "format":"json"
    })
    resp_json = response.json()
    if 'error' in resp_json:
        print(f"[ERROR] Editing {title} failed: {resp_json['error']}")
    else:
        print(f"[SUCCESS] Edited: {title}")

# --- HatnoteCleaner ---
class HatnoteCleaner:
    def __init__(self, template_names):
        self.template_names = template_names

    def remove_hatnotes(self, wikitext):
        parsed = mwparserfromhell.parse(wikitext)
        removed_any = False
        for template in parsed.filter_templates():
            if template.name.strip() in self.template_names:
                parsed.remove(template)
                removed_any = True
        return str(parsed), removed_any

# --- Main ---
def main():
    print(f"[INFO] Starting bot. DRY_RUN={DRY_RUN}, MAX_ARTICLES={MAX_ARTICLES}")
    session = login_and_get_session(BOT_USER, BOT_PASSWORD)
    csrf_token = get_csrf_token(session)

    category_title = "Category:Articles with hatnote templates targeting a nonexistent page"
    pages = fetch_category_pages(session, category_title, MAX_ARTICLES)

    # Step 1: Collect all template names in the pages
    hatnote_names = set()
    for page in pages:
        wikitext = fetch_page_content(session, page['title'])
        if not wikitext:
            continue
        parsed = mwparserfromhell.parse(wikitext)
        for template in parsed.filter_templates():
            hatnote_names.add(template.name.strip())
    print(f"[INFO] Collected {len(hatnote_names)} templates to remove.")

    cleaner = HatnoteCleaner(hatnote_names)

    # Step 2: Remove templates from each page
    for page in pages:
        title = page['title']
        wikitext = fetch_page_content(session, title)
        if not wikitext:
            continue
        new_text, removed = cleaner.remove_hatnotes(wikitext)
        if removed:
            if DRY_RUN:
                print(f"[DRY RUN] Would edit: {title}")
            else:
                edit_page(session, title, new_text, csrf_token)

    print("[INFO] Done processing pages.")

if __name__ == "__main__":
    main()
