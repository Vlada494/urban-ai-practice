"""Read a cached regional OSM extract. Downloads run only when called by a cell."""
from hashlib import md5
import json
from pathlib import Path
import re
import time

import geopandas as gpd
import osmium
import pandas as pd
import requests
from shapely import from_wkb, make_valid
from shapely.geometry import Point
from shapely.prepared import prep

EXTRACT_URL = 'https://download.openstreetmap.fr/extracts/russia/volga_federal_district/tatarstan_republic-latest.osm.pbf'
CHECKSUM_URL = EXTRACT_URL.replace('-latest.osm.pbf', '.osm.pbf.md5')
FIELDS = ['osm_type', 'osm_id', 'name', 'landuse', 'building', 'building:levels', 'population', 'amenity', 'capacity']


def file_md5(path):
    digest = md5()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def download_extract(folder):
    """Fetch once, resume interrupted transfers, and verify the publisher's MD5."""
    from .kazan_support import now, write_json
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/'tatarstan_republic.osm.pbf'
    note_path = folder/'tatarstan_republic.download.json'
    if path.exists() and note_path.exists():
        note = json.loads(note_path.read_text(encoding='utf-8'))
        if file_md5(path) != note['md5']:
            raise RuntimeError('Сохранённый PBF не прошёл проверку целостности. Покажи эту ошибку в чате.')
        print('Используем уже скачанную выгрузку Татарстана.', flush=True)
        return path, note

    session = requests.Session()
    session.headers.update({'User-Agent':'UrbanAIPractice/1.0 (educational OSM processing)', 'Accept-Encoding':'identity'})
    try:
        checksum_response = session.get(CHECKSUM_URL, timeout=(10,30))
        checksum_response.raise_for_status()
        expected = checksum_response.text.split()[0].lower()
        if not re.fullmatch('[0-9a-f]{32}', expected):
            raise RuntimeError('Источник не вернул контрольную сумму PBF. Файл не загружен.')
        part = folder/'tatarstan_republic.osm.pbf.part'
        part_note = folder/'tatarstan_republic.part.json'
        if part.exists() and (not part_note.exists() or json.loads(part_note.read_text())['md5']!=expected):
            part.write_bytes(b'')  # only this downloader's incomplete temporary file
        write_json({'md5':expected}, part_note)

        for attempt in range(3):
            offset = part.stat().st_size if part.exists() else 0
            headers = {'Range':f'bytes={offset}-'} if offset else {}
            try:
                with session.get(EXTRACT_URL, headers=headers, stream=True, timeout=(10,45)) as response:
                    # An interrupted transfer may already have completed its bytes.
                    if response.status_code==416 and part.exists() and file_md5(part)==expected:
                        last_modified = None
                    else:
                        response.raise_for_status()
                        resumed = response.status_code==206 and offset>0
                        if response.status_code==206 and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):
                            raise RuntimeError('Источник вернул неправильный диапазон байтов.')
                        if not resumed:
                            offset = 0
                        length = int(response.headers.get('Content-Length','0'))
                        total = offset+length
                        current = offset
                        next_progress = current
                        print('Скачиваем готовый файл Татарстана (около 96 МБ).', flush=True)
                        with part.open('ab' if resumed else 'wb') as stream:
                            for chunk in response.iter_content(chunk_size=1024*1024):
                                if not chunk:
                                    continue
                                stream.write(chunk)
                                current += len(chunk)
                                if current>=next_progress:
                                    tail = f' / {total/1e6:.1f} МБ' if total else ' МБ'
                                    print(f'  Получено {current/1e6:.1f}'+tail, flush=True)
                                    next_progress = current+5*1024*1024
                        last_modified = response.headers.get('Last-Modified')
                if file_md5(part)!=expected:
                    # Keep a bad transfer for diagnosis, but never parse it as OSM.
                    part.replace(folder/f'tatarstan-bad-{time.time_ns()}.pbf.part')
                    raise RuntimeError('Контрольная сумма не совпала. Повтори ячейку: повреждённый файл не использован.')
                part.replace(path)
                note = {'source':'OpenStreetMap France regional extract', 'url':EXTRACT_URL,
                        'md5_url':CHECKSUM_URL, 'md5':expected, 'bytes':path.stat().st_size,
                        'last_modified':last_modified, 'retrieved_at_utc':now()}
                write_json(note, note_path)
                print('Файл скачан; контрольная сумма совпала.', flush=True)
                return path, note
            except requests.RequestException as error:
                if attempt==2:
                    raise RuntimeError('Связь с хранилищем прервалась. Повтори эту ячейку: загрузка продолжится с сохранённого места.') from error
                print('Связь прервалась; сохраняем полученную часть и повторяем.', flush=True)
                time.sleep(2**(attempt+1))
    finally:
        session.close()


def extract_city_groups(path, boundary):
    """Assemble complete OSM areas before filtering them to the city polygon."""
    polygon = boundary.to_crs(4326).geometry.union_all()
    prepared = prep(polygon)
    factory = osmium.geom.WKBFactory()
    rows = {'landuse':[], 'buildings':[], 'schools':[]}
    quality = {'geometry_errors':0, 'geometry_error_examples':[], 'repaired_geometries':0}

    class CityHandler(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.nodes_seen = 0

        def node(self, node):
            self.nodes_seen += 1
            if self.nodes_seen % 1000000 == 0:
                print(f'  Прочитано узлов региона: {self.nodes_seen:,}', flush=True)
            if node.tags.get('amenity')!='school' or not node.location.valid():
                return
            geometry = Point(node.location.lon,node.location.lat)
            if prepared.intersects(geometry):
                tags = dict(node.tags)
                rows['schools'].append({**{k:tags.get(k) for k in FIELDS},
                    'osm_type':'node', 'osm_id':node.id, 'geometry':geometry})

        def area(self, area):
            tags = dict(area.tags)
            groups = []
            if 'landuse' in tags:
                groups.append('landuse')
            if 'building' in tags:
                groups.append('buildings')
            if tags.get('amenity')=='school':
                groups.append('schools')
            if not groups:
                return
            try:
                geometry = from_wkb(factory.create_multipolygon(area))
                if not geometry.is_valid:
                    geometry = make_valid(geometry)
                    quality['repaired_geometries'] += 1
                if geometry.geom_type not in {'Polygon','MultiPolygon'} or geometry.is_empty:
                    raise ValueError('Not a polygon after repair')
                if not prepared.intersects(geometry):
                    return
            except (RuntimeError,ValueError) as error:
                quality['geometry_errors'] += 1
                if len(quality['geometry_error_examples'])<10:
                    quality['geometry_error_examples'].append({'id':area.orig_id(),'error':str(error)})
                return
            row = {**{k:tags.get(k) for k in FIELDS}, 'osm_type':'way' if area.from_way() else 'relation',
                   'osm_id':area.orig_id(), 'geometry':geometry}
            for group in groups:
                rows[group].append(row.copy())

    print('Читаем локальный файл: готовим землепользование, здания и школы Казани.', flush=True)
    print('Файл читается дважды для сборки полигонов с отношениями и отверстиями.', flush=True)
    CityHandler().apply_file(str(path), locations=True, idx='flex_mem')
    frames = {}
    for group, objects in rows.items():
        if objects:
            frame = gpd.GeoDataFrame(objects, geometry='geometry', crs=4326)
            frame = frame.drop_duplicates(['osm_type','osm_id']).reset_index(drop=True)
        else:
            frame = gpd.GeoDataFrame({c:[] for c in FIELDS}, geometry=gpd.GeoSeries([],crs=4326))
        frames[group] = frame
        print(group, len(frame), 'объектов внутри/на границе Казани', flush=True)
    return frames, quality


def fetch_regional_features(boundary, tags, path, keep_columns, geometry_types, allow_empty=False):
    from .kazan_support import read_layer, save_layer, source_note, OSM_CITATION
    path = Path(path)
    if path.exists():
        return read_layer(path)
    extract, note = download_extract(path.parent/'extract_cache')
    frames, quality = extract_city_groups(extract, boundary)
    if frames['landuse'].empty or frames['buildings'].empty:
        raise RuntimeError('В выгрузке не найдены здания или землепользование города. Слои не сохранены: нужна проверка источника/границы.')
    if quality['geometry_errors']:
        print('Внимание: ошибки сборки геометрии по региону:',quality['geometry_errors'],
              'Подробности записаны в source.json; проверь качество перед выводами.',flush=True)
    destinations = {'landuse':'kazan_raw_landuse.geojson', 'buildings':'kazan_raw_buildings.geojson',
                    'schools':'kazan_raw_schools.geojson'}
    for group, filename in destinations.items():
        destination = path.parent/filename
        if destination.exists():
            continue
        staged = destination.with_name(destination.name+'.writing')
        save_layer(frames[group], staged)
        staged.replace(destination)
        source_note(destination, source='OpenStreetMap / OpenStreetMap France regional PBF',
                    extract=note, objects=len(frames[group]), group=group,
                    boundary_filter='Full geometry intersects saved Kazan boundary',
                    geometry_quality_for_region=quality, attribution=OSM_CITATION)
    frame = read_layer(path)
    frame = frame[frame.geom_type.isin(geometry_types)].copy()
    for column in keep_columns:
        if column not in frame:
            frame[column] = None
    if frame.empty and not allow_empty:
        raise ValueError(f'Не найдены объекты для {path.name}. Нужна проверка данных.')
    return frame[[*keep_columns,'geometry']].reset_index(drop=True)
