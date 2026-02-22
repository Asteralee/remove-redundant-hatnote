import os
import requests
import mwparserfromhell

# --- Configuration from environment variables ---
API_URL = "https://test.wikipedia.org/w/api.php"
BOT_USER = os.getenv("BOT_USER")
BOT_PASSWORD = os.getenv("BOT_PASSWORD")
MAX_ARTICLES = int(os.getenv("MAX_ARTICLES", 15))
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"

HEADERS = {
    "User-Agent": "SimpleWikiHatnoteBot/1.0 (https://github.com/yourname/simplewiki-hatnote-cleanup-bot)"
}

if not BOT_USER or not BOT_PASSWORD:
    raise ValueError("BOT_USER and BOT_PASSWORD must be set as environment variables.")

# --- Login functions ---
def login_and_get_session(username, password):
    session = requests.Session()
    session.headers.update(HEADERS)

    # Step 1: Get login token
    r1 = session.get(API_URL, params={
        'action': 'query',
        'meta': 'tokens',
        'type': 'login',
        'format': 'json'
    })
    r1.raise_for_status()
    login_token = r1.json()['query']['tokens']['logintoken']

    # Step 2: Perform login
    r2 = session.post(API_URL, data={
        'action': 'login',
        'lgname': username,
        'lgpassword': password,
        'lgtoken': login_token,
        'format': 'json'
    })
    r2.raise_for_status()

    if r2.json()['login']['result'] != 'Success':
        raise Exception("Login failed!")

    # Step 3: Verify login
    r3 = session.get(API_URL, params={
        'action': 'query',
        'meta': 'userinfo',
        'format': 'json'
    })
    r3.raise_for_status()
    logged_in_user = r3.json()['query']['userinfo']['name']
    print(f"[INFO] Logged in as {logged_in_user}")

    return session

def get_csrf_token(session):
    r = session.get(API_URL, params={
        'action': 'query',
        'meta': 'tokens',
        'format': 'json'
    })
    r.raise_for_status()
    return r.json()['query']['tokens']['csrftoken']

# --- Hatnote removal logic ---
class HatnoteCleaner:
    def remove_hatnotes(self, wikitext):
        parsed = mwparserfromhell.parse(wikitext)
        removed_any = False

        for template in parsed.filter_templates():
            name = template.name.strip().lower()
            if 'hatnote' in name:
                removed_any = True
                parsed.remove(template)

        return str(parsed), removed_any

# --- Main bot workflow ---
def main():
    print(f"[INFO] Starting bot. DRY_RUN={DRY_RUN}, MAX_ARTICLES={MAX_ARTICLES}")
    cleaner = HatnoteCleaner()
    session = login_and_get_session(BOT_USER, BOT_PASSWORD)
    csrf_token = get_csrf_token(session)

    # Fetch pages from category
    r = session.get(API_URL, params={
        "action": "query",
        "list": "categorymembers",
        "cmtitle": "Category:Articles with hatnote templates targeting a nonexistent page",
        "cmlimit": MAX_ARTICLES,
        "format": "json"
    })
    r.raise_for_status()
    pages = r.json()['query']['categorymembers']
    print(f"[INFO] Found {len(pages)} pages in category.")

    count = 0
    for page in pages:
        if count >= MAX_ARTICLES:
            break
        title = page['title']
        print(f"[INFO] Processing page: {title}")

        # Fetch page content
        r_page = session.get(API_URL, params={
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "titles": title,
            "format": "json"
        })
        r_page.raise_for_status()
        page_data = next(iter(r_page.json()['query']['pages'].values()))

        if 'revisions' not in page_data:
            print(f"[WARN] No content for page: {title}, skipping.")
            continue

        wikitext = page_data['revisions'][0]['*']
        new_text, removed = cleaner.remove_hatnotes(wikitext)

        if removed:
            print(f"[INFO] Hatnote template(s) found in {title} — will be removed.")
            if DRY_RUN:
                print(f"[DRY RUN] Would edit: {title}")
            else:
                response = session.post(API_URL, data={
                    "action": "edit",
                    "title": title,
                    "text": new_text,
                    "token": csrf_token,
                    "summary": "Bot - Removing redlinked hatnote template ([[en:WP:HNR|more info]])",
                    "format": "json"
                })
                resp_json = response.json()
                if 'error' in resp_json:
                    print(f"[ERROR] Editing {title} failed: {resp_json['error']}")
                else:
                    print(f"[SUCCESS] Edited: {title}")
            count += 1
        else:
            print(f"[INFO] No hatnotes found in {title}, skipping.")

    print(f"[INFO] Done. Processed {count} page(s).")

if __name__ == "__main__":
    main()
