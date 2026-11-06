"""Pure helper regression checks, executable without a QGIS installation."""
import ast
import pathlib
import re
import unittest
from urllib.parse import urlsplit, urlunsplit, quote, unquote, parse_qsl

source = pathlib.Path(__file__).with_name('public_services.py').read_text()
tree = ast.parse(source)
names = {'normalize_url', 'service_parts', 'catalog_child', 'layer_groups'}
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


if __name__ == '__main__':
    unittest.main()
