# -*- coding: utf-8 -*-
"""
du_number_checker.py

Daily du number checker with Telegram alerts.

Flow:
- Open du prepaid flexi plans page
- Click "Setup my plan"
- Click "Change" on the number card
- Find the search box in the modal
- For each configured number:
    - Search for the number
    - Parse results
- If any numbers appear available, send a Telegram alert.
"""

import os
import sys
import traceback
from typing import List, Tuple

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ---------------- CONFIGURATION ----------------

DU_URL = "https://shop.du.ae/en/personal/s-du-prepaid-flexi-plans"

# List of numbers to check.
# Each tuple is: (what you type in the search box, what you expect to see in the results).
NUMBERS_TO_CHECK: List[Tuple[str, str]] = [
    ("282 0202", "282 0202"),
    # Add more if you like, for example:
    ("1051661", "1051661"),
]

# Telegram bot credentials.
# Recommended: set these as environment variables in your cloud host.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8534765631:AAHxHvm5ITXuDVncEvdrGx5gBROF3sG7UQ8")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1479175062")

# Headless browser config
HEADLESS = True
SLOW_MO_MS = 0


# ---------------- TELEGRAM UTILS ----------------

def send_telegram_message(text: str) -> None:
    """Send a Telegram message via bot API."""
    token = TELEGRAM_BOT_TOKEN
    chat_id = TELEGRAM_CHAT_ID

    if not token or not chat_id or "PUT_YOUR" in token or "PUT_YOUR" in chat_id:
        print("[WARN] Telegram credentials not set; skipping notification.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=10)
        if resp.status_code != 200:
            print("[ERROR] Failed to send Telegram message:", resp.text)
        else:
            print("[INFO] Telegram notification sent.")
    except Exception as e:
        print("[ERROR] Exception while sending Telegram message:", repr(e))


# ---------------- PLAYWRIGHT HELPERS ----------------

def get_search_box(page):
    """Try several strategies to locate the search box in the modal."""
    # 1) Try placeholder-based (if present)
    try:
        loc = page.get_by_placeholder("Search for a number")
        if loc.count() > 0:
            print("[DEBUG] Found search box via placeholder.")
            return loc.first
    except Exception:
        pass

    # 2) Try role/name
    try:
        loc = page.get_by_role("textbox", name="Search for a number")
        if loc.count() > 0:
            print("[DEBUG] Found search box via role/name.")
            return loc.first
    except Exception:
        pass

    # 3) Fallback: any visible text/search input in the modal
    print("[DEBUG] Falling back to visible text/search input detection...")
    candidates = page.locator("input[type='text'], input[type='search']")
    count = candidates.count()
    print("[DEBUG] Found {} candidate input(s).".format(count))

    for i in range(count):
        el = candidates.nth(i)
        try:
            if el.is_visible():
                print("[DEBUG] Using visible input candidate #{}".format(i))
                return el
        except Exception:
            continue

    return None


def open_du_number_modal(page):
    """Navigate to the du page, close any popup, click Setup my plan and Change."""
    print("[INFO] Opening du page...")
    try:
        page.goto(DU_URL, wait_until="domcontentloaded", timeout=30000)
    except PlaywrightTimeoutError:
        print("[WARN] Page load timeout, continuing anyway (URL: {})".format(page.url))
    page.wait_for_timeout(3000)

    # Dismiss notification popup if it appears
    try:
        popup_btn = page.get_by_text("I'll do this later", exact=False)
        if popup_btn.count() > 0:
            print("[INFO] Dismissing notification popup...")
            popup_btn.first.click()
            page.wait_for_timeout(500)
    except Exception:
        pass

    # Click "Setup my plan"
    print("[INFO] Clicking 'Setup my plan'...")
    page.get_by_text("Setup my plan", exact=False).first.click()
    page.wait_for_timeout(3000)

    # Click "Change" on the number card (avoid "Change to du" in header)
    print("[INFO] Clicking 'Change' on the number card...")
    try:
        change_link = page.get_by_text("Change", exact=True).first
        change_link.click(force=True)
    except Exception as e:
        print("[WARN] Exact 'Change' click failed ({}). Trying scoped locator...".format(e))
        try:
            card = page.get_by_text("Your new number", exact=False).first
            change_link = card.locator("xpath=..").get_by_text("Change", exact=False).first
            change_link.click(force=True)
        except Exception as e2:
            print("[ERROR] Could not click 'Change' on card:", repr(e2))
            raise

    page.wait_for_timeout(3000)
    print("[INFO] Number picker modal should now be open.")


# ---------------- CORE CHECK LOGIC ----------------

def check_numbers() -> List[Tuple[str, str]]:
    """Check all numbers and return list of (search_value, match_fragment) that appear available."""
    available = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO_MS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ],
        )
        page = browser.new_page()

        try:
            open_du_number_modal(page)

            # Find search box once and reuse it
            print("[INFO] Locating search input in modal...")
            search_box = get_search_box(page)
            if search_box is None:
                print("[ERROR] Could not find any suitable search input.")
                browser.close()
                return available

            # Loop over all numbers
            for search_value, match_fragment in NUMBERS_TO_CHECK:
                try:
                    print("[INFO] Checking number '{}'...".format(search_value))
                    search_box.click()
                    search_box.fill(search_value)
                    search_box.press("Enter")

                    page.wait_for_timeout(5000)

                    body_text = page.text_content("body") or ""
                    normalized_body = body_text.replace(" ", "")
                    normalized_fragment = match_fragment.replace(" ", "")

                    if "No results found" in body_text:
                        print("[INFO] '{}' not available (No results found).".format(search_value))
                    elif normalized_fragment in normalized_body:
                        print("[INFO] '{}' appears to be AVAILABLE.".format(match_fragment))
                        available.append((search_value, match_fragment))
                    else:
                        print("[WARN] Ambiguous result for '{}'. Did not see 'No results found' or the exact fragment.".format(search_value))
                except Exception as e:
                    print("[ERROR] Error while checking '{}': {}".format(search_value, repr(e)))
                    traceback.print_exc()

        except Exception as outer:
            print("[ERROR] Failed during page setup or modal open:", repr(outer))
            traceback.print_exc()
        finally:
            browser.close()

    return available


# ---------------- ENTRYPOINT ----------------

def main():
    print("[INFO] Starting du number check...")

    available = check_numbers()

    if not available:
        print("[INFO] No numbers available today.")
        return

    # Build a single message listing all available numbers
    lines = ["The following numbers appear to be available on du:"]
    for search_value, match_fragment in available:
        lines.append("- {}".format(match_fragment))

    message = "\n".join(lines)
    print("[INFO] At least one number appears available. Sending Telegram alert...")
    send_telegram_message(message)


if __name__ == "__main__":
    main()
