"""
Hovedprogram for syntetisk kartgenerering.
Genererer terreng og vegnett til separate GeoPackage-filer.

Bruk:
    python synthetic_map.py [--layers LAYER1,LAYER2,...]

Tilgjengelige lag:
    - terrain: Terrengpunkter, TIN, og høydekurver → synthetic_terrain.gpkg
    - roads: Vegnett (riksveier) → synthetic_vegnett.gpkg
    - buildings: Bygninger → synthetic_bygning.gpkg
    - all: Alt (standardvalg)

Eksempler:
    python synthetic_map.py                          # Generer alt
    python synthetic_map.py --layers terrain         # Bare terreng
    python synthetic_map.py --layers roads           # Bare vegnett
    python synthetic_map.py --layers buildings        # Bare bygninger
"""

import os
import sys
import argparse
import geopandas as gpd
from synthetic_hoydekurve_module import generate_terrain
from synthetic_vegnett_module import generate_roads, generate_vegkant
from synthetic_bygning_module import generate_buildings

# ===== KONFIGURASJON =====

# Geografisk område
BBOX = (500000, 6700000, 502000, 6702000)  # (minx, miny, maxx, maxy) UTM-koordinater
CRS = "EPSG:25833"  # UTM zone 33N for Norge

# Output-filer
OUTPUT_TERRAIN_GPKG = "synthetic_terrain.gpkg"
OUTPUT_ROADS_GPKG = "synthetic_vegnett.gpkg"
OUTPUT_BUILDINGS_GPKG = "synthetic_bygning.gpkg"

LAYER_ORDER = ["terrain", "roads", "buildings"]
LAYER_DEPENDENCIES = {
    "terrain": [],
    "roads": ["terrain"],
    "buildings": ["terrain", "roads"],
}

# Terrengparametre
TERRAIN_CONFIG = {
    "bbox": BBOX,
    "crs": CRS,
    # Høyde
    "h_min": 100.0,
    "h_max": 130.0,
    # Primære punkter
    "n_primary": 15,
    # Sekundære punkter (nivå 1)
    "sec_per_tri": 5,
    "sec_delta": 3.0,
    # Tertiære punkter (nivå 2)
    "ter_per_tri": 3,
    "ter_delta": 1.0,
    # Kvaternære punkter (nivå 3)
    "qua_per_tri": 3,
    "qua_delta": 0.4,
    # Kvintære punkter (nivå 4)
    "qui_per_tri": 3,
    "qui_delta": 0.1,
    # Høydekurver
    "ekvidistanse": 1.0
}

# ===== FUNKSJONER =====

def resolve_layers_with_dependencies(layers=None):
    """Utvid valgte lag med nødvendige avhengigheter i fast rekkefølge."""
    if layers is None:
        return list(LAYER_ORDER)

    resolved = set()
    pending = list(layers)
    while pending:
        layer = pending.pop()
        if layer in resolved:
            continue
        resolved.add(layer)
        pending.extend(LAYER_DEPENDENCIES.get(layer, []))

    return [layer for layer in LAYER_ORDER if layer in resolved]

def generate_all_layers(layers=None):
    """
    Generer valgte kartlag til separate GeoPackage-filer.
    
    Args:
        layers: Liste av lag å generere (['terrain', 'roads'])
                Hvis None, generer alt
    """
    layers = resolve_layers_with_dependencies(layers)
    
    terrain_data = None
    gdf_roads = None

    if 'terrain' in layers:
        print("Genererer terreng...")
        terrain_data = generate_terrain(**TERRAIN_CONFIG)
    
    # Skriv terreng-layers
    if 'terrain' in layers:
        print(f"Skriver terrenglag til {OUTPUT_TERRAIN_GPKG}...")
        if os.path.exists(OUTPUT_TERRAIN_GPKG):
            os.remove(OUTPUT_TERRAIN_GPKG)
        
        terrain_data["gdf_pts"].to_file(OUTPUT_TERRAIN_GPKG, layer="terrain_points", driver="GPKG")
        print("  ✓ terrain_points")
        
        terrain_data["gdf_tin"].to_file(OUTPUT_TERRAIN_GPKG, layer="terrain_tin", driver="GPKG")
        print("  ✓ terrain_tin")
        
        terrain_data["gdf_contours"].to_file(OUTPUT_TERRAIN_GPKG, layer="hoydekurver_1m", driver="GPKG")
        print("  ✓ hoydekurver_1m")
        
        print(f"\nTerreng-statistikk ({OUTPUT_TERRAIN_GPKG}):")
        print(f"  Punkter: {len(terrain_data['gdf_pts'])}")
        print(f"  TIN-triangler: {len(terrain_data['gdf_tin'])}")
        print(f"  Høydekurver: {len(terrain_data['gdf_contours'])}")
    
    # Generer og skriv vegnett
    if 'roads' in layers:
        print(f"\nGenererer vegnett...")
        gdf_roads = generate_roads(terrain_data, crs=CRS)
        
        if os.path.exists(OUTPUT_ROADS_GPKG):
            os.remove(OUTPUT_ROADS_GPKG)
        
        gdf_roads.to_file(OUTPUT_ROADS_GPKG, layer="vegnett_riksveg", driver="GPKG")
        print(f"Skrevet til {OUTPUT_ROADS_GPKG}")
        print("  ✓ vegnett_riksveg")
        
        # Generer vegkanter
        gdf_vegkant = generate_vegkant(gdf_roads, crs=CRS)
        gdf_vegkant.to_file(OUTPUT_ROADS_GPKG, layer="vegkant", driver="GPKG")
        print("  \u2713 vegkant")
        
        print(f"\nVeg-statistikk ({OUTPUT_ROADS_GPKG}):")
        print(f"  Veger totalt: {len(gdf_roads)}")
        for vtype, count in gdf_roads["veg_type"].value_counts().items():
            print(f"  {vtype}: {count}")
        print(f"  Vegkanter: {len(gdf_vegkant)}")
    
    # Generer og skriv bygninger
    if 'buildings' in layers:
        print(f"\nGenererer bygninger...")
        gdf_buildings = generate_buildings(gdf_roads, bbox=BBOX, crs=CRS)
        
        if os.path.exists(OUTPUT_BUILDINGS_GPKG):
            os.remove(OUTPUT_BUILDINGS_GPKG)
        
        gdf_buildings.to_file(OUTPUT_BUILDINGS_GPKG, layer="bygninger", driver="GPKG")
        print(f"Skrevet til {OUTPUT_BUILDINGS_GPKG}")
        print("  ✓ bygninger")
        
        print(f"\nBygning-statistikk ({OUTPUT_BUILDINGS_GPKG}):")
        print(f"  Bygninger totalt: {len(gdf_buildings)}")
        if len(gdf_buildings) > 0:
            for btype, count in gdf_buildings["bygning_type"].value_counts().items():
                print(f"  {btype}: {count}")
    
    print("\n✅ Kartgenerering fullført")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '--layers',
        default='all',
        help='Kartlag å generere (terrain, roads, eller all). Kommasseparert liste hvis flere.'
    )
    
    args = parser.parse_args()
    
    # Parser lagargument
    if args.layers.lower() == 'all':
        requested_layers = ['terrain', 'roads', 'buildings']
    else:
        requested_layers = [l.strip().lower() for l in args.layers.split(',')]
    
    # Valider lagene
    valid_layers = {'terrain', 'roads', 'buildings'}
    invalid = set(requested_layers) - valid_layers
    if invalid:
        print(f"❌ Feil: ukjente lag: {invalid}")
        print(f"   Tillatte lag: {valid_layers}")
        sys.exit(1)

    layers = resolve_layers_with_dependencies(requested_layers)
    
    print(f"📍 Område: {BBOX}")
    print(f"🗺️  Koordinatsystem: {CRS}")
    print(f"📊 Valgte lag: {', '.join(requested_layers)}")
    print(f"🔗 Kjøres i rekkefølge: {', '.join(layers)}\n")
    generate_all_layers(layers)


if __name__ == "__main__":
    main()
