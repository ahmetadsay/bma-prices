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
- the product has not had an alert in the last REPEAT_DAYS days, unless the
  price has fallen by the same margin again since that alert.

One issue per brand: every model of that brand at a new low goes into the
same email, the reviewed model first. (On 25 October 2026 the first Sleep
Firm alert named only the Luxe, the biggest fall in dollars, while the Sleep
Firm we review had dropped to its lowest too.)

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
        last = sent.get(key)
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


def line_for(d):
    member = " (member price: free email sign-up at the store)" if d["member"] else ""
    return (f"- {d['name']} (Queen): ${d['price']:,}{member}, the lowest of {d['readings']} "
            f"readings since {d['first']}. Lowest before today: ${d['low']:,}. "
            f"List price: ${d['rrp']:,}.")


def issue_for(group, models):
    """models: every drop of one brand, the reviewed model first."""
    lead = models[0]
    review = next((m["review"] for m in models if m["review"]), "")
    review = f"{SITE}/{review}/" if review else f"{SITE}/best-mattress-deals-australia/"
    if len(models) == 1:
        subject = f"{lead['name']} is at its lowest price we've recorded: ${lead['price']:,}"
        intro = "Today our price tracker read it at the lowest price we have recorded:"
    else:
        subject = f"{group}: {len(models)} mattresses at their lowest prices we've recorded"
        intro = (f"Today our price tracker read {len(models)} {group} mattresses at the lowest "
                 f"prices we have recorded:")
    email = (
        f"Subject: {subject}\n\n"
        f"Hi,\n\n"
        f"You asked us to tell you when {group} drops its price. {intro}\n\n"
        + "\n".join(line_for(m) for m in models) + "\n\n"
        f"Prices can change quickly, so check the store's own page before you buy.\n\n"
        f"Live prices for every brand we track: {SITE}/best-mattress-deals-australia/\n"
        f"Our review: {review}\n\n"
        f"Best Mattress Australia\n"
    )
    names = ", ".join(f"{m['name']} ${m['price']:,}" for m in models)
    title = f"Price alert: {names} (lowest recorded)"
    keys = " · ".join(f"`{m['key']}` ${m['price']:,} (önceki en düşük ${m['low']:,})" for m in models)
    body = (
        f"**Ne yapılacak:** MailerLite → Campaigns → Create campaign. Alıcılar: "
        f"**{group}** ve **Any brand** grupları. Aşağıdaki metni yapıştır, gönder, "
        f"sonra bu issue'yu kapat.\n\n"
        f"Ürünler: {keys}\n\n"
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
    if not dry and today != dt.date.today().isoformat():
        # fetch_prices.py wrote nothing today (it crashed), so there is no new
        # reading to judge, only yesterday's again.
        print(f"No readings dated today; newest is {today}. No alerts.")
        return

    drops = find_drops(prices, history, sent, today)
    # One email per brand: every model at a new low, the one we review first.
    brands = {}
    for d in drops:
        brands.setdefault(d["group"], []).append(d)
    print(f"{len(brands)} price alert(s) for {today}")
    for group, models in brands.items():
        models.sort(key=lambda m: (not m["review"], m["price"]))
        title, body = issue_for(group, models)
        if dry:
            print(f"\n--- {title}\n{body}")
            continue
        url = open_issue(title, body)
        print(f"  {title} -> {url}")
        for m in models:
            sent[m["key"]] = {"date": today, "price": m["price"], "group": group}
    if not dry:
        sent_path.write_text(json.dumps(sent, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
