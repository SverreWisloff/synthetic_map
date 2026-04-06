"""
Veggenereringsmodul for syntetisk kartdata.
Genererer riksveier basert på terrengmodell.
"""

import numpy as np
import geopandas as gpd
import shapely.geometry as geom


def interpolate_height_from_tin(x, y, all_points, triangles):
    """Interpoler høyde basert på TIN ved hjelp av barysentriskekoordinater."""
    for simplex in triangles:
        tri_pts = all_points[simplex]
        v0 = tri_pts[2][:2] - tri_pts[0][:2]
        v1 = tri_pts[1][:2] - tri_pts[0][:2]
        v2 = np.array([x, y]) - tri_pts[0][:2]
        
        dot00 = np.dot(v0, v0)
        dot01 = np.dot(v0, v1)
        dot02 = np.dot(v0, v2)
        dot11 = np.dot(v1, v1)
        dot12 = np.dot(v1, v2)
        
        inv_denom = 1 / (dot00 * dot11 - dot01 * dot01) if (dot00 * dot11 - dot01 * dot01) != 0 else 0
        u = (dot11 * dot02 - dot01 * dot12) * inv_denom
        v = (dot00 * dot12 - dot01 * dot02) * inv_denom
        
        if u >= 0 and v >= 0 and u + v <= 1:
            w0 = 1 - u - v
            h = w0 * tri_pts[0][2] + u * tri_pts[2][2] + v * tri_pts[1][2]
            return float(h)
    
    distances = np.sqrt((all_points[:, 0] - x)**2 + (all_points[:, 1] - y)**2)
    nearest_idx = np.argmin(distances)
    return float(all_points[nearest_idx][2])


def normalize_angle(angle):
    """Normaliser vinkel til intervallet [-pi, pi]."""
    while angle > np.pi:
        angle -= 2 * np.pi
    while angle < -np.pi:
        angle += 2 * np.pi
    return angle


def sample_arc(center, radius, start_angle, end_angle, num_points=12):
    """Sample punkter langs en sirkulær bue."""
    angles = np.linspace(start_angle, end_angle, num_points)
    return [(center[0] + radius * np.cos(angle), center[1] + radius * np.sin(angle)) for angle in angles[1:]]


def compute_arc_center(start_point, direction, radius, turn_direction):
    """Beregn senter for en sirkulær bue tangent til startretningen."""
    normal = np.array([-np.sin(direction), np.cos(direction)])
    return np.array(start_point) + turn_direction * radius * normal


def create_arc_segment(start_point, start_direction, radius, arc_length, point_density=0.2):
    """Lag et buesegment tangent til startretningen."""
    radius_abs = abs(radius)
    arc_angle = arc_length / radius_abs
    turn_direction = 1 if radius > 0 else -1
    center = compute_arc_center(start_point, start_direction, radius_abs, turn_direction)
    start_angle = np.arctan2(start_point[1] - center[1], start_point[0] - center[0])
    end_angle = start_angle + turn_direction * arc_angle
    num_points = max(3, int(arc_length * point_density))
    arc_pts = sample_arc(center, radius_abs, start_angle, end_angle, num_points=num_points)
    return arc_pts, normalize_angle(start_direction + turn_direction * arc_angle)


def create_riksveg(all_points, triangles, bbox, segment_length_min=100.0, segment_length_max=200.0,
                    radius_min=150.0, radius_max=250.0, point_density=0.2, max_attempts=200,
                    start=None, end=None, veg_type="Riksveg", veg_nummer=1):
    """Generer en veg som en sekvens av kontinuerlige segmenter."""
    minx, miny, maxx, maxy = bbox
    if start is None:
        start = np.array((minx + np.random.uniform(15.0, 25.0), miny + np.random.uniform(15.0, 25.0)))
    else:
        start = np.array(start)
    if end is None:
        end = np.array((maxx - np.random.uniform(15.0, 25.0), maxy - np.random.uniform(15.0, 25.0)))
    else:
        end = np.array(end)

    for attempt in range(max_attempts):
        points = [tuple(start)]
        current_point = np.array(start)
        current_direction = np.arctan2(end[1] - start[1], end[0] - start[0])

        # Første segment er rett linje
        first_len = np.random.uniform(segment_length_min, segment_length_max)
        first_end = current_point + first_len * np.array([np.cos(current_direction), np.sin(current_direction)])
        points.append((first_end[0], first_end[1]))
        current_point = np.array(first_end)

        while np.linalg.norm(current_point - end) > segment_length_max:
            target_direction = np.arctan2(end[1] - current_point[1], end[0] - current_point[0])
            direction_diff = normalize_angle(target_direction - current_direction)
            radius = np.random.uniform(radius_min, radius_max)
            if direction_diff < 0.0:
                radius = -radius

            segment_length = np.random.uniform(segment_length_min, segment_length_max)
            arc_pts, next_direction = create_arc_segment(current_point, current_direction, radius, segment_length,
                                                         point_density=point_density)
            candidate = geom.LineString(points + arc_pts)
            if not candidate.is_simple:
                break

            points.extend(arc_pts)
            current_point = np.array(points[-1])
            current_direction = next_direction

        else:
            # Legg på siste rette del inn mot endepunktet
            remaining = np.linalg.norm(end - current_point)
            if remaining > 1e-3:
                num_last = max(2, int(remaining * point_density))
                for i in range(1, num_last + 1):
                    t = i / num_last
                    x = current_point[0] * (1 - t) + end[0] * t
                    y = current_point[1] * (1 - t) + end[1] * t
                    points.append((x, y))

            candidate = geom.LineString(points)
            if not candidate.is_simple:
                continue

            elevation_points = []
            for x, y in points:
                z = interpolate_height_from_tin(x, y, all_points, triangles)
                elevation_points.append((x, y, z))

            return {
                "geometry": candidate,
                "veg_type": veg_type,
                "veg_nummer": veg_nummer,
                "elevation_points": elevation_points
            }

    raise RuntimeError(f"Klarte ikke generere en enkel {veg_type} uten selvkrysning")


def generate_roads(terrain_data, crs="EPSG:25833"):
    """
    Generer riksvegnettet basert på terrengdata.
    
    Args:
        terrain_data: dict returnert fra generate_terrain()
        crs: Koordinatsystem
    
    Returns:
        GeoDataFrame med riksvegene
    """
    all_points = terrain_data["all_points"]
    tri5 = terrain_data["tri5"]
    bbox = terrain_data["bbox"]
    
    # Generer hovedriksveg
    main_riksveg = create_riksveg(all_points, tri5.simplices, bbox)
    
    # Generer grenveg fra 25% av hovedriksvegen til nordvesthjørnet
    main_line = main_riksveg["geometry"]
    branch_point = main_line.interpolate(main_line.length * 0.25)
    branch_start = (branch_point.x, branch_point.y)
    branch_end = np.array((bbox[0] + 20.0, bbox[3] - 20.0))
    
    branch_riksveg = None
    for attempt in range(50):
        candidate = create_riksveg(all_points, tri5.simplices, bbox, start=branch_start, end=branch_end)
        if not candidate["geometry"].crosses(main_line) and not candidate["geometry"].overlaps(main_line):
            branch_riksveg = candidate
            branch_riksveg["veg_nummer"] = 2
            break

    if branch_riksveg is None:
        raise RuntimeError("Klarte ikke generere en sekundær riksveg uten krysning")

    # Opprett GeoDataFrame
    gdf_riksveg = gpd.GeoDataFrame([main_riksveg, branch_riksveg], crs=crs)
    return gdf_riksveg
