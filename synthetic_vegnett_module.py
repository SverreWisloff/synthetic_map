"""
Veggenereringsmodul for syntetisk kartdata.
Genererer riksveier basert på terrengmodell.
"""

import numpy as np
import geopandas as gpd
import shapely.geometry as geom


def interpolate_height_from_tin(x, y, all_points, tri_delaunay):
    """Interpoler høyde basert på TIN ved hjelp av Delaunay find_simplex + barysentriske koordinater."""
    simplex_idx = tri_delaunay.find_simplex(np.array([x, y]))
    if simplex_idx >= 0:
        simplex = tri_delaunay.simplices[simplex_idx]
        tri_pts = all_points[simplex]
        v0 = tri_pts[2][:2] - tri_pts[0][:2]
        v1 = tri_pts[1][:2] - tri_pts[0][:2]
        v2 = np.array([x, y]) - tri_pts[0][:2]
        denom = v0[0] * v1[1] - v0[1] * v1[0]
        if abs(denom) > 1e-12:
            u = (v1[1] * v2[0] - v1[0] * v2[1]) / denom
            v = (v0[0] * v2[1] - v0[1] * v2[0]) / denom
            w = 1 - u - v
            h = w * tri_pts[0][2] + u * tri_pts[2][2] + v * tri_pts[1][2]
            return float(h)
    # Fallback: nærmeste punkt
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
                    start=None, end=None, veg_type="Riksveg", veg_nummer=1, veg_navn=None):
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
        
        prev_was_straight = False
        while np.linalg.norm(current_point - end) > segment_length_max and iterations < iteration_limit:
            iterations += 1
            
            # Beregn retning mot slutten
            target_direction = np.arctan2(end[1] - current_point[1], end[0] - current_point[0])
            direction_diff = normalize_angle(target_direction - direction_to_end)
            
            # Avgør om vi skal kurve eller gå rett (maks én rett segment på rad)
            if prev_was_straight or np.random.random() < 0.4:  # Tving kurve etter rett segment
                radius = np.random.uniform(radius_min, radius_max)
                if direction_diff < 0.0:
                    radius = -radius
                segment_length = np.random.uniform(segment_length_min, segment_length_max)
                
                try:
                    arc_pts, next_direction = create_arc_segment(current_point, direction_to_end, radius, 
                                                                  segment_length, point_density=point_density)
                    points.extend(arc_pts)
                    direction_to_end = next_direction
                    prev_was_straight = False
                except:
                    pass  # Hopp over dårlige segmenter
            else:  # Rett linje
                segment_length = np.random.uniform(segment_length_min, segment_length_max)
                next_point = current_point + segment_length * np.array([np.cos(direction_to_end), 
                                                                        np.sin(direction_to_end)])
                points.append((next_point[0], next_point[1]))
                prev_was_straight = True
            
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
            "veg_navn": veg_navn or f"{veg_type}{veg_nummer}",
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
        "veg_navn": veg_navn or f"{veg_type}{veg_nummer}",
        "elevation_points": elevation_points
    }


def create_kommunalveg(all_points, triangles, bbox, segment_length_min=50.0, segment_length_max=100.0,
                       radius_min=70.0, radius_max=100.0, point_density=0.2, max_attempts=20,
                       start=None, end=None, veg_type="KommunalVeg", veg_nummer=1, veg_navn=None):
    """Generer en kommunalveg med kortere segmenter og mindre bueradius enn riksveg."""
    return create_riksveg(
        all_points, triangles, bbox,
        segment_length_min=segment_length_min, segment_length_max=segment_length_max,
        radius_min=radius_min, radius_max=radius_max,
        point_density=point_density, max_attempts=max_attempts,
        start=start, end=end, veg_type=veg_type, veg_nummer=veg_nummer, veg_navn=veg_navn,
    )


def generate_private_avkjorsler(kommunale_veger, all_points, triangles, bbox,
                                all_roads=None,
                                avstand_fra_ende=50.0, avstand_min=70.0, avstand_max=120.0,
                                lengde_min=10.0, lengde_max=50.0):
    """
    Generer private avkjørsler (korte stikkveger) fra kommunale veger.

    Hver avkjørsel er en 2-punkts linje, normalt (90°) på den kommunale vegen,
    med tilfeldig lengde og tilfeldig side (venstre/høyre).
    Avkjørsler som krysser andre veger forkastes.

    Args:
        kommunale_veger: liste av road-dicts med "geometry"
        all_points: terrengpunkter for høydeinterpolasjon
        triangles: TIN-triangler
        bbox: (minx, miny, maxx, maxy)
        all_roads: liste av alle road-dicts for krysningssjekk
        avstand_fra_ende: minimumsavstand fra vegendene (meter)
        avstand_min: minimumsavstand mellom avkjørsler (meter)
        avstand_max: maksimumsavstand mellom avkjørsler (meter)
        lengde_min: minimum avkjørsellengde (meter)
        lengde_max: maksimum avkjørsellengde (meter)

    Returns:
        list of road-dicts
    """
    from shapely.geometry import box as shp_box
    from shapely.ops import unary_union
    minx, miny, maxx, maxy = bbox
    area_poly = shp_box(minx, miny, maxx, maxy)

    # Samle alle andre veggeometrier for krysningssjekk
    other_road_lines = []
    if all_roads:
        for r in all_roads:
            other_road_lines.append(r["geometry"])
    else:
        for v in kommunale_veger:
            other_road_lines.append(v["geometry"])
    other_roads_union = unary_union(other_road_lines)

    avkjorsler = []
    nummer = 0

    for veg in kommunale_veger:
        line = veg["geometry"]
        road_length = line.length
        veg_navn = veg.get("veg_navn", "")

        distance_along = avstand_fra_ende
        end_limit = road_length - avstand_fra_ende

        while distance_along < end_limit:
            point_on_road = line.interpolate(distance_along)

            # Beregn tangentretning
            eps = 1.0
            d_fwd = min(distance_along + eps, road_length)
            d_bwd = max(distance_along - eps, 0)
            p_fwd = line.interpolate(d_fwd)
            p_bwd = line.interpolate(d_bwd)
            dx = p_fwd.x - p_bwd.x
            dy = p_fwd.y - p_bwd.y
            seg_len = np.sqrt(dx**2 + dy**2)
            if seg_len < 1e-6:
                distance_along += avstand_min
                continue

            # Normal (90°) til vegen: (-dy, dx) normalisert
            nx, ny = -dy / seg_len, dx / seg_len

            # Tilfeldig side og lengde
            side = np.random.choice([1, -1])
            lengde = np.random.uniform(lengde_min, lengde_max)

            end_x = point_on_road.x + side * lengde * nx
            end_y = point_on_road.y + side * lengde * ny

            avkjorsel_line = geom.LineString([
                (point_on_road.x, point_on_road.y),
                (end_x, end_y),
            ])

            # Sjekk at endepunktet er innenfor bbox
            if area_poly.contains(geom.Point(end_x, end_y)):
                # Sjekk at avkjørselen ikke krysser andre veger
                if avkjorsel_line.crosses(other_roads_union):
                    distance_along += np.random.uniform(avstand_min, avstand_max)
                    continue

                # Interpoler høyder
                z_start = interpolate_height_from_tin(point_on_road.x, point_on_road.y, all_points, triangles)
                z_end = interpolate_height_from_tin(end_x, end_y, all_points, triangles)

                nummer += 1
                avkjorsler.append({
                    "geometry": avkjorsel_line,
                    "veg_type": "PrivatAvkjørsel",
                    "veg_nummer": nummer,
                    "veg_navn": f"Avkjørsel_{veg_navn}_{nummer}",
                    "elevation_points": [
                        (point_on_road.x, point_on_road.y, z_start),
                        (end_x, end_y, z_end),
                    ],
                })

            # Neste avkjørsel
            distance_along += np.random.uniform(avstand_min, avstand_max)

    return avkjorsler


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
    main_riksveg = create_riksveg(all_points, tri5, bbox, veg_nummer=1, veg_navn="RiksvegA")
    
    # Generer grenveg fra 25% av hovedriksvegen til nordvesthjørnet
    main_line = main_riksveg["geometry"]
    branch_point = main_line.interpolate(main_line.length * 0.25)
    branch_start = (branch_point.x, branch_point.y)
    branch_end = np.array((bbox[0] + 20.0, bbox[3] - 20.0))
    
    branch_riksveg = None
    for attempt in range(50):
        candidate = create_riksveg(
            all_points,
            tri5,
            bbox,
            start=branch_start,
            end=branch_end,
            veg_nummer=2,
            veg_navn="RiksvegB",
        )
        if not candidate["geometry"].crosses(main_line) and not candidate["geometry"].overlaps(main_line):
            branch_riksveg = candidate
            break

    if branch_riksveg is None:
        raise RuntimeError("Klarte ikke generere en sekundær riksveg uten krysning")

    # Generer KommunalVegA fra midt på RiksvegA til midten av nordkanten
    kommunal_start_pt = main_line.interpolate(main_line.length * 0.5)
    kommunal_start = (kommunal_start_pt.x, kommunal_start_pt.y)
    kommunal_end = ((bbox[0] + bbox[2]) * 0.5, bbox[3] - 20.0)

    branch_line = branch_riksveg["geometry"]
    kommunalveg_a = None
    for attempt in range(50):
        candidate = create_kommunalveg(
            all_points, tri5, bbox,
            start=kommunal_start, end=kommunal_end,
            veg_nummer=1, veg_navn="KommunalVegA",
        )
        cline = candidate["geometry"]
        if not cline.crosses(main_line) and not cline.crosses(branch_line):
            kommunalveg_a = candidate
            break

    if kommunalveg_a is None:
        raise RuntimeError("Klarte ikke generere KommunalVegA uten krysning")

    # Generer KommunalVegB fra 20% ut på KommunalVegA til 20% ut på RiksvegB
    komm_a_line = kommunalveg_a["geometry"]
    kommb_start_pt = komm_a_line.interpolate(komm_a_line.length * 0.25)
    kommb_end_pt = branch_line.interpolate(branch_line.length * 0.25)
    kommb_start = (kommb_start_pt.x, kommb_start_pt.y)
    kommb_end = (kommb_end_pt.x, kommb_end_pt.y)

    kommunalveg_b = None
    komm_a_line_geom = kommunalveg_a["geometry"]
    for attempt in range(50):
        candidate = create_kommunalveg(
            all_points, tri5, bbox,
            start=kommb_start, end=kommb_end,
            veg_nummer=2, veg_navn="KommunalVegB",
        )
        cline = candidate["geometry"]
        if not cline.crosses(main_line) and not cline.crosses(branch_line) and not cline.crosses(komm_a_line_geom):
            kommunalveg_b = candidate
            break

    if kommunalveg_b is None:
        raise RuntimeError("Klarte ikke generere KommunalVegB uten krysning")

    # Generer private avkjørsler fra kommunale veger
    alle_veger = [main_riksveg, branch_riksveg, kommunalveg_a, kommunalveg_b]
    avkjorsler = generate_private_avkjorsler(
        [kommunalveg_a, kommunalveg_b],
        all_points, tri5, bbox,
        all_roads=alle_veger,
    )

    # Opprett GeoDataFrame
    all_roads = [main_riksveg, branch_riksveg, kommunalveg_a, kommunalveg_b] + avkjorsler
    gdf_riksveg = gpd.GeoDataFrame(all_roads, crs=crs)
    return gdf_riksveg


# Vegbredder (halvparten brukes som buffer)
VEGBREDDE = {
    "Riksveg": 10.0,
    "KommunalVeg": 5.0,
    "PrivatAvkjørsel": 4.0,
}


def _unit_vector(vector):
    """Returner normalisert vektor eller None for nullvektor."""
    length = np.linalg.norm(vector)
    if length < 1e-9:
        return None
    return vector / length


def _line_intersection(point_a, direction_a, point_b, direction_b):
    """Finn skjæringspunkt mellom to uendelige linjer."""
    det = direction_a[0] * direction_b[1] - direction_a[1] * direction_b[0]
    if abs(det) < 1e-9:
        return None
    delta = point_b - point_a
    scale_a = (delta[0] * direction_b[1] - delta[1] * direction_b[0]) / det
    return point_a + scale_a * direction_a


def _build_tangent_fillet_candidates(line_point_a, line_dir_a, line_point_b, line_dir_b, radius, num_points=12,
                                     inverse_arc=False, center_side_origin=None, center_side_axis=None):
    """Bygg alle gyldige sirkelbuer som er tangent til to linjer med gitt radius."""
    dir_a = _unit_vector(line_dir_a)
    dir_b = _unit_vector(line_dir_b)
    if dir_a is None or dir_b is None:
        return []

    intersection = _line_intersection(np.array(line_point_a), dir_a, np.array(line_point_b), dir_b)
    if intersection is None:
        return []

    dot_product = float(np.clip(np.dot(dir_a, dir_b), -1.0, 1.0))
    angle = np.arccos(dot_product)
    if angle < 1e-3 or abs(np.pi - angle) < 1e-3:
        return []

    tangent_distance = radius / np.tan(angle / 2.0)
    tangent_a = intersection + dir_a * tangent_distance
    tangent_b = intersection + dir_b * tangent_distance

    normal_a = np.array([-dir_a[1], dir_a[0]])
    normal_b = np.array([-dir_b[1], dir_b[0]])

    candidates = []
    for sign_a in (-1.0, 1.0):
        for sign_b in (-1.0, 1.0):
            candidate_a = tangent_a + sign_a * normal_a * radius
            candidate_b = tangent_b + sign_b * normal_b * radius
            error = np.linalg.norm(candidate_a - candidate_b)
            candidate_center = 0.5 * (candidate_a + candidate_b)
            if error > 1e-4:
                continue

            start_angle = np.arctan2(tangent_a[1] - candidate_center[1], tangent_a[0] - candidate_center[0])
            end_angle = np.arctan2(tangent_b[1] - candidate_center[1], tangent_b[0] - candidate_center[0])

            tangent_ccw = _unit_vector(np.array([
                -(tangent_a[1] - candidate_center[1]),
                tangent_a[0] - candidate_center[0],
            ]))
            if tangent_ccw is None:
                continue

            if np.dot(tangent_ccw, dir_a) >= np.dot(-tangent_ccw, dir_a):
                if end_angle <= start_angle:
                    end_angle += 2 * np.pi
            else:
                if end_angle >= start_angle:
                    end_angle -= 2 * np.pi

            if inverse_arc:
                if end_angle > start_angle:
                    end_angle -= 2 * np.pi
                else:
                    end_angle += 2 * np.pi

            angle_span = abs(end_angle - start_angle)
            point_count = max(num_points, int(np.ceil(angle_span / (np.pi / 12.0))) + 1)
            angles = np.linspace(start_angle, end_angle, point_count)
            arc_coords = [
                (
                    candidate_center[0] + radius * np.cos(angle_value),
                    candidate_center[1] + radius * np.sin(angle_value),
                )
                for angle_value in angles
            ]
            side_value = None
            if center_side_origin is not None and center_side_axis is not None:
                side_value = float(np.dot(candidate_center - center_side_origin, center_side_axis))
            candidates.append({
                "geometry": geom.LineString(arc_coords),
                "center": candidate_center,
                "side_value": side_value,
                "length": radius * angle_span,
            })

    return candidates


def _append_boundary_lines(vegkanter, road, geometry, veg_type, bredde):
    """Legg til boundary-linjer fra en buffergeometri."""
    from shapely.geometry import MultiLineString

    boundary = geometry.boundary
    if boundary.is_empty:
        return

    lines = list(boundary.geoms) if isinstance(boundary, MultiLineString) else [boundary]
    for line in lines:
        vegkanter.append({
            "geometry": line,
            "veg_type": veg_type,
            "veg_navn": road.get("veg_navn", ""),
            "vegbredde": bredde,
        })


def _extract_boundary_lines(geometry):
    """Hent boundary som liste av linjer."""
    from shapely.geometry import MultiLineString

    boundary = geometry.boundary
    if boundary.is_empty:
        return []
    return list(boundary.geoms) if isinstance(boundary, MultiLineString) else [boundary]


def _split_line_at_point(line, split_point):
    """Splitt en linje i punktet nærmest split_point."""
    from shapely.ops import substring

    split_geom = geom.Point(float(split_point[0]), float(split_point[1]))
    distance_along = line.project(split_geom)
    if distance_along <= 1e-9 or distance_along >= line.length - 1e-9:
        return [line]

    first = substring(line, 0.0, distance_along)
    second = substring(line, distance_along, line.length)
    parts = []
    for part in (first, second):
        if not part.is_empty and len(part.coords) >= 2:
            parts.append(part)
    return parts or [line]


def _split_boundary_lines_at_points(boundary_lines, split_points, tolerance=1e-3):
    """Splitt boundary-linjer ved punktene som ligger nærmest de oppgitte split-punktene."""
    current_lines = list(boundary_lines)
    for split_point in split_points:
        split_geom = geom.Point(float(split_point[0]), float(split_point[1]))
        best_index = None
        best_distance = float("inf")
        for index, line in enumerate(current_lines):
            distance = line.distance(split_geom)
            if distance < best_distance:
                best_distance = distance
                best_index = index

        if best_index is None or best_distance > tolerance:
            continue

        line = current_lines.pop(best_index)
        split_parts = _split_line_at_point(line, split_point)
        current_lines[best_index:best_index] = split_parts

    return current_lines


def _get_split_point_near_arc_end(fillet, boundary_lines):
    """Velg den bue-enden som ligger nærmest stikkvegens vegkant."""
    if fillet.is_empty or not boundary_lines:
        return None

    start_point = geom.Point(fillet.coords[0])
    end_point = geom.Point(fillet.coords[-1])
    start_distance = min(line.distance(start_point) for line in boundary_lines)
    end_distance = min(line.distance(end_point) for line in boundary_lines)
    if start_distance <= end_distance:
        return np.array(start_point.coords[0])
    return np.array(end_point.coords[0])


def _find_parent_main_road(ep, stikk_idx, stikkveg_type, regler_for_type, gdf_roads):
    """Finn nærmeste hovedveg for et gitt stikkveg-endepunkt."""
    ep_point = geom.Point(ep)
    best_match = None
    best_distance = float("inf")

    for regel in regler_for_type:
        hovedveg_type = regel["hovedveg"]
        hovedveger = gdf_roads[gdf_roads["veg_type"] == hovedveg_type]
        if hovedveg_type == stikkveg_type:
            hovedveger = hovedveger[hovedveger.index != stikk_idx]

        for _, main_road in hovedveger.iterrows():
            distance = main_road.geometry.distance(ep_point)
            if distance < best_distance:
                best_distance = distance
                best_match = {
                    "main_road": main_road,
                    "main_type": hovedveg_type,
                    "regel_kilde": f"{stikkveg_type}<-{hovedveg_type}",
                }

    if best_match is None or best_distance > 1.0:
        return None
    return best_match


def _add_t_junction_fillets(vegkanter, side_road, main_roads, main_half_width, side_half_width,
                            fillet_radius, num_arc, side_type, fillet_records=None,
                            endpoint_pairs=None):
    """Legg til avrundingsbuer for en stikkveg som møter en hovedveg i et T-kryss."""
    if endpoint_pairs is None:
        side_coords = list(side_road.geometry.coords)
        endpoints = [
            (np.array(side_coords[0]), np.array(side_coords[1])),
            (np.array(side_coords[-1]), np.array(side_coords[-2])),
        ]
    else:
        endpoints = endpoint_pairs

    for ep, next_pt in endpoints:
        ep_point = geom.Point(ep)
        parent_main = None
        min_dist = float("inf")
        for _, main_road in main_roads.iterrows():
            dist = main_road.geometry.distance(ep_point)
            if dist < min_dist:
                min_dist = dist
                parent_main = main_road

        if parent_main is None or min_dist > 1.0:
            continue

        main_line = parent_main.geometry
        proj_d = main_line.project(ep_point)
        eps_d = 1.0
        p_fwd = main_line.interpolate(min(proj_d + eps_d, main_line.length))
        p_bwd = main_line.interpolate(max(proj_d - eps_d, 0))

        main_axis = _unit_vector(np.array([p_fwd.x - p_bwd.x, p_fwd.y - p_bwd.y]))
        side_axis = _unit_vector(next_pt - ep)
        if main_axis is None or side_axis is None:
            continue

        main_normal = np.array([-main_axis[1], main_axis[0]])
        if np.dot(side_axis, main_normal) < 0:
            main_normal = -main_normal
        main_edge_point = ep + main_normal * main_half_width

        side_normal = np.array([-side_axis[1], side_axis[0]])
        side_edge_specs = [
            {"point": ep + side_normal * side_half_width, "side_sign": 1.0},
            {"point": ep - side_normal * side_half_width, "side_sign": -1.0},
        ]

        edge_candidates = []
        for edge_spec in side_edge_specs:
            side_edge_point = edge_spec["point"]
            corner_point = _line_intersection(main_edge_point, main_axis, side_edge_point, side_axis)
            if corner_point is None:
                continue

            along_main = np.dot(corner_point - ep, main_axis)
            if abs(along_main) < 1e-6:
                along_main = np.dot(side_edge_point - ep, main_axis)
            main_direction = main_axis if along_main >= 0 else -main_axis

            fillet_candidates = _build_tangent_fillet_candidates(
                main_edge_point,
                main_direction,
                side_edge_point,
                side_axis,
                fillet_radius,
                num_points=num_arc,
                inverse_arc=True,
                center_side_origin=ep,
                center_side_axis=side_normal,
            )
            side_sign = edge_spec["side_sign"]
            valid_candidates = [
                candidate for candidate in fillet_candidates
                if candidate["side_value"] is not None and side_sign * candidate["side_value"] > 1e-9
            ]
            if valid_candidates:
                edge_candidates.append(valid_candidates)

        chosen_candidates = []
        if len(edge_candidates) == 2:
            best_pair = None
            best_score = float("inf")
            for candidate_a in edge_candidates[0]:
                for candidate_b in edge_candidates[1]:
                    score = abs(candidate_a["length"] - candidate_b["length"])
                    if score < best_score:
                        best_score = score
                        best_pair = (candidate_a, candidate_b)
            if best_pair is not None:
                chosen_candidates = list(best_pair)
        elif len(edge_candidates) == 1:
            chosen_candidates = [min(edge_candidates[0], key=lambda candidate: candidate["length"])]

        for candidate in chosen_candidates:
            fillet = candidate["geometry"]
            if fillet.is_empty:
                continue
            if fillet_records is not None:
                fillet_records.append({
                    "fillet": fillet,
                })
            vegkanter.append({
                "geometry": fillet,
                "veg_type": side_type,
                "veg_navn": side_road.get("veg_navn", ""),
                "vegbredde": side_half_width * 2.0,
            })


def generate_vegkant(gdf_roads, crs="EPSG:25833", fillet_radius=4.0):
    """
    Generer vegkanter ved å buffre senterlinjer med halv vegbredde
    og trekke ut venstre og høyre kantlinje.

    T-kryss behandles eksplisitt som hovedveg og stikkveg.
    Kommunalveg går inn på riksveg som stikkveg, og privat avkjørsel
    går inn på kommunalveg som stikkveg.

    Args:
        gdf_roads: GeoDataFrame med veger (må ha 'veg_type')
        crs: Koordinatsystem
        fillet_radius: Radius på avrundingsbue ved kryss (meter)

    Returns:
        GeoDataFrame med vegkant-linjer
    """
    from shapely.ops import unary_union

    vegkanter = []
    num_arc = 8
    t_kryss_regler = [
        {"hovedveg": "Riksveg", "stikkveg": "KommunalVeg"},
        {"hovedveg": "KommunalVeg", "stikkveg": "KommunalVeg"},
        {"hovedveg": "KommunalVeg", "stikkveg": "PrivatAvkjørsel"},
    ]
    regler_per_stikkveg = {}
    for regel in t_kryss_regler:
        regler_per_stikkveg.setdefault(regel["stikkveg"], []).append(regel)

    road_types = set(gdf_roads["veg_type"].unique())
    stikkvegtyper = {regel["stikkveg"] for regel in t_kryss_regler}

    for veg_type in sorted(road_types - stikkvegtyper):
        bredde = VEGBREDDE.get(veg_type, 4.0)
        for _, road in gdf_roads[gdf_roads["veg_type"] == veg_type].iterrows():
            buffered = road.geometry.buffer(bredde / 2.0, cap_style=2)
            _append_boundary_lines(
                vegkanter,
                road,
                buffered,
                veg_type,
                bredde,
            )

    for stikkveg_type in sorted(stikkvegtyper):
        regler_for_type = regler_per_stikkveg.get(stikkveg_type, [])
        stikkveger = gdf_roads[gdf_roads["veg_type"] == stikkveg_type]
        if not regler_for_type or stikkveger.empty:
            continue

        stikkbredde = VEGBREDDE.get(stikkveg_type, 4.0)
        stikk_half_width = stikkbredde / 2.0

        for stikk_idx, stikkveg in stikkveger.iterrows():
            side_coords = list(stikkveg.geometry.coords)
            endpoint_pairs = [
                (np.array(side_coords[0]), np.array(side_coords[1])),
                (np.array(side_coords[-1]), np.array(side_coords[-2])),
            ]
            endpoint_matches = []
            for ep, next_pt in endpoint_pairs:
                parent_match = _find_parent_main_road(ep, stikk_idx, stikkveg_type, regler_for_type, gdf_roads)
                if parent_match is None:
                    continue
                endpoint_matches.append({
                    "endpoint": ep,
                    "next_pt": next_pt,
                    **parent_match,
                })

            buffered = stikkveg.geometry.buffer(stikk_half_width, cap_style=2)
            if not endpoint_matches:
                _append_boundary_lines(
                    vegkanter,
                    stikkveg,
                    buffered,
                    stikkveg_type,
                    stikkbredde,
                )
                continue

            hovedveg_union = unary_union([
                match["main_road"].geometry.buffer(VEGBREDDE.get(match["main_type"], 4.0) / 2.0, cap_style=2)
                for match in endpoint_matches
            ])

            clipped = buffered.difference(hovedveg_union)
            boundary_lines = _extract_boundary_lines(clipped) if not clipped.is_empty else []
            fillet_records = []

            for match in endpoint_matches:
                hoved_half_width = VEGBREDDE.get(match["main_type"], 4.0) / 2.0
                _add_t_junction_fillets(
                    vegkanter,
                    stikkveg,
                    gpd.GeoDataFrame([match["main_road"]], crs=gdf_roads.crs),
                    hoved_half_width,
                    stikk_half_width,
                    fillet_radius,
                    num_arc,
                    stikkveg_type,
                    fillet_records=fillet_records,
                    endpoint_pairs=[(match["endpoint"], match["next_pt"])],
                )

            split_points = [
                split_point
                for record in fillet_records
                for split_point in [_get_split_point_near_arc_end(record["fillet"], boundary_lines)]
                if split_point is not None
            ]

            for line in _split_boundary_lines_at_points(boundary_lines, split_points):
                vegkanter.append({
                    "geometry": line,
                    "veg_type": stikkveg_type,
                    "veg_navn": stikkveg.get("veg_navn", ""),
                    "vegbredde": stikkbredde,
                })

    dekkede_typar = {regel["hovedveg"] for regel in t_kryss_regler} | stikkvegtyper
    for veg_type in sorted(road_types - dekkede_typar):
        bredde = VEGBREDDE.get(veg_type, 4.0)
        for _, road in gdf_roads[gdf_roads["veg_type"] == veg_type].iterrows():
            buffered = road.geometry.buffer(bredde / 2.0, cap_style=2)
            _append_boundary_lines(
                vegkanter,
                road,
                buffered,
                veg_type,
                bredde,
            )

    return gpd.GeoDataFrame(vegkanter, crs=crs)
