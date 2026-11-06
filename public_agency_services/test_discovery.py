"""Discovery behavior tests using lightweight tree/network stand-ins, not a QGIS UI test."""
import ast
import pathlib
import re
import unittest
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit, quote, unquote, parse_qsl

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
names = {'normalize_url', 'service_parts', 'catalog_child', 'layer_groups', 'ServicesDialog'}
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


if __name__ == '__main__':
    unittest.main()
