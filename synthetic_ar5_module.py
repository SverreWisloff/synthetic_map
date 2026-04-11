"""
AR5-genereringsmodul for syntetisk kartdata.
Genererer heldekkende AR5-flater fra terreng, vann, vegnett og bygninger.
"""

import geopandas as gpd
import numpy as np
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from synthetic_vann_module import _build_triangle_data, _detect_flat_areas


def _safe_unary_union(geometries):
    """Returner robust union for polygongeometrier."""
    cleaned = [geometry.buffer(0) for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not cleaned:
        return None
    union = unary_union(cleaned)
    if union.is_empty:
        return None
    return union.buffer(0)


def _iter_polygon_parts(geometry):
    """Iterer over Polygon-deler fra en vilkårlig polygonal geometri."""
    if geometry is None or geometry.is_empty:
        return []
    geometry = geometry.buffer(0)
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [part for part in getattr(geometry, "geoms", []) if isinstance(part, Polygon)]


def _merge_polygons(geometries, clip_geometry=None, merge_distance=0.0, min_area=1.0):
    """Slå sammen polygoner, valgfritt med liten merge-avstand, og returner flater."""
    prepared = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not prepared:
        return []

    if merge_distance > 0:
        prepared = [geometry.buffer(merge_distance) for geometry in prepared]

    merged = _safe_unary_union(prepared)
    if merged is None:
        return []

    if merge_distance > 0:
        merged = merged.buffer(-merge_distance)
    if clip_geometry is not None:
        merged = merged.intersection(clip_geometry)

    return [polygon.buffer(0) for polygon in _iter_polygon_parts(merged) if polygon.area >= min_area]


def _subtract_from_polygons(polygons, mask, clip_geometry=None, min_area=1.0):
    """Trekk masken fra polygoner og returner gjenværende polygonflater."""
    if not polygons:
        return []
    results = []
    for polygon in polygons:
        geometry = polygon if mask is None else polygon.difference(mask)
        if clip_geometry is not None:
            geometry = geometry.intersection(clip_geometry)
        results.extend(part.buffer(0) for part in _iter_polygon_parts(geometry) if part.area >= min_area)
    return results


def _weighted_numeric_attributes(source_gdf, polygon, fields):
    """Overfør numeriske attributter fra kildeflater ved arealvektet middel."""
    values = {field: [] for field in fields}
    weights = []

    for row in source_gdf.itertuples(index=False):
        overlap_area = polygon.intersection(row.geometry).area
        if overlap_area <= 1e-6:
            continue
        weights.append(overlap_area)
        for field in fields:
            values[field].append(float(getattr(row, field, 0.0)))

    attributes = {}
    if not weights:
        for field in fields:
            attributes[field] = 0.0
        return attributes

    total_weight = float(sum(weights))
    for field in fields:
        weighted_sum = sum(value * weight for value, weight in zip(values[field], weights))
        attributes[field] = weighted_sum / total_weight if total_weight > 0 else 0.0
    return attributes


def _build_water_replacement_gdf(source_gdf, polygons, value_fields, crs):
    """Bygg oppdatert GeoDataFrame for vannflater basert på AR5-geometri."""
    records = []
    for polygon in polygons:
        attributes = _weighted_numeric_attributes(source_gdf, polygon, value_fields)
        records.append({
            "geometry": polygon,
            **attributes,
            "areal": float(polygon.area),
        })

    columns = ["geometry", *value_fields, "areal"]
    if not records:
        return gpd.GeoDataFrame({column: [] for column in columns}, geometry=[], crs=crs)
    return gpd.GeoDataFrame(records, geometry="geometry", crs=crs)


def _build_transport_polygons(gdf_roads, road_widths, clip_geometry):
    """Generer samferdselsflater fra vegsenterlinjer og vegbredder."""
    geometries = []
    for row in gdf_roads.itertuples(index=False):
        width = float(road_widths.get(row.veg_type, 4.0))
        geometries.append(row.geometry.buffer(width / 2.0, cap_style=2))
    return _merge_polygons(geometries, clip_geometry=clip_geometry, min_area=1.0)


def _build_bebygd_polygons(gdf_buildings, clip_geometry, building_buffer, merge_distance):
    """Generer bebygde flater fra buffrede bygningsfotavtrykk."""
    geometries = [row.geometry.buffer(building_buffer) for row in gdf_buildings.itertuples(index=False)]
    return _merge_polygons(
        geometries,
        clip_geometry=clip_geometry,
        merge_distance=merge_distance,
        min_area=1.0,
    )


def _build_fulldyrka_polygons(terrain_data, available_geometry, max_slope_degrees, min_area, smooth_distance):
    """Finn relativt flate gjenværende områder og lag fulldyrka jord."""
    if available_geometry is None or available_geometry.is_empty:
        return []

    tri_data = _build_triangle_data(terrain_data["all_points"], terrain_data["tri5"])
    flat_components = _detect_flat_areas(tri_data, max_slope_degrees)
    if not flat_components:
        return []

    candidate_geometries = []
    minx, miny, maxx, maxy = available_geometry.bounds
    for component in flat_components:
        polygons = [tri_data["polygons"][idx] for idx in component]
        union = _safe_unary_union(polygons)
        if union is None:
            continue
        component_bounds = union.bounds
        if component_bounds[2] < minx or component_bounds[0] > maxx or component_bounds[3] < miny or component_bounds[1] > maxy:
            continue
        geometry = union.intersection(available_geometry)
        if geometry.is_empty:
            continue
        if smooth_distance > 0:
            geometry = geometry.buffer(smooth_distance).buffer(-smooth_distance)
        candidate_geometries.extend(part for part in _iter_polygon_parts(geometry) if part.area >= min_area)

    return _merge_polygons(candidate_geometries, clip_geometry=available_geometry, min_area=min_area)


def _validate_no_overlaps(type_geometries, tolerance=1.0):
    """Kontroller at ulike AR5-typer ikke overlapper i nevneverdig grad."""
    type_names = list(type_geometries.keys())
    for index, type_name in enumerate(type_names):
        geometry_a = _safe_unary_union(type_geometries[type_name])
        if geometry_a is None:
            continue
        for other_type in type_names[index + 1:]:
            geometry_b = _safe_unary_union(type_geometries[other_type])
            if geometry_b is None:
                continue
            overlap_area = geometry_a.intersection(geometry_b).area
            if overlap_area > tolerance:
                raise RuntimeError(f"AR5-overlapp mellom {type_name} og {other_type}: {overlap_area:.2f} m2")


def generate_ar5(
    terrain_data,
    water_data,
    gdf_roads,
    gdf_buildings,
    bbox,
    crs="EPSG:25833",
    road_widths=None,
    building_buffer=100.0,
    built_merge_distance=20.0,
    fulldyrka_max_slope=4.0,
    fulldyrka_min_area=20000.0,
    flat_area_smooth_distance=4.0,
):
    """Generer heldekkende AR5-flater og oppdaterte vannflater."""
    area_polygon = box(*bbox)
    road_widths = {} if road_widths is None else dict(road_widths)

    samferdsel_polygons = _build_transport_polygons(gdf_roads, road_widths, area_polygon)
    samferdsel_mask = _safe_unary_union(samferdsel_polygons)

    bebygd_polygons = _build_bebygd_polygons(gdf_buildings, area_polygon, building_buffer, built_merge_distance)
    # Samferdsel har høyest prioritet. Bebygd skal bare reduseres mot Samferdsel,
    # mens vann og myr senere reduseres mot Bebygd.
    bebygd_polygons = _subtract_from_polygons(bebygd_polygons, samferdsel_mask, clip_geometry=area_polygon)
    bebygd_polygons = _merge_polygons(bebygd_polygons, clip_geometry=area_polygon, min_area=1.0)
    bebygd_mask = _safe_unary_union(bebygd_polygons)

    ferskvann_polygons = []
    for row in water_data["gdf_innsjokant"].itertuples(index=False):
        geometry = row.geometry.intersection(area_polygon)
        if geometry.is_empty:
            continue
        if samferdsel_mask is not None:
            geometry = geometry.difference(samferdsel_mask)
        if geometry.is_empty:
            continue
        # Hvis Bebygd treffer en ferskvannflate, fjernes hele ferskvannflaten fra AR5.
        if bebygd_mask is not None and geometry.intersects(bebygd_mask):
            continue
        ferskvann_polygons.extend(part.buffer(0) for part in _iter_polygon_parts(geometry) if part.area >= 1.0)
    ferskvann_polygons = _merge_polygons(ferskvann_polygons, clip_geometry=area_polygon, min_area=1.0)
    ferskvann_mask = _safe_unary_union(ferskvann_polygons)

    myr_polygons = _merge_polygons(water_data["gdf_myrgrense"].geometry, clip_geometry=area_polygon, min_area=1.0)
    myr_blockers = _safe_unary_union([geometry for geometry in [samferdsel_mask, bebygd_mask, ferskvann_mask] if geometry is not None])
    myr_polygons = _subtract_from_polygons(myr_polygons, myr_blockers, clip_geometry=area_polygon)
    myr_polygons = _merge_polygons(myr_polygons, clip_geometry=area_polygon, min_area=1.0)
    myr_mask = _safe_unary_union(myr_polygons)

    occupied_without_fulldyrka = _safe_unary_union([
        geometry
        for geometry in [samferdsel_mask, ferskvann_mask, myr_mask, bebygd_mask]
        if geometry is not None
    ])
    available_geometry = area_polygon if occupied_without_fulldyrka is None else area_polygon.difference(occupied_without_fulldyrka)

    fulldyrka_polygons = _build_fulldyrka_polygons(
        terrain_data,
        available_geometry,
        max_slope_degrees=fulldyrka_max_slope,
        min_area=fulldyrka_min_area,
        smooth_distance=flat_area_smooth_distance,
    )
    fulldyrka_mask = _safe_unary_union(fulldyrka_polygons)

    occupied = _safe_unary_union([
        geometry
        for geometry in [samferdsel_mask, ferskvann_mask, myr_mask, bebygd_mask, fulldyrka_mask]
        if geometry is not None
    ])
    barskog_geometry = area_polygon if occupied is None else area_polygon.difference(occupied)
    barskog_polygons = _merge_polygons(_iter_polygon_parts(barskog_geometry), clip_geometry=area_polygon, min_area=1.0)

    # Fyll eventuelle numeriske restsliver tilbake til Barskog for heldekkende AR5.
    ar5_geometry = _safe_unary_union(samferdsel_polygons + ferskvann_polygons + myr_polygons + bebygd_polygons + fulldyrka_polygons + barskog_polygons)
    remaining_gap = area_polygon if ar5_geometry is None else area_polygon.difference(ar5_geometry)
    if not remaining_gap.is_empty and remaining_gap.area > 1.0:
        barskog_polygons = _merge_polygons(barskog_polygons + _iter_polygon_parts(remaining_gap), clip_geometry=area_polygon, min_area=1.0)

    type_geometries = {
        "Samferdsel": samferdsel_polygons,
        "Ferskvann": ferskvann_polygons,
        "Myr": myr_polygons,
        "Bebygd": bebygd_polygons,
        "Fulldyrka jord": fulldyrka_polygons,
        "Barskog": barskog_polygons,
    }
    _validate_no_overlaps(type_geometries)

    final_union = _safe_unary_union([geometry for polygons in type_geometries.values() for geometry in polygons])
    uncovered_geometry = area_polygon if final_union is None else area_polygon.difference(final_union)
    if not uncovered_geometry.is_empty and uncovered_geometry.area > 1.0:
        barskog_polygons = list(barskog_polygons) + [part.buffer(0) for part in _iter_polygon_parts(uncovered_geometry) if part.area > 0.01]
        type_geometries["Barskog"] = barskog_polygons
        final_union = _safe_unary_union([geometry for polygons in type_geometries.values() for geometry in polygons])
        uncovered_geometry = area_polygon if final_union is None else area_polygon.difference(final_union)

    uncovered_area = uncovered_geometry.area
    if uncovered_area > 1.0:
        raise RuntimeError(f"AR5 dekker ikke hele området. Gjenstaende areal: {uncovered_area:.2f} m2")

    ar5_records = []
    for ar5_type, polygons in type_geometries.items():
        for polygon in polygons:
            ar5_records.append({
                "geometry": polygon,
                "ar5_type": ar5_type,
                "areal": float(polygon.area),
            })

    gdf_ar5 = gpd.GeoDataFrame(ar5_records, geometry="geometry", crs=crs)
    gdf_ar5 = gdf_ar5.sort_values(["ar5_type", "areal"], ascending=[True, False]).reset_index(drop=True)

    updated_lakes = _build_water_replacement_gdf(
        water_data["gdf_innsjokant"],
        ferskvann_polygons,
        value_fields=["hoyde"],
        crs=crs,
    )
    updated_myr = _build_water_replacement_gdf(
        water_data["gdf_myrgrense"],
        myr_polygons,
        value_fields=["snitt_helning"],
        crs=crs,
    )

    return {
        "gdf_ar5": gdf_ar5,
        "gdf_innsjokant": updated_lakes,
        "gdf_myrgrense": updated_myr,
        "uncovered_area": float(uncovered_area),
        "total_area": float(area_polygon.area),
    }