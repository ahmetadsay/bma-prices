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

Stores that are not on Shopify (Emma, Ecosa, Origin, Sleeping Duck, Ergoflex,
added 2026-10-05) carry a "reader" in products.json instead of a variant id.
Their Queen price comes straight from data the page itself ships — JSON-LD,
WooCommerce's variation list, Next.js page data or Ergoflex's basket data —
see page_price(). No browser is needed for them; method is "page".

If a page cannot be read, the last good reading is kept for up to seven days.
After that the product falls back to its list price with no sale, because an
old sale price may have ended and the safe mistake is to quote too high, never
too low.

    python fetch_prices.py               full run (needs Playwright + Chromium)
    python fetch_prices.py --no-browser  list prices only, for a quick local check
"""

import datetime as dt
import html as htmllib
import json
import pathlib
import re
import sys
import urllib.request
from urllib.parse import urlparse

HERE = pathlib.Path(__file__).parent
OUT = HERE / "prices.json"
HISTORY = HERE / "history.json"
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


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-AU"})
    return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")


def _ld_products(html):
    """Every schema.org Product in the page's JSON-LD, ProductGroup variants included."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("@type") == "Product":
                found.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            walk(json.loads(block))
        except ValueError:
            continue
    return found


def page_price(p):
    """(rrp, sale) for a store that is not on Shopify, read from data the page
    itself carries, so no browser is needed. Each reader names the one place in
    that store's HTML where the Queen price lives. sale is None when no discount
    shows. "no_was": true records the selling price only, and never the store's
    own "was" figure (see Emma in products.json)."""
    reader = p["reader"]
    rrp = sale = None
    # wcstore reads JSON, not the page: WooCommerce's public Store API for one
    # variation. Origin's product page came back from GitHub's US runner without
    # its variation list on 2026-10-06; the API answers the same either way.
    html = "" if reader == "wcstore" else fetch_html(p["url"])

    if reader == "wcstore":
        api = "{0.scheme}://{0.netloc}/wp-json/wc/store/v1/products/{1}".format(urlparse(p["url"]), p["variant"])
        prices = json.loads(fetch_html(api))["prices"]
        unit = 10 ** int(prices.get("currency_minor_unit", 2))
        price, regular = int(prices["price"]) / unit, int(prices["regular_price"]) / unit
        rrp, sale = (regular, price) if regular > price else (price, None)

    elif reader == "jsonld":
        # A Product (or ProductGroup variant) whose name matches, e.g. "| Queen".
        for prod in _ld_products(html):
            if re.search(p["match"], prod.get("name", "")):
                offer = prod.get("offers") or {}
                offer = offer[0] if isinstance(offer, list) else offer
                price = float(offer["price"])
                was = None
                spec = offer.get("priceSpecification") or []
                for s in spec if isinstance(spec, list) else [spec]:
                    if "Strikethrough" in str(s.get("priceType", "")):
                        was = float(s["price"])
                rrp, sale = (was, price) if was and was > price else (price, None)
                break

    elif reader == "woocommerce":
        # WooCommerce's variation list: display_price is what the shopper pays.
        m = re.search(r'data-product_variations="([^"]*)"', html)
        for v in json.loads(htmllib.unescape(m.group(1))) if m else []:
            if any(re.search(p["match"], str(a)) for a in v.get("attributes", {}).values()):
                price, regular = float(v["display_price"]), float(v["display_regular_price"])
                rrp, sale = (regular, price) if regular > price else (price, None)
                break

    elif reader == "nextjs":
        # Next.js page data: a variants list keyed by SKU.
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        for v in re.finditer(r'\{"price":(\d+(?:\.\d+)?),"options":\{[^}]*\},"sku":"([^"]+)"', m.group(1) if m else ""):
            if v.group(2) == p["sku"]:
                rrp = float(v.group(1))
                break

    elif reader == "ergoflex":
        # Ergoflex's basket data: {"<id>":{"ID":"<id>","RRP":..,"Price":..,"ReducedPrice":..}}
        m = re.search(r'"%s":\{"ID":"%s",(.*?)\}' % (p["sku"], p["sku"]), html)
        if m:
            data = json.loads("{" + m.group(1) + "}")
            full = max(float(data.get("RRP") or 0), float(data.get("Price") or 0))
            reduced = float(data.get("ReducedPrice") or 0)
            rrp, sale = (full, reduced) if 0 < reduced < full else (full, None)

    if rrp is None:
        raise ValueError(f"{reader}: no Queen price found")
    if p.get("no_was"):
        rrp, sale = (sale or rrp), None
    if not 200 <= (sale or rrp) <= 10000:
        raise ValueError(f"{reader}: implausible price {sale or rrp}")
    return rrp, sale


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
        for host in {urlparse(p["url"]).hostname for p in products if not p.get("reader")}:
            domain = "." + (host[4:] if host.startswith("www.") else host)
            for name, value in (("localization", "AU"), ("cart_currency", "AUD")):
                cookies.append({"name": name, "value": value, "domain": domain, "path": "/"})
        context.add_cookies(cookies)
        page = context.new_page()

    brands, failures = {}, []
    for p in products:
        key = p["key"]
        if p.get("reader"):
            # Not on Shopify: one reading straight from the page's own data.
            try:
                rrp, sale = page_price(p)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{key}: page data — {e}")
                if key in previous:
                    brands[key] = previous[key]
                continue
            brands[key] = {
                "name": p["name"], "size": p["size"], "review": p["review"],
                "source": p["url"], "rrp": round(rrp),
                "sale": round(sale) if sale else None,
                "method": "page", "read": today.isoformat(),
            }
            entry = brands[key]
            shown = f"${entry['sale']:,} (list ${entry['rrp']:,})" if entry["sale"] else f"${entry['rrp']:,}"
            print(f"  {key:28} {shown:26} page")
            continue
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
                if not result.get("price") or result["price"] >= rrp:
                    # No discount yet. The discount apps sometimes finish late,
                    # and a missed discount would publish the list price, so
                    # look once more before believing it.
                    page.wait_for_timeout(8000)
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

    # One point per product per reading date. A carried entry is an older
    # reading already on file, so it adds nothing; a later run on the same day
    # replaces the earlier one, which is how a misread gets corrected.
    history = json.loads(HISTORY.read_text()) if HISTORY.exists() else {}
    series = history.setdefault("brands", {})
    for key, entry in brands.items():
        if entry.get("method") == "carried":
            continue
        series.setdefault(key, {})[entry["read"]] = [entry["rrp"], entry["sale"]]
    history["_readme"] = ("Every reading fetch_prices.py has made, by product and date: "
                          "[rrp, sale]. sale is null when no discount was showing.")
    history["brands"] = {k: dict(sorted(v.items())) for k, v in sorted(series.items())}
    HISTORY.write_text(json.dumps(history, indent=1) + "\n")

    print(f"\n{len(brands)} written, {len(failures)} failed")
    for f in failures:
        print("  FAILED", f)
    if len(failures) > MAX_FAILURES:
        sys.exit(1)


if __name__ == "__main__":
    main()
