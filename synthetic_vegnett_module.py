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
                    radius_min=150.0, radius_max=250.0, point_density=0.2, max_attempts=20,
                    start=None, end=None, veg_type="Riksveg", veg_nummer=1):
    """Generer en veg som en sekvens av kontinuerlige segmenter (forenklet, raskere versjon)."""
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
        direction_to_end = np.arctan2(end[1] - start[1], end[0] - start[0])
        
        # Generer segmenter inntil vi er nær slutten
        iteration_limit = int(np.linalg.norm(end - start) / segment_length_min * 1.5)
        iterations = 0
        
        while np.linalg.norm(current_point - end) > segment_length_max and iterations < iteration_limit:
            iterations += 1
            
            # Beregn retning mot slutten
            target_direction = np.arctan2(end[1] - current_point[1], end[0] - current_point[0])
            direction_diff = normalize_angle(target_direction - direction_to_end)
            
            # Avgør om vi skal kurve eller gå rett
            if np.random.random() < 0.4:  # 40% sjanse for kurving
                radius = np.random.uniform(radius_min, radius_max)
                if direction_diff < 0.0:
                    radius = -radius
                segment_length = np.random.uniform(segment_length_min, segment_length_max)
                
                try:
                    arc_pts, next_direction = create_arc_segment(current_point, direction_to_end, radius, 
                                                                  segment_length, point_density=point_density)
                    points.extend(arc_pts)
                    direction_to_end = next_direction
                except:
                    pass  # Hopp over dårlige segmenter
            else:  # Rett linje
                segment_length = np.random.uniform(segment_length_min, segment_length_max)
                next_point = current_point + segment_length * np.array([np.cos(direction_to_end), 
                                                                        np.sin(direction_to_end)])
                points.append((next_point[0], next_point[1]))
            
            current_point = np.array(points[-1])
        
        # Legg til siste rett del mot endepunktet
        remaining = np.linalg.norm(end - current_point)
        if remaining > 1e-3:
            num_last = max(2, int(remaining * point_density))
            for i in range(1, num_last + 1):
                t = i / num_last
                x = current_point[0] * (1 - t) + end[0] * t
                y = current_point[1] * (1 - t) + end[1] * t
                points.append((x, y))
        
        # Valider linja
        candidate = geom.LineString(points)
        if not candidate.is_simple:
            continue
        
        # Interpoler høyder
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
    
    # Fallback: generer en enkel rett linje hvis ingen kurving funker
    points = [tuple(start), tuple(end)]
    elevation_points = []
    for x, y in points:
        z = interpolate_height_from_tin(x, y, all_points, triangles)
        elevation_points.append((x, y, z))
    
    return {
        "geometry": geom.LineString(points),
        "veg_type": veg_type,
        "veg_nummer": veg_nummer,
        "elevation_points": elevation_points
    }


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
