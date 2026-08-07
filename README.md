# Hillcrest Tee Time Auto-Booker

Automatically logs into foreUP and books the earliest available tee time
for 4 players, the moment the 7-day booking window opens at 7:00 PM.
Runs entirely in the cloud (GitHub Actions) so it works regardless of
whether your iPad is on.

## Honest expectations

I built this without being able to log into your actual foreUP account, so
the page-element matching is my best guess based on how foreUP's booking
sites are typically structured. **The first run or two will likely need a
small adjustment** to one or two selectors in `book_tee_time.py`. The good
news: every run saves screenshots of each step, so you (or I, if you paste
me what you see) can quickly spot exactly where it went off track and fix
it. This is normal for this kind of automation — treat the first week as a
shakeout period, not a guarantee of success on day one.

## One-time setup (all doable from an iPad in Safari)

### 1. Create a GitHub account
Go to github.com and sign up (free) if you don't already have one.

### 2. Create a new repository
- Tap **+** → **New repository**
- Name it something like `hillcrest-tee-time-bot`
- Set it to **Public** (GitHub Actions free minutes are unlimited on public
  repos; Private repos have a monthly minute cap that this daily job would
  eat into). Nothing sensitive lives in the code itself — your password
  goes in encrypted Secrets, never in the repo files.

### 3. Upload the files
Upload these four files/folders, preserving the folder structure:
- `book_tee_time.py`
- `requirements.txt`
- `.github/workflows/book-tee-time.yml`
- `README.md` (optional, just for your reference)

On GitHub's mobile web interface: **Add file → Upload files**, drag/select
each one. For the `.github/workflows/book-tee-time.yml` file, you'll need
to create the folder path — GitHub lets you type
`.github/workflows/book-tee-time.yml` as the filename when uploading and it
creates the folders automatically.

### 4. Add your foreUP credentials as encrypted Secrets
In your new repo: **Settings → Secrets and variables → Actions → New
repository secret**
- Name: `FOREUP_USERNAME` → Value: your foreUP login email
- Name: `FOREUP_PASSWORD` → Value: your foreUP password

These are encrypted at rest, never shown in logs, and never visible to
anyone but you (not even me — I never see them).

### 5. Test it with a dry run
- Go to the **Actions** tab → **Book Hillcrest Tee Time** workflow →
  **Run workflow** button
- Leave `dry_run` set to `true`
- Run it, wait ~1-2 minutes, then click into the run and download the
  `screenshots` artifact at the bottom to see exactly how far it got and
  what the page looked like at each step

### 6. Fix anything that broke
If a screenshot shows it stalled (e.g., the login button wasn't found, or
the date picker didn't match), send me the screenshot description or what
you see and I'll adjust the corresponding selector in `book_tee_time.py`.

### 7. Go live
Once a dry run makes it all the way to the "ready to confirm" screen
successfully, you're set — the two scheduled triggers will fire
automatically every day at ~7:00 PM Mountain Time, waiting for the exact
second before grabbing the earliest slot for 4 players.

## Notes

- **Number of players**: hardcoded to 4 in the workflow file
  (`NUM_PLAYERS: "4"`). Change that line if it varies.
- **Which date**: always books exactly 7 days out from whatever day the
  workflow runs, matching Hillcrest's stated policy.
- **Cost**: $0 — GitHub Actions on a public repo is free for this usage
  level.
- **Security**: your credentials never touch this chat or any file in the
  repo — only GitHub's encrypted Secrets store, which the workflow reads
  at runtime.
