# RestWrangler

<img src="public_agency_services/icon.png" alt="RestWrangler globe cowboy swinging a lasso" width="220">

**Wrangle ArcGIS REST services into organized, shareable QGIS projects.**

RestWrangler is a QGIS plugin for browsing public ArcGIS Online and ArcGIS Enterprise REST services, selecting layers, and organizing them in your current project. Build a starter project with an agency's essential public data, save it as a `.qgz`, and share it with colleagues. Recipients need QGIS and access to the service URLs, but do not need an Esri license or this plugin installed.

## Download and install

**[Download RestWrangler v0.5.1 — Preview](https://github.com/camdenney/restwrangler/raw/refs/heads/main/downloads/RestWrangler_QGIS.zip)**

1. Download the plugin ZIP above without extracting it.
2. In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select `RestWrangler_QGIS.zip`, install it, and enable **RestWrangler** if needed.
4. Open **Plugins → RestWrangler → RestWrangler…**.

When updating, reinstall the ZIP and restart QGIS. Use the plugin download above for installation; GitHub's **Code → Download ZIP** contains the whole development repository.

Designed for QGIS 3.40+ and QGIS 4.x. **Experimental preview:** syntax and simulated discovery tests have passed; full QGIS UI/provider compatibility has not yet been independently verified.

## Features

- Paste an ArcGIS Online organization home URL to discover its public hosted feature-service directories automatically.
- Browse ArcGIS Hub/Open Data site catalogs, including services on external agency servers.
- Use native checkboxes with approximately one point of extra row spacing.
- Browse public REST directories, folders, FeatureServer services, and MapServer services.
- Select single layers directly, or select every sublayer with a group checkbox.
- Keep groups collapsed, with partial checkmarks for mixed selections.
- Identify layers using public ArcGIS item titles, with service names as a fallback.
- See layer/table counts and direct service counts in opened folders.
- Add layers into custom nested groups or preserve their service hierarchy.
- Choose server-styled map images or queryable vectors for supported MapServer layers.
- Save live service connections in an ordinary QGIS project.

## Quick start

Paste an AGOL organization home URL such as `https://coastalcomm.maps.arcgis.com/home/index.html`, or a public REST URL ending in `/rest/services`, a directory folder, `/FeatureServer`, `/MapServer`, or an individual layer number. Open a folder, select layers or groups, choose a destination such as `Agency / Hazards`, and click **Add checked layers**. Layers are initially switched off unless you enable **Turn added layers on**.

AGOL organization home URLs, ArcGIS Hub/Open Data site roots, and REST service URLs are supported. For example, paste `https://gisdata-caltrans.opendata.arcgis.com/` or `https://data-cslc.opendata.arcgis.com/`. Site catalogs list public Feature Service and Map Service entries from their catalog groups; other content is omitted. Custom-domain sites and dataset pages are not yet supported. Enterprise Portal home pages, web maps, and item-details pages are not supported. The AGOL lookup reads the organization ID and searches public hosted feature-service items, preserving their actual service hostnames; it never guesses a `services` number. It lists distinct directories found across the search results. If no public hosted layers expose a matching directory, paste a REST services URL directly. The project uses live services; it does not download an offline copy of the data.

See the **[full user guide](public_agency_services/README.md)** for accepted URLs, grouping, troubleshooting, and known limitations.

## Scope

FeatureServer layers/tables and MapServer layers/tables are supported. ImageServer, vector tiles, scene services, private-service authentication, and ArcGIS web map import are not included. ArcGIS vector symbology may not translate exactly into QGIS. Service availability and performance depend on the hosting agency.

## Development

The plugin lives in `public_agency_services/`. The internal folder name is retained for compatibility with earlier installations.

Run the standard-library tests without QGIS:

```bash
python public_agency_services/test_helpers.py
python public_agency_services/test_discovery.py
```

These tests cover URL/group handling and simulated discovery/selection behavior. They do not replace testing in QGIS with live services.

Build an installable ZIP from the source:

```bash
python build_plugin.py
```

This writes `downloads/RestWrangler_QGIS.zip`. See the user guide for a live QGIS acceptance checklist. Report problems through [GitHub Issues](https://github.com/camdenney/restwrangler/issues), including your QGIS version, operating system, and a public service URL that reproduces the issue. Do not include tokens or credentials.

## License

[MIT](LICENSE).
