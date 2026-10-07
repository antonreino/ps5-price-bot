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
    if any(x in t for x in ('preorder', 'presale', 'preventa', 'pre-compra', 'precompra',
                                  'reservar', 'reserva ya', 'proximamente')):
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
    expected_eans = tuple(str(x) for x in source.get('expected_eans', ()) if str(x))
    # No tomamos cualquier número de 13 dígitos del HTML como EAN: muchas webs
    # insertan IDs, timestamps o referencias internas de 13 cifras en scripts.
    # Solo validamos códigos publicados explícitamente como EAN/GTIN.
    labeled_eans = set()
    for pattern in (
        r'(?i)\bEAN\b\s*[:#-]?\s*(\d{13})',
        r'(?i)["\']gtin13["\']\s*:\s*["\']?(\d{13})',
        r'(?i)["\']gtin["\']\s*:\s*["\']?(\d{13})',
    ):
        labeled_eans.update(re.findall(pattern, html))
    if expected_eans and labeled_eans and not labeled_eans.intersection(expected_eans):
        raise ParseError('EAN/GTIN de la ficha no coincide con el esperado')

    found = {}
    recognized = False
    allowed_models = FAMILIES.get(source.get('family'), tuple(m for v in FAMILIES.values() for m in v))
    if diagnostics is not None:
        diagnostics.update(url=page_url, candidates=0, accepted=0, samples=[])

    def add(name, url, price, *, seller="", stock="unknown", shipping=None, condition="unknown", forced_model=None):
        if not isinstance(name, str) or not isinstance(url, str):
            return
        url = canonical(urljoin(page_url, url))
        if not url:
            return
        model = forced_model or classify(name, url, overrides, include_used)
        p = cents(price)
        if diagnostics is not None:
            diagnostics['candidates'] += 1
            if len(diagnostics['samples']) < 12:
                diagnostics['samples'].append({
                    'title': name[:240],
                    'url': url[:500],
                    'price_text': str(price)[:80],
                    'model': model,
                    'result': 'aceptado' if model in allowed_models and p is not None else 'sin modelo de esta familia o precio inválido',
                })
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
            link = card.select_one('a[href*="/product/"], a[href*="/_"]')
            name = card.select_one('[data-test="product-title"], h2, h3')
            price = card.select_one('[data-test="branded-price-whole-value"]')
            fraction = card.select_one('[data-test="branded-price-decimal-value"]')
            if link and name and price:
                raw = price.get_text(strip=True)
                if fraction:
                    raw += "," + fraction.get_text(strip=True).strip(",.")
                add(name.get_text(" ", strip=True), link["href"], raw,
                    stock=availability(card.get_text(" ", strip=True)))

        # Las fichas directas de MediaMarkt no siempre usan la estructura
        # de tarjeta de las páginas de búsqueda.
        if not cards:
            title_node = soup.select_one('h1')
            if title_node is None:
                meta_title = soup.select_one('meta[property="og:title"][content]')
                title_text = meta_title.get("content", "") if meta_title else ""
            else:
                title_text = title_node.get_text(" ", strip=True)

            price_node = soup.select_one(
                'meta[itemprop="price"][content], '
                'meta[property="product:price:amount"][content], '
                '[itemprop="price"][content]'
            )
            raw = price_node.get("content", "") if price_node else ""

            if not raw:
                whole = soup.select_one('[data-test="branded-price-whole-value"]')
                fraction = soup.select_one('[data-test="branded-price-decimal-value"]')
                if whole:
                    raw = whole.get_text(strip=True)
                    if fraction:
                        raw += "," + fraction.get_text(strip=True).strip(",.")

            if title_text and raw:
                recognized = True
                add(title_text, page_url, raw,
                    stock=availability(soup.get_text(" ", strip=True)[:12000]))
    elif parser == "game":
        found.clear()
        recognized = False
        visible = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        raw = re.sub(r"\s+", " ", html)

        name = ""
        h1 = soup.select_one("h1")
        if h1:
            name = h1.get_text(" ", strip=True)
        if not name:
            og = soup.select_one('meta[property="og:title"][content], meta[name="twitter:title"][content]')
            if og:
                name = og.get("content", "").strip()
        if not name and soup.title:
            name = soup.title.get_text(" ", strip=True)

        price_match = re.search(r"\b(\d{2,4})\s*(?:['’]|[,\.]|\s)\s*(\d{2})\s*€", visible)
        if not price_match:
            price_match = re.search(r"\b(\d{2,4})\s*(?:['’]|[,\.]|&apos;|&#39;|\s)\s*(\d{2})\s*(?:€|&euro;)", raw, re.I)
        if not price_match:
            price_match = re.search(r"\b(\d{2,4}(?:[.,]\d{2}))\s*(?:€|&euro;)", raw, re.I)

        if name and price_match:
            recognized = True
            raw_price = (price_match.group(1) + "," + price_match.group(2)
                         if price_match.lastindex == 2 else price_match.group(1))
            add(name, page_url, raw_price, seller="GAME", stock=availability(visible + " " + raw))

    elif parser == "carrefour":
        found.clear()
        recognized = False
        visible = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        name_node = soup.select_one("h1")
        name = name_node.get_text(" ", strip=True) if name_node else ""
        if not name:
            og = soup.select_one('meta[property="og:title"][content]')
            if og:
                name = og.get("content", "").strip()

        forced_model = None
        current = canonical(page_url)
        for configured_url, configured_model in source.get("url_models", {}).items():
            if canonical(configured_url) == current:
                forced_model = configured_model
                break

        seller_match = re.search(
            r"Vendido por\s+Carrefour(?:\s+con:)?(.*?)(?:Vendido por|Información del vendedor|Características|$)",
            visible, re.I
        )
        if name and seller_match:
            fragment = seller_match.group(1)[:1800]
            price_match = re.search(r"\b(\d{2,4}(?:[.,]\d{1,2})?)\s*€", fragment)
            if price_match:
                recognized = True
                add(name, page_url, price_match.group(1),
                    seller="Carrefour",
                    stock=availability(fragment),
                    forced_model=forced_model)

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
