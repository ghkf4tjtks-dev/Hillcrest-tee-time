# Hillcrest Golf Club (foreUP) tee time auto-booker.

# Logs in, waits until exactly 7:00:00 PM America/Denver time, then grabs
# the earliest available tee time for the target date (8 days out) and
# books it for the configured number of players.
#
# Required environment variables (set as GitHub Actions secrets):
#   FOREUP_USERNAME   - your foreUP login email
#   FOREUP_PASSWORD   - your foreUP login password
#
# Optional environment variables:
#   NUM_PLAYERS         - defaults to 4
#   HOLES               - "9" or "18", defaults to "9"
#   CART                - "Yes" or "No", defaults to "Yes"
#   DRY_RUN             - "true" to do everything except confirm the
#                         booking. Defaults to "false".
#   EARLY_EXIT_MINUTES  - if the script starts more than this many
#                         minutes before the 7 PM target, it exits
#                         immediately. Defaults to 15.
#   SKIP_WAIT           - "true" to skip the wait-until-7PM logic
#                         entirely, used for manual test runs.

import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

CLUB_ID = "20337"
SCHEDULE_ID = "4283"
BOOKING_URL = f"https://foreupsoftware.com/index.php/booking/{CLUB_ID}/{SCHEDULE_ID}#teetimes"

TIMEZONE = ZoneInfo("America/Denver")
TARGET_HOUR = 19  # 7:00 PM local time, when the booking window opens
DAYS_OUT = 8       # confirmed empirically: the 7 PM opening releases the
                   # date 8 days out, not 7 (e.g. Aug 7 7PM opens Aug 15)

NUM_PLAYERS = int(os.environ.get("NUM_PLAYERS", "4"))
HOLES = os.environ.get("HOLES", "9")
CART = os.environ.get("CART", "Yes")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
EARLY_EXIT_MINUTES = int(os.environ.get("EARLY_EXIT_MINUTES", "15"))

USERNAME = os.environ.get("FOREUP_USERNAME")
PASSWORD = os.environ.get("FOREUP_PASSWORD")

SCREENSHOT_DIR = "screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def log(msg: str) -> None:
    stamp = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{stamp}] {msg}", flush=True)


def snap(page, name: str) -> None:
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    try:
        page.screenshot(path=path, full_page=True)
        log(f"Saved screenshot: {path}")
    except Exception as e:
        log(f"Could not save screenshot {name}: {e}")


SKIP_WAIT = os.environ.get("SKIP_WAIT", "false").lower() == "true"


def wait_for_booking_window() -> datetime:
    now = datetime.now(TIMEZONE)
    target_today = now.replace(hour=TARGET_HOUR, minute=0, second=0, microsecond=0)

    if SKIP_WAIT:
        log("SKIP_WAIT is enabled (manual test run) -- skipping the wait-until-7PM "
            "logic and proceeding straight to the booking flow.")
        target_date = (now + timedelta(days=DAYS_OUT)).date()
        log(f"Target tee time date: {target_date.isoformat()}")
        return target_date

    minutes_until = (target_today - now).total_seconds() / 60

    if minutes_until > EARLY_EXIT_MINUTES:
        log(
            f"Current time {now.strftime('%H:%M:%S')} is {minutes_until:.0f} min "
            f"before the 7:00 PM window (more than the {EARLY_EXIT_MINUTES}-min "
            "threshold). Exiting early to save Actions minutes; the other "
            "scheduled trigger should be closer to the mark today."
        )
        sys.exit(0)

    if now < target_today:
        wait_seconds = (target_today - now).total_seconds()
        log(f"Waiting {wait_seconds:.0f} seconds until 7:00:00 PM local time...")
        time.sleep(wait_seconds)
    else:
        log("Already past 7:00 PM local time -- proceeding immediately (best effort).")

    target_date = (now + timedelta(days=DAYS_OUT)).date()
    log(f"Target tee time date: {target_date.isoformat()}")
    return target_date


def login(page) -> None:
    log("Navigating to booking page...")
    page.goto(BOOKING_URL, wait_until="domcontentloaded", timeout=30000)
    snap(page, "01_initial_load")

    try:
        login_trigger = page.get_by_role("link", name="Log In").or_(
            page.get_by_role("button", name="Log In")
        )
        login_trigger.first.click(timeout=8000)
        log("Clicked Log In trigger.")
    except PWTimeout:
        log("No separate Log In trigger found -- assuming login form is already visible.")

    snap(page, "02_login_form")

    email_field = page.get_by_placeholder("Email").first
    password_field = page.get_by_placeholder("Password").first

    email_field.wait_for(state="visible", timeout=15000)
    email_field.fill(USERNAME)
    password_field.fill(PASSWORD)
    snap(page, "03_credentials_filled")

    password_field.press("Enter")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PWTimeout:
        pass

    if password_field.is_visible():
        log("Enter key did not submit the login form -- trying a direct button click.")
        submit_btn = page.get_by_role("button", name="Log In", exact=True)
        submit_btn.last.click(timeout=10000)
        page.wait_for_load_state("networkidle", timeout=20000)

    snap(page, "04_after_login")
    log("Login submitted.")

    try:
        reserve_btn = page.get_by_role("link", name="Click Here to Reserve a Tee Time").or_(
            page.get_by_role("button", name="Click Here to Reserve a Tee Time")
        )
        reserve_btn.first.click(timeout=8000)
        log("Clicked 'Click Here to Reserve a Tee Time'.")
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        log("Could not find the 'Click Here to Reserve a Tee Time' button -- "
            "continuing in case we're already on the booking widget.")

    snap(page, "05_after_reserve_click")


def select_date(page, target_date) -> None:
    day_num = str(target_date.day)
    log(f"Clicking calendar day {day_num}...")

    try:
        page.get_by_text(day_num, exact=True).first.click(timeout=10000)
        page.wait_for_load_state("networkidle", timeout=15000)
        log(f"Clicked day {day_num} via text match.")
    except PWTimeout:
        log(f"Text match for day {day_num} failed -- trying role=button as a fallback.")
        try:
            page.get_by_role("button", name=day_num, exact=True).first.click(timeout=10000)
            page.wait_for_load_state("networkidle", timeout=15000)
            log(f"Clicked day {day_num} via button role.")
        except PWTimeout:
            log(f"Could not select day {day_num} either way -- proceeding anyway.")

    snap(page, "06_date_selected")


MAX_SLOT_ATTEMPTS = 6

UNAVAILABLE_PHRASES = [
    "no longer available",
    "unavailable",
    "sold out",
    "already booked",
    "not available",
    "select a different time",
]


def _set_holes(page) -> None:
    try:
        page.get_by_text(HOLES, exact=True).first.click(timeout=5000)
        log(f"Set holes to {HOLES}.")
    except Exception:
        log("Could not find a holes selector -- leaving default and continuing.")


def _set_players(page) -> None:
    try:
        players_dropdown = page.locator(
            "select[name*='player' i], select[id*='player' i]"
        ).first
        players_dropdown.select_option(str(NUM_PLAYERS), timeout=5000)
        log(f"Set players to {NUM_PLAYERS}.")
    except Exception:
        try:
            page.get_by_text(str(NUM_PLAYERS), exact=True).first.click(timeout=5000)
            log(f"Set players to {NUM_PLAYERS} via text match.")
        except Exception:
            log("Could not find a players selector -- leaving default and continuing.")


def _set_cart(page) -> None:
    try:
        page.get_by_text(CART, exact=True).first.click(timeout=5000)
        log(f"Set cart to {CART}.")
    except Exception:
        log("Could not find a cart selector -- leaving default and continuing.")


def _page_shows_unavailable_error(page) -> bool:
    try:
        body_text = page.inner_text("body").lower()
    except Exception:
        return False
    return any(phrase in body_text for phrase in UNAVAILABLE_PHRASES)


def _attempt_booking_on_open_slot(page, slot_label: str) -> bool:
    _set_holes(page)
    _set_players(page)
    _set_cart(page)
    snap(page, "players_set")

    if _page_shows_unavailable_error(page):
        log(f"Slot {slot_label} shows an unavailable message before confirming.")
        return False

    book_btn = page.get_by_role("button", name="Book Time", exact=True).or_(
        page.get_by_role("button", name="Book Now")
    ).or_(
        page.get_by_role("button", name="Book Tee Time")
    ).or_(
        page.get_by_role("button", name="Reserve")
    )

    if DRY_RUN:
        log("DRY_RUN is enabled -- NOT clicking the final booking confirmation.")
        snap(page, "dry_run_stopped_before_confirm")
        return True

    try:
        book_btn.first.click(timeout=10000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        log(f"Confirm click/timeout issue for slot {slot_label}.")
        return False

    snap(page, "after_confirm_click")

    if _page_shows_unavailable_error(page):
        log(f"Slot {slot_label} was taken out from under us at confirmation.")
        return False

    log(f"Booking confirmation submitted for slot {slot_label}.")
    return True


def book_earliest_slot(page) -> bool:
    log("Waiting for tee time tiles to load...")
    page.wait_for_selector("text=/\\d{1,2}:\\d{2}\\s*(AM|PM)/i", timeout=20000)
    snap(page, "07_teetimes_loaded")

    for attempt in range(1, MAX_SLOT_ATTEMPTS + 1):
        time_tiles = page.locator("text=/\\d{1,2}:\\d{2}\\s*(AM|PM)/i")
        count = time_tiles.count()
        log(f"Attempt {attempt}: {count} time-like elements currently on the page.")

        if count == 0:
            log("No tee times available -- nothing left to try.")
            return False

        slot = time_tiles.first
        slot_label = slot.inner_text()
        log(f"Trying slot: {slot_label}")
        slot.click()
        page.wait_for_load_state("networkidle", timeout=15000)
        snap(page, f"08_attempt{attempt}_slot_selected")

        success = _attempt_booking_on_open_slot(page, slot_label)
        if success:
            log(f"SUCCESS on attempt {attempt}: booked {slot_label}.")
            return True

        log(f"Attempt {attempt} for slot {slot_label} failed -- backing out and retrying.")
        for close_name in ["Close", "Cancel", "Back", "\u00d7"]:
            try:
                page.get_by_role("button", name=close_name).first.click(timeout=3000)
                break
            except Exception:
                continue
        page.wait_for_timeout(1000)
        snap(page, f"08_attempt{attempt}_backed_out")

    log(f"Exhausted {MAX_SLOT_ATTEMPTS} attempts without a successful booking.")
    return False


def main() -> None:
    if not USERNAME or not PASSWORD:
        log("ERROR: FOREUP_USERNAME / FOREUP_PASSWORD not set. Aborting.")
        sys.exit(1)

    target_date = wait_for_booking_window()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        page = context.new_page()

        try:
            login(page)
            select_date(page, target_date)
            success = book_earliest_slot(page)
            if success:
                log("DONE. Check the screenshots artifact to confirm the result.")
            else:
                log("Run completed but no booking was made -- check screenshots.")
                sys.exit(1)
        except Exception as e:
            log(f"ERROR during run: {e}")
            snap(page, "99_error_state")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
