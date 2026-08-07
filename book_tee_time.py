"""
Hillcrest Golf Club (foreUP) tee time auto-booker.

Logs in, waits until exactly 7:00:00 PM America/Denver time, then grabs the
earliest available tee time for the target date (7 days out) and books it
for the configured number of players.

Environment variables required (set as GitHub Actions secrets):
    FOREUP_USERNAME   - your foreUP login email
    FOREUP_PASSWORD   - your foreUP login password

Optional environment variables:
    NUM_PLAYERS       - defaults to 4
    DRY_RUN           - "true" to do everything except actually confirm the
                         booking (useful for testing). Defaults to "false".
    EARLY_EXIT_MINUTES - if the script starts more than this many minutes
                         before the 7:00 PM target, it exits immediately
                         instead of burning Actions minutes waiting.
                         Defaults to 15.

Notes / limitations:
    foreUP's booking page is a JavaScript single-page app, and the exact
    element structure can vary by club configuration. This script uses
    text-based matching (button/link text, ARIA roles) rather than fragile
    CSS class names wherever possible, and takes a screenshot after every
    major step so failures are easy to diagnose from the GitHub Actions
    run artifacts. If a selector below stops matching (foreUP updated their
    UI), check the "screenshots" artifact from the failed run and adjust
    the corresponding SELECTOR/step below.
"""

import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CLUB_ID = "20337"
SCHEDULE_ID = "4283"
BOOKING_URL = f"https://foreupsoftware.com/index.php/booking/{CLUB_ID}/{SCHEDULE_ID}#teetimes"

TIMEZONE = ZoneInfo("America/Denver")
TARGET_HOUR = 19  # 7:00 PM local time, when the booking window opens
DAYS_OUT = 7       # tee times release exactly 7 days in advance

NUM_PLAYERS = int(os.environ.get("NUM_PLAYERS", "4"))
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


# ---------------------------------------------------------------------------
# Timing: figure out today's target date and wait until 7:00:00 PM
# ---------------------------------------------------------------------------

def wait_for_booking_window() -> datetime:
    now = datetime.now(TIMEZONE)
    target_today = now.replace(hour=TARGET_HOUR, minute=0, second=0, microsecond=0)

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


# ---------------------------------------------------------------------------
# Booking flow
# ---------------------------------------------------------------------------

def login(page) -> None:
    log("Navigating to booking page...")
    page.goto(BOOKING_URL, wait_until="domcontentloaded", timeout=30000)
    snap(page, "01_initial_load")

    # foreUP usually pops a login modal automatically, or shows a "Login"
    # link/button if you're not authenticated yet.
    try:
        login_trigger = page.get_by_role("link", name="Login").or_(
            page.get_by_role("button", name="Login")
        )
        login_trigger.first.click(timeout=8000)
        log("Clicked Login trigger.")
    except PWTimeout:
        log("No separate Login trigger found -- assuming login form is already visible.")

    snap(page, "02_login_form")

    email_field = page.locator(
        "input[type='email'], input[name*='user' i], input[placeholder*='email' i]"
    ).first
    password_field = page.locator("input[type='password']").first

    email_field.wait_for(state="visible", timeout=15000)
    email_field.fill(USERNAME)
    password_field.fill(PASSWORD)
    snap(page, "03_credentials_filled")

    submit_btn = page.get_by_role("button", name="Login").or_(
        page.get_by_role("button", name="Sign In")
    )
    submit_btn.first.click()

    page.wait_for_load_state("networkidle", timeout=20000)
    snap(page, "04_after_login")
    log("Login submitted.")


def select_date(page, target_date) -> None:
    # foreUP typically supports a URL query param for date, but the SPA can
    # ignore it depending on version -- so we try the calendar UI as the
    # reliable path, using an ARIA-accessible date button as the target.
    date_label = target_date.strftime("%B %-d, %Y")  # e.g. "August 14, 2026"
    log(f"Looking for date picker entry: {date_label}")

    try:
        page.get_by_role("button", name=date_label).click(timeout=10000)
    except PWTimeout:
        log(
            "Could not find an exact date-label button; trying the day-of-month "
            "number as a fallback."
        )
        day_num = str(target_date.day)
        page.get_by_role("button", name=day_num, exact=True).first.click(timeout=10000)

    page.wait_for_load_state("networkidle", timeout=15000)
    snap(page, "05_date_selected")


MAX_SLOT_ATTEMPTS = 6  # how many times, in order, to try before giving up

# Phrases foreUP (or similar booking systems) commonly show when a slot
# you clicked has just been taken by someone else. If you see a run fail
# with a screenshot showing different wording than this, add it here.
UNAVAILABLE_PHRASES = [
    "no longer available",
    "unavailable",
    "sold out",
    "already booked",
    "not available",
    "select a different time",
]


def _set_players(page) -> None:
    try:
        players_dropdown = page.locator(
            "select[name*='player' i], select[id*='player' i]"
        ).first
        players_dropdown.select_option(str(NUM_PLAYERS), timeout=5000)
        log(f"Set players to {NUM_PLAYERS}.")
    except Exception:
        try:
            page.get_by_role("button", name=str(NUM_PLAYERS), exact=True).click(timeout=5000)
            log(f"Set players to {NUM_PLAYERS} via button.")
        except Exception:
            log("Could not find a players selector -- leaving default and continuing.")


def _page_shows_unavailable_error(page) -> bool:
    try:
        body_text = page.inner_text("body").lower()
    except Exception:
        return False
    return any(phrase in body_text for phrase in UNAVAILABLE_PHRASES)


def _attempt_booking_on_open_slot(page, slot_label: str) -> bool:
    """Assumes a slot's detail/modal view is already open. Tries to set
    players and confirm. Returns True on apparent success, False if the
    slot turned out to be unavailable or the confirm step failed."""

    _set_players(page)
    snap(page, "players_set")

    if _page_shows_unavailable_error(page):
        log(f"Slot {slot_label} shows an unavailable message before confirming.")
        return False

    book_btn = page.get_by_role("button", name="Book Now").or_(
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
    snap(page, "06_teetimes_loaded")

    for attempt in range(1, MAX_SLOT_ATTEMPTS + 1):
        # Re-query the list fresh each attempt -- after a failed booking
        # the page may re-render and remove the slot that just got taken,
        # so we can't reuse a stale locator/index from a previous loop.
        time_tiles = page.locator("text=/\\d{1,2}:\\d{2}\\s*(AM|PM)/i")
        count = time_tiles.count()
        log(f"Attempt {attempt}: {count} time-like elements currently on the page.")

        if count == 0:
            log("No tee times available -- nothing left to try.")
            return False

        # Slot index 0 is always "the earliest remaining" as long as we
        # re-query after every failure, so we always grab .first here
        # rather than incrementing an index (the taken slot disappears
        # from the list, so the next-earliest naturally becomes .first).
        slot = time_tiles.first
        slot_label = slot.inner_text()
        log(f"Trying slot: {slot_label}")
        slot.click()
        page.wait_for_load_state("networkidle", timeout=15000)
        snap(page, f"07_attempt{attempt}_slot_selected")

        success = _attempt_booking_on_open_slot(page, slot_label)
        if success:
            log(f"SUCCESS on attempt {attempt}: booked {slot_label}.")
            return True

        log(f"Attempt {attempt} for slot {slot_label} failed -- backing out and retrying.")
        # Try to close whatever modal/detail view is open so the next loop
        # iteration sees the fresh list of remaining tiles.
        for close_name in ["Close", "Cancel", "Back", "×"]:
            try:
                page.get_by_role("button", name=close_name).first.click(timeout=3000)
                break
            except Exception:
                continue
        page.wait_for_timeout(1000)
        snap(page, f"07_attempt{attempt}_backed_out")

    log(f"Exhausted {MAX_SLOT_ATTEMPTS} attempts without a successful booking.")
    return False


def main() -> None:
    if not USERNAME or not PASSWORD:
        log("ERROR: FOREUP_USERNAME / FOREUP_PASSWORD not set. Aborting.")
        sys.exit(1)

    target_date = wait_for_booking_window()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
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
