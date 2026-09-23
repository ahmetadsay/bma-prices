// Reads the price a shopper actually sees on a product page.
//
// Runs inside the rendered page, after the store's own scripts have applied any
// discount. That is the whole reason this bot uses a browser: Sleep Firm, for
// one, applies its sale client-side, so the product's .js data still says
// $1,560 while the page says $1,248.
//
// Rules, each one there because a real page broke without it:
//   - Look only inside the block that holds the add-to-cart form and the h1.
//     Product pages also carry "starting from" prices for other models.
//   - Skip struck-through amounts. That is the old price, not the price.
//   - Skip anything hidden. Shopify themes keep both a sale and a regular
//     price block in the DOM and hide one.
//   - Accept only amounts between half the list price and the list price.
//     Delivery fees, pillows and $10 add-ons fall outside it.
//   - Take the first that survives. The main price renders before upsells.
//
// Validated by hand against all 16 products on 2026-09-24.
(rrp) => {
  const visible = (e) =>
    e.checkVisibility
      ? e.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
      : e.offsetParent !== null;

  const struck = (e) => {
    if (e.closest("s, del, strike")) return true;
    for (let a = e, i = 0; a && i < 4; a = a.parentElement, i++) {
      if (getComputedStyle(a).textDecorationLine.includes("line-through")) return true;
    }
    return false;
  };

  const form = document.querySelector('form[action*="/cart/add"]');
  let box = form;
  while (box && box !== document.body && !box.querySelector("h1")) box = box.parentElement;
  if (!box || box === document.body) box = document.querySelector("main") || document.body;

  const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
  const seen = [];
  let node;
  while ((node = walker.nextNode())) {
    const el = node.parentElement;
    if (!el || el.closest("script, style, noscript") || !visible(el)) continue;
    for (const m of node.textContent.matchAll(/\$\s?([1-9][\d,]*(?:\.\d{2})?)/g)) {
      seen.push({ value: parseFloat(m[1].replace(/,/g, "")), struck: struck(el) });
    }
  }

  const live = seen.filter((x) => !x.struck && x.value >= rrp * 0.5 && x.value <= rrp * 1.001);
  return { price: live.length ? live[0].value : null, seen: seen.slice(0, 8) };
}
