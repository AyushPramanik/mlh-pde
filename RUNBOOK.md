# Incident Runbook — mlh-pe-hackathon

> **Purpose:** Step-by-step instructions for the on-call engineer who woke up
> at 3 AM to a pager alert. Assumes minimal cognitive function.
> Follow each section in order; stop when the incident is resolved.

---

## Quick Reference

| URL | What it is |
|-----|-----------|
| `http://localhost:5000/dashboard` | Standalone live dashboard |
| `http://localhost:3000` | Grafana (admin / admin) |
| `http://localhost:9090` | Prometheus |
| `http://localhost:5000/health` | Is the app alive? |
| `http://localhost:5000/metrics` | JSON metrics snapshot |
| `http://localhost:5000/alert-status` | Which alerts are firing |
| `http://localhost:5000/logs?limit=50` | Last 50 log lines (JSON) |
| `http://localhost:5000/prometheus` | Prometheus scrape endpoint |

---

## Alert: "Service Down — DB Unreachable"

**What triggered it:** The background monitor could not open a TCP connection
to PostgreSQL for a full check cycle (≥ 30 s).

### Step 1 — Confirm the alert is real

```bash
curl http://localhost:5000/health
# Expected: {"status":"ok","hostname":"..."}
# If this fails: the app process itself is also dead → go to Step 3.
```

```bash
curl http://localhost:5000/alert-status
# Look for: "service_down": {"firing": true}
```

### Step 2 — Check the database container

```bash
docker compose ps db
# Status should be "Up (healthy)". If "Exit" or "unhealthy" → Step 2b.
```

**2a — DB is running but unreachable**

```bash
docker compose logs db --tail 30
# Look for: "database system is ready to accept connections"
# If absent: DB is still starting → wait 30 s and retry Step 1.
```

**2b — DB container is down**

```bash
docker compose up -d db
# Wait ~10 s for healthcheck to pass, then verify:
curl http://localhost:5000/health
```

**2c — DB disk full**

```bash
docker system df          # check volume usage
docker compose exec db psql -U postgres -c "SELECT pg_size_pretty(pg_database_size('hackathon_db'));"
```

### Step 3 — Restart the app (last resort)

```bash
docker compose restart web
# Then watch:
docker compose logs web -f --tail 20
# Look for: {"message":"db_connected","attempt":1,...}
```

### Step 4 — Confirm resolution

```bash
curl http://localhost:5000/health        # must return 200
curl http://localhost:5000/alert-status  # "service_down": {"firing": false}
```

Alert auto-resolves after the next check cycle (≤ 30 s).
A "[RESOLVED] Service Back Up" email will be sent automatically.

---

## Alert: "High Error Rate"

**What triggered it:** More than 10 % of HTTP requests returned a 5xx status
code in the past 2 minutes (requires ≥ 5 requests in window).

### Step 1 — Measure the blast radius

```bash
curl "http://localhost:5000/alert-status"
# Read: current_metrics.error_rate and current_metrics.total
```

Open Grafana → **"Error Rate % — Threshold: 10%"** panel.
- If the spike is short (<2 min) and self-corrected: probable transient.
- If sustained and climbing: proceed to Step 2.

### Step 2 — Find the failing requests

```bash
curl "http://localhost:5000/logs?limit=100" | python3 -m json.tool | grep '"status": 5'
# or pipe through jq:
curl "http://localhost:5000/logs?limit=100" | jq '.[] | select(.status >= 500)'
```

Look at `path`, `method`, and `message` fields.  Patterns to spot:
- All failures on one endpoint → likely a code or data bug on that route.
- All failures across all endpoints → likely DB or infrastructure issue.
- Failures spiked with a recent deploy → rollback.

### Step 3 — Drill down

**All errors are DB-related (peewee.OperationalError):**
→ Follow **"Service Down"** runbook above.

**One endpoint is failing (e.g. POST /urls):**

```bash
# Check recent 500 log entries for that path
curl "http://localhost:5000/logs?limit=200" \
  | jq '[.[] | select(.status == 500 and .path == "/urls")][-10:]'
```

Check the `exception` field for stack traces.

**Errors started after a deploy:**

```bash
git log --oneline -5           # what changed?
docker compose logs web --tail 50   # startup errors?
```

To rollback:
```bash
git checkout <previous-sha>
docker compose up -d --build web
```

### Step 4 — Reduce load while investigating

If the service is degraded but alive, respond with 503 to shedload:
```bash
# Temporarily return maintenance response via nginx (if using scaling stack)
# Edit scaling/nginx/nginx.conf — add "return 503 Maintenance;" to location /
docker compose -f scaling/docker-compose.yml restart nginx
```

### Step 5 — Confirm resolution

Error rate should drop below 10 % within 2 minutes.

```bash
curl http://localhost:5000/alert-status
# "high_error_rate": {"firing": false}
```

---

## Sherlock Mode: Diagnosing a Fake Incident

Use this to practice before a real incident.

### Fake Incident A — "High CPU for 5 minutes"

**Grafana clues:**
1. Open **CPU % over time** panel → sustained spike.
2. Open **Request Rate by Status Code** → is RPS also elevated?
   - RPS high + CPU high → traffic surge (normal; watch error rate).
   - RPS flat + CPU high → runaway background task or memory leak.

**Log investigation:**
```bash
curl "http://localhost:5000/logs?limit=50" | jq '.[] | select(.duration_ms > 500)'
# Slow requests point to CPU-bound handler or slow DB query.
```

**Resolution hypothesis:** Check for a slow Peewee query using `EXPLAIN ANALYZE`
inside the container:
```bash
docker compose exec db psql -U postgres -d hackathon_db \
  -c "EXPLAIN ANALYZE SELECT * FROM url WHERE is_active = true;"
```

### Fake Incident B — "P95 Latency jumped to 2 s"

**Grafana clues:**
1. Open **Latency Percentiles** panel → P95 spiked, P50 unchanged → tail-latency issue.
2. Open **Top Endpoints — Request Rate** → which endpoint is responsible?

**Log investigation:**
```bash
curl "http://localhost:5000/logs?limit=200" \
  | jq '[.[] | select(.duration_ms > 1000)] | group_by(.path) | map({path: .[0].path, count: length})'
```

**Resolution hypothesis:** `GET /urls` with large result set, missing `LIMIT`.
Fix: add `?per_page=50` pagination or add an index on `is_active`.

### Fake Incident C — "Error rate 80%"

**Fire drill command:**
```bash
uv run python fire_drill.py --high-error-rate
```

**Grafana clues:**
1. **Error Rate %** panel → time of spike aligns with a deploy or config change.
2. **Request Rate by Status Code** → 5xx bars dominate.
3. **Top Endpoints** → one endpoint drives all errors?

**Log investigation:**
```bash
curl "http://localhost:5000/logs?limit=50" | jq '.[] | select(.level == "ERROR")'
# Read the "exception" field for the Python traceback.
```

---

## Escalation path

| Severity | Who | When |
|----------|-----|------|
| P1 — Service completely down | Wake oncall immediately | >2 min downtime |
| P2 — Error rate > 10 % for > 5 min | Slack `#incidents` | Sustained degradation |
| P3 — Latency > 1 s P95 | Jira ticket | Non-urgent, fix next business day |

---

## Useful one-liners

```bash
# Live log stream (requires running app)
docker compose logs web -f | python3 -c "import sys,json; [print(json.dumps(json.loads(l),indent=2)) for l in sys.stdin if l.strip()]"

# Count errors by path in the last 100 log lines
curl -s localhost:5000/logs?limit=100 | jq 'group_by(.path) | map({path:.[0].path, errors: map(select(.status>=500)) | length}) | sort_by(-.errors)[:5]'

# Current Prometheus metrics (human readable)
curl -s localhost:5000/prometheus | grep -v "^#" | sort
```
