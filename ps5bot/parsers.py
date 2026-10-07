"""JSON-LD y selectores acotados por ficha. Nunca busca el mínimo de toda la página."""
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .models import Offer, FAMILIES, canonical, cents, classify, normalize


class ParseError(Exception):
    pass


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def availability(value):
    t = normalize(value)
    if any(x in t for x in ("outofstock", "soldout", "discontinued", "agotado", "no disponible", "sin stock")):
        return "out_of_stock"
    if any(x in t for x in ('preorder', 'presale', 'preventa', 'reservar', 'reserva ya')):
        return 'preorder'
    if any(x in t for x in ("instock", "limitedavailability", "en stock", "anadir a la cesta", "anadir al carrito")):
        return "in_stock"
    return "unknown"


def parse_page(html, page_url, source, overrides=None, include_used=False, diagnostics=None):
    is_rss = '<rss' in html[:1000].lower()
    soup = BeautifulSoup('<html></html>' if is_rss else html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    block_text = " ".join((title, soup.get_text(" ", strip=True)[:5000]))
    if (re.search(r"captcha|robot check|access denied|just a moment|acceso denegado|lo sentimos", block_text, re.I)
            or re.search(r"acceso automatizado|automated access", block_text, re.I)
            or soup.select_one('form[action*="validateCaptcha"]')):
        raise ParseError("Página de bloqueo/CAPTCHA")
    found = {}
    recognized = False
    allowed_models = FAMILIES.get(source.get('family'), tuple(m for v in FAMILIES.values() for m in v))
    if diagnostics is not None:
        diagnostics.update(url=page_url, candidates=0, accepted=0, samples=[])

    def add(name, url, price, *, seller="", stock="unknown", shipping=None, condition="unknown"):
        if not isinstance(name, str) or not isinstance(url, str):
            return
        url = canonical(urljoin(page_url, url))
        if not url:
            return
        model = classify(name, url, overrides, include_used)
        p = cents(price)
        if diagnostics is not None:
            diagnostics['candidates'] += 1
            if len(diagnostics['samples']) < 12:
                diagnostics['samples'].append({'title': name[:240], 'price_text': str(price)[:80],
                    'model': model, 'result': 'aceptado' if model in allowed_models and p is not None else 'sin modelo de esta familia o precio inválido'})
        if model not in allowed_models or p is None:
            return
        if not include_used and any(x in normalize(condition) for x in ("used", "refurb", "reacond", "segunda")):
            return
        # Esta edición se lanza el 29/10/2026. No anunciar entrega inmediata antes.
        if model == 'switch2_zelda40' and stock == 'in_stock' and datetime.now(ZoneInfo('Europe/Madrid')).date().isoformat() < '2026-10-29':
            stock = 'preorder'
        offer = Offer(source["name"], url, name[:400], model, p, str(seller or ""),
                      source["kind"], stock, shipping, condition)
        found.setdefault(offer.key, offer)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for product in walk(payload):
            types = product.get("@type", "")
            if isinstance(types, str):
                types = [types]
            if not any(str(t).lower() in ("product", "productgroup") for t in types):
                continue
            offers = product.get("offers", [])
            if isinstance(offers, dict):
                offers = [offers]
            if offers:
                recognized = True
            for offer in offers:
                if not isinstance(offer, dict) or offer.get("priceCurrency") != "EUR":
                    continue
                aggregate = str(offer.get("@type", "")).lower() == "aggregateoffer"
                if aggregate and source["kind"] == "retailer":
                    continue  # 'desde', usado o variantes: no es precio de compra confirmado.
                seller = offer.get("seller", offer.get("offeredBy", {}))
                if isinstance(seller, dict):
                    seller = seller.get("name", "")
                shipping = None
                details = offer.get("shippingDetails", {})
                if isinstance(details, dict):
                    rate = details.get("shippingRate", {})
                    if isinstance(rate, dict) and rate.get("currency") == "EUR":
                        shipping = 0 if str(rate.get("value")) in ("0", "0.0", "0.00") else cents(rate.get("value"))
                add(product.get("name"), offer.get("url") or product.get("url") or product.get("@id") or page_url,
                    offer.get("lowPrice") if aggregate else offer.get("price"),
                    seller=seller, stock=availability(offer.get("availability", "")), shipping=shipping,
                    condition=offer.get("itemCondition", product.get("itemCondition", "unknown")))

    parser = source["parser"]
    if parser == "idealo":
        cards = soup.select('[class*="resultList__item_"]')
        recognized = recognized or bool(cards)
        for card in cards:
            name = card.select_one('[class*="productSummary__title"]')
            link = name.find_parent("a", href=True) if name else None
            price = card.select_one('[class*="detailedPriceInfo__price_"]')
            if name and link and price:
                add(name.get_text(" ", strip=True), link["href"], price.get_text(" ", strip=True))
    elif parser == "amazon":
        cards = soup.select('[data-component-type="s-search-result"][data-asin]')
        recognized = recognized or bool(cards)
        for card in cards:
            name = card.select_one("h2")
            price = card.select_one('.a-price:not(.a-text-price) .a-offscreen')
            asin = card.get("data-asin", "")
            name_text = (name.get('aria-label') or name.get_text(' ', strip=True)) if name else ''
            if not name_text:
                alt = card.select_one('img.s-image[alt]')
                name_text = alt.get('alt', '') if alt else ''
            raw = price.get_text() if price else ''
            if not raw:
                whole = card.select_one('.a-price:not(.a-text-price) .a-price-whole')
                fraction = card.select_one('.a-price:not(.a-text-price) .a-price-fraction')
                if whole and fraction:
                    raw = whole.get_text(strip=True).rstrip(',.') + ',' + fraction.get_text(strip=True)
            if name_text and re.fullmatch(r"[A-Z0-9]{10}", asin):
                add(name_text, f"https://www.amazon.es/dp/{asin}", raw,
                    stock=availability(card.get_text(" ", strip=True)))
        main_title = soup.select_one('#productTitle')
        main_price = soup.select_one('#corePriceDisplay_desktop_feature_div .a-price:not(.a-text-price) .a-offscreen, #corePrice_feature_div .a-price:not(.a-text-price) .a-offscreen')
        if main_title:
            recognized = True
            stock = soup.select_one('#availability')
            if main_price:
                add(main_title.get_text(' ', strip=True), page_url, main_price.get_text(),
                    stock=availability(stock.get_text(' ', strip=True) if stock else ''))
    elif parser == "fnac":
        cards = soup.select('.Article-item, .js-articleItem')
        recognized = recognized or bool(cards)
        for card in cards:
            name = card.select_one('a.Article-title, a.js-minifa-title')
            price = card.select_one('.userPrice, .Article-price')
            if name and price:
                add(name.get_text(" ", strip=True), name.get("href", ""), price.get_text(" ", strip=True),
                    stock=availability(card.get_text(" ", strip=True)))
    elif parser == "mediamarkt":
        cards = soup.select('[data-test="mms-product-card"]')
        recognized = recognized or bool(cards)
        for card in cards:
            link = card.select_one('a[href*="/product/"]')
            name = card.select_one('[data-test="product-title"], h2, h3')
            price = card.select_one('[data-test="branded-price-whole-value"]')
            fraction = card.select_one('[data-test="branded-price-decimal-value"]')
            if link and name and price:
                raw = price.get_text(strip=True)
                if fraction:
                    raw += "," + fraction.get_text(strip=True).strip(",.")
                add(name.get_text(" ", strip=True), link["href"], raw,
                    stock=availability(card.get_text(" ", strip=True)))
    elif parser == "chollometro":
        # Las clases pueden cambiar: si desaparecen, se informa de error de extracción.
        cards = soup.select('article.thread, article[id^="thread_"]')
        recognized = recognized or bool(cards)
        for card in cards:
            if card.select_one('.thread--expired, .cept-expired') or 'thread--expired' in card.get('class', []):
                continue
            link = card.select_one('a.thread-title--list, a.cept-tt, a[href*="/ofertas/"]')
            price = card.select_one('.thread-price, .cept-tp')
            if link and price:
                name = link.get_text(" ", strip=True)
                description = card.select_one('.userHtml-content')
                if description and classify(name, link.get('href', ''), overrides, include_used) is None:
                    # Solo referencias concretas del anuncio, no inferencias por capacidad.
                    hints = re.findall(r'\bcfi[- ]?\d{4}[ab]?\b|\bcha(?:s|ss)is\s*[a-e]\b|\b[a-e]\s+cha(?:s|ss)is\b', normalize(description.get_text(' ', strip=True)))
                    if hints:
                        name += ' [' + ', '.join(dict.fromkeys(hints)) + ']'
                seller = card.select_one('[data-t="merchantLink"]')
                add(name, link.get("href", ""), price.get_text(" ", strip=True),
                    seller=seller.get_text(' ', strip=True) if seller else '')
        if is_rss:
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(html)
                recognized = True
                for item in root.findall('./channel/item'):
                    name = item.findtext('title', '')
                    desc = BeautifulSoup(item.findtext('description', ''), 'html.parser').get_text(' ', strip=True)
                    merchant = item.find('{http://www.pepper.com/rss}merchant')
                    if merchant is not None and merchant.get('price'):
                        if not re.search(r'agotad|caducad|expirad', normalize(name)):
                            add(name, item.findtext('link', ''), merchant.get('price'), seller=merchant.get('name', ''))
                        continue
                    prices = re.findall(r'(\d+(?:[.,]\d+)*)\s*€', name)
                    if not prices:
                        prices = re.findall(r'(\d+(?:[.,]\d+)*)\s*€', desc)
                    # Solo una cantidad: evita elegir PVP anterior o cuotas.
                    if len(prices) == 1 and not re.search(r'agotad|caducad|expirad', normalize(name + ' ' + desc)):
                        add(name, item.findtext('link', ''), prices[0])
            except ET.ParseError as exc:
                raise ParseError("RSS inválido") from exc
    if not recognized:
        raise ParseError("Sin fichas/precios reconocibles; puede requerir JavaScript o un ajuste del adaptador")
    if diagnostics is not None:
        diagnostics['accepted'] = len(found)
    return list(found.values())
