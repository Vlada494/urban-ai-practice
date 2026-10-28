"""Offline checks of the environment; no city data is downloaded."""

import sys

import my_package
import blocksnet
import geopandas as gpd
import ipykernel
import nbformat
import torch
import torch_geometric
from importlib.metadata import version
from my_package.my_module import MyClass, my_function
from shapely.geometry import Point


def main():
    assert sys.version_info[:2] == (3, 12), sys.version
    assert version("blocksnet") == "1.0.0a9"
    assert MyClass(123).my_arg == 123
    assert my_function(123, 456) == 579

    point = gpd.GeoSeries([Point(0, 0)], crs="EPSG:4326")
    projected = point.to_crs("EPSG:3857")
    assert projected.iloc[0].x == 0
    assert torch.tensor([2, 3]).sum().item() == 5

    print("Python:", sys.version.split()[0])
    print("Interpreter:", sys.executable)
    for package in ("my_package", "blocksnet", "geopandas", "torch", "torch-geometric", "ipykernel", "jupyter"):
        print(f"{package}: {version(package)}")
    print("Environment ready. Offline checks passed.")


if __name__ == "__main__":
    main()
