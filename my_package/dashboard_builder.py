"""Render saved Kazan outputs. Never download or rerun city calculations."""
from __future__ import annotations
import argparse
import hashlib
from html import escape
import io
import json
import re
from pathlib import Path
import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely import set_precision

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'examples/data'
ASSETS=ROOT/'my_package/dashboard_assets'
LAND={'residential':'Жилая','business':'Деловая','recreation':'Рекреационная',
      'industrial':'Промышленная','transport':'Транспортная','special':'Специальная',
      'agriculture':'Сельскохозяйственная','unknown':'Не определено'}
STRELKA={'low-rise model':'Малоэтажная модель','low-rise non-residential':'Малоэтажная нежилая',
 'individual residential':'Индивидуальная жилая','mid-rise':'Среднеэтажная',
 'mid-rise non-residential':'Среднеэтажная нежилая','central model':'Центральная модель',
 'high-rise modern microdistrict':'Современный многоэтажный микрорайон',
 'high-rise soviet microdistrict':'Советский многоэтажный микрорайон',
 'high-rise non-residential':'Многоэтажная нежилая','mid-rise block':'Среднеэтажный квартал',
 'mid-rise microdistrict':'Среднеэтажный микрорайон'}

def morph_label(value):
    if value is None or pd.isna(value): return 'Не определено'
    if value in STRELKA: return STRELKA[value]
    text=str(value)
    for a,b in [('high-mid-rise','Повышенная этажность'),('low-rise','Малоэтажная'),
                ('mid-rise','Среднеэтажная'),('high-rise','Многоэтажная'),('tower','Высотная'),
                ('low-density','низкая плотность'),('high-density','высокая плотность'),
                ('non-residential','нежилая'),('mixed-use','смешанная'),('residential','жилая')]:
        text=text.replace(a,b)
    return text

def spec():
    rows=[]
    def add(group,key,label,unit='доля',note='',category=False,labels=None):
        rows.append(dict(group=group,key=key,label=label,unit=unit,note=note,category=category,labels=labels or {}))
    for key,label in LAND.items():
        if key!='unknown': add('Землепользование',key,f'Доля: {label.lower()}',note='Доля площади квартала по зонам OSM. Пропуск не означает ноль.')
    add('Землепользование','land_use','Преобладающая функция','категория',category=True,labels=LAND)
    add('Землепользование','share','Доля преобладающей функции',note='Доля площади, занятая преобладающей функцией.')
    add('Транспорт','travel_mean_min','Среднее время до кварталов','мин','Автомобильный сценарий без пробок + прямые подходы 5 км/ч. Среднее по всем кварталам, включая собственную нулевую диагональ.')
    add('Транспорт','travel_median_min','Медианное время до кварталов','мин')
    add('Транспорт','connector_m','Подход к дорожному узлу','м','Прямое расстояние до узла; не проверенный пешеходный маршрут.')
    for key,label,unit,note in [
      ('building_count','Количество зданий','зданий','Объекты OSM, отнесённые к кварталу.'),
      ('population','Модельное население','чел.','Модельная оценка, не официальная численность населения.'),
      ('footprint_area','Пятно зданий','м²','Сумма площадей оснований зданий.'),
      ('build_floor_area','Площадь этажей','м²','Суммарная площадь этажей зданий.'),
      ('living_area','Жилая площадь','м²','Рассчитана по типу, площади и этажности; коэффициент 0,9.'),
      ('non_living_area','Нежилая площадь','м²','Остаток от площади этажей.'),
      ('number_of_floors','Сумма этажностей зданий','этажей (сумма)','Суммирование при агрегации, НЕ средняя этажность квартала. Средневзвешенная этажность показана в L.'),
      ('is_living','Жилые здания по принятому правилу','зданий','Число зданий, отнесённых к жилым.'),
      ('floors_imputed_count','Здания с восстановленной этажностью','зданий','При пропуске принято 1 этаж.'),
      ('unknown_use_count','Здания без уточнённого назначения','зданий','Тег building=yes.'),
      ('population_estimated_count','Здания с оценённым населением','зданий','Жилые здания без положительного наблюдаемого населения.'),
      ('site_area','Площадь квартала','м²','Площадь геометрии квартала в метрической проекции.')]: add('Здания и население',key,label,unit,note)
    add('Школы','school_count','Количество объектов школ','объектов','Объекты OSM после удаления очевидных дублей; не официальный реестр.')
    add('Школы','school_capacity','Модельная вместимость школ','мест','Все объекты имеют условную вместимость 250 мест из конфигурации BlocksNet.')
    add('Школы','capacity_estimated_count','Школы с оценённой вместимостью','объектов')
    for key,label,unit in [('demand','Модельная потребность','мест'),('demand_left','Нераспределённая потребность','мест'),
      ('demand_within','Спрос, обеспеченный в пределах 15 мин','мест'),('demand_without','Спрос, обеспеченный за пределами порога','мест'),
      ('capacity_left','Оставшиеся места','мест'),('capacity_within','Места, использованные в пределах порога','мест'),
      ('capacity_without','Места, использованные за пределами порога','мест'),
      ('provision_strong','Обеспеченность в пределах 15 мин','доля'),('provision_weak','Обеспеченность со всем распределением','доля')]:
        add('Обеспеченность школами','school_'+key,label,unit,'Учебный сценарий: 120 мест на 1000 модельных жителей; 15 автомобильных минут; max_depth=1. При нулевом спросе пропуск обеспеченности не заменяется нулём.')
    for key,label,note in [
      ('fsi','FSI — интенсивность застройки','Площадь этажей / площадь квартала.'),
      ('gsi','GSI — доля пятна застройки','Пятно зданий / площадь квартала.'),
      ('mxi','MXI — доля жилых площадей','Жилые площади / площадь этажей.'),
      ('l','L — средневзвешенная этажность','Площадь этажей / пятно зданий.'),
      ('osr','OSR — открытое пространство на площадь этажей','(Площадь квартала − пятно зданий) / площадь этажей.'),
      ('share_living','Жилые площади к пятну зданий','В этой версии BlocksNet делится на пятно зданий и может быть больше 1.'),
      ('share_non_living','Нежилые площади к пятну зданий','В этой версии BlocksNet делится на пятно зданий и может быть больше 1.')]:
        add('Плотность','dens_'+key,label,'этажей' if key=='l' else 'отношение',note)
    add('Типы застройки','spacematrix_cluster','Кластер Spacematrix','номер',category=True)
    add('Типы застройки','spacematrix_morphotype','Морфотип Spacematrix','категория',category=True)
    add('Типы застройки','strelka_morphotype','Морфотип «Стрелка»','категория',category=True,labels=STRELKA)
    add('Доступность по площади','area_accessibility','Время с весами по площади','мин','Среднее автомобильное время с весами по площади кварталов. Это не расстояние до центра и не пешеходный норматив.')
    return rows

def read_layer(name):
    path=DATA/name
    if not path.is_file(): raise FileNotFoundError(f'Не найден {name}. Сначала заверши сохранение результатов в ноутбуке.')
    return gpd.read_file(path)

def svg_plot(draw,size=(8,3.5)):
    fig,ax=plt.subplots(figsize=size)
    draw(fig,ax)
    if ax in fig.axes: ax.spines[['top','right']].set_visible(False)
    fig.tight_layout()
    out=io.StringIO()
    fig.savefig(out,format='svg',bbox_inches='tight',transparent=True)
    plt.close(fig)
    return out.getvalue()[out.getvalue().index('<svg'):]

def compact_geo(frame,tolerance=1):
    # Metres, never simplify geographic degrees. Only the display copy changes.
    view=frame.to_crs(32639).copy()
    view.geometry=view.geometry.simplify(tolerance,preserve_topology=True)
    view=view.to_crs(4326)
    rounded=set_precision(view.geometry,grid_size=0.000001)
    view.geometry=rounded.where(~rounded.is_empty,view.geometry)
    return json.loads(view.to_json(drop_id=True,na='null'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dashboard.html')
    args=parser.parse_args()
    final=read_layer('kazan_blocks_final.geojson')
    if not final.block_id.is_unique or len(final)!=5159: raise ValueError('Проверь полноту кварталов в итоговом GeoJSON.')
    specs=spec()
    required={s['key'] for s in specs}-{'connector_m'}
    if required-set(final.columns): raise ValueError(f'Нет показателей: {sorted(required-set(final.columns))}')
    connector=read_layer('kazan_overture_connector_diagnostics.geojson')
    final=final.merge(connector[['block_id','connector_m']],on='block_id',validate='one_to_one')
    if final.connector_m.isna().any(): raise ValueError('Не для всех кварталов сохранена диагностика дорожной сети.')
    schools=read_layer('kazan_services.geojson')
    boundary=read_layer('kazan_boundaries.geojson')
    links=read_layer('kazan_school_links.geojson')
    methodology=json.loads((DATA/'kazan_methodology.json').read_text(encoding='utf-8'))
    coverage=pd.read_csv(DATA/'kazan_pipeline_coverage.csv')
    if not coverage.iloc[:,-1].all(): raise ValueError('Проверка полноты в пункте 12 не пройдена.')
    matrix=pd.read_parquet(DATA/'kazan_acc_mx.parquet')
    matrix.columns=matrix.columns.astype(int)
    if matrix.shape!=(len(final),len(final)) or not np.isfinite(matrix.to_numpy()).all(): raise ValueError('Матрица неполная или содержит недостижимые пары.')
    if set(matrix.index)!=set(final.block_id): raise ValueError('Идентификаторы кварталов в матрице и итоговом слое отличаются.')
    land=pd.read_csv(DATA/'kazan_land_use_shares.csv')
    clusters=pd.read_csv(DATA/'kazan_spacematrix_clusters.csv')
    population=int(final.population.sum()); buildings=int(final.building_count.sum())
    school_count=int(final.school_count.sum()); capacity=int(final.school_capacity.sum())
    demand=int(final.school_demand.sum()); provided=int(final.school_demand_within.sum())
    unknown=int(final.land_use.isna().sum()); no_morph=int(final.spacematrix_morphotype.isna().sum())
    findings=[
      f'Исследование охватывает всю выбранную границу Казани: сохранены {len(final):,} кварталов. Они построены по дорогам, воде и железным дорогам OSM и могут отличаться от официальных кварталов.',
      f'Жилая функция преобладает в 2301 квартале и занимает 40,7% суммарной площади кварталов. У {unknown:,} кварталов ({unknown/len(final):.1%}) функция не определена; по площади это 11,4%. Отсутствие тега OSM не означает отсутствие функции.',
      f'В кварталы отнесены {buildings:,} зданий. Модель дала {population:,} жителей при 30 м² жилой площади на человека. У 74 189 зданий этажность восстановлена, у 61 926 не уточнён тип. Численность нельзя выдавать за официальную статистику.',
      f'Найдены {school_count} объектов школ OSM. Вместимость всех объектов оценена как 250 мест: суммарно {capacity:,} условных мест. Главное ограничение — отсутствие наблюдаемых вместимостей, возможные ошибки классификации и дубли в OSM.',
      f'В сценарии обеспеченности распределено {provided:,} мест из {demand:,} модельной потребности ({provided/demand:.1%}). Это отношение суммарного обеспеченного спроса к суммарному спросу, а не среднее долей кварталов. Результат не доказывает реальную нехватку мест и не определяет места строительства школ.',
      f'По сохранённой матрице среднее время между кварталами — {matrix.to_numpy().mean():.1f} мин. Все пары достижимы. Используется автомобильная сеть Overture без пробок и прямые подходы 5 км/ч; у 11 кварталов подход длиннее 1 км.',
      f'FSI различается от {final.dens_fsi.min():.2f} до {final.dens_fsi.max():.2f}, медиана — {final.dens_fsi.median():.3f}. Высокие значения обозначают концентрацию площади этажей относительно площади квартала; сравнение зависит от размера и границ кварталов.',
      f'В Spacematrix получено 11 кластеров. Обе классификации определены у {len(final)-no_morph:,} кварталов; у {no_morph:,} ({no_morph/len(final):.1%}) тип не определён из-за отсутствия подходящих характеристик застройки.',
      f'Время с весами по площади лежит в диапазоне {final.area_accessibility.min():.1f}–{final.area_accessibility.max():.1f} мин. Меньшее значение означает меньшую среднюю удалённость от площади территории. Для объяснения причин различий нужны проверка данных и локальное знание города.'
    ]
    # Use nonbreaking thin spaces in grouped thousands; keep decimal commas.
    findings=[re.sub(r'(?<=\d)\.(?=\d)',',',re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))','\u202f',s)).replace('%',' %') for s in findings]
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.titleweight':'bold','svg.fonttype':'path',
                         'axes.labelcolor':'#3c4858','text.color':'#213047','axes.edgecolor':'#c9d0d4'})
    charts=[]
    def chart(title,caption,draw,size=(8,3.5)):
        charts.append(dict(title=title,caption=caption,svg=svg_plot(draw,size)))
    def land_chart(fig,ax):
        ordered=land.sort_values('percent'); ax.barh(ordered.label_ru,ordered.percent,color='#267d85')
        ax.set_xlabel('% суммарной площади кварталов')
    chart('Преобладающая функция','Площадь кварталов по преобладающей функции, не сумма пересечений зон.',land_chart)
    def hist(column,label,color='#267d85'):
        def draw(fig,ax):
            values=final[column].replace([np.inf,-np.inf],np.nan).dropna()
            ax.hist(values,bins=32,color=color,edgecolor='#fff',linewidth=.4)
            ax.set_xlabel(label); ax.set_ylabel('Кварталов')
        return draw
    chart('Модельное население','Включены кварталы с нулевым модельным населением; это не перепись.',hist('population','Модельное население, чел.'))
    chart('Количество школ','Количество объектов OSM по кварталам, включая нули.',hist('school_count','Объектов на квартал','#c4784d'))
    def provision_chart(fig,ax):
        ax.barh(['Обеспеченный спрос','Нераспределённый спрос'],[provided,int(final.school_demand_left.sum())],color=['#267d85','#c4784d'])
        ax.set_xlabel('Модельных мест')
    chart('Спрос и распределение мест','Условные 250 мест на объект; 120 мест на 1000 модельных жителей; 15 автомобильных минут.',provision_chart)
    chart('Среднее время до кварталов','Распределение средних времён кварталов; без пробок, с модельными подходами.',hist('travel_mean_min','Минуты','#52659b'))
    def density_chart(fig,unused):
        unused.remove()
        for i,key in enumerate(['fsi','gsi','mxi','l','osr','share_living','share_non_living']):
            ax=fig.add_subplot(3,3,i+1)
            values=final['dens_'+key].replace([np.inf,-np.inf],np.nan).dropna()
            ax.hist(values,bins=24,color='#267d85',edgecolor='white',linewidth=.3)
            ax.set_title(key.upper(),fontsize=10); ax.tick_params(labelsize=8)
    chart('Семь индексов застройки','Определения и значения доступны в таблице и переключателе карты. Пропуски исключены из гистограмм.',density_chart,(9,6))
    def morph_chart(fig,unused):
        unused.remove()
        for i,(column,title) in enumerate([('spacematrix_morphotype','Spacematrix'),('strelka_morphotype','Стрелка')]):
            ax=fig.add_subplot(2,1,i+1)
            values=final[column].map(morph_label).value_counts().sort_values()
            ax.barh(values.index,values.values,color='#52659b' if i==0 else '#267d85')
            ax.set_title(title); ax.set_xlabel('Кварталов')
    chart('Два способа классификации','«Не определено» показано отдельно. Число кластеров и число названий морфотипов могут различаться.',morph_chart,(9,10))
    chart('Доступность с учётом площади','Меньшее время означает меньшую среднюю удалённость от площади территории.',hist('area_accessibility','Минуты','#c4784d'))
    columns=list(dict.fromkeys(['block_id']+[s['key'] for s in specs]+['geometry']))
    geo=compact_geo(final[columns])
    for item in specs:
        if item['key']=='spacematrix_morphotype': item['labels']={v:morph_label(v) for v in final[item['key']].dropna().unique()}
    school_points=schools.copy(); school_points.geometry=schools.representative_point()
    choices=list(dict.fromkeys(final.nlargest(4,'population').block_id.astype(int).tolist()
        +final.nsmallest(4,'travel_mean_min').block_id.astype(int).tolist()+final.nlargest(4,'travel_mean_min').block_id.astype(int).tolist()))
    payload={'blocks':geo,'boundary':compact_geo(boundary,tolerance=5),'schools':compact_geo(school_points,0),
      'links':compact_geo(links,0),'specs':specs,'methodology':methodology,'findings':findings,
      'clusters':json.loads(clusters.to_json(orient='records')),
      'matrix_preview':{'ids':choices,'values':matrix.loc[choices,choices].round(2).values.tolist(),
                        'rows':len(matrix),'cols':len(matrix.columns),'finite':True},
      'headline':{'blocks':len(final),'buildings':buildings,'population':population,'schools':school_count},
      'summary':{'demand':demand,'provided':provided,'capacity':capacity,'unknown':unknown,'unknown_morph':no_morph,
                 'imputed_schools':methodology['school_capacity_imputed']},
      'source_files':{name:hashlib.sha256((DATA/name).read_bytes()).hexdigest() for name in [
          'kazan_blocks_final.geojson','kazan_methodology.json','kazan_pipeline_coverage.csv']}}
    packed=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</','<\\/')
    template=(ASSETS/'dashboard_template.html').read_text(encoding='utf-8')
    replacements={'__LEAFLET_CSS__':(ASSETS/'leaflet.css').read_text(encoding='utf-8'),
      '__LEAFLET_JS__':(ASSETS/'leaflet.js').read_text(encoding='utf-8'),'__PAYLOAD__':packed,
      '__CHARTS__':''.join(f'<article class="chart-card"><h3>{escape(c["title"])}</h3><p>{escape(c["caption"])}</p>{c["svg"]}</article>' for c in charts)}
    for key,value in replacements.items(): template=template.replace(key,value)
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(template,encoding='utf-8')
    if args.output.stat().st_size>20_000_000: raise ValueError('HTML превышает лимит 20 МБ формы сдачи.')
    if args.output.resolve()==(ROOT/'dashboard.html').resolve():
        site=ROOT/'docs'
        site.mkdir(exist_ok=True)
        (site/'index.html').write_text(template,encoding='utf-8')
        (site/'.nojekyll').touch()
    (ROOT/'CONCLUSIONS.txt').write_text('КАЗАНЬ — ВЫВОДЫ ПО СОХРАНЁННЫМ РЕЗУЛЬТАТАМ\n\n'
        +'\n\n'.join(f'{i+1}. {text}' for i,text in enumerate(findings))+'\n',encoding='utf-8')
    (ROOT/'dashboard_summary.json').write_text(json.dumps({k:payload[k] for k in ['headline','summary','findings','source_files']},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Готово: {args.output}; {args.output.stat().st_size/1e6:.2f} МБ; {len(specs)} показателей; {len(final)} кварталов.')
    print('Только чтение и оформление сохранённых результатов. Загрузки и расчёты BlocksNet не запускались.')

if __name__=='__main__': main()
