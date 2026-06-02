# Threat Model — Telemetry / Ranking API

Concise and honest. The leaderboard is an **honor-system** feature for a hobby,
open-source bot. The security goal is **mass-protection** of the board plus hard
**isolation** of the co-hosted `kilab` stack — not making a spoof-proof score.

## Assets

1. The leaderboard DB (usernames + cumulative counters + hashed IPs).
2. The `ADMIN_TOKEN` (ban/delete authority).
3. **The co-hosted `kilab` Docker stack** (the most valuable asset on the box).

## What an attacker CAN do (accepted / mitigated)

- **Spoof HWID and username.** The client is open source, so there is no real
  secret in it — a source editor can send any HWID/username. _Accepted._ The
  HWID is only a stable handle for mass bans/erasure, not authentication. This
  is stated plainly and not oversold.
- **Submit junk values within the caps.** Mitigated by strict pydantic
  validation (types, length caps, numeric maxima), per-IP **and** per-HWID rate
  limits (nginx **and** app-level), and an **implausible-jump** check that
  rejects a submit growing a counter far beyond the identity's last value.
- **Scrape the leaderboard.** Mitigated by a short in-process cache + per-IP
  rate limit; the board is public by design anyway.
- **Flood the endpoint.** Mitigated by defense-in-depth limits (nginx
  `limit_req` per-IP and per-HWID + app-level buckets) and fail2ban on the
  dedicated access log. No client secret means abuse defense is 100%
  server-side — hence both layers are required.
- **Forge `X-Forwarded-For` to dodge the app per-IP limit / poison `ip_hash`.**
  Mitigated: nginx appends the real peer to any client XFF, and the app trusts
  `X-Real-IP` (set by nginx) first, else the **right-most** XFF hop — never the
  attacker-controlled left-most entry. With a front proxy, `set_real_ip_from`
  makes `$remote_addr` the true edge IP. The real ceiling was always the nginx
  per-IP `limit_req` on the true TCP peer; this just keeps the app layer + the
  stored hash honest.
- **Grow the app rate-limit map without bound (rotating identities).**
  Mitigated: the in-process bucket map is swept globally (every Nth call and
  past a hard ceiling), evicting keys with no timestamp inside the window, so it
  cannot be used as a slow memory-exhaustion vector against the 256 MB
  container.

## What an attacker CANNOT do

- **Admin without the token.** `/admin/*` and the CLI require `ADMIN_TOKEN`,
  compared with `hmac.compare_digest` (constant-time). Unset token → admin is
  disabled (fail closed). The token is never in the client.
- **Pivot from a popped telemetry container to kilab.** Even with full RCE in
  this container there is **no path** to kilab because:
  - it runs on its **own** docker network (`m2fb_telemetry_net`), not kilab's;
  - it uses its **own** named volume (`m2fb_telemetry_data`), not a kilab volume;
  - it runs as a **non-root** user with a **read-only** rootfs (only `/data` and
    a tmpfs `/tmp` are writable);
  - it drops **ALL** Linux capabilities and sets `no-new-privileges`;
  - it is bound to **127.0.0.1** and exposed only through a dedicated nginx
    server-block — port 8081 is never public;
  - it shares **no secret** with kilab (separate `.env`, separate token/salt).
    The DEPLOY.md isolation checklist (`docker inspect` of network/volume/user/
    caps/ports) is the proof step before exposure.
- **Read raw client IPs.** Only a salted SHA-256 of the IP is stored
  (`IP_HASH_SALT`), so the DB holds no raw IP (GDPR).

## GDPR

- Telemetry is **OFF by default**; it sends only after the user explicitly opts
  in (client onboarding checkbox defaults off).
- The only personal datum is the self-chosen username; the HWID is a hash.
- Erasure is supported by HWID or username (`admin.delete` / CLI `delete`).
- Stored IPs are hashed, not raw.

## Residual risks (accepted)

- A determined attacker can still inflate a **single** identity's score within
  the per-submit caps and rate limits (e.g. slow, plausible growth). For an
  honor-system hobby board this is acceptable; bans/erasure handle the rest.
- HWID spoofing means a banned user can return under a new HWID/username. Again,
  mass-protection only — accepted and documented rather than overstated.

## Why kilab stays safe even if telemetry is fully compromised

The telemetry container is a sealed box: own network, own volume, non-root,
read-only FS, no caps, no shared secret, loopback-only. Compromising it yields
access to its own sqlite DB and nothing else on the host — there is no network
route, no shared mount, and no credential that reaches kilab.
