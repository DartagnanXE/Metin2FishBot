# Deploy + Hardening Runbook (RUN THESE YOURSELF)

No command in this repo runs against your server. Every step below is something
**you** run on the box. The constraint that matters: the host co-hosts the
`kilab` Docker stack — this service must stay isolated and least-privilege.

Assumptions (from the partial audit): Ubuntu 24.04, public ports 2222/80/443
only, `nginx:alpine` reverse-proxy on 80/443, fail2ban + unattended-upgrades
active, sshd hardened, `openclaw` in the docker group. The telemetry service is
internal (127.0.0.1) and reached only via a new nginx server-block on a new
subdomain.

---

## 0. Prerequisites

- A DNS A/AAAA record `ranking.example.tld` → the server IP.
- Docker + docker compose v2 available to `openclaw`.

## 1. Generate secrets (RUN YOURSELF)

```bash
cd /path/to/Metin2FishBot/server
cp .env.example .env
# Strong random values:
printf 'ADMIN_TOKEN=%s\n'  "$(openssl rand -hex 32)" >> .env
printf 'IP_HASH_SALT=%s\n' "$(openssl rand -hex 32)" >> .env
# Then EDIT .env to remove the placeholder ADMIN_TOKEN/IP_HASH_SALT lines that
# came from .env.example, keeping only the generated ones.
chmod 600 .env
```

The `ADMIN_TOKEN` never goes into the client. The client is open source.

## 2. Bring the container up on its OWN network + volume (RUN YOURSELF)

```bash
cd /path/to/Metin2FishBot/server
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8081/health      # -> ok
```

## 3. Verify isolation (RUN YOURSELF — this is the load-bearing check)

```bash
# (a) Only on its OWN network (expect m2fb_telemetry_net; NOT any kilab net):
docker inspect m2fb-telemetry --format '{{json .NetworkSettings.Networks}}'

# (b) Non-root user:
docker inspect m2fb-telemetry --format 'User={{.Config.User}}'   # User=app

# (c) Read-only rootfs:
docker inspect m2fb-telemetry --format 'ReadonlyRootfs={{.HostConfig.ReadonlyRootfs}}'  # true

# (d) Caps dropped + no-new-privileges:
docker inspect m2fb-telemetry --format 'CapDrop={{.HostConfig.CapDrop}}'                 # [ALL]
docker inspect m2fb-telemetry --format 'SecurityOpt={{.HostConfig.SecurityOpt}}'         # no-new-privileges:true

# (e) Volume is the dedicated one, NOT a kilab volume:
docker inspect m2fb-telemetry --format '{{json .Mounts}}'   # source m2fb_telemetry_data -> /data

# (f) Published only on loopback (expect 127.0.0.1:8081, NOT 0.0.0.0):
docker inspect m2fb-telemetry --format '{{json .NetworkSettings.Ports}}'
ss -ltnp | grep 8081
```

If any of (a)–(f) is wrong, STOP and fix the compose file before exposing it.
Confirm kilab is untouched:

```bash
docker network ls          # kilab networks unchanged; m2fb_telemetry_net is new
docker volume ls           # kilab volumes unchanged; m2fb_telemetry_data is new
docker inspect m2fb-telemetry --format '{{json .NetworkSettings.Networks}}' | grep -i kilab && echo "FAIL: on kilab net" || echo "OK: not on kilab net"
```

## 4. Add the nginx server-block + TLS (RUN YOURSELF)

```bash
# Copy the NEW server-block (do NOT edit the kilab proxy config):
sudo cp /path/to/Metin2FishBot/server/nginx/telemetry.conf \
        /etc/nginx/sites-available/ranking.example.tld
sudo ln -s /etc/nginx/sites-available/ranking.example.tld \
           /etc/nginx/sites-enabled/ranking.example.tld

# http{}-context directives at the top of telemetry.conf: the two limit_req_zone
# lines AND the `map $http_x_hwid $hwid_limit_key {...}` block must live in an
# http{} context. If your distro's nginx.conf already opens http{} (Debian/Ubuntu
# includes sites-enabled from inside it), they are fine where they are; if you
# instead include this file at the top level, move those lines into nginx.conf's
# http{} and delete them here.
#
# ANTI-SPOOF (recommended): if any proxy sits IN FRONT of this nginx (e.g. a CDN
# or load balancer), uncomment + set the `set_real_ip_from <that proxy subnet>;`
# + `real_ip_header X-Forwarded-For;` + `real_ip_recursive on;` lines in
# telemetry.conf so $remote_addr / X-Real-IP is the TRUE client IP (the app
# trusts X-Real-IP and the right-most XFF hop, never the forgeable left-most
# entry). If this nginx is itself the public TLS terminator, the TCP peer is
# already the real IP and you can leave those lines commented.

# Issue TLS for the subdomain (webroot or nginx plugin):
sudo certbot --nginx -d ranking.example.tld

sudo nginx -t && sudo systemctl reload nginx
```

## 5. Smoke-test through the public edge (RUN YOURSELF)

```bash
# Leaderboard (empty at first):
curl -fsS https://ranking.example.tld/leaderboard

# A submit (uses the wire schema; the app re-validates everything):
curl -fsS -X POST https://ranking.example.tld/submit \
  -H 'Content-Type: application/json' -H 'X-HWID: testhwid123' \
  -d '{"username":"smoketest","hwid":"testhwid123","fishing_catches":1,
       "puzzles_solved":0,"fishing_runtime_s":1.0,"puzzler_runtime_s":0.0,
       "app_version":"1.0.5","ts":1735000000}'

# Rate-limit check (fire >10/min; expect HTTP 429 to appear):
for i in $(seq 1 15); do \
  curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  https://ranking.example.tld/submit -H 'Content-Type: application/json' \
  -H 'X-HWID: testhwid123' \
  -d '{"username":"smoketest","hwid":"testhwid123","fishing_catches":1,
       "puzzles_solved":0,"fishing_runtime_s":1.0,"puzzler_runtime_s":0.0,
       "app_version":"1.0.5","ts":1735000000}'; done
```

## 6. Firewall + fail2ban (RUN YOURSELF)

- UFW stays **2222/80/443 only**. The telemetry container is internal
  (127.0.0.1) and reached solely via nginx — do **not** open 8081.

  ```bash
  sudo ufw status            # expect 2222, 80, 443; nothing for 8081
  ```

- fail2ban jail for the dedicated access log:

  ```ini
  # /etc/fail2ban/jail.d/ranking.conf
  [ranking-429]
  enabled  = true
  port     = http,https
  filter   = ranking-429
  logpath  = /var/log/nginx/ranking_access.log
  maxretry = 30
  findtime = 60
  bantime  = 3600
  ```

  ```ini
  # /etc/fail2ban/filter.d/ranking-429.conf
  [Definition]
  failregex = ^<HOST> .* "(GET|POST) /(submit|leaderboard).*" 429
  ```

  ```bash
  sudo systemctl restart fail2ban && sudo fail2ban-client status ranking-429
  ```

## 7. Admin (ban / unban / delete) — RUN YOURSELF

Inside the container (token from the env, never the client):

```bash
docker compose exec telemetry python -m server.cli list-bans
docker compose exec telemetry python -m server.cli ban   --hwid abc123 --reason cheating
docker compose exec telemetry python -m server.cli unban --hwid abc123
docker compose exec telemetry python -m server.cli delete --username Bob   # GDPR erasure
```

Or via HTTP with the token header:

```bash
curl -fsS -X POST https://ranking.example.tld/admin/ban \
  -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"kind":"hwid","value":"abc123","reason":"cheating"}'
```

## 8. Backups / maintenance (RUN YOURSELF)

```bash
# The DB lives in the named volume m2fb_telemetry_data (/data/telemetry.db).
docker run --rm -v m2fb_telemetry_data:/data -v "$PWD":/backup busybox \
  cp /data/telemetry.db /backup/telemetry-$(date +%F).db
```

## Postgres swap (optional, later)

For higher write concurrency, run a dedicated postgres container on the **same
isolated** `m2fb_telemetry_net` (still NOT the kilab network), point `DB_PATH`
→ a `DATABASE_URL`, and port `db.py` to `psycopg`/`asyncpg` using the same
parameterised queries (`migrations/0001_init.sql` has the postgres column-type
notes). Keep the isolation guarantees from step 3.
