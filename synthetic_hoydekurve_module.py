"""
Terrenggenereringsmodul for syntetisk kartdata.
Genererer terrengpunkter, TIN, og høydekurver.
"""

import numpy as np
import geopandas as gpd
import shapely.geometry as geom
from shapely.ops import linemerge, unary_union
from scipy.spatial import Delaunay


def points_in_triangle(a, b, c, n):
    """Generer n tilfeldige punkter innenfor trekant abc."""
    pts = []
    for _ in range(n):
        r1, r2 = np.random.rand(), np.random.rand()
        if r1 + r2 > 1:
            r1, r2 = 1 - r1, 1 - r2
        x = a[0] * (1 - r1 - r2) + b[0] * r1 + c[0] * r2
        y = a[1] * (1 - r1 - r2) + b[1] * r1 + c[1] * r2
        w0 = (1 - r1 - r2); w1 = r1; w2 = r2
        pts.append((x, y, w0, w1, w2))
    return pts


def add_level_points(points, tris, per_tri, delta, h_min, h_max):
    """Legg til punkter på neste nivå basert på eksisterende triangler."""
    added = []
    for tri in tris:
        idx_a, idx_b, idx_c = tri
        a = points[idx_a]
        b = points[idx_b]
        c = points[idx_c]
        for xyw in points_in_triangle(a, b, c, per_tri):
            x, y, w0, w1, w2 = xyw
            z_base = a[2] * w0 + b[2] * w1 + c[2] * w2
            z = float(np.clip(z_base + np.random.normal(scale=delta), h_min, h_max))
            added.append((x, y, z))
    return added


def generate_contours_from_tin(points, triangles, levels):
    """Generer høydekurver fra TIN ved konturinterpole."""
    contours = []
    for level in levels:
        segments = []
        for tri in triangles:
            p0, p1, p2 = points[tri[0]], points[tri[1]], points[tri[2]]
            h0, h1, h2 = p0[2], p1[2], p2[2]
            edges = [(p0, p1, h0, h1), (p1, p2, h1, h2), (p2, p0, h2, h0)]
            intersections = []
            for pa, pb, ha, hb in edges:
                if (ha <= level <= hb) or (hb <= level <= ha):
                    if ha != hb:
                        t = (level - ha) / (hb - ha)
                        x = pa[0] + t * (pb[0] - pa[0])
                        y = pa[1] + t * (pb[1] - pa[1])
                        intersections.append((x, y))
            if len(intersections) == 2:
                segments.append(geom.LineString(intersections))
        # Slå sammen segmenter til sammenhengende linjer
        if segments:
            merged = linemerge(unary_union(segments))
            if merged.geom_type == 'LineString':
                merged = [merged]
            elif merged.geom_type == 'MultiLineString':
                merged = list(merged.geoms)
            else:
                merged = []
            for line in merged:
                contours.append({"geometry": line, "hoyde": float(level)})
    return contours


def _smooth_line(line, iterations=2):
    """Enkel Chaikin-glatting av en linje."""
    coords = list(line.coords)
    for _ in range(iterations):
        if len(coords) < 3:
            break
        new_coords = [coords[0]]
        for i in range(len(coords) - 1):
            p0 = coords[i]
            p1 = coords[i + 1]
            q = (0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1])
            r = (0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1])
            new_coords.extend([q, r])
        new_coords.append(coords[-1])
        coords = new_coords
    return geom.LineString(coords)


def generate_terrain(bbox, crs="EPSG:25833", h_min=100.0, h_max=130.0,
                    n_primary=15, sec_per_tri=5, ter_per_tri=3, qua_per_tri=3, qui_per_tri=3,
                    sec_delta=3.0, ter_delta=1.0, qua_delta=0.4, qui_delta=0.1, ekvidistanse=1.0,
                    min_kurvlengde=50.0, glatt_iterasjoner=2):
    """
    Generer syntetisk terreng med multi-level punkter og høydekurver.
    
    Args:
        bbox: (minx, miny, maxx, maxy) - bounding box i UTM-koordinater
        crs: Koordinatsystem (default: EPSG:25833)
        h_min, h_max: Høyde-intervall
        n_primary: Antall primære punkter
        sec/ter/qua/qui_per_tri: Punkter per trekant på hvert nivå
        sec/ter/qua/qui_delta: Standardavvik for høydevariasjon
        ekvidistanse: Avstand mellom høydekurver
        min_kurvlengde: Minimum lengde for å beholde en kurve (meter)
        glatt_iterasjoner: Antall Chaikin-glattingsiterasjoner
    
    Returns:
        dict med keys: all_points, tri5, gdf_pts, gdf_tin, gdf_contours, crs, bbox
    """
    minx, miny, maxx, maxy = bbox
    
    # 1) Primærpunkter
    px = np.random.uniform(minx + 20, maxx - 20, n_primary)
    py = np.random.uniform(miny + 20, maxy - 20, n_primary)
    pz = np.random.uniform(h_min, h_max, n_primary)
    primary = np.column_stack((px, py, pz))
    
    # Legg til faste hjørnepunkter
    corner_heights = np.random.uniform(h_min, h_max, 4)
    corner_points = np.array([
        (minx, miny, corner_heights[0]),
        (minx, maxy, corner_heights[1]),
        (maxx, miny, corner_heights[2]),
        (maxx, maxy, corner_heights[3])
    ])
    primary = np.vstack([primary, corner_points])
    
    # 2) TIN fra primær
    tri0 = Delaunay(primary[:, :2])
    sec = add_level_points(primary, tri0.simplices, sec_per_tri, sec_delta, h_min, h_max)
    level1 = np.vstack([primary, np.array(sec)]) if len(sec) else primary
    
    # 3) TIN nivå 1
    tri1 = Delaunay(level1[:, :2])
    
    # 4) Tertiære punkter
    ter = add_level_points(level1, tri1.simplices, ter_per_tri, ter_delta, h_min, h_max)
    level2 = np.vstack([level1, np.array(ter)]) if len(ter) else level1
    
    # 5) TIN nivå 2
    tri2 = Delaunay(level2[:, :2])
    
    # 6) Kvaternære punkter
    qua = add_level_points(level2, tri2.simplices, qua_per_tri, qua_delta, h_min, h_max)
    level3 = np.vstack([level2, np.array(qua)]) if len(qua) else level2
    
    # 7) TIN nivå 3
    tri3 = Delaunay(level3[:, :2])
    
    # 8) Kvintære punkter
    qui = add_level_points(level3, tri3.simplices, qui_per_tri, qui_delta, h_min, h_max)
    level4 = np.vstack([level3, np.array(qui)]) if len(qui) else level3
    
    # 9) TIN nivå 4
    tri4 = Delaunay(level4[:, :2])
    
    # 10) Lag alle-punkter og 5. TIN
    all_points = level4
    tri5 = Delaunay(all_points[:, :2])
    
    # 11) Generer høydekurver
    levels = np.arange(h_min, h_max + ekvidistanse, ekvidistanse)
    lines = generate_contours_from_tin(all_points, tri5.simplices, levels)
    
    # 11b) Fjern små kurver og glatt
    filtered = []
    for feat in lines:
        line = feat["geometry"]
        if line.length < min_kurvlengde:
            continue
        feat["geometry"] = _smooth_line(line, iterations=glatt_iterasjoner)
        filtered.append(feat)
    lines = filtered
    
    # 12) GeoDataFrames
    gdf_pts = gpd.GeoDataFrame(all_points, columns=["x", "y", "hoyde"],
                               geometry=[geom.Point(x, y) for x, y, _ in all_points], crs=crs)
    gdf_tin = gpd.GeoDataFrame([{"geometry": geom.Polygon(all_points[s][:, :2]), "level": "all"}
                               for s in tri5.simplices], crs=crs)
    gdf_contours = gpd.GeoDataFrame(lines, crs=crs)
    
    return {
        "all_points": all_points,
        "tri5": tri5,
        "gdf_pts": gdf_pts,
        "gdf_tin": gdf_tin,
        "gdf_contours": gdf_contours,
        "crs": crs,
        "bbox": bbox,
        "h_min": h_min,
        "h_max": h_max
    }
