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
                                avstand_fra_ende=50.0, avstand_min=50.0, avstand_max=100.0,
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
    main_riksveg = create_riksveg(all_points, tri5.simplices, bbox, veg_nummer=1, veg_navn="RiksvegA")
    
    # Generer grenveg fra 25% av hovedriksvegen til nordvesthjørnet
    main_line = main_riksveg["geometry"]
    branch_point = main_line.interpolate(main_line.length * 0.25)
    branch_start = (branch_point.x, branch_point.y)
    branch_end = np.array((bbox[0] + 20.0, bbox[3] - 20.0))
    
    branch_riksveg = None
    for attempt in range(50):
        candidate = create_riksveg(
            all_points,
            tri5.simplices,
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
            all_points, tri5.simplices, bbox,
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
            all_points, tri5.simplices, bbox,
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
        all_points, tri5.simplices, bbox,
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


def generate_vegkant(gdf_roads, crs="EPSG:25833"):
    """
    Generer vegkanter ved å buffre senterlinjer med halv vegbredde
    og trekke ut venstre og høyre kantlinje.

    Args:
        gdf_roads: GeoDataFrame med veger (må ha 'veg_type')
        crs: Koordinatsystem

    Returns:
        GeoDataFrame med vegkant-linjer
    """
    from shapely.geometry import MultiLineString

    vegkanter = []

    for _, road in gdf_roads.iterrows():
        veg_type = road["veg_type"]
        bredde = VEGBREDDE.get(veg_type, 4.0)
        buffer_dist = bredde / 2.0

        # Buffer senterlinjen
        buffered = road.geometry.buffer(buffer_dist, cap_style=2)  # flat endecap

        # Hent ytre grense som vegkant-linjer
        boundary = buffered.boundary
        if boundary.is_empty:
            continue

        # Boundary kan være LineString eller MultiLineString
        if isinstance(boundary, MultiLineString):
            lines = list(boundary.geoms)
        else:
            lines = [boundary]

        for line in lines:
            vegkanter.append({
                "geometry": line,
                "veg_type": veg_type,
                "veg_navn": road.get("veg_navn", ""),
                "vegbredde": bredde,
            })

    return gpd.GeoDataFrame(vegkanter, crs=crs)
