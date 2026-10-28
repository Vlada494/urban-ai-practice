Казань: кварталы и метрики города — ДЗ 1
========================================

Учебное исследование всей Казани с BlocksNet 1.0.0a9. Сохранены результаты
для 5159 кварталов. Исходный шаблон проекта — python-package-boilerplate;
его лицензия и история сохранены.

Готовые результаты
------------------

* dashboard.html — одна HTML-страница: интерактивная карта, 47 показателей,
  графики, полные таблицы кварталов, характеристики кластеров и выводы.
* examples/kazan_homework.ipynb — выполненный ноутбук: все 26 ячеек кода
  выполнены без ошибок; план, запросы, определения, выводы и повторный запуск.
* examples/data — исходные GeoJSON, результаты, матрица времени и метаданные.
* CONCLUSIONS.txt — краткие выводы; SUBMISSION.txt — инструкция сдачи.

Просмотр и сборка
----------------

Публикация интерактивной карты в GitHub Pages
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

В настройках репозитория откройте Settings → Pages. В разделе Build and
deployment выберите Deploy from a branch, ветку main и папку /docs, затем Save.
Подготовленный docs/index.html — копия готового dashboard.html; Python на
сервере не запускается. После успешной публикации адрес карты:
https://vlada494.github.io/urban-ai-practice/

Карта при обычном открытии файла HTML на github.com не исполняется.
Для интерактивного просмотра используйте GitHub Pages либо скачайте HTML.
Пересборка make_dashboard.py обновляет и dashboard.html, и docs/index.html.

Откройте dashboard.html двойным щелчком или OPEN_DASHBOARD.cmd.
Карта кварталов, показатели, графики и Leaflet находятся внутри HTML.
Для подложки OpenStreetMap нужен интернет.

Пересобрать страницу из сохранённых результатов в PowerShell::

    .venv\Scripts\python.exe make_dashboard.py

Код только читает готовые файлы. Модельные расчёты и загрузка не повторяются.
Логика сборки находится в my_package/dashboard_builder.py, шаблон и библиотека
карты — в my_package/dashboard_assets. Все зависимости ведутся в pyproject.toml.

Для новой среды используйте Python 3.12 и ``python -m pip install -e .``.
Точный снимок установленной среды — requirements-lock.txt. При необходимости
полного воспроизведения используйте этот файл вместо произвольного обновления
зависимостей. Ноутбук выполняет студент, по ячейкам сверху вниз.

Данные и передача
----------------

Полный переносимый архив исходных данных и результатов:
submission/kazan_homework_complete.zip (создаётся prepare_submission.py).
В нём есть полная матрица Parquet, GeoJSON, готовый граф и скачанные срезы
Overture; источник не исчезнет вместе со старым выпуском на сервере.
Архив не содержит .venv и временных кэшей. Контрольные суммы — manifest.json.
Крупная копия матрицы CSV исключена из архива как дубликат Parquet.

ВНИМАНИЕ ДЛЯ ПУБЛИКАЦИИ: укажите здесь проверенную ссылку на архив данных
после загрузки в релиз GitHub или другое хранилище. Сейчас данные доступны
локально в полном составе; публичной ссылки на архив ещё нет.

Ограничения
-----------

Модельное население — не официальная статистика. Все 237 объектов школ
имеют восстановленную вместимость 250 мест. Обеспеченность — учебный сценарий,
не доказательство реального дефицита. Время автомобильное, без пробок,
с прямыми подходами 5 км/ч; это не пешеходный норматив. Пропуски и
неопределённые типы сохранены, а не заменены нулём. Источники: OpenStreetMap,
региональный экстракт Татарстана и Overture Transportation 2026-10-21.0.

Сдача
-----

https://forms.yandex.ru/cloud/6ad22113c45c078cec3c7c7d/

Прикрепляется отдельный dashboard.html размером менее 20 МБ. Нужны ФИО
и ссылка на свой GitHub. Факт сдачи подтверждается ответом формы.

Документация исходного шаблона
============================

Python package boilerplate (IDU) 
================================

.. logo-start

.. figure:: https://sun9-46.userapi.com/impf/aUFBStH0x_6jN9UhgwrKN1WN4hZ9Y2HMMrXT2w/NuzVobaGlZ0.jpg?size=1590x400&quality=95&crop=0,0,1878,472&sign=9d33baa41a86de35d951d4bbd8011994&type=cover_group
   :alt: The Institute of Design and Urban Studies

.. logo-end

|Documentation Status| |PythonVersion| |Black|

.. readme-start 

Installation
------------

The library can be installed with ``pip``:

::

   pip install git+https://github.com/vasilstar97/python-package-boilerplate@main


How to use
----------

Use the library by importing classes from ``my_package``:

::

   from my_package.my_module_1 import MyClass

For more detailed use case see our `examples <#examples>`__.

Data
----

All the required data is stored in `examples
data folder <./examples/data>`__.

Examples
--------

Next examples will help one to get used to the library:

1. Main `example <./examples/my_example.ipynb>`__ of the library.
2. ...

Documentation
-------------

Detailed information and description of the library is available in
`documentation <https://vasilstar97.github.io/python-package-boilerplate/>`__.

Project Structure
-----------------

The latest version of the library is available in the ``main`` branch.

The repository includes the following directories and modules:

-  `my_package <./my_package>`__
   directory with the library code:

   -  ...
   -  ...

-  `tests <./tests>`__
   ``pytest`` testing
-  `examples <./examples>`__
   examples of how the library works
-  `docs <./docs>`__
   documentation sources

Developing
----------

...

License
-------

The project has `BSD-3-Clause license <./LICENSE>`__

Acknowledgments
---------------

...

Contacts
--------

You can contact me:

-  `Vasilii Starikov <https://t.me/vasilstar>`__ - assistant

Also, you are welcomed to the `issues <./issues>`__ section!

Publications
------------

-  `My publication name from scholar or something <https://scholar.google.com/>`__
-  ...

.. |Documentation Status| image:: https://github.com/vasilstar97/python-package-boilerplate/actions/workflows/documentation.yml/badge.svg?branch=main
   :target: https://vasilstar97.github.io/python-package-boilerplate/
.. |PythonVersion| image:: https://img.shields.io/badge/python-3.10-blue
   :target: https://pypi.org/project/geopandas/
.. |Black| image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/psf/black

.. readme-end
