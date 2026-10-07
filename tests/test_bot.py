from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ps5bot.app import command_reply, load_config, collect
from ps5bot.models import Offer, cents, classify, canonical
from ps5bot.parsers import parse_page, ParseError
from ps5bot.network import FetchError, Telegram, retry_seconds
from ps5bot.store import Store

ROOT = Path(__file__).resolve().parent.parent
CONFIG = load_config(ROOT / 'config.json')


class ClassificationTests(unittest.TestCase):
    def test_four_models(self):
        cases = {
            'Sony PS5 CFI-1216B Digital 825GB': 'fat_digital',
            'Consola PlayStation 5 Chasis C': 'fat_disc',
            'Consola PS5 Slim Digital 825GB Chasis E': 'slim_digital',
            'Sony PlayStation 5 Slim Chasis E': 'slim_disc',
            'PS5 Slim Digital + lector': 'slim_disc',
            'PS5 Slim Digital sin lector': 'slim_digital',
            'PS5 Slim con lector + EA FC26 Digital': 'slim_disc',
            'Sony PS5 Digital E Chassis': 'slim_digital',
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(classify(title), expected)

    def test_exclusions(self):
        for title in ['PS5 Pro', 'PS5 Pro Slim', 'Sony PlayStation 5 CFI-7021',
                      'Mando DualSense PS5 Slim', 'Base para consola PS5 Slim',
                      'Juego PS5 Slim Digital', 'Lector PS5 Slim', 'PS5 Slim soporte vertical',
                      'PS5 Slim lector de discos', 'PS5 Slim segunda mano',
                      'PS5 Slim reacondicionada', 'PS5 Slim caja vacía',
                      'Sony PlayStation 5 Digital', 'Sony PS5 825GB']:
            with self.subTest(title=title):
                self.assertIsNone(classify(title))

    def test_override_cannot_admit_pro(self):
        url = 'https://www.amazon.es/dp/B012345678'
        self.assertIsNone(classify('PS5 Pro', url, {url: 'slim_disc'}))

    def test_locale_prices(self):
        for raw, expected in [('549€', 54900), ('1.299,99 €', 129999), ('649.99', 64999),
                              ('desde 564,50 €', 56450), ('1.000', 100000)]:
            self.assertEqual(cents(raw), expected)
        for raw in ['0', '-1', 'NaN', 'Infinity', '19 €/mes durante 24 meses', 'antes 699€ ahora 499€', 'None']:
            self.assertIsNone(cents(raw))

    def test_tracking_url_stable(self):
        self.assertEqual(canonical('https://www.amazon.es/Playstation/dp/B012345678/ref=x?tag=x'),
                         canonical('https://www.amazon.es/dp/B012345678'))


class ParserTests(unittest.TestCase):
    def source(self, name):
        return next(s for s in CONFIG['sources'] if s['name'] == name)

    def test_real_pcc(self):
        s = self.source('PcComponentes')
        offers = parse_page((ROOT / 'tests/fixtures/pcc-real.html').read_text(), s['urls'][0], s)
        self.assertTrue(any(o.model == 'slim_digital' and o.price == 59900 for o in offers))
        self.assertTrue(any(o.model == 'slim_disc' and o.price == 64900 for o in offers))
        self.assertTrue(all('Pro' not in o.title for o in offers))

    def test_real_idealo(self):
        s = self.source('Idealo')
        offers = parse_page((ROOT / 'tests/fixtures/idealo-real.html').read_text(), s['urls'][0], s, CONFIG['model_overrides'])
        self.assertEqual({o.model for o in offers}, {'fat_disc','fat_digital','slim_disc','slim_digital'})
        self.assertTrue(all(o.kind == 'comparison' for o in offers))

    def test_real_mediamarkt(self):
        s = self.source('MediaMarkt')
        offers = parse_page((ROOT / 'tests/fixtures/mm-real.html').read_text(), s['urls'][0], s)
        self.assertTrue(any(o.model == 'slim_digital' and o.price == 59900 for o in offers))
        self.assertTrue(all(o.model in ('slim_disc', 'slim_digital') for o in offers))

    def test_real_chollometro(self):
        s = self.source('Chollometro')
        offers = parse_page((ROOT / 'tests/fixtures/chollo_ps5-real.html').read_text(), s['urls'][0], s)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].model, 'slim_digital')
        self.assertEqual(offers[0].price, 51229)
        self.assertEqual(offers[0].seller, 'AliExpress')
        expired = parse_page((ROOT / 'tests/fixtures/chollo_slim-real.html').read_text(), s['urls'][-1], s)
        self.assertEqual(expired, [])

    def test_synthetic_chollo_rss(self):
        s = self.source('Chollometro')
        xml = '<rss><channel><item><title>PS5 Slim Digital 399€</title><link>https://www.chollometro.com/ofertas/x</link></item></channel></rss>'
        self.assertEqual(parse_page(xml, s['urls'][0], s)[0].price, 39900)

    def test_chollo_rss_explicit_price_not_old_rrp(self):
        s = self.source('Chollometro')
        xml = '<rss xmlns:pepper="http://www.pepper.com/rss"><channel><item><title>PS5 Slim Digital</title><description>Antes 549€, ahora 399€</description><pepper:merchant name="Amazon" price="399€"/><link>https://www.chollometro.com/ofertas/x</link></item></channel></rss>'
        offer = parse_page(xml,s['urls'][0],s)[0]
        self.assertEqual(offer.price,39900)
        self.assertEqual(offer.seller,'Amazon')

    def test_captcha_and_redesign_fail_loudly(self):
        for html in ['<title>Robot Check</title>', '<title>Tienda</title><p>599€</p>']:
            with self.assertRaises(ParseError):
                parse_page(html, 'https://www.amazon.es', self.source('Amazon'))

    def test_aggregate_is_not_retail_purchase(self):
        p = {'@type':'Product', 'name':'PS5 Slim', 'offers':{'@type':'AggregateOffer','lowPrice':199,'priceCurrency':'EUR'}}
        html = '<script type="application/ld+json">' + json.dumps(p) + '</script>'
        self.assertEqual(parse_page(html, 'https://www.fnac.es/a1', self.source('Fnac')), [])

    def test_stock_condition_and_shipping(self):
        p = {'@type':'Product','name':'PS5 Slim Digital', 'offers':{'@type':'Offer','price':449.99,'priceCurrency':'EUR',
              'availability':'https://schema.org/OutOfStock','shippingDetails':{'shippingRate':{'value':'0.00','currency':'EUR'}}}}
        html = lambda: '<script type="application/ld+json">' + json.dumps(p) + '</script>'
        offers = parse_page(html(), 'https://www.fnac.es/a1', self.source('Fnac'))
        self.assertEqual(offers[0].availability, 'out_of_stock')
        self.assertEqual(offers[0].shipping, 0)
        p['offers']['itemCondition'] = 'https://schema.org/RefurbishedCondition'
        self.assertEqual(parse_page(html(), 'https://www.fnac.es/a1', self.source('Fnac')), [])

    def test_synthetic_site_cards(self):
        cases = {
          'Amazon': '<div data-component-type="s-search-result" data-asin="B012345678"><h2>PS5 Slim Digital</h2><span class="a-price"><span class="a-offscreen">450€</span></span><span class="a-price a-text-price"><span class="a-offscreen">600€</span></span></div>',
          'Fnac': '<div class="Article-item"><a class="Article-title" href="/a123">PS5 Slim Digital</a><b class="userPrice">450€</b></div>',
          'MediaMarkt': '<div data-test="mms-product-card"><a href="/es/product/x"><h2>PS5 Slim Digital</h2></a><span data-test="branded-price-whole-value">450</span><span data-test="branded-price-decimal-value">00</span></div>',
          'Chollometro': '<article class="thread"><a class="thread-title--list" href="/ofertas/ps5-123">PS5 Slim Digital</a><span class="thread-price">450€</span></article>',
        }
        for name, html in cases.items():
            with self.subTest(name=name):
                s = self.source(name)
                offers = parse_page(html, s['urls'][0], s)
                self.assertEqual(len(offers), 1)
                self.assertEqual(offers[0].price, 45000)

    def test_expired_chollo_excluded(self):
        html = '<article class="thread thread--expired"><a class="thread-title--list" href="/ofertas/x">PS5 Slim</a><span class="thread-price">99€</span></article>'
        self.assertEqual(parse_page(html, 'https://www.chollometro.com', self.source('Chollometro')), [])

    def test_partial_source_failure_is_not_success(self):
        s = self.source('PcComponentes') | {'urls':['https://www.pccomponentes.com/a','https://www.pccomponentes.com/b']}
        with patch('ps5bot.app.fetch', side_effect=['<html/>', FetchError('HTTP 403')]), patch('ps5bot.app.parse_page', return_value=[]):
            with self.assertRaises(FetchError):
                collect(s, CONFIG)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state.db'
        self.store = Store(self.path, ('123',))
        self.offer = Offer('Amazon','https://www.amazon.es/dp/B012345678','PS5 Slim Digital','slim_digital',45000,availability='in_stock')

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def count(self):
        return self.store.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]

    def test_baseline_equal_drop_rise_restart(self):
        self.store.source_result('Amazon', [self.offer], now=100)
        self.store.source_result('Amazon', [self.offer], now=130)
        self.assertEqual(self.count(), 0)
        self.store.source_result('Amazon', [replace(self.offer,price=44999)], now=160)
        self.assertEqual(self.count(), 1)  # un céntimo también avisa
        self.store.db.close()
        self.store = Store(self.path, ('123',))
        self.store.source_result('Amazon', [replace(self.offer,price=44999)], now=190)
        self.assertEqual(self.count(), 1)
        self.store.source_result('Amazon', [self.offer], now=220)
        self.assertEqual(self.count(), 2)

    def test_all_offers_not_only_best(self):
        expensive = replace(self.offer,url='https://www.amazon.es/dp/B012345679',price=60000)
        self.store.source_result('Amazon', [self.offer,expensive], now=100)
        self.store.source_result('Amazon', [self.offer,replace(expensive,price=60100)], now=130)
        self.assertEqual(self.count(), 1)

    def test_failure_does_not_replace_price(self):
        self.store.source_result('Amazon', [self.offer], now=100)
        self.store.source_result('Amazon', [], error='HTTP 403', now=130)
        self.assertNotIn('<b>450', self.store.summary(now=135))
        self.assertEqual(self.store.db.execute('SELECT price FROM offers').fetchone()[0], 45000)
        self.store.source_result('Amazon', [], error='HTTP 403', now=160)
        self.assertEqual(self.count(), 1)  # una incidencia, no una por reintento

    def test_stale_and_disappeared_not_current(self):
        self.store.source_result('Amazon', [self.offer], now=100)
        self.assertIn('<b>450', self.store.summary(now=150))
        self.assertNotIn('<b>450', self.store.summary(now=281))
        self.store.source_result('Amazon', [], now=160)
        self.assertNotIn('<b>450', self.store.summary(now=161))

    def test_stock_and_deals_not_false_cheapest(self):
        self.store.source_result('Amazon', [replace(self.offer,availability='out_of_stock')], now=100)
        deal = replace(self.offer,source='Chollometro',kind='deal',price=9900)
        self.store.source_result('Chollometro', [deal], now=100)
        text = self.store.summary(now=110)
        self.assertNotIn('<b>450',text)
        self.assertNotIn('<b>99',text)
        self.assertIn('99 €',self.store.deals(now=110))

    def test_authorization_and_other_bot(self):
        msg = {'chat':{'id':999},'text':'/ps5'}
        self.assertIsNone(command_reply(msg,'testbot',('123',),self.store,CONFIG))
        msg['chat']['id'] = 123
        msg['text'] = '/ps5@otherbot'
        self.assertIsNone(command_reply(msg,'testbot',('123',),self.store,CONFIG))
        msg['text'] = '/ps5@testbot'
        self.assertIn('PS5 Slim lector',command_reply(msg,'testbot',('123',),self.store,CONFIG))

    def test_outbox_survives_failure(self):
        self.store.queue('Hola')
        row = self.store.pending()
        self.store.retry(row['id'], 100)
        self.assertIsNone(self.store.pending())
        self.assertEqual(self.count(), 1)
        self.store.sent(row['id'])
        self.assertEqual(self.count(), 0)

    def test_telegram_payload(self):
        with patch.object(Telegram, 'call', return_value={'message_id':1}) as call:
            Telegram('fake').send('123','<b>PS5</b>')
            self.assertEqual(call.call_args.args[0], 'sendMessage')
            self.assertEqual(call.call_args.args[1]['chat_id'], '123')
            self.assertEqual(call.call_args.args[1]['parse_mode'], 'HTML')


if __name__ == '__main__':
    unittest.main()
