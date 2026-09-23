# bma-prices

Reads the Queen price a shopper actually sees for each mattress reviewed on
[BestMattressAustralia.com.au](https://bestmattressaustralia.com.au), every
third day, and publishes it as `prices.json`. The site reads that file.

It uses a real browser because some stores apply their sale in the page after it
loads, so their product data alone shows the list price, not the price you pay.

- `products.json` — what to check. Add a product by adding its store URL and the
  Queen variant id.
- `extract.js` — how the price is read off the page.
- `fetch_prices.py` — the run. `--no-browser` for a quick local check.
- `.github/workflows/prices.yml` — the schedule. **Actions → Check prices → Run
  workflow** runs it now.
