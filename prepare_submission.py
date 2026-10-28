"""Archive saved homework files only; never download or recalculate data."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parent
DEST=ROOT/'submission'

def main():
    DEST.mkdir(exist_ok=True)
    source_names=['make_dashboard.py','prepare_submission.py','dashboard.html',
        'CONCLUSIONS.txt','SUBMISSION.txt','README.rst','pyproject.toml',
        'requirements-lock.txt','LICENSE','AGENTS.md','OPEN_DASHBOARD.cmd',
        'examples/kazan_homework.ipynb','examples/kazan_overview.png']
    files=[ROOT/name for name in source_names if (ROOT/name).is_file()]
    files += [p for p in (ROOT/'my_package').rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and p.suffix!='.pyc']
    files += [p for p in (ROOT/'references').glob('*.ipynb')]
    # Include the prepared ready graph and its downloaded source so release
    # expiry cannot prevent reproduction. Exclude redundant huge matrix CSV,
    # rejected old graph, old preview HTML and the regional download cache.
    for p in (ROOT/'examples/data').glob('kazan*'):
        if p.is_file() and p.suffix in {'.geojson','.csv','.parquet','.json','.graphml'}:
            if p.name not in {'kazan_acc_mx.csv','kazan-5901.graphml','kazan-5901.graphml.source.json',
                               'kazan_graph_coverage.geojson'}:
                files.append(p)
    files += [p for p in (ROOT/'examples/data/overture').glob('*') if p.is_file() and not p.name.endswith('.part')]
    files=sorted(set(files))
    manifest={str(p.relative_to(ROOT)).replace('\\','/'):{'bytes':p.stat().st_size,'sha256':sha256(p.read_bytes()).hexdigest()}
              for p in files}
    (DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    target=DEST/'kazan_homework_complete.zip'
    with ZipFile(target,'w',compression=ZIP_DEFLATED,compresslevel=4,allowZip64=True) as archive:
        for p in files: archive.write(p,Path('urban-ai-practice')/p.relative_to(ROOT))
        archive.write(DEST/'manifest.json','urban-ai-practice/submission_manifest.json')
        archive.writestr('urban-ai-practice/ARCHIVE_README.txt',
            'Архив содержит исходные GeoJSON, результаты, полную матрицу Parquet, готовый граф и срезы Overture.\n'
            'Матрица kazan_acc_mx.csv не дублируется из-за размера; те же значения хранятся в Parquet.\n'
            'Окружение .venv не включено. Установите Python 3.12 и зависимости из pyproject.toml.\n'
            'Для просмотра нужен только dashboard.html; для сборки: python make_dashboard.py.\n')
    print(f'Архив: {target}; {target.stat().st_size/1e6:.1f} МБ; файлов: {len(files)}')
    print('Для Яндекс Форм прикрепляется отдельный dashboard.html, а не этот архив.')

if __name__=='__main__': main()
