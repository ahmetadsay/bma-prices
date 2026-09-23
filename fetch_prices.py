#!/usr/bin/env python3
"""
Reads the Queen price a shopper actually sees for each mattress in
products.json, and writes prices.json for BestMattressAustralia.com.au.

Two readings per product:

  list price  from the store's Shopify /products/<handle>.js — reliable, but it
              is the list price, and for brands that discount client-side it
              never shows the sale.
  shelf price from the rendered product page in a real browser, after the
              store's own scripts have run — see extract.js.

`sale` is written only when the shelf price is lower than the list price.

If a page cannot be read, the last good reading is kept for up to seven days.
After that the product falls back to its list price with no sale, because an
old sale price may have ended and the safe mistake is to quote too high, never
too low.

    python fetch_prices.py               full run (needs Playwright + Chromium)
    python fetch_prices.py --no-browser  list prices only, for a quick local check
"""

import datetime as dt
import json
import pathlib
import sys
import urllib.request
from urllib.parse import urlparse

HERE = pathlib.Path(__file__).parent
OUT = HERE / "prices.json"
STALE_DAYS = 7
MAX_FAILURES = 3          # more than this and the run goes red, so someone looks
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def list_price(product):
    req = urllib.request.Request(product["url"] + ".js", headers={"User-Agent": UA})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read())
    for v in data["variants"]:
        if v["id"] == product["variant"]:
            price = v["price"] / 100
            compare = (v.get("compare_at_price") or 0) / 100
            return max(price, compare), price
    raise ValueError(f"variant {product['variant']} not found")


def main():
    use_browser = "--no-browser" not in sys.argv
    products = json.loads((HERE / "products.json").read_text())
    previous = json.loads(OUT.read_text())["brands"] if OUT.exists() else {}
    today = dt.date.today()
    extract = (HERE / "extract.js").read_text()

    page = browser = pw = None
    if use_browser:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
        context = browser.new_context(user_agent=UA, locale="en-AU", timezone_id="Australia/Sydney")
        # GitHub's runners are in the US, and Shopify serves a US visitor a
        # different market with different promotions. These are the cookies an
        # Australian visitor carries; they select the AU market.
        cookies = []
        for host in {urlparse(p["url"]).hostname for p in products}:
            domain = "." + (host[4:] if host.startswith("www.") else host)
            for name, value in (("localization", "AU"), ("cart_currency", "AUD")):
                cookies.append({"name": name, "value": value, "domain": domain, "path": "/"})
        context.add_cookies(cookies)
        page = context.new_page()

    brands, failures = {}, []
    for p in products:
        key = p["key"]
        try:
            rrp, server_price = list_price(p)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{key}: list price — {e}")
            if key in previous:
                brands[key] = previous[key]
            continue

        shelf, method = None, "server"
        if page:
            try:
                page.goto(f"{p['url']}?variant={p['variant']}", wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(4000)   # the stores' discount scripts run after load
                result = page.evaluate(extract, rrp)
                country = result.get("country")
                if country and country != "AU":
                    # Read in the wrong market: that is some other country's price.
                    failures.append(f"{key}: served market {country}, not AU")
                else:
                    shelf = result["price"]
                    method = "browser" if shelf else "server"
            except Exception as e:  # noqa: BLE001
                failures.append(f"{key}: page — {e}")

        entry = {
            "name": p["name"], "size": p["size"], "review": p["review"],
            "source": p["url"], "rrp": round(rrp), "sale": None,
            "method": method, "read": today.isoformat(),
        }

        if shelf is not None:
            if shelf < rrp:
                entry["sale"] = round(shelf)
        else:
            # No shelf reading. Prefer a recent browser reading of the same list
            # price; failing that, the store's own compare_at sale, which is a
            # real reading too — it just cannot see client-side discounts.
            old = previous.get(key)
            fresh = (
                use_browser and old and old.get("method") == "browser"
                and old.get("rrp") == round(rrp)
                and (today - dt.date.fromisoformat(old.get("read", "1970-01-01"))).days <= STALE_DAYS
            )
            if fresh:
                entry.update(sale=old.get("sale"), method="carried", read=old["read"])
            elif server_price < rrp:
                entry["sale"] = round(server_price)

        brands[key] = entry
        shown = f"${entry['sale']:,} (list ${entry['rrp']:,})" if entry["sale"] else f"${entry['rrp']:,}"
        print(f"  {key:28} {shown:26} {entry['method']}")

    if browser:
        browser.close()
        pw.stop()

    OUT.write_text(json.dumps({
        "_readme": "Written by fetch_prices.py every few days. Do not hand-edit. "
                   "`sale` is the price a shopper saw on the rendered product page, "
                   "present only when it was below the list price `rrp`.",
        "_checked": today.isoformat(),
        "_generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "brands": brands,
    }, indent=2) + "\n")

    print(f"\n{len(brands)} written, {len(failures)} failed")
    for f in failures:
        print("  FAILED", f)
    if len(failures) > MAX_FAILURES:
        sys.exit(1)


if __name__ == "__main__":
    main()
