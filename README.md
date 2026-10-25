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

## Member prices

From 2026-10-12 Sleep Republic and Ecosa show their discount as a "Member
Price" that anyone gets by giving an email address. When a member price is the
lowest price on the page it is written as `sale`, with `"member": true`, and the
site labels it "member price, free sign-up". Sleep Republic's is read from the
"Member Price" box on the rendered page (`extract.js`), Ecosa's from the
`validForMemberTier` price in its JSON-LD. The 2026-10-11 readings of both
missed it and show the list price.
- `fetch_prices.py` — the run. `--no-browser` for a quick local check.
- `.github/workflows/prices.yml` — the schedule. **Actions → Check prices → Run
  workflow** runs it now.

## history.json

Every reading the bot has made, per product and date, as `[rrp, sale]` (`sale` is `null` when no discount was showing), with a third value `"member"` when `sale` was a member price. A later run on the same day replaces the earlier one. Seeded from the commit history of `prices.json` back to 2026-09-23.

## Price alerts

`alerts.py` runs after each price read. When a tracked mattress reads below
every earlier reading by at least $20 or 2% (whichever is larger), with at
least seven earlier readings, it opens a GitHub issue labelled `price-alert`.
The issue holds a ready-to-paste email for the brand's MailerLite group and
"Any brand". One issue per brand, listing every model of that brand at a
new low (the reviewed model first), and no repeat for a product within seven
days unless its price falls again by the same margin (`alerts.json`
remembers, by product).
`python alerts.py --dry-run` prints what it would open.

## When a read fails

A product that cannot be read is tried once more after 20 seconds; if that
fails too, its last good reading is kept (up to seven days, as above). The
readings that worked are always saved and the alerts still run. The run turns
red only when a product has had no fresh reading for three runs in a row, or
when more than ten fail at once, which points at the bot rather than a store.
So a red run means something needs fixing, not that a store had a bad day.
