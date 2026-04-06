"""
Hovedprogram for syntetisk kartgenerering.
Genererer terreng, høydekurver, og vegnett til GeoPackage.

Bruk:
    python synthetic_map.py [--layers LAYER1,LAYER2,...]

Tilgjengelige lag:
    - terrain: Terrengpunkter og TIN
    - contours: Høydekurver
    - roads: Vegnett (riksveier)
    - all: Alt (standardvalg)

Eksempler:
    python synthetic_map.py                          # Generer alt
    python synthetic_map.py --layers contours        # Bare høydekurver
    python synthetic_map.py --layers terrain,roads   # Terreng og vegnett
"""

import os
import sys
import argparse
import geopandas as gpd
from synthetic_hoydekurve_module import generate_terrain
from synthetic_vegnett_module import generate_roads

# Konfigurasjon
BBOX = (500000, 6700000, 502000, 6702000)
CRS = "EPSG:25833"
OUTPUT_GPKG = "synthetic_hoydekurve.gpkg"

# Terrengparametrer
TERRAIN_PARAMS = {
    "bbox": BBOX,
    "crs": CRS,
    "h_min": 100.0,
    "h_max": 130.0,
    "n_primary": 15,
    "sec_per_tri": 5,
    "ter_per_tri": 3,
    "qua_per_tri": 3,
    "qui_per_tri": 3,
    "sec_delta": 3.0,
    "ter_delta": 1.0,
    "qua_delta": 0.4,
    "qui_delta": 0.1,
    "ekvidistanse": 1.0
}


def generate_all_layers(layers=None):
    """
    Generer valgte kartlag.
    
    Args:
        layers: Liste av lag å generere (['terrain', 'contours', 'roads'])
                Hvis None, generer alt
    """
    if layers is None:
        layers = ['terrain', 'contours', 'roads']
    
    # Generer terreng (alltid nødvendig for andre lag)
    print("Genererer terreng...")
    terrain_data = generate_terrain(**TERRAIN_PARAMS)
    
    # Forbered GeoPackage
    if os.path.exists(OUTPUT_GPKG):
        os.remove(OUTPUT_GPKG)
    
    # Skriv террeng-lag
    if 'terrain' in layers:
        print("  - Skriver terreng_points...")
        terrain_data["gdf_pts"].to_file(OUTPUT_GPKG, layer="terrain_points", driver="GPKG")
        print("  - Skriver terrain_tin...")
        terrain_data["gdf_tin"].to_file(OUTPUT_GPKG, layer="terrain_tin", driver="GPKG")
    
    # Skriv høydekurver
    if 'contours' in layers:
        print("  - Skriver hoydekurver_1m...")
        terrain_data["gdf_contours"].to_file(OUTPUT_GPKG, layer="hoydekurver_1m", driver="GPKG")
    
    # Generer og skriv vegnett
    if 'roads' in layers:
        print("Genererer vegnett...")
        gdf_roads = generate_roads(terrain_data, crs=CRS)
        print("  - Skriver vegnett_riksveg...")
        gdf_roads.to_file(OUTPUT_GPKG, layer="vegnett_riksveg", driver="GPKG")
    
    # Skriver statistikk
    print("\nFerdig: syntetisk kartdata skrevet til", OUTPUT_GPKG)
    print("Punkter:", len(terrain_data["gdf_pts"]))
    print("TIN-triangler:", len(terrain_data["gdf_tin"]))
    print("Høydekurver:", len(terrain_data["gdf_contours"]))
    if 'roads' in layers:
        print("Riksveg:", len(gdf_roads))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '--layers',
        default='all',
        help='Kartlag å generere (terrain, contours, roads, eller all). Kommasseparert liste.'
    )
    
    args = parser.parse_args()
    
    # Parser lagargument
    if args.layers.lower() == 'all':
        layers = ['terrain', 'contours', 'roads']
    else:
        layers = [l.strip().lower() for l in args.layers.split(',')]
    
    # Valider lagene
    valid_layers = {'terrain', 'contours', 'roads'}
    invalid = set(layers) - valid_layers
    if invalid:
        print(f"Feil: ukjente lag: {invalid}")
        print(f"Tillatte lag: {valid_layers}")
        sys.exit(1)
    
    print(f"Genererer lag: {', '.join(layers)}")
    generate_all_layers(layers)


if __name__ == "__main__":
    main()
