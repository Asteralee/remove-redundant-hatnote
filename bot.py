import os
import requests
import mwparserfromhell
import pywikibot

# --- Configuration from environment variables ---
API_URL = "https://test.wikipedia.org/w/api.php"
USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")
MAX_ARTICLES = int(os.getenv("MAX_ARTICLES", 50))
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"

HEADERS = {
    "User-Agent": "SimpleWikiHatnoteBot/1.0 (https://github.com/yourname/simplewiki-hatnote-cleanup-bot)"
}

if not USERNAME or not PASSWORD:
    raise ValueError("USERNAME and PASSWORD must be set as environment variables.")

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

    # Step 3: verify login
    r3 = session.get(API_URL, params={
        'action': 'query',
        'meta': 'userinfo',
        'format': 'json'
    })
    r3.raise_for_status()
    logged_in_user = r3.json()['query']['userinfo']['name']
    print(f"Logged in as {logged_in_user}")

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
    def __init__(self, site):
        self.site = site

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
    # Setup Pywikibot site
    site = pywikibot.Site('simple', 'wikipedia')
    cleaner = HatnoteCleaner(site)
    
    # Login via raw API
    session = login_and_get_session(USERNAME, PASSWORD)
    csrf_token = get_csrf_token(session)

    # Fetch articles from tracking category
    category = pywikibot.Category(
        site,
        "Category:Articles with hatnote templates targeting a nonexistent page"
    )
    count = 0

    for page in category.articles():
        if count >= MAX_ARTICLES:
            break

        new_text, removed = cleaner.remove_hatnotes(page.text)
        if removed:
            if DRY_RUN:
                print(f"[DRY RUN] Would edit: {page.title()}")
            else:
                # Edit using raw API
                response = session.post(API_URL, data={
                    "action": "edit",
                    "title": page.title(),
                    "text": new_text,
                    "token": csrf_token,
                    "summary": "Bot - Removing redlinked hatnote template ([https://en.wikipedia.org/wiki/Wikipedia:Hatnote#Rules read more!])",
                    "format": "json"
                })
                resp_json = response.json()
                if 'error' in resp_json:
                    print(f"Error editing {page.title()}: {resp_json['error']}")
                else:
                    print(f"Edited: {page.title()}")
            count += 1

if __name__ == "__main__":
    main()
