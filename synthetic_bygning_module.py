"""
Bygningsgenereringsmodul for syntetisk kartdata.
Genererer bygningsgrupper ved enden av private avkjørsler.
"""

import numpy as np
import geopandas as gpd
from shapely.geometry import Polygon, box
from shapely.affinity import rotate, translate
from shapely.ops import unary_union


def create_rectangular_building(width, depth):
    """Lag et rektangulært bygningsfotavtrykk sentrert i origo."""
    return box(-width / 2, -depth / 2, width / 2, depth / 2)


def create_l_shaped_building(width, depth):
    """Lag et L-formet bygningsfotavtrykk sentrert ca. i origo."""
    wing_w = width * np.random.uniform(0.4, 0.6)
    wing_d = depth * np.random.uniform(0.4, 0.6)

    main = box(0, 0, width, depth)
    wing = box(0, 0, wing_w, wing_d)

    corner = np.random.choice(["NE", "NW", "SE", "SW"])
    if corner == "NE":
        wing = translate(wing, xoff=width, yoff=depth - wing_d)
    elif corner == "NW":
        wing = translate(wing, xoff=-wing_w, yoff=depth - wing_d)
    elif corner == "SE":
        wing = translate(wing, xoff=width, yoff=0)
    else:
        wing = translate(wing, xoff=-wing_w, yoff=0)

    l_shape = unary_union([main, wing])
    cx, cy = l_shape.centroid.x, l_shape.centroid.y
    return translate(l_shape, xoff=-cx, yoff=-cy)


def _sample_building_dimensions(size_min, size_max, max_ratio):
    """Sample lengde og bredde med kontrollert forhold der lengde > bredde."""
    min_ratio = 1.05

    for _ in range(100):
        width = np.random.uniform(size_min, size_max)
        min_length = max(size_min, width * min_ratio)
        max_length = min(size_max, width * max_ratio * 0.999)
        if min_length < max_length:
            length = np.random.uniform(min_length, max_length)
            return length, width

    width = size_min
    length = min(size_max, size_min * min(max_ratio * 0.95, 1.2))
    return length, width


def _footprint_ratio(building):
    """Beregn lengde/bredde-forholdet til bygningens bounding box."""
    minx, miny, maxx, maxy = building.bounds
    length = max(maxx - minx, maxy - miny)
    width = min(maxx - minx, maxy - miny)
    if width < 1e-9:
        return float("inf")
    return length / width


def create_random_building(size_min=6.0, size_max=25.0):
    """Lag en tilfeldig bygning (rektangulær eller L-formet) med tilfeldig rotasjon."""
    for _ in range(100):
        if np.random.random() < 0.5:
            length, width = _sample_building_dimensions(size_min, size_max, max_ratio=2.0)
            bygning = create_rectangular_building(length, width)
            bygning_type = "Rektangulær"
            max_ratio = 2.0
        else:
            length, width = _sample_building_dimensions(size_min, size_max, max_ratio=1.5)
            bygning = create_l_shaped_building(length, width)
            bygning_type = "L-formet"
            max_ratio = 1.5

        angle = np.random.uniform(0, 360)
        bygning = rotate(bygning, angle, origin=(0, 0))
        if _footprint_ratio(bygning) < max_ratio:
            return bygning, bygning_type

    return bygning, bygning_type


def create_building_group(center_x, center_y, n_buildings=None,
                          size_min=6.0, size_max=30.0,
                          avstand_mellom=8.0):
    """
    Lag en bygningsgruppe med 2-3 bygninger rundt et senter.

    Returns:
        list of (Polygon, str) — bygningsgeometrier og typer
    """
    if n_buildings is None:
        n_buildings = np.random.choice([2, 3])

    buildings = []
    placed_polys = []

    for i in range(n_buildings):
        for _try in range(50):
            bygning, bygning_type = create_random_building(size_min, size_max)

            if i == 0:
                bx, by = center_x, center_y
            else:
                ref = placed_polys[-1]
                angle = np.random.uniform(0, 2 * np.pi)
                ref_bounds = ref.bounds
                ref_size = max(ref_bounds[2] - ref_bounds[0], ref_bounds[3] - ref_bounds[1])
                b_bounds = bygning.bounds
                b_size = max(b_bounds[2] - b_bounds[0], b_bounds[3] - b_bounds[1])
                offset = (ref_size + b_size) / 2 + avstand_mellom
                bx = ref.centroid.x + offset * np.cos(angle)
                by = ref.centroid.y + offset * np.sin(angle)

            placed = translate(bygning, xoff=bx, yoff=by)

            # Sjekk at avstand til alle plasserte bygninger >= avstand_mellom
            ok = True
            for existing in placed_polys:
                if placed.distance(existing) < avstand_mellom * 0.9:
                    ok = False
                    break

            if ok:
                placed_polys.append(placed)
                buildings.append((placed, bygning_type))
                break

    return buildings


def remove_overlapping_buildings(buildings, min_distance=2.0):
    """
    Fjern bygninger som overlapper eller ligger for tett: den minste slettes.

    Args:
        buildings: list of dicts med "geometry" og andre felter
        min_distance: minste tillatte avstand mellom bygninger (meter)

    Returns:
        filtrert liste av dicts
    """
    # Sorter etter areal, størst først
    sorted_buildings = sorted(buildings, key=lambda b: b["geometry"].area, reverse=True)
    kept = []

    for b in sorted_buildings:
        overlaps = False
        for existing in kept:
            if (
                b["geometry"].intersects(existing["geometry"])
                or b["geometry"].distance(existing["geometry"]) < min_distance
            ):
                overlaps = True
                break
        if not overlaps:
            kept.append(b)

    return kept


def generate_buildings(gdf_roads, bbox, crs="EPSG:25833",
                       size_min=6.0, size_max=25.0,
                       avstand_mellom_bygning=5.0,
                       avstand_fra_veg=20.0):
    """
    Generer bygninger ved enden av private avkjørsler.

    Args:
        gdf_roads: GeoDataFrame med veggeometrier (inkl. PrivatAvkjørsel)
        bbox: (minx, miny, maxx, maxy)
        crs: Koordinatsystem
        size_min: Minimum bygningsstørrelse (meter)
        size_max: Maksimum bygningsstørrelse (meter)
        avstand_mellom_bygning: Avstand mellom bygninger i en gruppe (meter)
        avstand_fra_veg: Hvor mye lenger fra vegen gruppesenteret flyttes langs avkjørselen (meter)

    Returns:
        GeoDataFrame med bygninger
    """
    minx, miny, maxx, maxy = bbox
    area_poly = box(minx, miny, maxx, maxy)

    avkjorsler = gdf_roads[gdf_roads["veg_type"] == "PrivatAvkjørsel"]

    all_buildings = []

    for _, avk in avkjorsler.iterrows():
        coords = list(avk.geometry.coords)
        # Endepunktet av avkjørselen (borte fra kommunalvegen)
        end_x, end_y = coords[-1][0], coords[-1][1]
        prev_x, prev_y = coords[-2][0], coords[-2][1]

        direction_x = end_x - prev_x
        direction_y = end_y - prev_y
        direction_length = np.sqrt(direction_x**2 + direction_y**2)
        if direction_length > 1e-6:
            end_x += avstand_fra_veg * direction_x / direction_length
            end_y += avstand_fra_veg * direction_y / direction_length

        group = create_building_group(
            end_x, end_y,
            size_min=size_min, size_max=size_max,
            avstand_mellom=avstand_mellom_bygning,
        )

        veg_navn = avk.get("veg_navn", "")

        for bygning_poly, bygning_type in group:
            if area_poly.contains(bygning_poly):
                all_buildings.append({
                    "geometry": bygning_poly,
                    "bygning_type": bygning_type,
                    "avkjorsel": veg_navn,
                })

    # Flytt bygninger som er nærmere enn 8m fra Riksveg/KommunalVeg, og slett de som overlapper
    hovedveger = gdf_roads[gdf_roads["veg_type"].isin(["Riksveg", "KommunalVeg"])]
    min_avstand_hovedveg = 13.0
    if len(hovedveger) > 0:
        hovedveg_lines = unary_union(hovedveger.geometry)
        moved_buildings = []
        for b in all_buildings:
            geom = b["geometry"]
            dist = geom.distance(hovedveg_lines)
            if dist < min_avstand_hovedveg:
                # Beregn retning bort fra nærmeste punkt på vegen
                nearest_on_road = hovedveg_lines.interpolate(hovedveg_lines.project(geom.centroid))
                dx = geom.centroid.x - nearest_on_road.x
                dy = geom.centroid.y - nearest_on_road.y
                length = np.sqrt(dx**2 + dy**2)
                if length < 1e-6:
                    continue  # Kan ikke beregne retning, slett bygningen
                # Flytt bygningen slik at avstand blir min_avstand_hovedveg
                shift = min_avstand_hovedveg - dist + 0.5  # litt margin
                moved_geom = translate(geom, xoff=shift * dx / length, yoff=shift * dy / length)
                if area_poly.contains(moved_geom) and not moved_geom.intersects(hovedveg_lines):
                    b = dict(b)
                    b["geometry"] = moved_geom
                    moved_buildings.append(b)
            else:
                moved_buildings.append(b)
        all_buildings = moved_buildings

    # Fjern bygninger som overlapper eller ligger nærmere enn 2 meter (minste slettes)
    all_buildings = remove_overlapping_buildings(all_buildings, min_distance=2.0)

    if not all_buildings:
        return gpd.GeoDataFrame(columns=["geometry", "bygning_type", "avkjorsel"], crs=crs)

    return gpd.GeoDataFrame(all_buildings, crs=crs)
