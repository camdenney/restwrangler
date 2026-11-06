"""Pure helper regression checks, executable without a QGIS installation."""
import ast
import pathlib
import re
import unittest
from urllib.parse import urlsplit, urlunsplit, quote, unquote, parse_qsl, urlencode

source = pathlib.Path(__file__).with_name('public_services.py').read_text()
tree = ast.parse(source)
names = {'hub_home_url', 'hub_catalog_groups', 'catalog_service_items', 'agol_home_url', 'hosted_directory_urls', 'json_request_url', 'merge_metadata_pages', 'normalize_url', 'service_parts', 'catalog_child', 'layer_groups'}
module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
exec(compile(module, '<helpers>', 'exec'), globals())


class HelpersTest(unittest.TestCase):
    def test_endpoints(self):
        self.assertEqual(normalize_url(' https://host/server/rest/services/A/featureserver/0/?f=pjson '),
                         'https://host/server/rest/services/A/FeatureServer/0')
        self.assertEqual(service_parts('https://host/arcgis/rest/services/A/MapServer/10'),
                         ('https://host/arcgis/rest/services/A/MapServer', 'MapServer', '10'))
        self.assertIsNone(service_parts('https://host/server/rest/services/Folder'))

    def test_reject_non_public_or_non_services(self):
        for url in ['file:///rest/services', 'https://host/portal/home',
                    'https://host/sharing/rest', 'https://user:pass@host/rest/services',
                    'https://host/rest/services?token=SECRET', 'https://host/rest/services?key=']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_url(url)

    def test_folder_service_names(self):
        root = 'https://host/server/rest/services'
        self.assertEqual(catalog_child(root, 'Planning/Parcels'), root + '/Planning/Parcels')
        self.assertEqual(catalog_child(root + '/Planning', 'Planning/Parcels'), root + '/Planning/Parcels')
        self.assertEqual(catalog_child(root + '/Planning', 'Parcels'), root + '/Planning/Parcels')
        self.assertEqual(catalog_child(root + '/Public%20Access', 'Public Access/Boat Ramps'),
                         root + '/Public%20Access/Boat%20Ramps')

    def test_nested_and_broken_parents(self):
        rows = {0: {'id': 0, 'name': 'Hazards', 'parentLayerId': -1},
                4: {'id': 4, 'name': 'Flood', 'parentLayerId': 0},
                8: {'id': 8, 'name': 'Zones', 'parentLayerId': 4}}
        self.assertEqual(layer_groups(rows[8], rows), ['Hazards', 'Flood'])
        self.assertEqual(layer_groups({'id': 20, 'parentLayerId': 99}, rows), [])
        rows[0]['parentLayerId'] = 8
        self.assertEqual(layer_groups(rows[8], rows), ['Hazards', 'Flood'])

    def test_home_url_normalization(self):
        for suffix in ['', '/', '/home/', '/home/index.html', '/home/index.html?f=pjson']:
            self.assertEqual(normalize_url('https://coastalcomm.maps.arcgis.com' + suffix),
                             'https://coastalcomm.maps.arcgis.com')
        for url in ['https://coastalcomm.maps.arcgis.com/home/item.html?id=abc',
                    'https://evil.example/home/index.html',
                    'https://coastalcomm.maps.arcgis.com.evil.example/home/index.html',
                    'https://coastalcomm.maps.arcgis.com?token=secret']:
            with self.assertRaises(ValueError): normalize_url(url)

    def test_different_hosts_and_wrong_organization(self):
        org = 'wwVnNW92ZHUIr0V0'
        roots = hosted_directory_urls([
            {'url': f'https://services9.arcgis.com/{org}/arcgis/rest/services/A/FeatureServer'},
            {'url': f'https://services9.arcgis.com/{org}/arcgis/rest/services/B/FeatureServer'},
            {'url': f'https://services2.arcgis.com/{org}/arcgis/rest/services/C/FeatureServer'},
            {'url': 'https://services1.arcgis.com/OTHERORG12345678/arcgis/rest/services/D/FeatureServer'},
            {'url': f'https://evil.example/{org}/arcgis/rest/services/E/FeatureServer'},
            {'url': None}], org)
        self.assertEqual(roots, [f'https://services2.arcgis.com/{org}/arcgis/rest/services',
                                 f'https://services9.arcgis.com/{org}/arcgis/rest/services'])

    def test_search_query_and_pagination_preserved(self):
        query = 'orgid:wwVnNW92ZHUIr0V0 AND type:"Feature Service"'
        url = 'https://org.maps.arcgis.com/sharing/rest/search?' + urlencode({'q': query, 'num': 100})
        params = dict(parse_qsl(urlsplit(json_request_url(url, 101)).query))
        self.assertEqual(params, {'q': query, 'num': '100', 'f': 'json', 'start': '101'})
        merged = merge_metadata_pages({'results': [{'url': 'first'}], 'nextStart': 101},
                                      {'results': [{'url': 'second'}], 'nextStart': -1})
        self.assertEqual([x['url'] for x in merged['results']], ['first', 'second'])
        self.assertEqual(merged['nextStart'], -1)

    def test_hub_and_open_data_roots(self):
        self.assertEqual(normalize_url('https://gisdata-caltrans.opendata.arcgis.com/'), 'https://gisdata-caltrans.opendata.arcgis.com')
        self.assertEqual(normalize_url('https://example.hub.arcgis.com/'), 'https://example.hub.arcgis.com')
        for url in ['https://example.hub.arcgis.com/datasets/abc', 'https://example.hub.arcgis.com.evil.org/',
                    'https://user:pass@example.hub.arcgis.com/', 'https://example.opendata.arcgis.com/?token=secret']:
            with self.assertRaises(ValueError): normalize_url(url)

    def test_hub_groups_and_external_service_urls(self):
        group = 'a' * 32
        self.assertEqual(hub_catalog_groups({'catalog': {'groups': [group, group, 'invalid']}}), [group])
        self.assertEqual(hub_catalog_groups({}, {'properties': {'contentGroupId': group}}), [group])
        self.assertEqual(hub_catalog_groups({}), [])
        url = 'https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHboundary/Districts/FeatureServer/0'
        entries = catalog_service_items([
            {'type': 'Feature Service', 'title': 'Districts', 'url': url},
            {'type': 'Feature Service', 'title': 'Duplicate', 'url': url},
            {'type': 'Map Service', 'title': 'Roads', 'url': 'https://server.example.org/arcgis/rest/services/Roads/MapServer'},
            {'type': 'Feature Service', 'url': url + '?token=secret'},
            {'type': 'CSV', 'url': 'https://example.org/file.csv'}])
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['url'], url)
        self.assertEqual(entries[0]['title'], 'Districts')


if __name__ == '__main__':
    unittest.main()
