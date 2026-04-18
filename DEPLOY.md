# Deploying bt-ml to Railway

~15 minutes end-to-end. The only thing Ayan does by hand is create the empty GitHub repo and click two buttons on railway.com.

## Prereqs
- Google Cloud project with **Directions API** + **Maps SDK for Android** + **Places API** enabled (already done).
- The Maps API key (lives in `local.properties` + env var here).

## One-time setup

### 1. Create an empty GitHub repo for bt-ml
Go to https://github.com/new → name it e.g. `bt-ml` → **create it empty** (no README, no .gitignore). Copy the SSH URL (`git@github.com:Ayansk11/bt-ml.git`).

### 2. Push bt-ml
```bash
cd /Users/ayansk11/Desktop/bt-ml
git remote add origin git@github.com:Ayansk11/bt-ml.git
git push -u origin main
```

### 3. Deploy on Railway
1. https://railway.com/new → **Deploy from GitHub repo** → pick `bt-ml`.
2. Railway auto-detects `railway.json` and the `service/Dockerfile`.
3. In the service's **Variables** tab add:
   ```
   GOOGLE_MAPS_API_KEY = AIzaSy...
   ```
   (Optionally: `LOG_LEVEL=INFO`.)
4. In the service's **Settings → Networking** tab, click **Generate Domain**. Railway gives you a URL like `https://bt-ml-production-xxxx.up.railway.app/`.
5. Hit `https://<your-railway-url>/healthz` — should return `{"status":"ok","model_source":"a1_lightgbm",...}` in a couple seconds.

### 4. Point the Android app at the deployed backend
On the `ayan/integrate-naishal` branch, open `local.properties` and set:
```
BACKEND_BASE_URL=https://<your-railway-url>/
```
Then rebuild. Chirag's phone now hits the deployed `/plan`, `/predictions`, `/stats`, `/detections/bunching`, `/nlq`, etc. over the public internet.

## Verifying the deploy

```bash
BASE=https://<your-railway-url>

curl -s "$BASE/healthz" | python3 -m json.tool
curl -s "$BASE/stats"   | python3 -m json.tool
curl -s "$BASE/plan?origin_lat=39.1674&origin_lng=-86.5240&dest_lat=39.2050&dest_lng=-86.5500" | python3 -m json.tool | head -40
```

## Cost / limits

- Railway free tier: **$5 credit/month + 500 hr execution**. This service sleeps fine when idle; demo traffic is well within the free tier.
- Google Directions: **$5 free credit/month + $5/1000 requests thereafter**. Our 60-second TTL cache + lat/lng rounding makes demo traffic effectively free.

## Rotation

The Maps key is currently a hackathon-grade shared secret. After submission:
1. Revoke at https://console.cloud.google.com/apis/credentials.
2. Generate a new key with Application restrictions → HTTP referrers (for Android the Places SDK needs the key unrestricted; for backend use you can restrict to Railway's egress IPs).
3. Update `GOOGLE_MAPS_API_KEY` in Railway Variables + `MAPS_API_KEY` in Android `local.properties`.

## Failure modes and where to look

| Symptom | Probable cause | Fix |
|---|---|---|
| `/plan` returns `status: "UPSTREAM_ERROR"` | Google rate-limit or billing issue | Check Google Cloud → APIs & Services → Dashboard → Directions API traffic graph |
| `/plan` returns `status: "REQUEST_DENIED"` | Directions API disabled on the key's project | APIs & Services → Library → Directions API → Enable |
| `/healthz` returns `a1_loaded: false` | `models/a1_delay_correction.joblib` wasn't copied into the image | Confirm `COPY models ./models` in `service/Dockerfile`; check Railway build logs |
| Slow (>1 s) cold `/plan` latency | Healthy — Google upstream is ~300-500ms cold; warm cache hits are <20ms | Nothing to fix; monitor `meta.cache_hit` in responses |
| Container restarts every few seconds | Check Railway logs for startup exception; most likely missing GTFS static files | Ensure `data/gtfs_static/*.txt` is committed to the repo |
