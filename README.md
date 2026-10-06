# bma-prices

Reads the Queen price a shopper actually sees for each mattress reviewed on
[BestMattressAustralia.com.au](https://bestmattressaustralia.com.au), every
day, and publishes it as `prices.json`. The site reads that file.

It uses a real browser because some stores apply their sale in the page after it
loads, so their product data alone shows the list price, not the price you pay.

- `products.json` — what to check. Add a Shopify product by adding its store URL
  and the Queen variant id. A store that is not on Shopify gets a `reader`
  instead (`jsonld`, `woocommerce`, `wcstore`, `nextjs` or `ergoflex`) plus the `match`,
  `sku` or `variant` that picks out its Queen price; see `page_price()` in `fetch_prices.py`.
  `no_was: true` records the selling price only and never the store's own
  "was" price.
- `extract.js` — how the price is read off the page.
- `fetch_prices.py` — the run. `--no-browser` for a quick local check.
- `.github/workflows/prices.yml` — the schedule. **Actions → Check prices → Run
  workflow** runs it now.

## history.json

Every reading the bot has made, per product and date, as `[rrp, sale]` (`sale` is `null` when no discount was showing). A later run on the same day replaces the earlier one. Seeded from the commit history of `prices.json` back to 2026-09-23.
