"""Open a GitHub issue when a tracked mattress hits its lowest price yet.

Runs after fetch_prices.py. The issue is the trigger for a price-drop email to
that brand's MailerLite group (and "Any brand"); GitHub emails the repository
owner when it opens. Each issue carries a ready-to-paste email.

A drop counts only when all of these hold, the same for every brand, partner
or not:
- today's reading is fresh (read today) and the product has at least
  MIN_READINGS earlier readings, so a new product cannot "drop" on day two;
- today's price is below every earlier reading by at least MIN_DROP_AUD or
  MIN_DROP_PCT of that low, whichever is larger, so $1 wobbles stay quiet;
- the brand has not had an alert in the last REPEAT_DAYS days, unless the
  price has fallen by the same margin again since that alert.

Run with --dry-run to print the issues instead of opening them.
"""

import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
MIN_READINGS = 7
MIN_DROP_AUD = 20
MIN_DROP_PCT = 0.02
REPEAT_DAYS = 7
SITE = "https://bestmattressaustralia.com.au"

# Mattresses only, keyed to the MailerLite interest group of their brand.
GROUPS = {
    "sleep-republic": "Sleep Republic", "sleep-republic-luxe": "Sleep Republic",
    "sleep-republic-es": "Sleep Republic", "yinahla": "Yinahla",
    "sleep-firm": "Sleep Firm", "sleep-firm-ultra": "Sleep Firm", "sleep-firm-luxe": "Sleep Firm",
    "luxara": "Luxara", "luxara-classic": "Luxara", "peace-lily": "Peace Lily",
    "koala": "Koala", "koala-plus": "Koala", "koala-luxe": "Koala",
    "emma": "Emma", "emma-luxe": "Emma",
    "ecosa": "Ecosa", "ecosa-truefirm": "Ecosa", "ecosa-pure": "Ecosa",
    "origin": "Origin", "origin-hybrid-plus": "Origin", "origin-hybrid-pro": "Origin",
    "onebed": "OneBed", "sleeping-duck": "Sleeping Duck", "ergoflex": "Ergoflex",
}


def price_of(reading):
    rrp, sale = reading[0], reading[1]
    return sale or rrp


def margin(low):
    return max(MIN_DROP_AUD, MIN_DROP_PCT * low)


def find_drops(prices, history, sent, today):
    drops = []
    for key, group in GROUPS.items():
        now = prices.get(key)
        past = history.get(key, {})
        if not now or now.get("read") != today:
            continue
        current = now["sale"] or now["rrp"]
        earlier = {d: r for d, r in past.items() if d < today}
        if len(earlier) < MIN_READINGS:
            continue
        low = min(price_of(r) for r in earlier.values())
        if current > low - margin(low):
            continue
        last = sent.get(group)
        if last:
            days = (dt.date.fromisoformat(today) - dt.date.fromisoformat(last["date"])).days
            if days < REPEAT_DAYS and current > last["price"] - margin(last["price"]):
                continue
        drops.append({
            "key": key, "group": group, "name": now["name"], "price": current,
            "rrp": now["rrp"], "member": bool(now.get("member")), "low": low,
            "first": min(earlier), "readings": len(earlier) + 1,
            "review": now.get("review") or "",
        })
    return drops


def issue_for(d):
    member = " (member price: free email sign-up at the store)" if d["member"] else ""
    review = f"{SITE}/{d['review']}/" if d["review"] else f"{SITE}/best-mattress-deals-australia/"
    subject = f"{d['name']} is at its lowest price we've recorded: ${d['price']:,}"
    email = (
        f"Subject: {subject}\n\n"
        f"Hi,\n\n"
        f"You asked us to tell you when {d['group']} drops its price. Today our price tracker read "
        f"the {d['name']} (Queen) at ${d['price']:,}{member}, the lowest of {d['readings']} readings "
        f"since {d['first']}. The lowest before today was ${d['low']:,}; the brand's list price is "
        f"${d['rrp']:,}.\n\n"
        f"Prices can change quickly, so check the store's own page before you buy.\n\n"
        f"Live prices for every brand we track: {SITE}/best-mattress-deals-australia/\n"
        f"Our review: {review}\n\n"
        f"Best Mattress Australia\n"
    )
    title = f"Price alert: {d['name']} ${d['price']:,} (lowest recorded, was ${d['low']:,})"
    body = (
        f"**Ne yapılacak:** MailerLite → Campaigns → Create campaign. Alıcılar: "
        f"**{d['group']}** ve **Any brand** grupları. Aşağıdaki metni yapıştır, gönder, "
        f"sonra bu issue'yu kapat.\n\n"
        f"Ürün anahtarı: `{d['key']}` · bugün ${d['price']:,} · önceki en düşük ${d['low']:,} · "
        f"liste ${d['rrp']:,}{' · üye fiyatı' if d['member'] else ''}\n\n"
        f"```text\n{email}```\n"
    )
    return title, body


def open_issue(title, body):
    repo = os.environ["GITHUB_REPOSITORY"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": body, "labels": ["price-alert"]}).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["html_url"]


def main():
    dry = "--dry-run" in sys.argv
    prices = json.loads((HERE / "prices.json").read_text())["brands"]
    history = json.loads((HERE / "history.json").read_text())["brands"]
    sent_path = HERE / "alerts.json"
    sent = json.loads(sent_path.read_text()) if sent_path.exists() else {}
    today = max((p.get("read") or "") for p in prices.values())

    drops = find_drops(prices, history, sent, today)
    # One email per brand per day: if two models of a brand drop, keep the bigger fall.
    best = {}
    for d in drops:
        if d["group"] not in best or (d["low"] - d["price"]) > (best[d["group"]]["low"] - best[d["group"]]["price"]):
            best[d["group"]] = d
    drops = list(best.values())
    print(f"{len(drops)} price alert(s) for {today}")
    for d in drops:
        title, body = issue_for(d)
        if dry:
            print(f"\n--- {title}\n{body}")
            continue
        url = open_issue(title, body)
        print(f"  {title} -> {url}")
        sent[d["group"]] = {"date": today, "price": d["price"], "key": d["key"]}
    if not dry:
        sent_path.write_text(json.dumps(sent, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
