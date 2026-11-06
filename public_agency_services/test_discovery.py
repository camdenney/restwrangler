"""Discovery behavior tests using lightweight tree/network stand-ins, not a QGIS UI test."""
import ast
import pathlib
import re
import unittest
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit, quote, unquote, parse_qsl, urlencode

ROLE, UNCHECKED, CHECKED, PARTIAL = 32, 0, 2, 1
Qt = SimpleNamespace(ItemFlag=SimpleNamespace(ItemIsUserCheckable=16))
QDialog = object


class Item:
    def __init__(self, parent=None, texts=None):
        self.children, self.values, self.expanded = [], {}, False
        self._parent = parent
        self.texts = list(texts or ['', '', ''])
        self._flags = 0
        self.check = None
        if parent is not None:
            parent.children.append(self)

    def setData(self, column, role, data): self.values[column, role] = dict(data)
    def data(self, column, role): return self.values.get((column, role))
    def setToolTip(self, *args): pass
    def parent(self): return self._parent
    def text(self, column): return self.texts[column] if column < len(self.texts) else ""
    def checkState(self, column): return self.check if self.check is not None else UNCHECKED
    def flags(self): return self._flags
    def setFlags(self, flags): self._flags = flags
    def setCheckState(self, column, state): self.check = state
    def childCount(self): return len(self.children)
    def child(self, index): return self.children[index]
    def takeChildren(self): self.children = []
    def setExpanded(self, value): self.expanded = value
    def setText(self, column, text):
        while len(self.texts) <= column: self.texts.append('')
        self.texts[column] = text


QTreeWidgetItem = Item
source = pathlib.Path(__file__).with_name('public_services.py').read_text()
names = {'hub_home_url', 'hub_catalog_groups', 'catalog_service_items', 'agol_home_url', 'hosted_directory_urls', 'json_request_url', 'merge_metadata_pages', 'normalize_url', 'service_parts', 'catalog_child', 'layer_groups', 'ServicesDialog'}
module = ast.Module(body=[n for n in ast.parse(source).body
                         if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names], type_ignores=[])
exec(compile(module, '<discovery>', 'exec'), globals())
BASE = 'https://host/arcgis/rest/services'


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.d = ServicesDialog.__new__(ServicesDialog)
        self.d.status = SimpleNamespace(setText=lambda s: None)
        self.d.filter_tree = lambda: None
        self.d.pending, self.d.requests, self.d.active_loads, self.d.generation = [], set(), 0, 0
        self.d.changing_checks = False
        self.d.metadata_cache, self.d.metadata_waiters = {}, {}
        self.calls = []
        self.d.fetch = lambda url, callback, generation: self.calls.append((url, callback, generation))

    def service(self, suffix='FeatureServer'):
        return self.d.node(None, 'Example', 'Service', BASE + '/Example/' + suffix, lazy=True)

    def test_single_service_becomes_checkable_without_child(self):
        item = self.service()
        self.d.loaded(item, {'layers': [{'id': 7, 'name': 'Parcels'}]}, None)
        self.assertEqual(item.childCount(), 0)
        self.assertEqual(item.check, UNCHECKED)
        self.assertEqual(item.data(0, ROLE)['record']['id'], '7')
        self.assertTrue(item.data(0, ROLE)['url'].endswith('/FeatureServer/7'))
        self.assertFalse(item.data(0, ROLE)['lazy'])

    def test_multiple_layers_and_nested_groups_collapsed(self):
        item = self.service('MapServer')
        self.d.loaded(item, {'layers': [
            {'id': 1, 'name': 'Hazards', 'subLayerIds': [4, 9]},
            {'id': 4, 'name': 'Flood', 'parentLayerId': 1},
            {'id': 9, 'name': 'Fire', 'parentLayerId': 1}]}, None)
        self.assertFalse(item.expanded)
        self.assertEqual(item.check, UNCHECKED)
        group = item.child(0)
        self.assertFalse(group.expanded)
        self.assertEqual(group.childCount(), 2)
        self.assertEqual(group.child(0).check, UNCHECKED)

    def test_layer_and_table_remain_separate(self):
        item = self.service()
        self.d.loaded(item, {'layers': [{'id': 0, 'name': 'Parcels'}],
                             'tables': [{'id': 5, 'name': 'Owners'}]}, None)
        self.assertFalse(item.expanded)
        self.assertEqual(item.childCount(), 2)
        self.assertTrue(item.child(1).data(0, ROLE)['record']['table'])

    def test_automatic_discovery_limits_concurrency_and_keeps_folders_lazy(self):
        root = self.d.node(None, 'Root', 'Endpoint', BASE, lazy=True)
        self.d.loaded(root, {'folders': ['Other'], 'services': [
            {'name': 'Service' + str(i), 'type': 'FeatureServer'} for i in range(10)]}, None)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(self.d.active_loads, 4)
        self.assertEqual(len(self.d.pending), 6)
        self.assertFalse(root.child(0).data(0, ROLE)['loading'])
        self.calls[0][1]({'layers': [{'id': 0, 'name': 'Ready'}]}, None)
        self.assertEqual(len(self.calls), 5)
        self.assertEqual(self.d.active_loads, 4)
        self.assertEqual(root.child(1).check, UNCHECKED)

    def test_failure_keeps_retry_and_releases_queue_slot(self):
        item = self.service()
        self.d.expand(item)
        self.calls[0][1](None, 'Service unavailable')
        self.assertTrue(item.data(0, ROLE)['lazy'])
        self.assertFalse(item.data(0, ROLE)['loading'])
        self.assertEqual(self.d.active_loads, 0)
        self.d.expand(item)
        self.assertEqual(len(self.calls), 2)

    def test_old_callback_does_not_modify_new_tree(self):
        item = self.service()
        self.d.expand(item)
        self.d.generation += 1
        self.d.active_loads = 0
        self.calls[0][1]({'layers': [{'id': 0, 'name': 'Stale'}]}, None)
        self.assertIsNone(item.check)
        self.assertEqual(self.d.active_loads, 0)

    def test_group_select_all_and_partial_selection(self):
        item = self.service()
        self.d.loaded(item, {'layers': [
            {'id': 1, 'name': 'Group', 'subLayerIds': [4, 9]},
            {'id': 4, 'name': 'survey', 'parentLayerId': 1},
            {'id': 9, 'name': 'survey', 'parentLayerId': 1}]}, None)
        item.setCheckState(0, CHECKED)
        self.d.check_changed(item, 0)
        group = item.child(0)
        self.assertEqual(group.check, CHECKED)
        self.assertEqual([n.check for n in self.d.leaf_items(item)], [CHECKED, CHECKED])
        group.child(0).setCheckState(0, UNCHECKED)
        self.d.check_changed(group.child(0), 0)
        self.assertEqual(group.check, PARTIAL)
        self.assertEqual(item.check, PARTIAL)
        group.setCheckState(0, UNCHECKED)
        self.d.check_changed(group, 0)
        self.assertEqual(item.check, UNCHECKED)
        self.assertEqual([n.check for n in self.d.leaf_items(item)], [UNCHECKED, UNCHECKED])

    def test_counts_and_service_name_fallback(self):
        item = self.service()
        self.d.loaded(item, {'layers': [{'id': 0, 'name': 'survey'}],
                             'tables': [{'id': 3, 'name': 'Repeats'}]}, None)
        self.assertEqual(item.text(3), '1 layer; 1 table')
        self.assertEqual(item.child(0).text(1), 'Example')
        self.assertEqual(item.child(1).text(3), '1 table')
        root = self.d.node(None, 'Root', 'Endpoint', BASE, lazy=True)
        self.d.loaded(root, {'folders': ['A'], 'services': [
            {'name': 'Example', 'type': 'FeatureServer'},
            {'name': 'Other', 'type': 'ImageServer'}]}, None)
        self.assertEqual(root.text(3), '2 services; 1 folder')

    def test_public_item_title_replaces_service_fallback(self):
        item = self.d.node(None, 'Survey', 'Service',
                          'https://services1.arcgis.com/org/arcgis/rest/services/Example/FeatureServer', lazy=True)
        item_id = 'a' * 32
        self.d.loaded(item, {'serviceItemId': item_id, 'layers': [{'id': 0, 'name': 'survey'}]}, None)
        self.assertEqual(item.text(1), 'Example')
        self.assertEqual(self.calls[0][0], 'https://www.arcgis.com/sharing/rest/content/items/' + item_id)
        self.calls[0][1]({'title': 'California Coastal Access Survey'}, None)
        self.assertEqual(item.text(1), 'California Coastal Access Survey')
        self.assertEqual(item.text(0), 'survey')

    def test_portal_discovery_and_failed_title_fallback(self):
        item = self.service()
        self.d.loaded(item, {'serviceItemId': 'b' * 32, 'layers': [{'id': 0, 'name': 'survey'}]}, None)
        self.assertEqual(self.calls[0][0], 'https://host/arcgis/rest/info')
        self.calls[0][1]({'owningSystemUrl': 'https://portal.example.org/portal'}, None)
        self.assertTrue(self.calls[1][0].startswith('https://portal.example.org/portal/sharing/rest/content/items/'))
        self.calls[1][1](None, 'Item is not public')
        self.assertEqual(item.text(1), 'Example')
        self.assertEqual(item.check, UNCHECKED)

    def test_home_to_directories_to_service_layers(self):
        home = 'https://coastalcomm.maps.arcgis.com'
        org = 'wwVnNW92ZHUIr0V0'
        item = self.d.node(None, 'Organization', 'Endpoint', home, lazy=True)
        self.d.expand(item)
        self.assertEqual(self.calls[0][0], home + '/sharing/rest/portals/self')
        self.calls[0][1]({'id': org, 'name': 'Coastal Commission'}, None)
        params = dict(parse_qsl(urlsplit(self.calls[1][0]).query))
        self.assertIn('orgid:' + org, params['q'])
        directory = f'https://services2.arcgis.com/{org}/arcgis/rest/services'
        self.calls[1][1]({'results': [{'url': directory + '/Parcels/FeatureServer'}]}, None)
        self.assertEqual(item.text(0), 'Coastal Commission')
        self.assertEqual(item.childCount(), 1)
        self.assertEqual(item.child(0).data(0, ROLE)['url'], directory)
        self.assertTrue(item.child(0).expanded)
        self.assertEqual(self.calls[2][0], directory)
        self.calls[2][1]({'services': [{'name': 'Parcels', 'type': 'FeatureServer'}]}, None)
        self.calls[3][1]({'layers': [{'id': 3, 'name': 'survey'}]}, None)
        leaf = item.child(0).child(0)
        self.assertEqual(leaf.check, UNCHECKED)
        self.assertTrue(leaf.data(0, ROLE)['url'].endswith('/FeatureServer/3'))

    def test_no_public_services_is_retryable(self):
        item = self.d.node(None, 'Org', 'Endpoint', 'https://example.maps.arcgis.com', lazy=True)
        self.d.expand(item)
        self.calls[0][1]({'id': 'a' * 16}, None)
        self.calls[1][1]({'results': []}, None)
        self.assertTrue(item.data(0, ROLE)['lazy'])
        self.assertFalse(item.data(0, ROLE)['loading'])
        self.assertEqual(item.text(3), 'Unavailable')
        self.assertEqual(self.d.active_loads, 0)
        self.d.expand(item)
        self.assertEqual(len(self.calls), 3)

    def test_missing_organization_id(self):
        item = self.d.node(None, 'Org', 'Endpoint', 'https://example.maps.arcgis.com', lazy=True)
        self.d.expand(item)
        self.calls[0][1]({'id': None}, None)
        self.assertTrue(item.data(0, ROLE)['lazy'])
        self.assertEqual(len(self.calls), 1)

    def test_hub_catalog_includes_non_agol_services(self):
        home = 'https://gisdata-caltrans.opendata.arcgis.com'
        root = self.d.node(None, 'Hub', 'Endpoint', home, lazy=True)
        self.d.expand(root)
        self.assertEqual(self.calls[0][0], 'https://hub.arcgis.com/api/v3/domains/gisdata-caltrans.opendata.arcgis.com')
        self.calls[0][1]({'siteId': 'a' * 32}, None)
        self.calls[1][1]({'title': 'Caltrans Home'}, None)
        self.calls[2][1]({'catalog': {'groups': ['b' * 32]}}, None)
        self.assertIn('group:' + 'b' * 32, dict(parse_qsl(urlsplit(self.calls[3][0]).query))['q'])
        url = 'https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHboundary/Districts/FeatureServer/0'
        self.calls[3][1]({'results': [{'type': 'Feature Service', 'title': 'Caltrans Districts', 'url': url}]}, None)
        self.assertEqual(root.text(3), '1 service entry')
        self.assertEqual(self.calls[4][0], url)
        self.calls[4][1]({'id': 0, 'name': 'survey'}, None)
        self.assertEqual(root.child(0).check, UNCHECKED)
        self.assertEqual(root.child(0).text(1), 'Caltrans Districts')
        self.assertEqual(root.child(0).data(0, ROLE)['url'], url)

    def test_hub_without_supported_catalog_can_retry(self):
        root = self.d.node(None, 'Hub', 'Endpoint', 'https://example.hub.arcgis.com', lazy=True)
        self.d.expand(root)
        self.calls[0][1]({'siteId': 'a' * 32}, None)
        self.calls[1][1]({'title': 'Empty site'}, None)
        self.calls[2][1]({}, None)
        self.assertTrue(root.data(0, ROLE)['lazy'])
        self.assertEqual(root.text(3), 'Unavailable')
        self.assertEqual(self.d.active_loads, 0)
        self.d.expand(root)
        self.assertEqual(len(self.calls), 4)


if __name__ == '__main__':
    unittest.main()
