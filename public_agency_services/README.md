# RestWrangler for QGIS

Build a reusable agency QGIS project from public ArcGIS Online or ArcGIS Enterprise services. The project stores live service connections, not offline copies. Recipients need QGIS, internet access, and access to the service URLs; they do not need this plugin or an Esri license.

## Install as a QGIS tool

1. Download **RestWrangler_QGIS.zip** without extracting it.
2. In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the ZIP and install it. Enable **RestWrangler** if needed.
4. Open **Plugins → RestWrangler → RestWrangler…**.

Designed for QGIS 3.40+ and QGIS 4.x (Qt5/Qt6). This is an experimental first release: Python syntax, URL/grouping tests, simulated tree/network discovery tests, and ZIP structure have been checked, but live QGIS UI/provider testing has not been performed.

## Run only the Python script instead

Extract the ZIP. In QGIS, open **Plugins → Python Console**, click **Show Editor**, open `public_agency_services/public_services.py`, then click **Run Script**. A standalone dialog opens. No pip installations are required. Run inside QGIS, not standalone Python. This is an interactive GUI tool, not a Processing algorithm or a batch-processing tool.

## Build an agency project

1. Paste the public REST services directory URL and click **Browse**.
2. Open folders as needed. Services are inspected automatically: single-layer services become checkboxes, and multi-layer services stay collapsed with a group checkbox. Check a group to select all its layers, or expand it to choose individual layers. You can select layers across multiple expanded services.
3. Enter a destination group path, for example `Coastal Commission / Hazards`.
4. Keep **Preserve folders, service names, and service subgroups** checked for automatic grouping, or uncheck it to put the selected layers directly in your chosen group.
5. Choose how to load MapServer layers. **Map images** retains the server-rendered appearance; **Vector features** enables attribute access and QGIS styling where the service supports queries. FeatureServer layers and tables always use vector connections.
6. Click **Add checked layers**. Repeat with another group or another URL. Browsing a new URL clears the browser's pending checks; already-added project layers remain.
7. Turn on the desired layers in QGIS and use **Zoom to Layer**, adjust ordering/style, and save using **Project → Save As… → .qgz**.
8. Give staff the `.qgz`. Test it on a second computer without an ArcGIS login before distributing it broadly.

Example organization:

- Coastal Commission
  - Coastal Zone
  - Public Access
  - Hazards
  - Reference Layers

Destination groups with matching names are reused at the same hierarchy level. Forward slashes in the destination field separate nested groups. When hierarchy preservation is enabled, original service group names are kept literally. To put different checked layers in different custom groups, add one batch per destination. You can also drag/reorder layers and groups normally in QGIS afterward.

## Accepted URLs

Illustrative shapes (replace host, organization ID, and service names):

- Server directory: `https://HOST/arcgis/rest/services`
- Server folder: `https://HOST/server/rest/services/Planning`
- ArcGIS Online organization services: `https://servicesN.arcgis.com/ORG_ID/arcgis/rest/services`
- Feature service: `https://HOST/arcgis/rest/services/Parcels/FeatureServer`
- Map service: `https://HOST/arcgis/rest/services/Hazards/MapServer`
- Individual layer: `https://HOST/arcgis/rest/services/Parcels/FeatureServer/0`

A trailing `?f=json` or `?f=pjson` is accepted and stripped. Other query parameters, embedded credentials, and tokens are rejected: this tool is intended to build shareable public connections.

Use the **service URL**, not the agency Portal home page, item details page, web map URL, or `/sharing/rest` directory. Portal content search and web map import are not included. For an individual REST group layer URL, browse its parent MapServer/FeatureServer endpoint to select its children.

## Scope and behavior

- Supports FeatureServer layers/tables and MapServer sublayers/tables. MapServer vectors require query support. MapServer raster layers use PNG32 export; unusual or cached-only services may not support this mode.
- ImageServer, VectorTileServer, SceneServer, geocoding, and geoprocessing services are listed as unsupported. This release does not import these services.
- Browsing is asynchronous, uses QGIS networking/proxy settings, and has a 45-second timeout per metadata request. Collapse and expand a failed node to retry. Changing endpoints cancels pending metadata requests.
- Layer-provider initialization can briefly block QGIS while connecting; Stop takes effect between layers, not during a provider's network request. Completed additions are retained on cancellation.
- Opening a directory or folder automatically inspects its FeatureServer and MapServer services, with at most four metadata requests in progress. Single-layer services become directly checkable rows; multi-layer services and their subgroups stay collapsed and have select-all checkboxes. Partial checkmarks indicate mixed selections. Folders still open on demand. Filtering does not open new folders or clear existing checks. **Check visible layers** selects loaded matches, including children of collapsed nodes. **Uncheck all** clears every check, including hidden matches. **Add checked layers** includes checked layers hidden by a later filter.
- New layers start off by default. This prevents immediate drawing of a large number of services. Enable **Turn added layers on** if preferred. Existing layers are not changed.
- Vector layers are set read-only in QGIS. No data edits are sent by this tool.
- Duplicate checks compare provider and source strings. This prevents repeated identical connections; differently configured connections to the same endpoint can still be added.
- Failures appear under **Show Details** in the results dialog. Successful additions remain even if other layers fail. Unsuccessful layers stay checked for retry.
- Service symbology may not translate perfectly to QGIS vector styling. ArcGIS web map popups, Arcade expressions, web map layer configuration, and relationships are not imported. Map images retain server rendering, but are not vector layers for analysis.
- A saved project still depends on the agency keeping URLs public and stable. Local files or other non-service layers added separately must be distributed separately. This tool does not download an offline dataset or alter sharing permissions.

## Suggested acceptance check in QGIS

1. Browse your agency's directory, expand one nested folder, and add one FeatureServer layer plus one table.
2. Add a MapServer sublayer in map-image mode and verify that it draws when switched on. Try vector mode separately if needed.
3. Check subgroup placement and add a second batch into a custom nested group.
4. Repeat an addition; confirm that the identical source is skipped.
5. Try an unavailable/private service; confirm an error appears and other selections can still be added.
6. Save/reopen the `.qgz`, then open it on a staff computer without this tool or an ArcGIS session.

Run the standard-library checks outside QGIS with `python test_helpers.py` and `python test_discovery.py` from this folder. Discovery tests use tree/network stand-ins; they do not validate the live QGIS UI or providers.

## Implementation references

- Esri Services Directory: https://developers.arcgis.com/rest/services-reference/enterprise/catalog/
- QGIS native ArcGIS provider URI construction: https://github.com/qgis/QGIS/blob/release-3_40/src/providers/arcgisrest/qgsarcgisrestdataitems.cpp

License: MIT. Source is included and can be adapted for agency use.

## Version 0.3.0: group selection, names, and counts

- Service groups and nested subgroups start collapsed. Check a group to select every descendant layer/table, including those hidden by the name filter. Expand it when you want individual selections. Clearing a group clears all its descendants. Partial checkmarks reflect mixed selections. Selecting a group only selects layers in the browser; click **Add checked layers** to add them to the project.
- Single-layer services remain directly checkable.
- **Item / service name** shows the public AGOL/Portal item title when `serviceItemId` and the owning portal can be resolved. While loading, or if the item title cannot be retrieved, it shows the REST service name. Hover over this column to see which source was used. Both layer names and this column are searchable.
- ArcGIS Online item titles are requested from its public item endpoint. For Enterprise, the tool uses `owningSystemUrl`, including discovery through `/rest/info`. An unavailable, private, or unlinked item does not prevent adding its otherwise public service. Standalone services with no linked item retain the REST name. This is the service's linked item title, not the title of an arbitrary web map containing it.
- **Count** shows selectable layers and tables for services and nested subgroups, e.g. `8 layers; 2 tables`. Group containers are not counted as layers. Directory/folder counts show direct service endpoints and child folders, e.g. `12 services; 3 folders`; they include unsupported service types and exclude the contents of nested folders. Folder counts appear when opened, and an ellipsis means not loaded yet. An unavailable service displays `Unavailable`.
- Directory folders remain on-demand navigation containers; service and sublayer groups have the bulk-selection checkboxes.
- Title lookups share the four-request queue with discovery and are cached for the current browse session. No sign-in is required for public item metadata.
- The internal plugin folder name is unchanged so this ZIP updates the existing installation. Install the ZIP again, then restart QGIS.

Additional API references:

- Public item titles: https://developers.arcgis.com/rest/users-groups-and-items/item/
- Owning portal discovery: https://developers.arcgis.com/rest/services-reference/enterprise/server-info/

## Version 0.3.1: branding

Includes the RestWrangler globe cowboy logo in the plugin manager, menu action, and dialog, plus an expanded description explaining how the tool wrangles public ArcGIS REST services into organized, shareable QGIS projects.
