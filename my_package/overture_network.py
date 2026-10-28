"""Convert downloaded Overture topology to NetworkX; never infer road junctions.

Only calls from notebook cells download/prepare research data. Import is offline.
"""
from hashlib import sha256
import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
from shapely.ops import substring

RELEASE = '2026-10-21.0'
SOURCE = 'https://docs.overturemaps.org/guides/transportation/'
SPEEDS = {'motorway':90,'trunk':70,'primary':50,'secondary':40,'tertiary':35,
          'residential':30,'living_street':15,'service':20,'unclassified':30,'track':15}
CAR_MODES = {'vehicle','motor_vehicle','car','motor_car','automobile'}


def _sequence(value):
    if isinstance(value,np.ndarray):
        return value.tolist()
    return list(value) if isinstance(value,(list,tuple)) else []


def query_bbox(boundary, buffer_m=20000):
    crs = boundary.estimate_utm_crs()
    region = boundary.to_crs(crs).geometry.union_all().buffer(buffer_m).envelope
    return gpd.GeoSeries([region],crs=crs).to_crs(4326).total_bounds.tolist()


def download_overture_network(boundary, data_dir, release=RELEASE):
    """Stream only the bbox subset of published connector/segment tables."""
    from overturemaps.core import record_batch_reader
    from overturemaps.writers import get_writer
    from .kazan_support import source_note

    folder = Path(data_dir)/'overture'
    folder.mkdir(parents=True,exist_ok=True)
    bbox = query_bbox(boundary)
    paths = {}
    for feature_type in ['segment','connector']:
        path = folder/f'kazan_{feature_type}_{release}.parquet'
        marker = Path(str(path)+'.source.json')
        if path.exists() and marker.exists():
            note = json.loads(marker.read_text(encoding='utf-8'))
            if note.get('release')!=release or not np.allclose(note['bbox'],bbox,atol=1e-8,rtol=0):
                raise ValueError('Кэш Overture относится к другой территории. Покажи эту ошибку в чате.')
            print('Читаем сохранённый слой:',feature_type,flush=True)
            paths[feature_type] = path
            continue
        print(f'Overture {release}: загружаем {feature_type} для Казани и 20-км запаса.',flush=True)
        print('Сначала читается индекс файлов; затем появится число полученных объектов.',flush=True)
        reader = record_batch_reader(feature_type,bbox=bbox,release=release,
                                     connect_timeout=10,request_timeout=60,stac=True)
        if reader is None:
            raise RuntimeError('Overture не вернул данные для выбранной территории/версии. Покажи сообщение сервера в чате.')
        staged = path.with_suffix('.parquet.part')
        count = 0
        try:
            with get_writer('geoparquet',str(staged),reader.schema) as writer:
                for batch in reader:
                    writer.write_batch(batch)
                    count += batch.num_rows
                    print(f'  {feature_type}: получено {count:,} объектов',flush=True)
        except Exception as error:
            raise RuntimeError(f'Загрузка Overture {feature_type} прервалась. Повтори эту ячейку: завершённые слои сохраняются.') from error
        if count==0:
            raise ValueError(f'Пустой слой Overture {feature_type}. Расчёт остановлен.')
        staged.replace(path)
        source_note(path,source=SOURCE,release=release,bbox=bbox,buffer_m=20000,
                    feature_type=feature_type,objects=count,
                    attribution='Overture Maps Foundation; OpenStreetMap contributors; upstream sources in the source tables')
        paths[feature_type] = path
    return paths['segment'],paths['connector']


def _matches(rule, position, heading):
    between = _sequence(rule.get('between'))
    if between and not (float(between[0])<=position<=float(between[1])):
        return False
    raw_when = rule.get('when') or {}
    if not isinstance(raw_when,dict):
        return False
    when = {key:value for key,value in raw_when.items() if value is not None}
    # No departure time, permit or special purpose is assumed for this model.
    if set(when)-{'heading','mode'}:
        return False
    if when.get('heading') not in (None,heading):
        return False
    modes = _sequence(when.get('mode'))
    return not modes or bool(set(modes)&CAR_MODES)


def _travel_time(row,left,right,length_m,heading):
    access = _sequence(row.get('access_restrictions'))
    limits = _sequence(row.get('speed_limits'))
    positions = {left,right}
    for rule in access+limits:
        for value in _sequence(rule.get('between')):
            if left<float(value)<right:
                positions.add(float(value))
    positions = sorted(positions)
    minutes = 0.0
    used_default = False
    for start,end in zip(positions,positions[1:]):
        midpoint = (start+end)/2
        allowed = True
        for rule in access:
            if _matches(rule,midpoint,heading):
                allowed = rule.get('access_type')=='allowed'
        if not allowed:
            return None,False
        speed = None
        for rule in limits:
            maximum = rule.get('max_speed')
            if isinstance(maximum,dict) and _matches(rule,midpoint,heading):
                value = maximum.get('value')
                if value is not None:
                    candidate = float(value)*(1.609344 if maximum.get('unit')=='mph' else 1)
                    if 0<candidate<=200:
                        speed = candidate if speed is None else min(speed,candidate)
        if speed is None:
            speed = SPEEDS[row['class']]
            used_default = True
        part_length = length_m*(end-start)/(right-left)
        minutes += part_length*60/(speed*1000)
    return minutes,used_default


def network_to_graph(segments,connectors,crs):
    """Keep published connector IDs; geometric crossings never create links."""
    segments = segments.to_crs(crs)
    connectors = connectors.to_crs(crs).drop_duplicates('id')
    coordinates = {str(row.id):(float(row.geometry.x),float(row.geometry.y))
                   for row in connectors.itertuples() if row.geometry.geom_type=='Point'}
    identifiers = {value:i for i,value in enumerate(sorted(coordinates))}
    graph = nx.MultiDiGraph(crs=int(crs.to_epsg()),simplified=True)
    quality = {'segments_seen':0,'car_segments':0,'missing_connector_pairs':0,
               'geometry_errors':0,'default_speed_edges':0,'conditional_access_rules':0,
               'turn_restrictions_not_modelled':0}
    for row in segments.to_dict('records'):
        quality['segments_seen'] += 1
        if row.get('subtype')!='road' or row.get('class') not in SPEEDS:
            continue
        flags = [flag for rule in _sequence(row.get('road_flags')) for flag in _sequence(rule.get('values'))]
        if any(value in flags for value in ['is_under_construction','is_abandoned']):
            continue
        quality['car_segments'] += 1
        quality['conditional_access_rules'] += sum(
            bool({key for key,value in (r.get('when') or {}).items() if value is not None}-{'heading','mode'})
            for r in _sequence(row.get('access_restrictions')))
        quality['turn_restrictions_not_modelled'] += len(_sequence(row.get('prohibited_transitions')))
        refs = sorted(_sequence(row.get('connectors')),key=lambda ref:float(ref['at']))
        line = row['geometry']
        if line.geom_type!='LineString' or line.is_empty or not line.is_valid:
            quality['geometry_errors'] += 1
            continue
        for a,b in zip(refs,refs[1:]):
            start,end = float(a['at']),float(b['at'])
            first,last = str(a['connector_id']),str(b['connector_id'])
            if first not in coordinates or last not in coordinates:
                quality['missing_connector_pairs'] += 1
                continue
            if not (0<=start<end<=1) or first==last:
                quality['geometry_errors'] += 1
                continue
            # Source linear references identify a section; physical junctions
            # are the supplied connectors, not intersections inferred in space.
            piece = substring(line,start,end,normalized=True)
            length = float(piece.length)
            if length<=0 or piece.geom_type!='LineString':
                quality['geometry_errors'] += 1
                continue
            for heading,left_id,right_id,geometry in [
                ('forward',first,last,piece),('backward',last,first,piece.reverse())]:
                minutes,estimated = _travel_time(row,start,end,length,heading)
                if minutes is None:
                    continue
                if not np.isfinite(minutes) or minutes<=0:
                    raise ValueError('Некорректное время ребра Overture.')
                for identifier in [left_id,right_id]:
                    x,y = coordinates[identifier]
                    graph.add_node(identifiers[identifier],x=x,y=y,overture_id=identifier)
                graph.add_edge(identifiers[left_id],identifiers[right_id],length=length,time_min=float(minutes),
                    travel_time=float(minutes)*60,geometry=geometry,highway=row['class'],
                    overture_segment_id=str(row['id']),speed_estimated=bool(estimated))
                quality['default_speed_edges'] += int(estimated)
    if graph.number_of_edges()==0:
        raise ValueError('В выгрузке не получился пригодный автомобильный граф.')
    return graph,quality


def prepare_overture_graph(segment_path,connector_path,crs,data_dir):
    from .kazan_support import reusable,stamp,source_note
    segment_path,connector_path = Path(segment_path),Path(connector_path)
    path = Path(data_dir)/'kazan_overture_drive.graphml'
    dependencies = [segment_path,connector_path,Path(__file__)]
    parameters = {'release':RELEASE,'mode':'drive','crs':int(crs.to_epsg()),'converter':1}
    if reusable([path],dependencies,parameters):
        graph = ox.load_graphml(path,edge_dtypes={'time_min':float})
        graph.graph['crs'] = int(crs.to_epsg())
        print('Прочитан сохранённый автомобильный граф Overture.',flush=True)
        return graph,path
    print('Переводим готовые связи Overture в формат BlocksNet.',flush=True)
    graph,quality = network_to_graph(gpd.read_parquet(segment_path),gpd.read_parquet(connector_path),crs)
    original_nodes = len(graph)
    component = max(nx.strongly_connected_components(graph),key=len)
    graph = graph.subgraph(component).copy()
    if len(graph)<2:
        raise ValueError('Нет связной автомобильной сети. Требуется проверка данных и ограничений.')
    quality.update({'nodes_before_component_selection':original_nodes,'nodes_used':len(graph),
                    'nodes_excluded':original_nodes-len(graph),'edges_used':graph.number_of_edges()})
    staged = path.with_name(path.name+'.writing')
    ox.save_graphml(graph,staged)
    staged.replace(path)
    stamp([path],dependencies,parameters)
    input_metadata = {p.name:json.loads(Path(str(p)+'.source.json').read_text(encoding='utf-8'))
                      for p in [segment_path,connector_path] if Path(str(p)+'.source.json').exists()}
    source_note(path,source=SOURCE,release=RELEASE,mode='drive',quality=quality,input_metadata=input_metadata,
        topology='Only published connector IDs; no junctions inferred from geometric crossings',
        speed_model=SPEEDS,
        limitations=['No congestion','Posted limits or class-based speeds',
                     'Conditional access and turn restrictions are not fully modelled',
                     'Linear references interpreted on projected geometry',
                     'Largest strongly connected car component; first/last connectors are straight-line estimates'])
    print(f'Граф Overture: {len(graph):,} узлов, {graph.number_of_edges():,} рёбер. Исключено узлов отдельных компонент: {quality["nodes_excluded"]:,}.',flush=True)
    return graph,path
