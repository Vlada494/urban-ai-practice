"""I/O and validation helpers. Importing this module never downloads city data."""

from datetime import datetime, timezone
from enum import Enum
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import time
from threading import Thread
from urllib.parse import quote
import zipfile

import folium
import geopandas as gpd
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
import requests
from IPython.display import IFrame
from shapely.geometry import LineString


GRAPH_URL = "https://dataverse.harvard.edu/api/access/datafile/10962604"
GRAPH_MEMBER = "russia-RUS/kazan-5901.graphml"
GRAPH_CITATION = "https://doi.org/10.7910/DVN/KA5HJ3"
OSM_CITATION = "https://www.openstreetmap.org/copyright"
LAND_USE_RU = {
    'residential':'Жилая', 'business':'Деловая', 'industrial':'Промышленная',
    'recreation':'Рекреационная', 'transport':'Транспортная',
    'agriculture':'Сельскохозяйственная', 'special':'Специальная',
}


def land_use_label(value):
    if isinstance(value, Enum):
        value = value.value
    if pd.isna(value):
        return 'Не определено'
    return LAND_USE_RU.get(value, str(value))


def landuse_table_ru(frame):
    """A presentation copy; preserve the original fields for BlocksNet."""
    table = pd.DataFrame(frame.drop(columns=[getattr(frame,'_geometry_column_name','geometry')],errors='ignore')).copy()
    if 'land_use' in table:
        table['land_use'] = table.land_use.map(land_use_label)
    names = {'land_use':'Функция квартала', 'share':'Доля преобладающей функции', 'block_id':'Номер квартала'}
    for column in table.columns:
        code = column.value if isinstance(column,Enum) else column
        if code in LAND_USE_RU:
            names[column] = 'Доля: ' + LAND_USE_RU[code]
    return table.rename(columns=names).rename_axis('Номер квартала')
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
# Notebook iframes have no normal web-page Referer. OSM explicitly supports
# identifying an application with X-Requested-With instead (its Referer guide).
# This uses normal on-screen tile requests and browser caching, never prefetch.
OSM_TILE_SCRIPT = r"""
(function () {
    if (L.TileLayer.prototype._urbanAiIdentified) return;
    const originalCreateTile = L.TileLayer.prototype.createTile;
    L.TileLayer.include({
        _urbanAiIdentified: true,
        createTile: function (coords, done) {
            const url = this.getTileUrl(coords);
            if (!/^https:\/\/([abc]\.)?tile\.openstreetmap\.org\//.test(url)) {
                return originalCreateTile.call(this, coords, done);
            }
            const tile = document.createElement('img');
            tile.alt = '';
            tile.setAttribute('role', 'presentation');
            fetch(url, {
                headers: {'X-Requested-With': 'UrbanAIPractice'},
                referrerPolicy: 'strict-origin-when-cross-origin',
                cache: 'default'
            }).then(function (response) {
                if (!response.ok) throw new Error('OSM tile HTTP ' + response.status);
                return response.blob();
            }).then(function (blob) {
                const objectUrl = URL.createObjectURL(blob);
                tile.onload = function () { URL.revokeObjectURL(objectUrl); done(null, tile); };
                tile.onerror = function (error) { URL.revokeObjectURL(objectUrl); done(error, tile); };
                tile.src = objectUrl;
            }).catch(function (error) { done(error, tile); });
            return tile;
        }
    });
})();
"""
OVERPASS_MIRRORS = (
    "https://overpass.private.coffee/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
)
_MAP_PREVIEW_SERVERS = {}


class _MapPreviewHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def preview_saved_map(path):
    """Display an existing HTML map in a notebook, without recomputing it.

    A loopback-only server gives the iframe a normal HTTP origin. Its daemon
    thread lasts for this Python kernel; the exported HTML stays independent.
    """
    path = Path(path).resolve(strict=True)
    folder = path.parent
    if folder not in _MAP_PREVIEW_SERVERS:
        handler = partial(_MapPreviewHandler, directory=str(folder))
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        _MAP_PREVIEW_SERVERS[folder] = server
        Thread(target=server.serve_forever, daemon=True, name='urban-map-preview').start()
    port = _MAP_PREVIEW_SERVERS[folder].server_address[1]
    return IFrame(f'http://127.0.0.1:{port}/{quote(path.name)}', width='100%', height=550)


class OverpassUnavailable(RuntimeError):
    """An unavailable or incomplete response must never become an empty map."""


def _check_overpass_response(response, *args, **kwargs):
    # OSMnx otherwise retries 429/504 recursively. Let our finite fallback loop
    # handle them, while leaving its normal server-slot checks enabled.
    if response.url.rstrip('/').endswith('/interpreter'):
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get('elements'), list):
            raise OverpassUnavailable('Сервер не вернул список объектов OSM.')
        if payload.get('remark'):
            raise OverpassUnavailable('Сервер вернул неполную выгрузку: ' + str(payload['remark']))
    return response


def _features_with_fallback(polygon, tags, allow_empty):
    original_url = ox.settings.overpass_url
    original_kwargs = ox.settings.requests_kwargs
    endpoints = list(dict.fromkeys([original_url, *OVERPASS_MIRRORS]))
    hooks = dict(original_kwargs.get('hooks') or {})
    previous = hooks.get('response', [])
    hooks['response'] = ([previous] if callable(previous) else list(previous or [])) + [_check_overpass_response]
    ox.settings.requests_kwargs = {**original_kwargs, 'hooks': hooks}
    failures = []
    try:
        for attempt, endpoint in enumerate(endpoints):
            ox.settings.overpass_url = endpoint
            print('Сервер OSM:', endpoint, flush=True)
            try:
                return ox.features_from_polygon(polygon, tags=tags), endpoint
            except ox._errors.InsufficientResponseError as error:
                if str(error).startswith('No matching features.'):
                    if allow_empty:
                        return gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs=4326)), endpoint
                    raise ValueError('Нет подходящих объектов OSM. Проверь запрос и территорию.') from error
                failures.append(type(error).__name__)
            except requests.HTTPError as error:
                status = error.response.status_code if error.response is not None else None
                if status not in {429, 500, 502, 503, 504}:
                    raise
                failures.append(f'HTTP {status}')
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.JSONDecodeError,
                    ox._errors.ResponseStatusCodeError, OverpassUnavailable) as error:
                failures.append(type(error).__name__)
            if attempt + 1 < len(endpoints):
                delay = 5 * (2 ** attempt)
                print(f'Сервер временно недоступен ({failures[-1]}). Через {delay} сек. пробуем резервный.', flush=True)
                time.sleep(delay)
        raise OverpassUnavailable(
            'Серверы OSM временно недоступны: ' + ', '.join(failures) + '. '
            'Уже сохранённые файлы не потеряны. Подожди несколько минут и повтори эту ячейку.'
        ) from None
    finally:
        ox.settings.overpass_url = original_url
        ox.settings.requests_kwargs = original_kwargs


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(value, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def clean_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(list(value) if isinstance(value, set) else value, ensure_ascii=False, default=str)
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def layer_payload(frame, id_column=None):
    frame = frame.copy()
    if frame.crs is None:
        raise ValueError("У слоя отсутствует система координат.")
    if id_column:
        frame[id_column] = frame.index.astype(int)
    for column in frame.columns:
        if column != frame.geometry.name:
            if pd.api.types.is_numeric_dtype(frame[column]):
                frame[column] = frame[column].replace([np.inf, -np.inf], np.nan)
            else:
                frame[column] = frame[column].map(clean_value)
    payload = json.loads(frame.to_crs(4326).to_json(drop_id=True, na="null"))
    # A GeoJSON foreign member retains the schema of an empty layer.
    payload["field_names"] = [c for c in frame.columns if c != frame.geometry.name]
    return payload


def save_layer(frame, path, id_column=None):
    write_json(layer_payload(frame, id_column), path)


def read_layer(path, crs=None, id_column=None):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload["features"]:
        frame = gpd.GeoDataFrame.from_features(payload["features"], crs=4326)
    else:
        frame = gpd.GeoDataFrame({c: [] for c in payload.get("field_names", [])}, geometry=gpd.GeoSeries([], crs=4326))
    if id_column and id_column in frame.columns:
        frame = frame.set_index(id_column)
        frame.index = frame.index.astype(int)
        frame.index.name = None
    return frame.to_crs(crs) if crs is not None else frame


def source_note(path, **information):
    write_json({"retrieved_at_utc": now(), **information}, Path(str(path) + ".source.json"))


def signature(dependencies, parameters):
    digest = sha256(json.dumps(parameters, sort_keys=True, default=str).encode())
    # Changes to helper algorithms invalidate derived results as well.
    digest.update(Path(__file__).read_bytes())
    for path in dependencies:
        path = Path(path)
        digest.update(str(path.name).encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def reusable(paths, dependencies, parameters, force=False):
    paths = [Path(p) for p in paths]
    marker = Path(str(paths[0]) + ".cache.json")
    if force or not all(p.exists() for p in paths) or not marker.exists():
        return False
    return json.loads(marker.read_text(encoding="utf-8")).get("signature") == signature(dependencies, parameters)


def stamp(paths, dependencies, parameters):
    write_json({"signature": signature(dependencies, parameters), "created_at_utc": now()}, str(paths[0]) + ".cache.json")


def fetch_boundary(query, path):
    path = Path(path)
    if path.exists():
        return read_layer(path)
    frame = ox.geocode_to_gdf(query)
    frame = frame[frame.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    if frame.empty:
        raise ValueError("Поиск не вернул полигон границы. Нужна проверка территории.")
    point = frame.to_crs(4326).geometry.union_all().centroid
    if not (47 < point.x < 51 and 54 < point.y < 57):
        raise ValueError("Найденная граница находится далеко от Казани. Проверь запрос.")
    save_layer(frame, path)
    source_note(path, source="OpenStreetMap / Nominatim", query=query, attribution=OSM_CITATION,
                osm_id=frame.get("osm_id", pd.Series(dtype=object)).tolist(),
                display_name=frame.get("display_name", pd.Series(dtype=object)).tolist())
    return frame


def fetch_features(boundary, tags, path, keep_columns, geometry_types, allow_empty=False):
    path = Path(path)
    if path.exists():
        return read_layer(path)
    # Avoid unavailable public query servers for the remaining three city layers.
    if path.name in {'kazan_raw_landuse.geojson', 'kazan_raw_buildings.geojson', 'kazan_raw_schools.geojson'}:
        from .regional_osm import fetch_regional_features
        return fetch_regional_features(boundary, tags, path, keep_columns, geometry_types, allow_empty)
    frame, endpoint = _features_with_fallback(boundary.to_crs(4326).geometry.union_all(), tags, allow_empty)
    if isinstance(frame.index, pd.MultiIndex):
        frame.index.names = ["osm_type", "osm_id"]
        frame = frame.reset_index()
    frame = frame[frame.geom_type.isin(geometry_types)].copy()
    if not frame.empty:
        frame.geometry = frame.geometry.make_valid()
        frame = frame[frame.geom_type.isin(geometry_types) & ~frame.geometry.is_empty].copy()
    for column in keep_columns:
        if column not in frame:
            frame[column] = None
    frame = frame[[*keep_columns, "geometry"]].reset_index(drop=True)
    if frame.empty and not allow_empty:
        raise ValueError(f"Нет подходящей геометрии для {path.name}; дальнейший расчёт остановлен.")
    save_layer(frame, path)
    source_note(path, source="OpenStreetMap / Overpass", endpoint=endpoint,
                tags=tags, objects=len(frame), attribution=OSM_CITATION)
    return frame


def inspect_map(layers, output_path=None):
    nonempty = [frame.to_crs(4326) for frame in layers.values() if not frame.empty]
    if not nonempty:
        raise ValueError("Нет геометрии для карты.")
    bounds = np.vstack([frame.total_bounds for frame in nonempty])
    west, south, east, north = bounds[:, 0].min(), bounds[:, 1].min(), bounds[:, 2].max(), bounds[:, 3].max()
    map_ = folium.Map(location=[(south + north) / 2, (west + east) / 2], zoom_start=11, tiles=None)
    folium.TileLayer(OSM_TILE_URL, name="OpenStreetMap",
                    attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                    max_zoom=19).add_to(map_)
    map_.get_root().script.add_child(folium.Element(OSM_TILE_SCRIPT), name="osm_identification")
    colors = ["#df6935", "#285c91", "#1e9dba", "#83799f", "#458156"]
    for number, (name, frame) in enumerate(layers.items()):
        if frame.empty:
            continue
        payload = layer_payload(frame, "block_id" if name == "Кварталы" else None)
        fields = [c for c in ["block_id", "name", "display_name", "land_use"] if c in payload["field_names"]]
        color = colors[number % len(colors)]
        folium.GeoJson(payload, name=name,
                       style_function=lambda _, c=color: {"color": c, "weight": 1, "fillOpacity": 0.08},
                       tooltip=folium.GeoJsonTooltip(fields=fields) if fields else None).add_to(map_)
    folium.LayerControl(collapsed=False).add_to(map_)
    map_.fit_bounds([[south, west], [north, east]])
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        map_.save(str(output_path))
        # IPython calls this only for display. Keep Map.save()/render() portable,
        # while notebook display uses an HTTP iframe instead of srcdoc.
        map_._repr_html_ = lambda **kwargs: preview_saved_map(output_path)._repr_html_()
    return map_


def plot_columns(frame, columns, title, output_path=None):
    columns = [c for c in columns if c in frame]
    if not columns:
        raise ValueError("Не найдены столбцы для отображения.")
    fig, axes = plt.subplots(len(columns), 1, figsize=(10, 5 * len(columns)), squeeze=False)
    for ax, column in zip(axes.flat, columns):
        plot_frame = frame.copy()
        legend_kwds = None
        if column == 'land_use':
            codes = plot_frame[column].map(lambda x: x.value if isinstance(x,Enum) else x)
            categories = [land_use_label(code) for code in sorted(codes.dropna().unique())]
            labels = codes.map(lambda code: np.nan if pd.isna(code) else land_use_label(code))
            plot_frame[column] = pd.Categorical(labels, categories=categories, ordered=True)
            legend_kwds = {'title':'Функция квартала', 'fontsize':8,
                           'loc':'upper left', 'bbox_to_anchor':(1.02,1)}
        elif pd.api.types.is_numeric_dtype(plot_frame[column]):
            plot_frame[column] = plot_frame[column].replace([np.inf, -np.inf], np.nan)
        else:
            plot_frame[column] = plot_frame[column].map(lambda x: x.value if isinstance(x, Enum) else x)
        if plot_frame[column].notna().any():
            plot_frame.plot(column=column, legend=True, ax=ax, legend_kwds=legend_kwds,
                            missing_kwds={"color": "#ddd", "label":"Не определено"})
        else:
            plot_frame.plot(color="#ddd", ax=ax)
            ax.text(0.02, 0.02, "Нет определённых значений", transform=ax.transAxes)
        display_column = {'land_use':'Функция квартала', 'share':'Доля преобладающей функции'}.get(column,column)
        ax.set_title(f"{title}: {display_column}")
        ax.set_axis_off()
    fig.tight_layout()
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
    return fig


def download_ready_graph(raw_folder):
    """Called only by a student's notebook cell. Downloads an existing graph, never builds one."""
    raw_folder = Path(raw_folder)
    graph_path = raw_folder / "kazan-5901.graphml"
    if graph_path.exists():
        return graph_path
    archive_path = raw_folder / "russia-RUS_graphml.zip"
    if not archive_path.exists():
        temporary = archive_path.with_suffix(".zip.part")
        with requests.get(GRAPH_URL, stream=True, timeout=(30, 300)) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            print(f"Загрузка архива готовых графов России: {total / 1024**2:.1f} МБ, если размер указан сервером.")
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    stream.write(chunk)
        temporary.replace(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        if GRAPH_MEMBER not in archive.namelist():
            raise ValueError("В архиве не найден заранее проверенный граф Казани. Нужна проверка каталога.")
        with archive.open(GRAPH_MEMBER) as source, graph_path.open("wb") as target:
            shutil.copyfileobj(source, target)
    source_note(graph_path, source=GRAPH_CITATION, download_url=GRAPH_URL, archive_member=GRAPH_MEMBER,
                mode="drive", dataset_year=2025, boundary="GHSL urban centre; not necessarily the municipal boundary")
    return graph_path


def prepare_drive_graph(path, crs):
    graph = ox.load_graphml(path)
    original_nodes = graph.number_of_nodes()
    if original_nodes == 0 or graph.number_of_edges() == 0:
        raise ValueError("Пустой готовый граф.")
    if not graph.is_directed():
        graph = graph.to_directed()
    if not all("length" in d and float(d["length"]) > 0 for *_, d in graph.edges(data=True)):
        raise ValueError("У рёбер нет положительной длины в метрах; нельзя оценить время.")
    if not all("travel_time" in d for *_, d in graph.edges(data=True)):
        graph = ox.routing.add_edge_speeds(graph, hwy_speeds={
            "motorway": 90, "motorway_link": 40, "trunk": 70, "trunk_link": 40,
            "primary": 50, "secondary": 40, "tertiary": 35, "residential": 30,
            "living_street": 15, "service": 20, "unclassified": 30,
        }, fallback=30)
        graph = ox.routing.add_edge_travel_times(graph)
    for *_, attributes in graph.edges(data=True):
        attributes["time_min"] = float(attributes["travel_time"]) / 60
        if not np.isfinite(attributes["time_min"]) or attributes["time_min"] < 0:
            raise ValueError("Некорректное время ребра.")
    component = max(nx.strongly_connected_components(graph), key=len)
    graph = graph.subgraph(component).copy()
    graph = ox.projection.project_graph(graph, to_crs=crs)
    graph.graph["crs"] = int(crs.to_epsg())
    print(f"Готовый автомобильный граф: {original_nodes} узлов; в основной сильносвязной компоненте {len(graph)}.")
    print("Время — модель без пробок. Подход от квартала к ближайшему узлу оценивается по прямой со скоростью 5 км/ч.")
    return graph


def graph_coverage(blocks, graph, max_connector_m):
    points = blocks.representative_point()
    _, distances = ox.distance.nearest_nodes(graph, points.x, points.y, return_dist=True)
    result = blocks.copy()
    result["connector_m"] = distances
    result["graph_covered"] = np.array(distances) <= max_connector_m
    return result


def numeric(series):
    return pd.to_numeric(series.astype(str).str.replace(",", ".", regex=False), errors="coerce")


def deduplicate_schools(schools):
    """Merge obvious same-name OSM point/campus duplicates and preserve a reported capacity."""
    schools = schools.copy().reset_index(drop=True)
    duplicates = schools.geometry.normalize().to_wkb().duplicated()
    schools = schools.loc[~duplicates].copy()
    polygons = schools[schools.geom_type.isin(["Polygon", "MultiPolygon"])]
    points = schools[schools.geom_type.eq("Point")]
    to_drop = []
    if not polygons.empty and not points.empty:
        matches = points.sjoin(polygons[["geometry"]], predicate="within")
        for point_id, row in matches.iterrows():
            polygon_id = row["index_right"]
            point_name = str(schools.loc[point_id, "name"] or "").strip().lower()
            polygon_name = str(schools.loc[polygon_id, "name"] or "").strip().lower()
            if not point_name or not polygon_name or point_name == polygon_name:
                if pd.isna(schools.loc[polygon_id, "capacity"]) and pd.notna(schools.loc[point_id, "capacity"]):
                    schools.loc[polygon_id, "capacity"] = schools.loc[point_id, "capacity"]
                to_drop.append(point_id)
    schools = schools.drop(index=to_drop).reset_index(drop=True)
    return schools


def provision_links_geojson(links, blocks):
    rows = []
    points = blocks.representative_point()
    for (source, target), row in links.iterrows():
        a, b = points.loc[source], points.loc[target]
        # These straight segments are OD links, never actual road routes.
        rows.append({"source": int(source), "target": int(target), "value": float(row["value"]),
                     "geometry": LineString([a, b])})
    if not rows:
        return gpd.GeoDataFrame({"source": [], "target": [], "value": []}, geometry=gpd.GeoSeries([], crs=blocks.crs))
    return gpd.GeoDataFrame(rows, crs=blocks.crs)
