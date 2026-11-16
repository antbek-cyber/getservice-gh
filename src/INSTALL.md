# GetService GH update: install notes

## Order
1. Back up the database.
2. Run `schema_changes.sql` (see the notes inside; the last block is PostgreSQL only).
3. Copy the files into your project (map below) and redeploy.

## Where files go
| File | Destination |
|---|---|
| `routes.py`, `models.py` | project root (replace) |
| `templates/*.html` (22 files) | your `templates/` folder |
| `static/manifest.json` | your `static/` folder (replace your current one) |
| `static/icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `favicon-48.png`, `logo.svg` | your `static/` folder (new logo) |
| `static/assetlinks.json` | your `static/` folder, then fill in the two placeholders |

`layout.html` is the new shared shell. Your existing `base.html` is untouched
(pages I haven't seen, such as admin and privacy, may still use it).

## Delete these old templates (no route renders them; they use fields that don't exist)
`search.html`, `worker.html`, `register.html`, `booking_success.html`, `my_jobs_login.html`

## Android (AAB) checklist
- [ ] `https://YOUR-DOMAIN/manifest.json` opens in a browser and shows JSON
- [ ] `static/icon-192.png`, `icon-512.png` and `icon-maskable-512.png` exist (included in this package)
- [ ] `https://YOUR-DOMAIN/service-worker.js` opens (it is `static/service-worker.js`)
- [ ] `static/assetlinks.json` filled in with your package name + SHA-256, then
      `https://YOUR-DOMAIN/.well-known/assetlinks.json` opens
- [ ] Site is served over HTTPS
- Play App Signing: use the SHA-256 of the *App signing key* (Play Console >
  Setup > App signing), not the upload key.
- Give PWABuilder or Bubblewrap the manifest URL directly:
  `https://YOUR-DOMAIN/manifest.json`

## Behaviour changes to know about
- Booking price comes from the worker's daily rate (GHS 200 if unset).
- Customers pay from their dashboard after the worker accepts.
- Job posters' phone numbers are visible only to logged-in workers.
- Customers no longer get web-push (only workers can subscribe); they get the in-app bell.
- To enable CSRF later: `CSRFProtect(app)`, exempt `/paystack/webhook`. All forms already carry the token field.

## Password reset (new)
Customers and workers get a "Forgot password?" link on their login pages. A signed, single-use link
(valid 1 hour) is emailed to the address on the account.

**1. Set these environment variables so email can be sent** (any SMTP provider works; Gmail needs an
"App password", not your normal password):

| Variable | Example |
|---|---|
| `MAIL_SERVER` | `smtp.gmail.com` |
| `MAIL_PORT` | `587` (use `465` for SSL) |
| `MAIL_USERNAME` | `yourapp@gmail.com` |
| `MAIL_PASSWORD` | the app password |
| `MAIL_FROM` | optional, defaults to `MAIL_USERNAME` |

Without these, no email is sent. The page still shows the same confirmation (so it never reveals who is registered).

**2. Workers need an email on file.** Signup now has an optional email field, and workers can add one
under Edit profile. Existing workers have none until they add it.

**3. People with no email:** an admin opens `/admin/reset-link/worker/<id>` (or `/customer/<id>`) to get a
one-hour link to send privately, with a WhatsApp button. Add a link to your admin worker list:
`<a href="{{ url_for('admin_reset_link', role='worker', user_id=w.id) }}">Reset link</a>`

Notes: the reset needs no database change. Links die once used. Existing logged-in sessions stay logged in
after a reset (Flask sessions can't be revoked individually).

## Terms and Privacy pages (new)
`templates/terms.html` and `templates/privacy.html` replace your existing ones. Everything that is specific
to your business lives in **`templates/_legal.html`**; edit the values there once (business name, contact email,
address, refund window, retention period, your Data Protection Commission number if you have one, and the
"Verified badge" wording). Both pages update together. Sign-up forms now say the user agrees to both.
These are drafts written from how the app works. Have a Ghanaian lawyer review them before relying on them.

## SMS phone verification (new)
New and existing customers and workers confirm their phone with a 6-digit code texted to them. Codes work for
10 minutes, allow 5 wrong guesses, 60 seconds between texts, 5 texts per account per day. Nobody is logged in
until the code checks out.

**It stays OFF until you configure an SMS provider**, so deploying this can never lock anyone out.

**Run `schema_changes.sql` first** (section 0 adds a `phone_verified` column to `customer` and `worker`),
or the app will error. The `phone_otp` table is created automatically.

| Variable | Value |
|---|---|
| `SMS_PROVIDER` | `arkesel` (or `twilio`) |
| `ARKESEL_API_KEY` | from your Arkesel dashboard |
| `SMS_SENDER_ID` | a sender ID you have **registered** with Arkesel (max 11 characters, e.g. `GetService`) |
| `REQUIRE_PHONE_VERIFICATION` | optional; `0` switches the check off again without removing the code |

Twilio instead: `SMS_PROVIDER=twilio`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` (a number, or a
Messaging Service SID starting `MG`). For local testing use `SMS_PROVIDER=console` with debug on; the code is
printed in the server log instead of being sent.

**Test with your own number first.** The Arkesel request follows their published format, but I could not send a
real SMS. If texts do not arrive, the server log shows `SMS provider arkesel refused the message: HTTP <code> <reply>`.

Things to know:
- Existing users must verify at their next login. To skip that for people already on your platform, run the
  two optional `UPDATE ... phone_verified = TRUE` lines in `schema_changes.sql`.
- Each text costs money. Limits above cap abuse, and failed sends do not use up a person's daily allowance.
- Someone could register with another person's number and leave it unverified, blocking that person from
  signing up. If this becomes a problem, ask me to add a rule that releases unverified numbers after a few days.
- The per-IP limits are kept in server memory. With several server processes, use Flask-Limiter with Redis.

## Admin pages (new)
`templates/admin_login.html` and `templates/admin_dashboard.html` replace your existing ones.
- **Dashboard:** workers waiting for approval first (Approve / View / Delete, plus "Approve all"), then all
  workers, customers and admins, with a filter box. Each person has a "Password reset link" button.
  Super admins also get a form to create more admins. A banner links to Payouts when any need attention.
- **Admin navigation:** when an admin is logged in, the top bar and bottom tabs switch to Site / Admin /
  Payouts / Log out (they no longer show the public Log in / Join tabs). This is done in `layout.html`.
- **The `admin_payouts.html` page from the payouts update is linked from the dashboard.**
- Admin accounts must already exist. The first super admin has to be created in the database
  (set `is_admin` and `is_super_admin` true on a `user` row); after that, use the dashboard form.

## Automatic payouts to workers (new)
**How it works now:** customer pays (money is held in Paystack) -> job is done -> the **customer** taps
"Confirm job complete and pay worker" -> the worker's money is sent to their mobile money wallet straight away.
The worker's old "Mark job complete" button became "Job finished? Ask customer to confirm": it only
notifies the customer and never releases money.

**Run section 0b of `schema_changes.sql` first** (new columns on `worker` and `worker_payout`), or the app errors.

**Paystack dashboard (you must do these; the code cannot):**
1. Make sure **Transfers** are enabled on your account (contact Paystack if the Transfers page is missing).
2. **Turn off transfer OTP / "confirm transfers before sending".** With it on, every payout is held waiting for
   a code and the app marks it "Needs attention".
3. **Money must be in your *available* Paystack balance.** Paystack only transfers from available balance, not
   from payments still waiting to settle. Either keep collected funds in your Paystack balance (Paystack Ghana has
   a setting for how long collected funds stay in balance before auto-settling to your bank) or top up the balance
   (free for Ghana businesses). If the balance is short, the payout waits in a queue and retries automatically.
4. Your webhook URL stays `https://YOUR-DOMAIN/paystack/webhook`. It now also receives
   `transfer.success`, `transfer.failed` and `transfer.reversed`.

**Retries (needed if the balance is ever short):** set an environment variable `CRON_SECRET` to a long random
string, then have a scheduler call this every 10 minutes (Render Cron Job, or a free service such as cron-job.org):
`POST https://YOUR-DOMAIN/internal/process-payouts` with header `X-Cron-Secret: <your secret>`.
Without `CRON_SECRET` the endpoint does not exist. Queued payouts also go out the moment a worker saves their
payout account, and an admin can retry any payout at `/admin/payouts`.

**Workers must add a mobile money number** (dashboard > "Add your mobile money number"; MTN, Vodafone or
AirtelTigo). They re-enter their password to change it.

Costs and limits (from Paystack's Ghana pricing): about **GHS 1 per mobile money transfer**, paid from your
balance (you absorb it unless you change the code), and a **GHS 10 minimum** per transfer. Please confirm both
in your own dashboard.

Things to know:
- Until a customer confirms, the worker is not paid. A customer who never taps confirm leaves the worker unpaid.
  Consider an auto-release after a few days (ask me to add it).
- A payout moves through: waiting for customer, releasing, sending, paid out, or needs attention.
  Payouts waiting for funds retry for up to 7 days; real failures stop after 5 tries and appear at `/admin/payouts`.
- Jobs already marked complete under the old flow keep a stuck "pending" payout; see the optional SQL in section 0b.
- Terms and privacy pages were updated to describe this flow. Have them reviewed before relying on them.
