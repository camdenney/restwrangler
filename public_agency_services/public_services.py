"""RestWrangler: QGIS GUI tool, no third-party Python packages.
Run this file from QGIS's Python Console editor, or install the plugin ZIP.
Designed for QGIS 3.40+ and Qt5/Qt6. See README.md for scope and validation.
License: MIT
"""
import json
import os
from qgis.PyQt.QtGui import QIcon
import re
from urllib.parse import urlsplit, urlunsplit, quote, unquote, parse_qsl, urlencode

from qgis.PyQt.QtCore import Qt, QUrl, QTimer, QSettings
from qgis.PyQt.QtNetwork import QNetworkRequest, QNetworkReply
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QCheckBox, QComboBox, QMessageBox,
    QProgressDialog, QAbstractItemView, QApplication,
)
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction
from qgis.core import (
    QgsNetworkAccessManager, QgsDataSourceUri, QgsVectorLayer,
    QgsRasterLayer, QgsProject, QgsLayerTreeGroup,
)

ROLE = Qt.ItemDataRole.UserRole
CHECKED = Qt.CheckState.Checked
UNCHECKED = Qt.CheckState.Unchecked
PARTIAL = Qt.CheckState.PartiallyChecked
SETTING = 'PublicAgencyServices/last_url'
ICON_PATH = os.path.join(os.path.dirname(globals().get('__file__', '')), 'icon.png')


def agol_home_url(text):
    """Recognize organization home URLs, not item pages or arbitrary hosts."""
    p = urlsplit(text.strip())
    host = (p.hostname or '').lower()
    if (p.scheme.lower() in ('http', 'https') and not p.username and not p.password
            and p.port in (None, 80, 443)
            and re.fullmatch(r'[a-z0-9-]+\.maps(?:\.[a-z0-9-]+)?\.arcgis\.com', host)
            and p.path.rstrip('/').lower() in ('', '/home', '/home/index.html')):
        return 'https://' + host
    return None


def hub_home_url(text):
    """Recognize ArcGIS-hosted Hub/Open Data site roots, not dataset pages."""
    p = urlsplit(text.strip())
    host = (p.hostname or '').lower()
    if (p.scheme.lower() in ('http', 'https') and not p.username and not p.password
            and p.port in (None, 80, 443) and p.path.rstrip('/') == ''
            and re.fullmatch(r'[a-z0-9-]+\.(?:opendata|hub)\.arcgis\.com', host)):
        return 'https://' + host
    return None


def hub_catalog_groups(site_data, site_item=None):
    """Read explicit legacy catalog groups, with content-group fallback."""
    groups = site_data.get('catalog', {}).get('groups', [])
    valid = [g for g in groups if isinstance(g, str) and re.fullmatch(r'[0-9a-fA-F]{32}', g)]
    if not valid and site_item:
        group = (site_item.get('properties') or {}).get('contentGroupId')
        if isinstance(group, str) and re.fullmatch(r'[0-9a-fA-F]{32}', group):
            valid.append(group)
    return list(dict.fromkeys(valid))


def catalog_service_items(results):
    """Keep supported public ArcGIS endpoints, including non-hosted agency servers."""
    services, seen = [], set()
    for row in results:
        if row.get('type') not in ('Feature Service', 'Map Service'):
            continue
        try:
            url = normalize_url(row.get('url') or '')
        except (ValueError, TypeError):
            continue
        parts = service_parts(url)
        if not parts or url in seen:
            continue
        seen.add(url)
        services.append({'url': url, 'title': row.get('title') or unquote(parts[0].rsplit('/', 2)[-2]),
                         'kind': parts[1]})
    return services


def hosted_directory_urls(items, organization_id):
    """Discover real hosts from matching hosted feature services; never guess a shard."""
    roots = set()
    for item in items:
        url = item.get('url')
        if not isinstance(url, str):
            continue
        p = urlsplit(url)
        host = (p.hostname or '').lower()
        if (p.scheme.lower() not in ('http', 'https') or not host.endswith('.arcgis.com')
                or p.username or p.password or p.query or p.fragment):
            continue
        match = re.fullmatch(r'/([^/]+)/arcgis/rest/services/.+/FeatureServer(?:/\d+)?/?', p.path, re.I)
        if match and match[1] == organization_id:
            roots.add(urlunsplit(('https', p.netloc, '/' + organization_id + '/arcgis/rest/services', '', '')))
    return sorted(roots)


def json_request_url(url, start=None):
    """Preserve encoded search parameters while replacing format/paging parameters."""
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query) if k not in ('f', 'start')]
    query.append(('f', 'json'))
    if start is not None:
        query.append(('start', str(start)))
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), ''))


def merge_metadata_pages(previous, current):
    merged = dict(current)
    for key in ('services', 'results'):
        if key in previous or key in current:
            merged[key] = previous.get(key, []) + current.get(key, [])
    if 'folders' in previous or 'folders' in current:
        merged['folders'] = list(dict.fromkeys(previous.get('folders', []) + current.get('folders', [])))
    return merged


def normalize_url(text):
    """Accept service-directory, folder, service, or numeric layer endpoints."""
    p = urlsplit(text.strip())
    if p.scheme.lower() not in ('http', 'https') or not p.netloc or p.username or p.password:
        raise ValueError('Enter a full http(s) REST services URL without credentials.')
    if any(k.lower() != 'f' for k, _ in parse_qsl(p.query, keep_blank_values=True)):
        raise ValueError('Use a public endpoint without tokens or other query parameters. Only ?f=json is accepted.')
    home = agol_home_url(text) or hub_home_url(text)
    if home:
        return home
    path = p.path.rstrip('/')
    if not re.search(r'/rest/services(?:/|$)', path, re.I):
        raise ValueError('Enter an AGOL home URL, an ArcGIS Hub/Open Data site root, or a REST services URL. Enterprise Portal home URLs, custom-domain sites, and item/dataset pages are not supported.')
    match = re.search(r'/(FeatureServer|MapServer)(?:/(\d+))?$', path, re.I)
    if match:
        canonical = 'FeatureServer' if match[1].lower() == 'featureserver' else 'MapServer'
        path = path[:match.start()] + '/' + canonical + ('/' + match[2] if match[2] else '')
    return urlunsplit((p.scheme.lower(), p.netloc, path, '', ''))


def service_parts(url):
    m = re.search(r'/(FeatureServer|MapServer)(?:/(\d+))?$', url)
    if not m:
        return None
    base = url[:m.start()] + '/' + m[1]
    return base, m[1], m[2]


def catalog_child(url, name):
    """ArcGIS names can be root-relative (Folder/Service) or local."""
    m = re.search(r'/rest/services(?:/|$)', url, re.I)
    root = url[:m.start()] + '/rest/services'
    folder = unquote(url[len(root):].strip('/'))
    name = str(name).strip('/')
    if folder and not name.startswith(folder + '/'):
        name = folder + '/' + name
    return root + '/' + quote(name, safe='/')


def layer_groups(layer, by_id):
    """Parent chain with protection against malformed service cycles."""
    groups, seen = [], {layer.get('id')}
    pid = layer.get('parentLayerId', -1)
    while pid in by_id and pid not in seen:
        seen.add(pid)
        parent = by_id[pid]
        groups.insert(0, parent.get('name', str(pid)))
        pid = parent.get('parentLayerId', -1)
    return groups


def direct_group(parent, name):
    for child in parent.children():
        if isinstance(child, QgsLayerTreeGroup) and child.name() == name:
            return child
    return parent.addGroup(name)


class ServicesDialog(QDialog):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.setWindowTitle('RestWrangler → QGIS')
        self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(1180, 680)
        self.requests = set()
        self.metadata_cache = {}
        self.metadata_waiters = {}
        self.changing_checks = False
        self.pending = []
        self.active_loads = 0
        self.generation = 0
        self.adding = False
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('AGOL home, ArcGIS Hub/Open Data site, or public REST services URL:'))
        bar = QHBoxLayout()
        self.url = QLineEdit(str(QSettings().value(SETTING, '')))
        self.url.setPlaceholderText('https://your-agency.maps.arcgis.com/home/index.html or https://…/rest/services')
        self.browse = QPushButton('Browse')
        bar.addWidget(self.url, 1)
        bar.addWidget(self.browse)
        layout.addLayout(bar)
        layout.addWidget(QLabel('Check a layer or a service group to select all its layers. Groups stay collapsed; open them to select individual layers.'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter discovered layers and services…')
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Layer / group', 'Item / service name', 'Type', 'Count', 'REST URL'])
        self.style_checkboxes()
        self.tree.setColumnWidth(0, 280)
        self.tree.setColumnWidth(1, 290)
        self.tree.setColumnWidth(2, 120)
        self.tree.setColumnWidth(3, 170)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.tree, 1)
        bar = QHBoxLayout()
        for title, callback in [('Check visible layers', lambda: self.check_visible(True)),
                                ('Uncheck all', lambda: self.check_visible(False))]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            bar.addWidget(button)
        bar.addStretch()
        layout.addLayout(bar)
        bar = QHBoxLayout()
        bar.addWidget(QLabel('Destination group path:'))
        self.group = QLineEdit('Agency public layers')
        self.group.setPlaceholderText('e.g. Coastal Commission / Hazards (blank = project root)')
        bar.addWidget(self.group, 1)
        layout.addLayout(bar)
        bar = QHBoxLayout()
        self.preserve = QCheckBox('Preserve folders, service names, and service subgroups')
        self.preserve.setChecked(True)
        bar.addWidget(self.preserve)
        bar.addWidget(QLabel('MapServer layers:'))
        self.mode = QComboBox()
        self.mode.addItems(['Map images (server styling)', 'Vector features (queryable layers only)'])
        bar.addWidget(self.mode)
        layout.addLayout(bar)
        bar = QHBoxLayout()
        self.visible = QCheckBox('Turn added layers on')
        self.visible.setChecked(False)
        self.skip = QCheckBox('Skip connections already in project')
        self.skip.setChecked(True)
        bar.addWidget(self.visible)
        bar.addWidget(self.skip)
        bar.addStretch()
        layout.addLayout(bar)
        self.status = QLabel('Ready. Public FeatureServer and MapServer services supported.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        bar = QHBoxLayout()
        self.add = QPushButton('Add checked layers')
        close = QPushButton('Close')
        bar.addStretch()
        bar.addWidget(self.add)
        bar.addWidget(close)
        layout.addLayout(bar)
        self.browse.clicked.connect(self.start)
        self.url.returnPressed.connect(self.start)
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemChanged.connect(self.check_changed)
        self.search.textChanged.connect(self.filter_tree)
        self.add.clicked.connect(self.add_layers)
        close.clicked.connect(self.close)

    def style_checkboxes(self):
        """Explicit high-contrast states for native Windows and dark themes."""
        folder = os.path.dirname(ICON_PATH)
        checked = os.path.abspath(os.path.join(folder, 'checkmark.svg')).replace(chr(92), '/')
        partial = os.path.abspath(os.path.join(folder, 'partial.svg')).replace(chr(92), '/')
        self.tree.setStyleSheet("""
            QTreeWidget::indicator { width: 18px; height: 18px; margin: 2px;
                border: 2px solid #64748b; border-radius: 3px; }
            QTreeWidget::indicator:unchecked { background-color: #ffffff; }
            QTreeWidget::indicator:unchecked:hover { background-color: #e0f2fe; border-color: #0284c7; }
            QTreeWidget::indicator:checked { background-color: #15803d; border-color: #86efac;
                image: url("%s"); }
            QTreeWidget::indicator:indeterminate { background-color: #b45309; border-color: #fcd34d;
                image: url("%s"); }
        """ % (checked, partial))

    def items(self):
        def walk(parent):
            for i in range(parent.childCount()):
                child = parent.child(i)
                yield child
                yield from walk(child)
        return walk(self.tree.invisibleRootItem())

    def node(self, parent, name, kind, url='', groups=None, record=None, lazy=False):
        item = QTreeWidgetItem(parent, [name, '', kind, '…' if lazy else '', url])
        item.setToolTip(0, url)
        data = {'url': url, 'groups': groups or [], 'record': record,
                'lazy': lazy, 'loading': False}
        item.setData(0, ROLE, data)
        if record:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, UNCHECKED)
        if lazy:
            QTreeWidgetItem(item, ['Expand to load…'])
        return item

    def cancel_requests(self):
        self.generation += 1
        self.pending.clear()
        self.metadata_cache.clear()
        self.metadata_waiters.clear()
        self.active_loads = 0
        for item in self.items():
            data = item.data(0, ROLE)
            if data and data.get('loading'):
                data['loading'] = False
                item.setData(0, ROLE, data)
        for reply in list(self.requests):
            reply.abort()

    def start(self):
        if self.adding:
            return
        try:
            url = normalize_url(self.url.text())
        except ValueError as exc:
            QMessageBox.warning(self, 'REST URL', str(exc))
            return
        self.cancel_requests()
        self.tree.clear()
        self.search.clear()
        QSettings().setValue(SETTING, url)
        root = self.node(self.tree, unquote(url.rsplit('/', 1)[-1]), 'Endpoint', url, lazy=True)
        root.setExpanded(True)

    def expand(self, item):
        data = item.data(0, ROLE)
        if not data or not data['lazy'] or data['loading']:
            return
        data['loading'] = True
        item.setData(0, ROLE, data)
        self.status.setText('Loading ' + data['url'])
        if item.childCount():
            item.child(0).setText(0, 'Discovering layers…')
        if hub_home_url(data['url']):
            self.resolve_hub(item, data['url'])
        elif agol_home_url(data['url']):
            self.resolve_organization(item, data['url'])
        else:
            self.pending.append((data['url'], lambda result, error: self.loaded(item, result, error)))
            self.pump_loads()

    def resolve_hub(self, item, home):
        attempted = []
        def failed(message):
            for url in attempted:
                self.metadata_cache.pop(url, None)
            self.loaded(item, None, message)
        def request(url, callback):
            attempted.append(url)
            self.cached_metadata(url, callback)
        def domain_ready(domain, error):
            if error:
                failed('Could not resolve the ArcGIS Hub/Open Data site: ' + error)
                return
            site_id = domain.get('siteId') or domain.get('itemId')
            if not isinstance(site_id, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', site_id):
                failed('The Hub domain response did not identify a site item. Paste a REST services URL directly.')
                return
            base = 'https://www.arcgis.com/sharing/rest/content/items/' + site_id
            def item_ready(site_item, item_error):
                if item_error:
                    failed('Could not read the public Hub site item: ' + item_error)
                    return
                def data_ready(site_data, data_error):
                    if data_error:
                        failed('Could not read the public Hub catalog: ' + data_error)
                        return
                    groups = hub_catalog_groups(site_data, site_item)
                    if not groups:
                        failed('This site does not expose a supported group-based catalog. Paste an AGOL home URL or REST services URL directly.')
                        return
                    query = '(' + ' OR '.join('group:' + g for g in groups) + ') AND (type:"Feature Service" OR type:"Map Service")'
                    search_url = 'https://www.arcgis.com/sharing/rest/search?' + urlencode({'q': query, 'num': 100})
                    def search_ready(search, search_error):
                        if search_error:
                            failed('Could not search the public Hub catalog: ' + search_error)
                            return
                        services = catalog_service_items(search.get('results', []))
                        if not services:
                            failed('No public FeatureServer or MapServer entries were found in this site catalog.')
                            return
                        self.loaded(item, {'catalog_services': services, 'name': site_item.get('title') or domain.get('siteTitle') or home}, None)
                    request(search_url, search_ready)
                request(base + '/data', data_ready)
            request(base, item_ready)
        request('https://hub.arcgis.com/api/v3/domains/' + quote(urlsplit(home).hostname, safe=''), domain_ready)

    def resolve_organization(self, item, home):
        def failed(message):
            # Allow a collapse/expand retry to issue fresh metadata requests.
            self.metadata_cache.pop(home + '/sharing/rest/portals/self', None)
            self.loaded(item, None, message)

        def organization_ready(result, error):
            if error:
                failed('Could not read the AGOL organization: ' + error)
                return
            org_id = result.get('id')
            if not isinstance(org_id, str) or not re.fullmatch(r'[A-Za-z0-9]{16}', org_id):
                failed('No organization ID was returned. Use an AGOL organization home URL or paste a REST services URL directly.')
                return
            query = f'orgid:{org_id} AND type:"Feature Service" AND typekeywords:"Hosted Service"'
            search_url = home + '/sharing/rest/search?' + urlencode({'q': query, 'num': 100})
            self.status.setText('Discovering public hosted services for ' + result.get('name', org_id))

            def services_ready(search, search_error):
                if search_error:
                    self.metadata_cache.pop(search_url, None)
                    failed('Could not search public hosted services: ' + search_error)
                    return
                roots = hosted_directory_urls(search.get('results', []), org_id)
                if not roots:
                    self.metadata_cache.pop(search_url, None)
                    failed('No public hosted feature-service directory was found for this organization. Paste a known REST services URL directly; private services require sign-in and are not supported.')
                    return
                self.loaded(item, {'directories': roots, 'name': result.get('name', org_id)}, None)
            self.cached_metadata(search_url, services_ready)
        self.cached_metadata(home + '/sharing/rest/portals/self', organization_ready)

    def pump_loads(self):
        # Limit concurrent service metadata requests for large agency catalogs.
        while self.pending and self.active_loads < 4:
            url, callback = self.pending.pop(0)
            generation = self.generation
            self.active_loads += 1

            def complete(result, error, callback=callback, epoch=generation):
                if epoch != self.generation:
                    return
                try:
                    callback(result, error)
                finally:
                    self.active_loads -= 1
                    self.pump_loads()
            self.fetch(url, complete, generation)

    def fetch(self, url, callback, generation, start=None, accumulated=None):
        request = QNetworkRequest(QUrl(json_request_url(url, start)))
        reply = QgsNetworkAccessManager.instance().get(request)
        self.requests.add(reply)
        timer = QTimer(reply)
        timer.setSingleShot(True)
        timer.timeout.connect(reply.abort)
        timer.start(45000)

        def finish():
            timer.stop()
            self.requests.discard(reply)
            try:
                if generation != self.generation:
                    return
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    raise ValueError(reply.errorString() + ' (request timeout: 45 seconds)')
                result = json.loads(bytes(reply.readAll()).decode('utf-8-sig'))
                if not isinstance(result, dict):
                    raise ValueError('Expected an ArcGIS JSON object.')
                if result.get('error'):
                    err = result['error']
                    raise ValueError(str(err.get('message', err)) + ': ' + '; '.join(err.get('details') or []))
                if accumulated:
                    result = merge_metadata_pages(accumulated, result)
                next_start = result.get('nextStart', -1)
                if isinstance(next_start, int) and next_start > 0:
                    if start is not None and next_start <= start:
                        raise ValueError('The server returned a non-advancing pagination cursor.')
                    self.fetch(url, callback, generation, next_start, result)
                    return
                callback(result, None)
            except Exception as exc:
                callback(None, str(exc))
            finally:
                reply.deleteLater()
        reply.finished.connect(finish)

    def loaded(self, item, result, error):
        data = item.data(0, ROLE)
        data['loading'] = False
        item.takeChildren()
        if error:
            item.setData(0, ROLE, data)
            QTreeWidgetItem(item, ['Load failed. Collapse and expand to retry.', '', error])
            item.setText(3, 'Unavailable')
            self.status.setText(error)
            return
        try:
            self.populate(item, result, data)
            data['lazy'] = False
            item.setData(0, ROLE, data)
            if service_parts(data['url']):
                self.configure_service(item)
                if data.get('catalog_title'):
                    self.set_service_title(item, data['catalog_title'], 'Public item title from the Hub site catalog.')
                else:
                    self.resolve_item_title(item, result)
            self.status.setText('Layers ready. Remaining service checks: ' +
                                str(len(self.pending) + max(0, self.active_loads - 1)))
        except Exception as exc:
            item.takeChildren()
            QTreeWidgetItem(item, [str(exc)])
            item.setData(0, ROLE, data)
            self.status.setText(str(exc))
        self.filter_tree()

    def populate(self, item, result, data):
        url, groups = data['url'], data['groups']
        if hub_home_url(url):
            services = result['catalog_services']
            item.setText(0, result['name'])
            item.setText(2, 'Hub / Open Data')
            item.setText(3, str(len(services)) + (' service entry' if len(services) == 1 else ' service entries'))
            item.setToolTip(3, 'Distinct supported service/layer URLs in the public site catalog; not every service owned by the organization.')
            for service in services:
                child = self.node(item, service['title'], service['kind'], service['url'], groups, lazy=True)
                info = child.data(0, ROLE)
                info['catalog_title'] = service['title']
                child.setData(0, ROLE, info)
                child.setText(1, service['title'])
                self.expand(child)
            return
        if agol_home_url(url):
            directories = result['directories']
            item.setText(0, result['name'])
            item.setText(2, 'AGOL organization')
            item.setText(3, str(len(directories)) + ' service director' + ('y' if len(directories) == 1 else 'ies'))
            for directory in directories:
                child = self.node(item, urlsplit(directory).netloc, 'Services directory', directory, lazy=True)
                child.setExpanded(True)
                self.expand(child)
            return
        parts = service_parts(url)
        if not parts:
            if 'services' not in result and 'folders' not in result:
                raise ValueError('This is not an ArcGIS services directory. Use a /rest/services endpoint.')
            services, folders = result.get('services', []), result.get('folders', [])
            item.setText(3, f'{len(services)} service' + ('s' if len(services) != 1 else '') +
                         f'; {len(folders)} folder' + ('s' if len(folders) != 1 else ''))
            item.setToolTip(3, 'Direct children only; includes unsupported service types. Subfolder contents are not included.')
            for folder in folders:
                self.node(item, folder.rsplit('/', 1)[-1], 'Folder', catalog_child(url, folder),
                          groups + [folder.rsplit('/', 1)[-1]], lazy=True)
            for service in result.get('services', []):
                name, kind = service['name'], service['type']
                child_url = catalog_child(url, name) + '/' + kind
                service_node = self.node(item, name.rsplit('/', 1)[-1], kind if kind in ('FeatureServer', 'MapServer') else kind + ' (unsupported)',
                                         child_url, groups, lazy=kind in ('FeatureServer', 'MapServer'))
                if kind in ('FeatureServer', 'MapServer'):
                    self.expand(service_node)
            return
        base, kind, layer_id = parts
        service_name = unquote(base.rsplit('/', 2)[-2])
        if layer_id is not None:
            if result.get('subLayers') or result.get('subLayerIds'):
                raise ValueError('For a group layer, browse the parent ' + kind + ' URL instead.')
            rows = [dict(result, id=int(layer_id))]
        else:
            rows = result.get('layers', []) + [dict(t, type='Table') for t in result.get('tables', [])]
        by_id = {row['id']: row for row in rows}
        group_nodes = {}
        selectable = [row for row in rows if not (
            row.get('subLayerIds') or row.get('subLayers') or row.get('type') == 'Group Layer')]
        for row in selectable:
            ancestry = layer_groups(row, by_id)
            parent = item
            for depth, name in enumerate(ancestry):
                key = tuple(ancestry[:depth + 1])
                if key not in group_nodes:
                    group_nodes[key] = self.node(parent, name, 'Service group')
                parent = group_nodes[key]
            record = {'base': base, 'kind': kind, 'id': str(row['id']),
                      'table': row.get('type') == 'Table', 'name': row.get('name', str(row['id']))}
            layer_url = base + '/' + record['id']
            if len(selectable) == 1:
                # Reuse the service row as the selectable layer; no redundant dropdown.
                item.takeChildren()
                data.update(record=record, url=layer_url,
                            groups=groups + [service_name] + ancestry)
                item.setText(0, record['name'])
                item.setText(2, 'Table' if record['table'] else kind)
                item.setText(4, layer_url)
                item.setToolTip(0, service_name + '\n' + layer_url)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, UNCHECKED)
            else:
                self.node(parent, record['name'], 'Table' if record['table'] else kind,
                          layer_url, groups + [service_name] + ancestry, record)
        if not selectable:
            QTreeWidgetItem(item, ['No selectable layers or tables listed.'])
        self.set_service_title(item, service_name, 'REST service name (fallback when an item title is unavailable).')

    def leaf_items(self, item):
        data = item.data(0, ROLE) or {}
        if data.get('record'):
            yield item
        for i in range(item.childCount()):
            yield from self.leaf_items(item.child(i))

    def configure_service(self, item):
        """Count selectable leaves; only fully loaded service groups get checkboxes."""
        previous = self.changing_checks
        self.changing_checks = True
        try:
            def configure(node):
                data = node.data(0, ROLE)
                if not data:
                    return
                leaves = list(self.leaf_items(node))
                tables = sum(bool(leaf.data(0, ROLE)['record']['table']) for leaf in leaves)
                layers = len(leaves) - tables
                counts = []
                if layers:
                    counts.append(f'{layers} layer' + ('s' if layers != 1 else ''))
                if tables:
                    counts.append(f'{tables} table' + ('s' if tables != 1 else ''))
                node.setText(3, '; '.join(counts) or '0 layers')
                if not data.get('record') and leaves:
                    data['check_group'] = True
                    node.setData(0, ROLE, data)
                    node.setFlags(node.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    node.setCheckState(0, UNCHECKED)
                    node.setToolTip(0, 'Check to select all layers and tables in this group, including filtered-out layers.')
                    node.setExpanded(False)
                for i in range(node.childCount()):
                    configure(node.child(i))
            configure(item)
        finally:
            self.changing_checks = previous

    def check_changed(self, item, column):
        if column != 0 or self.changing_checks:
            return
        data = item.data(0, ROLE) or {}
        if not (data.get('record') or data.get('check_group')):
            return
        self.changing_checks = True
        try:
            if data.get('check_group'):
                state = CHECKED if item.checkState(0) == CHECKED else UNCHECKED
                for leaf in self.leaf_items(item):
                    leaf.setCheckState(0, state)
            # Recompute groups bottom-up, including nested groups and ancestors.
            root = item
            while root.parent() is not None:
                root = root.parent()
            def update(node):
                for i in range(node.childCount()):
                    update(node.child(i))
                info = node.data(0, ROLE) or {}
                if info.get('check_group'):
                    states = [leaf.checkState(0) for leaf in self.leaf_items(node)]
                    state = (CHECKED if states and all(s == CHECKED for s in states)
                             else UNCHECKED if all(s == UNCHECKED for s in states) else PARTIAL)
                    node.setCheckState(0, state)
            update(root)
        finally:
            self.changing_checks = False

    def set_service_title(self, item, title, explanation):
        item.setText(1, title)
        item.setToolTip(1, explanation)
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, ROLE):
                self.set_service_title(child, title, explanation)

    def cached_metadata(self, url, callback):
        if url in self.metadata_cache:
            callback(*self.metadata_cache[url])
            return
        if url in self.metadata_waiters:
            self.metadata_waiters[url].append(callback)
            return
        self.metadata_waiters[url] = [callback]
        def received(result, error):
            self.metadata_cache[url] = (result, error)
            for waiter in self.metadata_waiters.pop(url, []):
                waiter(result, error)
        self.pending.append((url, received))
        self.pump_loads()

    def resolve_item_title(self, item, service):
        """Public item title when discoverable; REST service name remains the fallback."""
        item_id = service.get('serviceItemId', '')
        if not re.fullmatch(r'[0-9a-fA-F]{32}', str(item_id)):
            return
        base = service_parts(item.data(0, ROLE)['url'])[0]
        def from_portal(portal):
            portal = str(portal or '').rstrip('/')
            parsed = urlsplit(portal)
            if parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.username or parsed.password or parsed.query:
                return
            item_url = portal + '/sharing/rest/content/items/' + item_id
            def title_ready(result, error):
                if not error and result.get('title'):
                    self.set_service_title(item, str(result['title']), 'Public ArcGIS item title: ' + item_url)
                    self.filter_tree()
            self.cached_metadata(item_url, title_ready)
        host = (urlsplit(base).hostname or '').lower()
        if host.endswith('.arcgis.com'):
            from_portal('https://www.arcgis.com')
        elif service.get('owningSystemUrl'):
            from_portal(service['owningSystemUrl'])
        else:
            prefix = re.split(r'/rest/services(?:/|$)', base, flags=re.I)[0]
            def info_ready(result, error):
                if not error:
                    from_portal(result.get('owningSystemUrl'))
            self.cached_metadata(prefix + '/rest/info', info_ready)

    def filter_tree(self, *args):
        needle = self.search.text().strip().casefold()
        def visit(item, inherited=False):
            own = inherited or not needle or any(needle in item.text(col).casefold() for col in (0, 1))
            child_matches = [visit(item.child(i), own) for i in range(item.childCount())]
            match = own or any(child_matches)
            item.setHidden(not match)
            return match
        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def check_visible(self, checked):
        for item in self.items():
            data = item.data(0, ROLE)
            if data and data.get('record') and (not checked or not item.isHidden()):
                item.setCheckState(0, CHECKED if checked else UNCHECKED)

    def add_layers(self):
        selected = [i for i in self.items() if i.data(0, ROLE) and
                    i.data(0, ROLE).get('record') and i.checkState(0) == CHECKED]
        if not selected:
            QMessageBox.information(self, 'Select layers', 'Wait for services to load, then check at least one layer.')
            return
        project = QgsProject.instance()
        known = {(lyr.providerType(), lyr.source()) for lyr in project.mapLayers().values()}
        successes, skipped, failures = 0, 0, []
        self.adding = True
        self.setEnabled(False)
        progress = QProgressDialog('Connecting to layers…', 'Stop', 0, len(selected), self.iface.mainWindow())
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        try:
            for index, item in enumerate(selected):
                progress.setValue(index)
                progress.setLabelText('Connecting: ' + item.text(0))
                QApplication.processEvents()
                if progress.wasCanceled():
                    break
                data = item.data(0, ROLE)
                rec = data['record']
                try:
                    uri = QgsDataSourceUri()
                    raster = rec['kind'] == 'MapServer' and self.mode.currentIndex() == 0 and not rec['table']
                    if raster:
                        uri.setParam('url', rec['base'])
                        uri.setParam('layer', rec['id'])
                        uri.setParam('format', 'png32')
                        provider = 'arcgismapserver'
                    else:
                        uri.setParam('url', rec['base'] + '/' + rec['id'])
                        provider = 'arcgisfeatureserver'
                    source = uri.uri(False)
                    if self.skip.isChecked() and (provider, source) in known:
                        skipped += 1
                        item.setCheckState(0, UNCHECKED)
                        continue
                    layer = (QgsRasterLayer if raster else QgsVectorLayer)(source, rec['name'], provider)
                    if not layer.isValid():
                        raise ValueError('QGIS provider could not open this layer. Check public access, query capability, or try Map images mode.')
                    if not raster:
                        layer.setReadOnly(True)
                    layer.setCustomProperty('PublicAgencyServices/restUrl', data['url'])
                    parent = project.layerTreeRoot()
                    path = [p.strip() for p in self.group.text().split('/') if p.strip()]
                    if self.preserve.isChecked():
                        path += data['groups']
                    for name in path:
                        parent = direct_group(parent, name)
                    project.addMapLayer(layer, False)
                    node = parent.addLayer(layer)
                    node.setItemVisibilityChecked(self.visible.isChecked())
                    known.add((provider, source))
                    known.add((provider, layer.source()))
                    item.setCheckState(0, UNCHECKED)
                    successes += 1
                except Exception as exc:
                    failures.append(rec['name'] + ': ' + str(exc))
            message = f'Added {successes}; skipped {skipped}; failed {len(failures)}.'
            if progress.wasCanceled():
                message += ' Stopped; completed additions were kept.'
            self.status.setText(message)
            if failures:
                box = QMessageBox(self)
                box.setWindowTitle('Layer results')
                box.setText(message)
                box.setDetailedText('\n'.join(failures))
                box.exec()
        finally:
            progress.close()
            self.setEnabled(True)
            self.adding = False
            self.iface.mapCanvas().refresh()

    def reject(self):
        if not self.adding:
            self.cancel_requests()
            super().reject()

    def closeEvent(self, event):
        if self.adding:
            event.ignore()
            return
        self.cancel_requests()
        super().closeEvent(event)


class PublicAgencyServicesPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dialog = None
        self.action = None

    def initGui(self):
        self.action = QAction(QIcon(ICON_PATH), 'RestWrangler…', self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu('RestWrangler', self.action)

    def run(self):
        if self.dialog is None:
            self.dialog = ServicesDialog(self.iface)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def unload(self):
        if self.dialog:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None
        if self.action:
            self.iface.removePluginMenu('RestWrangler', self.action)
            self.action.deleteLater()


def launch():
    """Keep a reference on iface so the console-launched dialog stays alive."""
    from qgis.utils import iface
    previous = getattr(iface, '_public_agency_services_dialog', None)
    if previous:
        previous.close()
        previous.deleteLater()
    dialog = ServicesDialog(iface)
    iface._public_agency_services_dialog = dialog
    dialog.show()
    return dialog


if __name__ in ('__main__', '__console__'):
    launch()
