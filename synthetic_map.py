"""
Hovedprogram for syntetisk kartgenerering.
Genererer terreng, vann, vegnett og bygninger til separate GeoPackage-filer.

Bruk:
    python synthetic_map.py [--layers LAYER1,LAYER2,...]

Tilgjengelige lag:
    - terrain: Terrengpunkter, TIN, og høydekurver → synthetic_terrain.gpkg
    - water: Vannobjekter (innsjøkant, elv/bekk, myr) → synthetic_vann.gpkg
    - roads: Vegnett (riksveier) → synthetic_vegnett.gpkg
    - buildings: Bygninger → synthetic_bygning.gpkg
    - all: Alt (standardvalg)

Eksempler:
    python synthetic_map.py                          # Generer alt
    python synthetic_map.py --layers terrain         # Bare terreng
    python synthetic_map.py --layers water           # Terreng + vann
    python synthetic_map.py --layers roads           # Terreng + vegnett
    python synthetic_map.py --layers buildings       # Terreng + vegnett + bygninger
"""

import argparse
import os
import sys

from synthetic_bygning_module import generate_buildings
from synthetic_hoydekurve_module import generate_terrain
from synthetic_vann_module import generate_water
from synthetic_vegnett_module import generate_roads, generate_vegkant

# ===== KONFIGURASJON =====

# Geografisk område
BBOX = (500000, 6700000, 502000, 6702000)
CRS = "EPSG:25833"

# Output-filer
OUTPUT_TERRAIN_GPKG = "synthetic_terrain.gpkg"
OUTPUT_WATER_GPKG = "synthetic_vann.gpkg"
OUTPUT_ROADS_GPKG = "synthetic_vegnett.gpkg"
OUTPUT_BUILDINGS_GPKG = "synthetic_bygning.gpkg"

LAYER_ORDER = ["terrain", "water", "roads", "buildings"]
LAYER_DEPENDENCIES = {
    "terrain": [],
    "water": ["terrain"],
    "roads": ["terrain"],
    "buildings": ["terrain", "roads"],
}

TERRAIN_CONFIG = {
    "bbox": BBOX,
    "crs": CRS,
    "h_min": 100.0,
    "h_max": 130.0,
    "n_primary": 15,
    "sec_per_tri": 5,
    "sec_delta": 3.0,
    "ter_per_tri": 3,
    "ter_delta": 1.0,
    "qua_per_tri": 3,
    "qua_delta": 0.4,
    "qui_per_tri": 3,
    "qui_delta": 0.1,
    "ekvidistanse": 1.0,
}

WATER_CONFIG = {
    "crs": CRS,
    "inlet_stream_min_length": 100.0,
    "inlet_stream_max_length": 500.0,
    "max_inlets_per_lake": 2,
    "outlet_stream_min_length": 300.0,
    "outlet_stream_max_length": 700.0,
    "outlet_max_climb_height": 2.0,
    "min_lake_area": 400.0,
    "max_lake_area": 20000.0,
    "max_lake_count": 8,
    "min_inner_lake_contours": 1,
    "max_inner_lake_contours": 3,
    "myr_slope_threshold": 1.5,
    "min_myr_area": 500.0,
    "max_myr_area": 10000.0,
    "max_myr_count": 8,
    "myr_merge_distance": 6.0,
    "smooth_iterations": 2,
    "polygon_smooth_distance": 4.0,
}

ROAD_CONFIG = {
    "generation_attempts": 8,
    "main_road": {
        "segment_length_min": 100.0,
        "segment_length_max": 200.0,
        "radius_min": 150.0,
        "radius_max": 250.0,
        "point_density": 0.2,
        "max_attempts": 20,
    },
    "branch_road": {
        "attach_fraction": (0.22, 0.30),
        "end_offset": (18.0, 28.0),
        "candidate_attempts": 50,
        "segment_length_min": 100.0,
        "segment_length_max": 200.0,
        "radius_min": 150.0,
        "radius_max": 250.0,
        "point_density": 0.2,
        "max_attempts": 20,
    },
    "municipal_road_a": {
        "attach_fraction_main": (0.44, 0.56),
        "end_fraction_x": (0.42, 0.58),
        "end_offset": (18.0, 28.0),
        "candidate_attempts": 50,
        "segment_length_min": 50.0,
        "segment_length_max": 100.0,
        "radius_min": 70.0,
        "radius_max": 100.0,
        "point_density": 0.2,
        "max_attempts": 20,
    },
    "municipal_road_b": {
        "attach_fraction_municipal_a": (0.20, 0.32),
        "attach_fraction_branch": (0.20, 0.32),
        "candidate_attempts": 50,
        "segment_length_min": 50.0,
        "segment_length_max": 100.0,
        "radius_min": 70.0,
        "radius_max": 100.0,
        "point_density": 0.2,
        "max_attempts": 20,
    },
    "private_driveways": {
        "avstand_fra_ende": 50.0,
        "avstand_min": 70.0,
        "avstand_max": 120.0,
        "lengde_min": 10.0,
        "lengde_max": 50.0,
    },
}

ROAD_EDGE_CONFIG = {
    "fillet_radius": 4.0,
    "num_arc_points": 8,
    "road_widths": {
        "Riksveg": 10.0,
        "KommunalVeg": 5.0,
        "PrivatAvkjørsel": 4.0,
    },
    "t_junction_rules": [
        {"hovedveg": "Riksveg", "stikkveg": "KommunalVeg"},
        {"hovedveg": "KommunalVeg", "stikkveg": "KommunalVeg"},
        {"hovedveg": "KommunalVeg", "stikkveg": "PrivatAvkjørsel"},
    ],
}


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
    """Generer valgte kartlag til separate GeoPackage-filer."""
    layers = resolve_layers_with_dependencies(layers)

    terrain_data = None
    gdf_roads = None

    if "terrain" in layers:
        print("Genererer terreng...")
        terrain_data = generate_terrain(**TERRAIN_CONFIG)

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

    if "water" in layers:
        print("\nGenererer vannobjekter...")
        water_data = generate_water(terrain_data, **WATER_CONFIG)

        if os.path.exists(OUTPUT_WATER_GPKG):
            os.remove(OUTPUT_WATER_GPKG)

        water_data["gdf_innsjokant"].to_file(OUTPUT_WATER_GPKG, layer="innsjokant", driver="GPKG")
        print(f"Skrevet til {OUTPUT_WATER_GPKG}")
        print("  ✓ innsjokant")

        water_data["gdf_elvbekk"].to_file(OUTPUT_WATER_GPKG, layer="elvbekk", driver="GPKG")
        print("  ✓ elvbekk")

        water_data["gdf_myrgrense"].to_file(OUTPUT_WATER_GPKG, layer="myrgrense", driver="GPKG")
        print("  ✓ myrgrense")

        print(f"\nVann-statistikk ({OUTPUT_WATER_GPKG}):")
        print(f"  Innsjøer: {len(water_data['gdf_innsjokant'])}")
        print(f"  Elv/bekk: {len(water_data['gdf_elvbekk'])}")
        print(f"  Myr: {len(water_data['gdf_myrgrense'])}")

    if "roads" in layers:
        print("\nGenererer vegnett...")
        road_error = None
        for attempt in range(1, ROAD_CONFIG["generation_attempts"] + 1):
            try:
                gdf_roads = generate_roads(
                    terrain_data,
                    crs=CRS,
                    main_road_config=ROAD_CONFIG["main_road"],
                    branch_road_config=ROAD_CONFIG["branch_road"],
                    municipal_road_a_config=ROAD_CONFIG["municipal_road_a"],
                    municipal_road_b_config=ROAD_CONFIG["municipal_road_b"],
                    private_driveway_config=ROAD_CONFIG["private_driveways"],
                )
                road_error = None
                break
            except RuntimeError as error:
                road_error = error
                if attempt == ROAD_CONFIG["generation_attempts"]:
                    raise
                print(f"  Forsøk {attempt}/{ROAD_CONFIG['generation_attempts']} mislyktes: {error}")
                print("  Prøver veggenerering på nytt...")

        if road_error is not None:
            raise road_error

        if os.path.exists(OUTPUT_ROADS_GPKG):
            os.remove(OUTPUT_ROADS_GPKG)

        gdf_roads.to_file(OUTPUT_ROADS_GPKG, layer="vegnett_riksveg", driver="GPKG")
        print(f"Skrevet til {OUTPUT_ROADS_GPKG}")
        print("  ✓ vegnett_riksveg")

        gdf_vegkant = generate_vegkant(
            gdf_roads,
            crs=CRS,
            fillet_radius=ROAD_EDGE_CONFIG["fillet_radius"],
            road_widths=ROAD_EDGE_CONFIG["road_widths"],
            t_junction_rules=ROAD_EDGE_CONFIG["t_junction_rules"],
            num_arc_points=ROAD_EDGE_CONFIG["num_arc_points"],
        )
        gdf_vegkant.to_file(OUTPUT_ROADS_GPKG, layer="vegkant", driver="GPKG")
        print("  ✓ vegkant")

        print(f"\nVeg-statistikk ({OUTPUT_ROADS_GPKG}):")
        print(f"  Veger totalt: {len(gdf_roads)}")
        for vtype, count in gdf_roads["veg_type"].value_counts().items():
            print(f"  {vtype}: {count}")
        print(f"  Vegkanter: {len(gdf_vegkant)}")

    if "buildings" in layers:
        print("\nGenererer bygninger...")
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
        "--layers",
        default="all",
        help="Kartlag å generere (terrain, water, roads, buildings, eller all). Kommasseparert liste hvis flere.",
    )

    args = parser.parse_args()

    if args.layers.lower() == "all":
        requested_layers = ["terrain", "water", "roads", "buildings"]
    else:
        requested_layers = [layer.strip().lower() for layer in args.layers.split(",")]

    valid_layers = {"terrain", "water", "roads", "buildings"}
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
