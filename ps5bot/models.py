from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

LABELS = {
    "fat_digital": "PS5 Edición Digital (Fat)",
    "fat_disc": "PS5 Con disco (Fat)",
    "slim_digital": "PS5 Slim Digital",
    "slim_disc": "PS5 Slim lector",
    "switch2_zelda40": "Nintendo Switch 2 · Zelda 40.º aniversario",
}
PS5_MODELS = ('fat_digital', 'fat_disc', 'slim_digital', 'slim_disc')
SWITCH_MODELS = ('switch2_zelda40',)
FAMILIES = {'ps5': PS5_MODELS, 'switch2': SWITCH_MODELS}


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)).lower()
                   if not unicodedata.combining(c))


def cents(value):
    """Un precio aislado, nunca el texto completo de una ficha."""
    s = str(value).strip().replace("\xa0", "").replace(" ", "")
    s = re.sub(r"^(?:desde|EUR)", "", s, flags=re.I).replace("€", "")
    s = re.sub(r"EUR$", "", s, flags=re.I).strip()
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", s):
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        amount = Decimal(s)
        if not amount.is_finite() or not 0 < amount <= 10000:
            return None
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


def euro(value):
    return (f"{value / 100:.2f}".replace(".", ",").removesuffix(",00") + " €")


def canonical(url):
    if len(url) > 2000:
        return ""
    p = urlsplit(url)
    if p.scheme not in ("https", "http") or not p.hostname or p.username:
        return ""
    if p.hostname.endswith("amazon.es"):
        asin = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", p.path)
        if asin:
            return "https://www.amazon.es/dp/" + asin.group(1)
    params = [(k, v) for k, v in parse_qsl(p.query)
              if not k.lower().startswith(("utm_", "ref", "aff", "awc", "tag", "origin", "sv_"))]
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), urlencode(params), ""))


def classify(title, url="", overrides=None, include_used=False):
    t = normalize(title)
    if re.search(r'\bswitch\s*2\b', t):
        return classify_switch(title, include_used=include_used)
    if not re.search(r"\b(?:ps\s*5|play\s*station\s*5)\b", t):
        return None
    if re.search(r"\bpro\b|\bcfi[- ]?7\d{3}", t):
        return None
    if not include_used and re.search(r"reacondicion|segunda mano|usad[oa]|refurb|renewed|seminuev|reestren", t):
        return None
    # Rechaza accesorios/juegos incluso cuando contienen 'para consola PS5 Slim'.
    if re.search(r"\b(?:para|compatible con)\s+(?:la\s+)?(?:consola\s+)?(?:sony\s+)?(?:ps5|playstation\s*5)", t):
        return None
    if re.search(r"^(?:sony\s+)?(?:mando|dualsense|lector|unidad de disco|soporte|base|funda|carcasa|cubierta|auricular|cable|juego|videojuego|tarjeta|ssd|disco duro|ventilador|cargador)\b", t):
        return None
    if re.search(r"\b(?:solo caja|caja vacia|sin consola|averiada|para piezas)\b", t):
        return None
    primary = t.split(' + ')[0]
    if re.search(r'\b(?:soporte|funda|carcasa|cubierta|cargador|ventilador|refrigerador|cable|auriculares)\b', primary):
        return None
    if re.search(r'\blector de discos\b', primary) and not re.search(r'\bcon (?:lector|disco)', primary):
        return None
    override = (overrides or {}).get(canonical(url))
    if override in PS5_MODELS:
        return override
    slim = bool(re.search(r"\bslim\b|\bcfi[- ]?(?:20|21)\d{2}|\bcha(?:s|ss)is\s*[de]\b|\b[de]\s+cha(?:s|ss)is\b", primary))
    fat = bool(re.search(r"\bfat\b|\bcfi[- ]?1[012]\d{2}|\bcha(?:s|ss)is\s*[abc]\b|\b[abc]\s+cha(?:s|ss)is\b", primary))
    if slim == fat:  # Ni identificado, o título contradictorio.
        return None
    digital = bool(re.search(r"\bdigital\b|sin (?:disco|lector)|\bcfi[- ]?\d{4}b\b", primary))
    extra_drive = bool(re.search(r'\+\s*(?:lector|unidad de disco)', t))
    disc = extra_drive or bool(re.search(r"con (?:disco|lector)|\bblu[- ]?ray\b|\bcfi[- ]?\d{4}a\b", primary))
    if digital and disc:
        # Pack digital + lector físico explícito: cuenta como consola con lector.
        if extra_drive:
            digital = False
        else:
            return None
    # En una familia ya identificada, la edición sin 'Digital' es la estándar.
    return ("slim" if slim else "fat") + ("_digital" if digital else "_disc")


def classify_switch(title, include_used=False):
    t = normalize(title).replace('™', '').replace('®', '')
    # El aniversario debe identificar la consola, no un accesorio/juego de un pack.
    primary = re.split(r'\s\+\s', t)[0]
    if not (re.search(r'\bswitch\s*2\b', primary) and 'zelda' in primary):
        return None
    if not re.search(r'\b40(?:\b|th)', primary):
        return None
    if not include_used and re.search(r'reacondicion|segunda mano|usad[oa]|refurb|renewed|seminuev', t):
        return None
    if re.search(r'\b(?:oled|lite|funda|mando|controller|joy.?con|carcasa|skin|vinilo|protector|estuche|carrying|case|dock|amiibo|cable|adaptador|soporte|accesorio|juego|videojuego|game|codigo|key|upgrade)\b', primary):
        return None
    if re.search(r'\b(?:para|compatible|sin consola|caja vacia|solo caja|averiad|piezas)\b', primary):
        return None
    if not re.search(r'\b(?:consola|videoconsola|console)\b', primary) and not re.match(r'^(?:nintendo\s+)?switch\s*2\b', primary):
        return None
    return 'switch2_zelda40'


@dataclass(frozen=True)
class Offer:
    source: str
    url: str
    title: str
    model: str
    price: int
    seller: str = ""
    kind: str = "retailer"  # retailer, comparison, deal
    availability: str = "unknown"  # in_stock, preorder, out_of_stock, unknown
    shipping: int | None = None
    condition: str = "unknown"

    @property
    def key(self):
        return hashlib.sha256(f"{self.source}|{canonical(self.url)}|{self.seller}".encode()).hexdigest()
