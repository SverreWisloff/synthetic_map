"""
Vanngenereringsmodul for syntetisk kartdata.
Genererer innsjøkanter, elv/bekk-senterlinjer og myrgrenser fra TIN-terreng.
"""

from collections import deque

import geopandas as gpd
import numpy as np
from shapely.affinity import rotate
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import substring, unary_union


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
    return LineString(coords)


def _safe_unary_union(geometries):
    """Returner en robust union, også for tomme input."""
    if not geometries:
        return None
    union = unary_union(geometries)
    if union.is_empty:
        return None
    return union


def _iter_polygon_parts(geometry):
    """Iterer over polygon-deler fra Polygon eller MultiPolygon."""
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [geom for geom in getattr(geometry, "geoms", []) if isinstance(geom, Polygon)]


def _cross_2d(vec_a, vec_b):
    """2D-kryssprodukt som skalar."""
    return vec_a[0] * vec_b[1] - vec_a[1] * vec_b[0]


def _ray_segment_intersection(origin, direction, start, end, epsilon=1e-9):
    """Finn første skjæringspunkt mellom en stråle og et linjesegment i 2D."""
    segment = end - start
    denom = _cross_2d(direction, segment)
    if abs(denom) <= epsilon:
        return None

    delta = start - origin
    ray_t = _cross_2d(delta, segment) / denom
    seg_t = _cross_2d(delta, direction) / denom
    if ray_t <= epsilon:
        return None
    if seg_t < -epsilon or seg_t > 1 + epsilon:
        return None

    intersection = origin + ray_t * direction
    return float(ray_t), intersection


def _build_triangle_data(all_points, tri5):
    """Bygg avledet trekantdata fra Delaunay-TIN."""
    simplices = tri5.simplices
    neighbors = tri5.neighbors
    triangle_count = len(simplices)

    centroids = np.zeros((triangle_count, 2), dtype=float)
    centroid_heights = np.zeros(triangle_count, dtype=float)
    areas = np.zeros(triangle_count, dtype=float)
    slope_degrees = np.zeros(triangle_count, dtype=float)
    downhill_vectors = np.zeros((triangle_count, 2), dtype=float)
    polygons = []
    boundary_touch = np.zeros(triangle_count, dtype=bool)

    for idx, simplex in enumerate(simplices):
        tri_pts = all_points[simplex]
        xy = tri_pts[:, :2]
        polygons.append(Polygon(xy))
        centroids[idx] = np.mean(xy, axis=0)
        centroid_heights[idx] = float(np.mean(tri_pts[:, 2]))
        edge_a = xy[1] - xy[0]
        edge_b = xy[2] - xy[0]
        areas[idx] = abs(0.5 * (edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0]))

        vec1 = tri_pts[1] - tri_pts[0]
        vec2 = tri_pts[2] - tri_pts[0]
        normal = np.cross(vec1, vec2)
        nz = normal[2]
        if abs(nz) < 1e-12:
            slope_degrees[idx] = 90.0
        else:
            gradient_x = -normal[0] / nz
            gradient_y = -normal[1] / nz
            gradient_magnitude = np.hypot(gradient_x, gradient_y)
            slope_degrees[idx] = float(np.degrees(np.arctan(gradient_magnitude)))
            downhill_vectors[idx] = np.array([-gradient_x, -gradient_y], dtype=float)

        boundary_touch[idx] = np.any(neighbors[idx] == -1)

    return {
        "simplices": simplices,
        "neighbors": neighbors,
        "centroids": centroids,
        "centroid_heights": centroid_heights,
        "areas": areas,
        "slope_degrees": slope_degrees,
        "downhill_vectors": downhill_vectors,
        "polygons": polygons,
        "boundary_touch": boundary_touch,
        "all_points": all_points,
    }


def _compute_flow_directions(tri_data):
    """Finn nedstrøms nabo per triangel via fasettens utløpskant."""
    simplices = tri_data["simplices"]
    all_points = tri_data["all_points"]
    neighbors = tri_data["neighbors"]
    centroids = tri_data["centroids"]
    downhill_vectors = tri_data["downhill_vectors"]
    downstream = np.full(len(simplices), -1, dtype=int)
    exit_points = np.full((len(simplices), 2), np.nan, dtype=float)
    exit_edges = np.full(len(simplices), -1, dtype=int)

    edge_pairs = [(1, 2), (2, 0), (0, 1)]

    for idx, simplex in enumerate(simplices):
        direction = downhill_vectors[idx]
        direction_norm = np.linalg.norm(direction)
        if direction_norm <= 1e-12:
            continue

        direction = direction / direction_norm
        origin = centroids[idx]
        triangle_xy = all_points[simplex][:, :2]

        best_hit = None
        best_edge_idx = -1
        for edge_idx, (start_idx, end_idx) in enumerate(edge_pairs):
            hit = _ray_segment_intersection(origin, direction, triangle_xy[start_idx], triangle_xy[end_idx])
            if hit is None:
                continue
            hit_t, intersection = hit
            if best_hit is not None and hit_t >= best_hit[0]:
                continue
            best_hit = (hit_t, intersection)
            best_edge_idx = edge_idx

        if best_hit is None:
            continue

        exit_points[idx] = best_hit[1]
        exit_edges[idx] = best_edge_idx
        downstream[idx] = neighbors[idx][best_edge_idx]

    sinks = downstream == -1
    return downstream, sinks, exit_points, exit_edges


def _compute_flow_accumulation(tri_data, downstream):
    """Akkumuler areal nedstrøms gjennom TIN-nettverket."""
    heights = tri_data["centroid_heights"]
    areas = tri_data["areas"]
    accumulation = areas.copy()

    for idx in np.argsort(heights)[::-1]:
        target = downstream[idx]
        if target >= 0:
            accumulation[target] += accumulation[idx]

    return accumulation


def _build_upstream_map(downstream):
    """Bygg oppstrøms naboskapsliste fra nedstrøms peker."""
    upstream_map = [[] for _ in range(len(downstream))]
    for idx, target in enumerate(downstream):
        if target >= 0:
            upstream_map[target].append(idx)
    return upstream_map


def _compute_valley_scores(tri_data):
    """Skår som favoriserer triangler som ligger lavere enn sine naboer."""
    heights = tri_data["centroid_heights"]
    valley_scores = np.zeros(len(heights), dtype=float)
    for idx, neighbors in enumerate(tri_data["neighbors"]):
        valid_neighbors = [int(neighbor) for neighbor in neighbors if neighbor >= 0]
        if not valid_neighbors:
            continue
        valley_scores[idx] = max(0.0, float(np.mean(heights[valid_neighbors]) - heights[idx]))
    return valley_scores


def _find_lake_triangle_indices(lake_geometry, tri_data):
    """Finn triangler hvis sentroider ligger i innsjøpolygonet."""
    if lake_geometry.is_empty:
        return set()

    minx, miny, maxx, maxy = lake_geometry.bounds
    centroids = tri_data["centroids"]
    candidate_indices = np.where(
        (centroids[:, 0] >= minx)
        & (centroids[:, 0] <= maxx)
        & (centroids[:, 1] >= miny)
        & (centroids[:, 1] <= maxy)
    )[0]

    inside = {
        int(idx)
        for idx in candidate_indices
        if lake_geometry.contains(Point(centroids[idx])) or lake_geometry.intersects(tri_data["polygons"][idx])
    }
    return inside


def _nearest_boundary_coordinate(polygon, coordinate):
    """Finn nærmeste punkt på polygonets ytre grense."""
    boundary = polygon.boundary
    projected = boundary.project(Point(coordinate))
    point = boundary.interpolate(projected)
    return (float(point.x), float(point.y))


def _extract_coordinate_candidates(geometry):
    """Trekk ut punktkandidater fra vilkårlig skjæringsgeometri."""
    if geometry is None or geometry.is_empty:
        return []
    geom_type = geometry.geom_type
    if geom_type == "Point":
        return [(float(geometry.x), float(geometry.y))]
    if geom_type == "MultiPoint":
        return [(float(point.x), float(point.y)) for point in geometry.geoms]
    if geom_type == "LineString":
        coords = list(geometry.coords)
        if not coords:
            return []
        mid = coords[len(coords) // 2]
        return [(float(mid[0]), float(mid[1]))]
    if geom_type.startswith("Multi") or geom_type == "GeometryCollection":
        candidates = []
        for part in getattr(geometry, "geoms", []):
            candidates.extend(_extract_coordinate_candidates(part))
        return candidates
    return []


def _segment_boundary_coordinate(polygon, start_coordinate, end_coordinate):
    """Finn skjæringspunkt mellom et segment og innsjøgrensen."""
    segment = LineString([start_coordinate, end_coordinate])
    candidates = _extract_coordinate_candidates(segment.intersection(polygon.boundary))
    if not candidates:
        return _nearest_boundary_coordinate(polygon, end_coordinate)
    end_point = np.array(end_coordinate, dtype=float)
    return min(candidates, key=lambda coord: float(np.linalg.norm(np.array(coord, dtype=float) - end_point)))


def _trim_line_to_length_range(line, min_length, max_length, keep_end=False):
    """Klipp linje til tillatt lengdeintervall."""
    if line.is_empty:
        return None
    if line.length > max_length:
        if keep_end:
            line = substring(line, line.length - max_length, line.length)
        else:
            line = substring(line, 0.0, max_length)
    if line.length < min_length:
        return None
    return line


def _line_directness_ratio(line):
    """Forhold mellom linjelengde og direkte avstand mellom endepunkter."""
    coords = list(line.coords)
    if len(coords) < 2:
        return 0.0
    start = np.array(coords[0], dtype=float)
    end = np.array(coords[-1], dtype=float)
    direct_distance = float(np.linalg.norm(end - start))
    if direct_distance <= 1e-9:
        return 0.0
    return float(line.length / direct_distance)


def _bend_straight_stream(line, amplitude_scale=0.02):
    """Legg inn svak kurvatur i nesten rette bekkelinjer."""
    if line.is_empty:
        return line

    coords = list(line.coords)
    if len(coords) >= 8 and _line_directness_ratio(line) >= 1.06:
        return line

    start = np.array(coords[0], dtype=float)
    end = np.array(coords[-1], dtype=float)
    direction = end - start
    direction_norm = float(np.linalg.norm(direction))
    if direction_norm <= 1e-9:
        return line

    tangent = direction / direction_norm
    normal = np.array([-tangent[1], tangent[0]], dtype=float)
    phase_seed = float((start[0] * 0.013 + start[1] * 0.017 + end[0] * 0.019 + end[1] * 0.023) % 1.0)
    sign = -1.0 if phase_seed < 0.5 else 1.0

    def build_bent_line(scale_multiplier, offset_pattern):
        amplitude = max(4.0, min(60.0, direction_norm * amplitude_scale * scale_multiplier))
        fractions = [0.18, 0.38, 0.62, 0.82]
        bent_coords = [tuple(start)]
        for fraction, offset_factor in zip(fractions, offset_pattern):
            base_point = start + direction * fraction
            offset = normal * amplitude * offset_factor * sign
            bent_coords.append((float(base_point[0] + offset[0]), float(base_point[1] + offset[1])))
        bent_coords.append(tuple(end))
        return LineString(bent_coords)

    def build_arc_line(amplitude):
        control = (start + end) / 2.0 + normal * amplitude * sign
        coords = []
        for t in np.linspace(0.0, 1.0, 17):
            point = ((1.0 - t) ** 2) * start + 2.0 * (1.0 - t) * t * control + (t ** 2) * end
            coords.append((float(point[0]), float(point[1])))
        return LineString(coords)

    bent_line = build_bent_line(1.0, [0.55, 1.0, -0.8, -0.35])
    if not bent_line.is_valid or bent_line.length <= 0:
        return line
    if _line_directness_ratio(bent_line) >= 1.03:
        return bent_line

    stronger_line = build_bent_line(4.5, [0.45, 1.1, 1.15, 0.35])
    if stronger_line.is_valid and stronger_line.length > 0:
        if _line_directness_ratio(stronger_line) >= 1.03:
            return stronger_line

    arc_line = build_arc_line(min(90.0, direction_norm * 0.16))
    if arc_line.is_valid and arc_line.length > 0:
        return arc_line
    return bent_line


def _prepare_line_for_bend(line, min_length, max_length, keep_end=False):
    """Kort inn nesten rette linjer litt før kurvatur, slik at buen overlever sluttklipping."""
    if line is None or line.is_empty:
        return line
    if line.length < max_length * 0.95:
        return line
    if _line_directness_ratio(line) > 1.04:
        return line
    reduced_max_length = max(min_length, max_length * 0.9)
    return _trim_line_to_length_range(line, min_length, reduced_max_length, keep_end=keep_end)


def _trace_inlet_stream(start_idx, lake_geometry, lake_triangles, tri_data, downstream, exit_points):
    """Tracer en nedstrøms linje som ender ved innsjøgrensen."""
    coords = [tuple(tri_data["centroids"][start_idx])]
    visited = set()
    current = int(start_idx)
    end_height = None

    while current not in visited:
        visited.add(current)
        next_idx = int(downstream[current])
        if next_idx < 0:
            return None

        next_centroid = tuple(tri_data["centroids"][next_idx])
        if next_idx in lake_triangles:
            boundary_coordinate = _segment_boundary_coordinate(lake_geometry, coords[-1], next_centroid)
            if coords[-1] != boundary_coordinate:
                coords.append(boundary_coordinate)
            end_height = float(tri_data["centroid_heights"][next_idx])
            break

        current_exit = exit_points[current]
        if np.all(np.isfinite(current_exit)):
            exit_coordinate = tuple(float(value) for value in current_exit)
            if coords[-1] != exit_coordinate:
                coords.append(exit_coordinate)
        if coords[-1] != next_centroid:
            coords.append(next_centroid)
        current = next_idx

    if len(coords) < 2:
        return None
    return LineString(coords), end_height


def _trace_outlet_stream(
    start_idx,
    lake_geometry,
    lake_triangles,
    lake_id,
    lake_owner,
    tri_data,
    downstream,
    exit_points,
):
    """Tracer en utløpslinje fra nærmeste innsjøgrense og nedstrøms ut av innsjøen."""
    start_coordinate = _nearest_boundary_coordinate(lake_geometry, tuple(tri_data["centroids"][start_idx]))
    coords = [start_coordinate]
    start_centroid = tuple(tri_data["centroids"][start_idx])
    if coords[-1] != start_centroid:
        coords.append(start_centroid)

    current = int(start_idx)
    visited = set()
    while current not in visited:
        visited.add(current)
        current_exit = exit_points[current]
        if np.all(np.isfinite(current_exit)):
            exit_coordinate = tuple(float(value) for value in current_exit)
            if coords[-1] != exit_coordinate:
                coords.append(exit_coordinate)

        next_idx = int(downstream[current])
        if next_idx < 0:
            break
        if next_idx in lake_triangles:
            break
        if lake_owner[next_idx] >= 0 and lake_owner[next_idx] != lake_id:
            break

        next_centroid = tuple(tri_data["centroids"][next_idx])
        if coords[-1] != next_centroid:
            coords.append(next_centroid)
        current = next_idx

    if len(coords) < 2:
        return None
    return LineString(coords), float(tri_data["centroid_heights"][current])


def _line_overlap_ratio(line_a, line_b):
    """Andel overlapp mellom to linjer relativt til korteste linje."""
    min_length = min(line_a.length, line_b.length)
    if min_length <= 1e-9:
        return 0.0
    return float(line_a.intersection(line_b.buffer(1.5)).length / min_length)


def _filter_long_stream_features(stream_features, max_outlet_length):
    """Kutt ut lange utløpsbekker som gir unaturlige, dominerende former."""
    filtered = []
    for feature in stream_features:
        if feature.get("bekk_type") == "outlet" and feature.get("lengde", 0.0) > max_outlet_length:
            continue
        filtered.append(feature)
    return filtered


def _pick_inlet_streams_for_lake(
    lake_id,
    lake_feature,
    lake_triangles,
    lake_owner,
    tri_data,
    downstream,
    upstream_map,
    exit_points,
    accumulation,
    valley_scores,
    min_length,
    max_length,
    max_count,
    smooth_iterations,
):
    """Velg 0-2 innløpsbekker som drenerer mot innsjøen og ligger i søkk."""
    if not lake_triangles or max_count <= 0:
        return []

    contributing = set()
    queue = deque(lake_triangles)
    visited = set(lake_triangles)
    while queue:
        current = queue.popleft()
        for upstream_idx in upstream_map[current]:
            if upstream_idx in visited:
                continue
            if lake_owner[upstream_idx] >= 0 and lake_owner[upstream_idx] != lake_id:
                continue
            visited.add(upstream_idx)
            contributing.add(upstream_idx)
            queue.append(upstream_idx)

    if not contributing:
        return []

    candidate_indices = []
    for idx in contributing:
        upstream_contributing = sum(1 for upstream_idx in upstream_map[idx] if upstream_idx in contributing)
        if upstream_contributing != 1:
            candidate_indices.append(idx)
    if not candidate_indices:
        candidate_indices = list(contributing)

    scored_candidates = []
    for idx in candidate_indices:
        traced = _trace_inlet_stream(idx, lake_feature["geometry"], lake_triangles, tri_data, downstream, exit_points)
        if traced is None:
            continue
        line, end_height = traced
        line = _trim_line_to_length_range(line, min_length, max_length, keep_end=True)
        if line is None:
            continue
        if smooth_iterations > 0:
            line = _smooth_line(line, iterations=smooth_iterations)
        line = _prepare_line_for_bend(line, min_length, max_length, keep_end=True)
        if line is None:
            continue
        line = _trim_line_to_length_range(line, min_length, max_length, keep_end=True)
        if line is None:
            continue
        line = _bend_straight_stream(line)
        line = _trim_line_to_length_range(line, min_length, max_length, keep_end=True)
        if line is None:
            continue

        start_height = float(tri_data["centroid_heights"][idx])
        valley_score = float(valley_scores[idx])
        score = float(accumulation[idx] * (1.0 + valley_score) * (0.75 + min(line.length / max_length, 1.0)))
        scored_candidates.append({
            "geometry": line,
            "lake_id": int(lake_id),
            "bekk_type": "inlet",
            "lengde": float(line.length),
            "start_hoyde": start_height,
            "slutt_hoyde": float(lake_feature["hoyde"] if end_height is None else end_height),
            "akkumulasjon": float(accumulation[idx]),
            "valley_score": valley_score,
            "start_tri": int(idx),
            "score": score,
        })

    if not scored_candidates:
        return []

    scored_candidates.sort(key=lambda feature: (feature["score"], feature["lengde"]), reverse=True)

    desired_count = 1
    if len(scored_candidates) >= 2 and lake_feature["areal"] >= 2500.0:
        desired_count = min(max_count, 2)
    else:
        desired_count = min(max_count, 1)

    selected = []
    for candidate in scored_candidates:
        if any(_line_overlap_ratio(candidate["geometry"], existing["geometry"]) > 0.6 for existing in selected):
            continue
        selected.append(candidate)
        if len(selected) >= desired_count:
            break

    for feature in selected:
        feature.pop("score", None)
    return selected


def _pick_outlet_stream_for_lake(
    lake_id,
    lake_feature,
    lake_triangles,
    lake_owner,
    tri_data,
    downstream,
    exit_points,
    accumulation,
    valley_scores,
    min_length,
    max_length,
    max_climb_height,
    smooth_iterations,
):
    """Velg maksimalt én utløpsbekk per innsjø."""
    if not lake_triangles:
        return []

    boundary_candidates = set()
    for tri_idx in lake_triangles:
        for neighbor in tri_data["neighbors"][tri_idx]:
            if neighbor < 0 or neighbor in lake_triangles:
                continue
            if lake_owner[neighbor] >= 0 and lake_owner[neighbor] != lake_id:
                continue
            boundary_candidates.add(int(neighbor))

    if not boundary_candidates:
        return []

    lake_height = float(lake_feature["hoyde"])
    accessible_candidates = []
    queue = deque(sorted(boundary_candidates, key=lambda idx: tri_data["centroid_heights"][idx]))
    visited = set(queue)

    while queue:
        current = queue.popleft()
        current_height = float(tri_data["centroid_heights"][current])
        if current_height <= lake_height + max_climb_height:
            accessible_candidates.append(current)
            for neighbor in tri_data["neighbors"][current]:
                if neighbor < 0 or neighbor in visited or neighbor in lake_triangles:
                    continue
                if lake_owner[neighbor] >= 0 and lake_owner[neighbor] != lake_id:
                    continue
                neighbor_height = float(tri_data["centroid_heights"][neighbor])
                if neighbor_height > lake_height + max_climb_height:
                    continue
                visited.add(int(neighbor))
                queue.append(int(neighbor))

    scored_candidates = []
    for idx in accessible_candidates:
        next_idx = int(downstream[idx])
        if next_idx < 0 or next_idx in lake_triangles:
            continue
        if lake_owner[next_idx] >= 0 and lake_owner[next_idx] != lake_id:
            continue

        traced = _trace_outlet_stream(
            idx,
            lake_feature["geometry"],
            lake_triangles,
            lake_id,
            lake_owner,
            tri_data,
            downstream,
            exit_points,
        )
        if traced is None:
            continue
        line, end_height = traced
        line = _trim_line_to_length_range(line, min_length, max_length, keep_end=False)
        if line is None:
            continue
        if smooth_iterations > 0:
            line = _smooth_line(line, iterations=smooth_iterations)
        line = _prepare_line_for_bend(line, min_length, max_length, keep_end=False)
        if line is None:
            continue
        line = _trim_line_to_length_range(line, min_length, max_length, keep_end=False)
        if line is None:
            continue
        line = _bend_straight_stream(line)
        line = _trim_line_to_length_range(line, min_length, max_length, keep_end=False)
        if line is None:
            continue

        climb_height = max(0.0, float(tri_data["centroid_heights"][idx]) - lake_height)
        score = float(line.length * (1.0 + 0.25 * valley_scores[idx]) - 35.0 * climb_height + 0.002 * accumulation[idx])
        scored_candidates.append({
            "geometry": line,
            "lake_id": int(lake_id),
            "bekk_type": "outlet",
            "lengde": float(line.length),
            "start_hoyde": lake_height,
            "slutt_hoyde": end_height,
            "akkumulasjon": float(accumulation[idx]),
            "valley_score": float(valley_scores[idx]),
            "start_tri": int(idx),
            "climb_hoyde": climb_height,
            "score": score,
        })

    if not scored_candidates:
        return []

    best = max(scored_candidates, key=lambda feature: feature["score"])
    best.pop("score", None)
    return [best]


def _generate_lake_linked_streams(
    tri_data,
    downstream,
    exit_points,
    accumulation,
    lake_features,
    inlet_min_length,
    inlet_max_length,
    max_inlets_per_lake,
    outlet_min_length,
    outlet_max_length,
    outlet_max_climb_height,
    smooth_iterations,
):
    """Generer bekkelinjer knyttet direkte til hver innsjø."""
    if not lake_features:
        return []

    upstream_map = _build_upstream_map(downstream)
    valley_scores = _compute_valley_scores(tri_data)
    lake_triangle_sets = []
    lake_owner = np.full(len(downstream), -1, dtype=int)

    for lake_id, lake_feature in enumerate(lake_features):
        triangles = _find_lake_triangle_indices(lake_feature["geometry"], tri_data)
        lake_triangle_sets.append(triangles)
        for tri_idx in triangles:
            if lake_owner[tri_idx] < 0:
                lake_owner[tri_idx] = lake_id

    stream_features = []
    for lake_id, lake_feature in enumerate(lake_features):
        lake_triangles = lake_triangle_sets[lake_id]
        inlet_features = _pick_inlet_streams_for_lake(
            lake_id,
            lake_feature,
            lake_triangles,
            lake_owner,
            tri_data,
            downstream,
            upstream_map,
            exit_points,
            accumulation,
            valley_scores,
            min_length=inlet_min_length,
            max_length=inlet_max_length,
            max_count=max_inlets_per_lake,
            smooth_iterations=smooth_iterations,
        )
        outlet_features = _pick_outlet_stream_for_lake(
            lake_id,
            lake_feature,
            lake_triangles,
            lake_owner,
            tri_data,
            downstream,
            exit_points,
            accumulation,
            valley_scores,
            min_length=outlet_min_length,
            max_length=outlet_max_length,
            max_climb_height=outlet_max_climb_height,
            smooth_iterations=smooth_iterations,
        )
        stream_features.extend(inlet_features)
        stream_features.extend(outlet_features)

    return stream_features


def _extract_streams(
    tri_data,
    downstream,
    accumulation,
    exit_points,
    stream_threshold,
    min_stream_length,
    smooth_iterations,
):
    """Ekstraher bekkesegmenter fra triangler med høy nok flow accumulation."""
    stream_mask = accumulation >= stream_threshold
    if not np.any(stream_mask):
        return []

    upstream_counts = np.zeros(len(stream_mask), dtype=int)
    for idx, target in enumerate(downstream):
        if target >= 0 and stream_mask[idx] and stream_mask[target]:
            upstream_counts[target] += 1

    visited = set()
    reaches = []

    def trace_reach(start_idx):
        start_point = tuple(tri_data["centroids"][start_idx])
        coords = [start_point]
        accum_values = [float(accumulation[start_idx])]
        current = start_idx
        while True:
            current_exit = exit_points[current]
            if np.all(np.isfinite(current_exit)):
                exit_coord = tuple(current_exit)
                if coords[-1] != exit_coord:
                    coords.append(exit_coord)
            next_idx = downstream[current]
            if next_idx < 0 or not stream_mask[next_idx]:
                break
            edge = (current, next_idx)
            if edge in visited:
                break
            visited.add(edge)
            accum_values.append(float(accumulation[next_idx]))
            current = next_idx
        if len(coords) < 2:
            return None
        line = LineString(coords)
        if smooth_iterations > 0:
            line = _smooth_line(line, iterations=smooth_iterations)
        if line.length < min_stream_length:
            return None
        end_height = float(tri_data["centroid_heights"][current])
        start_height = float(tri_data["centroid_heights"][start_idx])
        elevation_drop = max(0.0, start_height - end_height)
        fall_ratio = elevation_drop / line.length if line.length > 0 else 0.0
        return {
            "geometry": line,
            "akkumulasjon": float(max(accum_values)),
            "lengde": float(line.length),
            "start_tri": int(start_idx),
            "slutt_tri": int(current),
            "elevation_drop": elevation_drop,
            "fall_ratio": fall_ratio,
        }

    start_nodes = [
        idx for idx, is_stream in enumerate(stream_mask)
        if is_stream and upstream_counts[idx] != 1 and downstream[idx] >= 0 and stream_mask[downstream[idx]]
    ]
    start_nodes = sorted(
        start_nodes,
        key=lambda idx: (upstream_counts[idx] != 0, -tri_data["centroid_heights"][idx]),
    )

    for start_idx in start_nodes:
        reach = trace_reach(start_idx)
        if reach is not None:
            reaches.append(reach)

    for idx, target in enumerate(downstream):
        if not stream_mask[idx] or target < 0 or not stream_mask[target]:
            continue
        if (idx, target) in visited:
            continue
        reach = trace_reach(idx)
        if reach is not None:
            reaches.append(reach)

    return reaches


def _collect_components(indices, neighbors):
    """Finn sammenhengende komponenter i en indeksmengde."""
    remaining = set(int(idx) for idx in indices)
    components = []
    while remaining:
        start_idx = remaining.pop()
        queue = deque([start_idx])
        component = {start_idx}
        while queue:
            current = queue.popleft()
            for neighbor in neighbors[current]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(int(neighbor))
                    queue.append(int(neighbor))
        components.append(component)
    return components


def _region_boundary_edges(tri_data, region):
    """Finn randkanter for en trekantregion."""
    simplices = tri_data["simplices"]
    neighbors = tri_data["neighbors"]
    all_points = tri_data["all_points"]
    region_set = set(region)
    boundary_edges = []
    edge_pairs = [(1, 2), (2, 0), (0, 1)]

    for tri_idx in region:
        simplex = simplices[tri_idx]
        for edge_idx, neighbor in enumerate(neighbors[tri_idx]):
            if neighbor in region_set:
                continue
            point_idx_a, point_idx_b = edge_pairs[edge_idx]
            vertex_a = all_points[simplex[point_idx_a]]
            vertex_b = all_points[simplex[point_idx_b]]
            boundary_edges.append({
                "neighbor": int(neighbor),
                "min_z": float(min(vertex_a[2], vertex_b[2])),
                "max_z": float(max(vertex_a[2], vertex_b[2])),
            })
    return boundary_edges


def _find_depression_seeds(tri_data, tolerance=0.05):
    """Finn trekantfrø som ligger lavere enn alle nabotriangler."""
    heights = tri_data["centroid_heights"]
    neighbors = tri_data["neighbors"]
    seeds = []

    for idx, height in enumerate(heights):
        if tri_data["boundary_touch"][idx]:
            continue
        valid_neighbors = [int(neighbor) for neighbor in neighbors[idx] if neighbor >= 0]
        if not valid_neighbors:
            continue
        neighbor_heights = heights[valid_neighbors]
        if np.all(height <= neighbor_heights + tolerance) and np.any(height < neighbor_heights - tolerance):
            seeds.append(idx)

    return np.array(seeds, dtype=int)


def _detect_depressions(tri_data, seed_indices):
    """Finn lukkede depresjoner basert på lokale lavpunkter."""
    sink_indices = np.asarray(seed_indices, dtype=int)
    if len(sink_indices) == 0:
        return []

    components = _collect_components(sink_indices, tri_data["neighbors"])
    depressions = []

    for component in components:
        if any(tri_data["boundary_touch"][idx] for idx in component):
            continue

        region = set(component)
        spill_elevation = None

        for _ in range(20):
            boundary_edges = _region_boundary_edges(tri_data, region)
            if not boundary_edges:
                region = set()
                break
            if any(edge["neighbor"] < 0 for edge in boundary_edges):
                region = set()
                break
            spill_elevation = min(edge["min_z"] for edge in boundary_edges)
            additions = set()
            for edge in boundary_edges:
                neighbor = edge["neighbor"]
                if neighbor < 0 or neighbor in region:
                    continue
                if tri_data["centroid_heights"][neighbor] <= spill_elevation + 0.05:
                    additions.add(neighbor)
            if not additions:
                break
            region.update(additions)

        if not region or spill_elevation is None:
            continue

        depressions.append({
            "triangles": sorted(region),
            "spill_elevation": float(spill_elevation),
        })

    return depressions


def _generate_lake_polygons(tri_data, depressions, min_lake_area, smooth_distance):
    """Konverter depresjoner til innsjøpolygoner."""
    lakes = []
    for depression in depressions:
        polygons = [tri_data["polygons"][idx] for idx in depression["triangles"]]
        lake_geom = _safe_unary_union(polygons)
        if lake_geom is None:
            continue
        if smooth_distance > 0:
            lake_geom = lake_geom.buffer(smooth_distance).buffer(-smooth_distance)
        for polygon in _iter_polygon_parts(lake_geom):
            if polygon.area < min_lake_area:
                continue
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if polygon.is_empty or polygon.area < min_lake_area:
                continue
            lakes.append({
                "geometry": polygon,
                "hoyde": float(depression["spill_elevation"]),
                "areal": float(polygon.area),
            })
    return lakes


def _is_closed_contour(geometry, tolerance=1e-6):
    """Sjekk om en geometri er en lukket kurve som kan bli innsjøkant."""
    if geometry.is_empty or geometry.geom_type != "LineString":
        return False
    if geometry.is_ring:
        return True
    coords = list(geometry.coords)
    if len(coords) < 4:
        return False
    start = np.array(coords[0], dtype=float)
    end = np.array(coords[-1], dtype=float)
    return float(np.linalg.norm(start - end)) <= tolerance


def _generate_lake_polygons_from_closed_contours(
    gdf_contours,
    min_lake_area,
    max_lake_area=None,
    min_inner_contours=1,
    max_inner_contours=3,
    merge_touch_distance=0.5,
):
    """Finn innsjøkandidater fra lukkede høydekurver med 1-3 lavere lukkede kurver inni."""
    # Innsjøer styres av lukkede høydekurver: en ytre lukket kurve blir kandidat
    # når den omslutter 1-3 lavere lukkede kurver, slik at innsjøkanten følger terrengets forsenkning.
    closed_contours = []
    for row in gdf_contours.itertuples(index=False):
        geometry = row.geometry
        if not _is_closed_contour(geometry):
            continue
        polygon = Polygon(geometry)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon.is_empty or polygon.area < min_lake_area:
            continue
        closed_contours.append({
            "geometry": polygon,
            "hoyde": float(row.hoyde),
            "areal": float(polygon.area),
            "repr_point": polygon.representative_point(),
        })

    candidates = []
    for outer in closed_contours:
        lower_inside = []
        for inner in closed_contours:
            if inner is outer:
                continue
            if inner["hoyde"] >= outer["hoyde"]:
                continue
            if outer["geometry"].contains(inner["repr_point"]):
                lower_inside.append(inner)
        if min_inner_contours <= len(lower_inside) <= max_inner_contours:
            candidates.append({
                "geometry": outer["geometry"],
                "hoyde": outer["hoyde"],
                "areal": outer["areal"],
                "inner_count": len(lower_inside),
            })

    selected = []
    for candidate in sorted(candidates, key=lambda feat: (feat["areal"], feat["hoyde"])):
        geometry = _shrink_polygon_to_max_area(candidate["geometry"], max_lake_area, min_lake_area)
        if geometry is None:
            continue
        candidate = {
            **candidate,
            "geometry": geometry,
            "areal": float(geometry.area),
        }
        compare_geometry = geometry.buffer(merge_touch_distance) if merge_touch_distance > 0 else geometry
        if any(compare_geometry.intersects(existing["geometry"]) for existing in selected):
            continue
        selected.append(candidate)

    return selected


def _limit_features(features, max_count, sort_key):
    """Begrens antall features ved å beholde de største/viktigste."""
    if max_count is None or max_count <= 0 or len(features) <= max_count:
        return list(features)
    return sorted(features, key=sort_key, reverse=True)[:max_count]


def _filter_stream_features(
    stream_features,
    lake_features,
    myr_features,
    min_elevation_drop,
    min_fall_ratio,
    max_myr_overlap_ratio,
):
    """Filtrer bort bekkelinjer som er for flate eller ligger nesten helt inne i myr."""
    if not stream_features:
        return []

    myr_union = _safe_unary_union([feature["geometry"] for feature in myr_features])
    filtered = []
    for feature in stream_features:
        if feature["elevation_drop"] < min_elevation_drop:
            continue
        if feature["fall_ratio"] < min_fall_ratio:
            continue
        if myr_union is not None and feature["geometry"].length > 0:
            overlap_length = feature["geometry"].intersection(myr_union).length
            overlap_ratio = overlap_length / feature["geometry"].length
            if overlap_ratio > max_myr_overlap_ratio:
                continue
        filtered.append(feature)
    return filtered


def _features_to_gdf(features, columns, crs):
    """Bygg GeoDataFrame med eksplisitt geometri også for tomme lister."""
    if not features:
        return gpd.GeoDataFrame({column: [] for column in columns}, geometry=[], crs=crs)
    return gpd.GeoDataFrame(features, geometry="geometry", crs=crs)


def _shrink_polygon_to_max_area(polygon, max_area, min_area, iterations=24):
    """Krymp et polygon innover til arealet er under eller lik maksareal."""
    if polygon.is_empty:
        return None
    if max_area is None or max_area <= 0 or polygon.area <= max_area:
        return polygon

    minx, miny, maxx, maxy = polygon.bounds
    low = 0.0
    high = max(maxx - minx, maxy - miny)
    best = None

    for _ in range(iterations):
        mid = (low + high) / 2.0
        candidate = polygon.buffer(-mid)
        parts = [part for part in _iter_polygon_parts(candidate) if part.area >= min_area]
        if not parts:
            high = mid
            continue
        candidate = max(parts, key=lambda part: part.area)
        if candidate.area > max_area:
            low = mid
            continue
        best = candidate.buffer(0)
        high = mid

    if best is None or best.is_empty or best.area < min_area:
        return None
    return best


def _split_polygon_to_max_area(polygon, max_area, min_area, max_depth=8):
    """Del opp et polygon rekursivt langs roterte snitt til alle deler er under maksareal."""
    if polygon.is_empty:
        return []
    if max_area is None or max_area <= 0 or polygon.area <= max_area:
        return [polygon]
    if max_depth <= 0:
        return []

    rotated_rect = polygon.minimum_rotated_rectangle
    rect_coords = list(rotated_rect.exterior.coords)
    if len(rect_coords) < 4:
        return []

    longest_edge = None
    longest_length = -1.0
    for idx in range(4):
        start = np.array(rect_coords[idx], dtype=float)
        end = np.array(rect_coords[idx + 1], dtype=float)
        edge = end - start
        length = float(np.hypot(edge[0], edge[1]))
        if length > longest_length:
            longest_length = length
            longest_edge = edge

    if longest_edge is None or longest_length <= 1e-9:
        return []

    base_angle = float(np.degrees(np.arctan2(longest_edge[1], longest_edge[0])))
    offset_angle = 17.0 if max_depth % 2 == 0 else -17.0
    split_angle = base_angle + offset_angle

    centroid = polygon.centroid
    rotated_polygon = rotate(polygon, -split_angle, origin=centroid, use_radians=False)
    minx, miny, maxx, maxy = rotated_polygon.bounds
    width = maxx - minx
    height = maxy - miny
    if width <= 1e-9 and height <= 1e-9:
        return []

    if width >= height:
        mid = (minx + maxx) / 2.0
        split_boxes = [
            box(minx - 1.0, miny - 1.0, mid, maxy + 1.0),
            box(mid, miny - 1.0, maxx + 1.0, maxy + 1.0),
        ]
    else:
        mid = (miny + maxy) / 2.0
        split_boxes = [
            box(minx - 1.0, miny - 1.0, maxx + 1.0, mid),
            box(minx - 1.0, mid, maxx + 1.0, maxy + 1.0),
        ]

    pieces = []
    for split_box in split_boxes:
        clipped = rotated_polygon.intersection(split_box)
        for part in _iter_polygon_parts(clipped):
            if part.is_empty or part.area < min_area:
                continue
            restored = rotate(part, split_angle, origin=centroid, use_radians=False).buffer(0)
            if restored.is_empty or restored.area < min_area:
                continue
            pieces.append(restored)

    if len(pieces) <= 1:
        return []

    results = []
    for piece in pieces:
        results.extend(_split_polygon_to_max_area(piece, max_area, min_area, max_depth=max_depth - 1))
    return results


def _detect_flat_areas(tri_data, max_slope_degrees):
    """Finn sammenhengende områder av flate triangler."""
    flat_indices = np.where(tri_data["slope_degrees"] <= max_slope_degrees)[0]
    if len(flat_indices) == 0:
        return []
    return _collect_components(flat_indices, tri_data["neighbors"])


def _merge_nearby_myr_features(features, min_myr_area, max_myr_area, merge_distance):
    """Slå sammen myrflater som berører eller ligger svært nær hverandre."""
    if not features or merge_distance is None or merge_distance < 0:
        return list(features)

    # Myr bygges først fra flate TIN-regioner, og nære polygoner slås deretter sammen
    # med en liten buffer/debuffer-operasjon for å unngå kunstige glipper mellom flater.
    buffered_geometries = [feature["geometry"].buffer(merge_distance) for feature in features]
    remaining = set(range(len(features)))
    groups = []

    while remaining:
        start_idx = remaining.pop()
        queue = deque([start_idx])
        group = {start_idx}
        while queue:
            current = queue.popleft()
            current_geometry = buffered_geometries[current]
            for other_idx in list(remaining):
                if not current_geometry.intersects(buffered_geometries[other_idx]):
                    continue
                remaining.remove(other_idx)
                group.add(other_idx)
                queue.append(other_idx)
        groups.append(sorted(group))

    merged_features = []
    for group in groups:
        group_features = [features[idx] for idx in group]
        merged_geometry = _safe_unary_union([feature["geometry"].buffer(merge_distance) for feature in group_features])
        if merged_geometry is None:
            continue
        merged_geometry = merged_geometry.buffer(-merge_distance)
        if merged_geometry.is_empty:
            merged_geometry = _safe_unary_union([feature["geometry"] for feature in group_features])
            if merged_geometry is None:
                continue

        total_area = sum(feature["areal"] for feature in group_features)
        if total_area <= 0:
            total_area = 1.0
        mean_slope = sum(feature["snitt_helning"] * feature["areal"] for feature in group_features) / total_area

        for polygon in _iter_polygon_parts(merged_geometry.buffer(0)):
            if polygon.is_empty or polygon.area < min_myr_area:
                continue
            sub_polygons = _split_polygon_to_max_area(polygon, max_myr_area, min_myr_area)
            if not sub_polygons:
                if max_myr_area is None or polygon.area <= max_myr_area:
                    sub_polygons = [polygon]
                else:
                    continue
            for sub_polygon in sub_polygons:
                if sub_polygon.is_empty or sub_polygon.area < min_myr_area:
                    continue
                if max_myr_area is not None and sub_polygon.area > max_myr_area:
                    continue
                merged_features.append({
                    "geometry": sub_polygon,
                    "areal": float(sub_polygon.area),
                    "snitt_helning": float(mean_slope),
                })

    return merged_features


def _generate_myr_polygons(tri_data, flat_components, lakes, min_myr_area, max_myr_area, smooth_distance, merge_distance):
    """Konverter flate trekantklynger til myrpolygoner."""
    lake_union = _safe_unary_union([lake["geometry"] for lake in lakes])
    features = []

    for component in flat_components:
        # Myr tas fra sammenhengende TIN-triangler med lav helning, og innsjøflater trekkes ut
        # før geometri glattes og eventuelt deles ned til tillatt maksareal.
        polygons = [tri_data["polygons"][idx] for idx in component]
        myr_geom = _safe_unary_union(polygons)
        if myr_geom is None:
            continue
        if lake_union is not None:
            myr_geom = myr_geom.difference(lake_union)
        if myr_geom.is_empty:
            continue
        if smooth_distance > 0:
            myr_geom = myr_geom.buffer(smooth_distance).buffer(-smooth_distance)
        mean_slope = float(np.mean(tri_data["slope_degrees"][list(component)]))
        for polygon in _iter_polygon_parts(myr_geom):
            if polygon.area < min_myr_area:
                continue
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if polygon.is_empty or polygon.area < min_myr_area:
                continue
            sub_polygons = _split_polygon_to_max_area(polygon, max_myr_area, min_myr_area)
            if not sub_polygons:
                if max_myr_area is None or polygon.area <= max_myr_area:
                    sub_polygons = [polygon]
                else:
                    continue
            for sub_polygon in sub_polygons:
                if sub_polygon.is_empty or sub_polygon.area < min_myr_area:
                    continue
                if max_myr_area is not None and sub_polygon.area > max_myr_area:
                    continue
                features.append({
                    "geometry": sub_polygon,
                    "areal": float(sub_polygon.area),
                    "snitt_helning": mean_slope,
                })
    return _merge_nearby_myr_features(features, min_myr_area, max_myr_area, merge_distance)


def generate_water(
    terrain_data,
    crs="EPSG:25833",
    inlet_stream_min_length=100.0,
    inlet_stream_max_length=500.0,
    max_inlets_per_lake=2,
    outlet_stream_min_length=300.0,
    outlet_stream_max_length=700.0,
    outlet_max_climb_height=2.0,
    min_lake_area=200.0,
    max_lake_area=None,
    max_lake_count=None,
    min_inner_lake_contours=1,
    max_inner_lake_contours=3,
    myr_slope_threshold=1.5,
    min_myr_area=500.0,
    max_myr_area=None,
    max_myr_count=None,
    smooth_iterations=2,
    polygon_smooth_distance=4.0,
    myr_merge_distance=6.0,
):
    """Generer vannobjekter fra terrengdata."""
    all_points = terrain_data["all_points"]
    tri5 = terrain_data["tri5"]

    # Hele vannmodellen bygger på TIN-et: vi utleder helning, fallretning og naboskap per triangel
    # og bruker disse som felles grunnlag for innsjøer, bekker og myr.
    tri_data = _build_triangle_data(all_points, tri5)
    downstream, sinks, exit_points, exit_edges = _compute_flow_directions(tri_data)
    accumulation = _compute_flow_accumulation(tri_data, downstream)

    gdf_contours = terrain_data.get("gdf_contours")
    # Innsjøer genereres før øvrige vannobjekter, fordi både bekkelogikk og myrfratrekk
    # må vite hvor innsjøflatene ligger.
    lake_features = _generate_lake_polygons_from_closed_contours(
        gdf_contours,
        min_lake_area=min_lake_area,
        max_lake_area=max_lake_area,
        min_inner_contours=min_inner_lake_contours,
        max_inner_contours=max_inner_lake_contours,
    )
    lake_features = _limit_features(lake_features, max_lake_count, lambda feat: feat["areal"])

    flat_components = _detect_flat_areas(tri_data, myr_slope_threshold)
    # Myr lages fra de flateste TIN-områdene etter at innsjøene er tatt ut, og nære myrflater
    # slås sammen slik at ett sammenhengende våtområde ikke ender som flere naboflater.
    myr_features = _generate_myr_polygons(
        tri_data,
        flat_components,
        lake_features,
        min_myr_area=min_myr_area,
        max_myr_area=max_myr_area,
        smooth_distance=polygon_smooth_distance,
        merge_distance=myr_merge_distance,
    )
    myr_features = _limit_features(myr_features, max_myr_count, lambda feat: feat["areal"])

    # Bekker knyttes direkte til innsjøene: innløp spores ned mot innsjøen fra oppstrøms triangler,
    # mens ett mulig utløp følger TIN-gradienten ut fra innsjøkanten dersom terrenget tillater det.
    stream_features = _generate_lake_linked_streams(
        tri_data,
        downstream,
        exit_points,
        accumulation,
        lake_features,
        inlet_min_length=inlet_stream_min_length,
        inlet_max_length=inlet_stream_max_length,
        max_inlets_per_lake=max_inlets_per_lake,
        outlet_min_length=outlet_stream_min_length,
        outlet_max_length=outlet_stream_max_length,
        outlet_max_climb_height=outlet_max_climb_height,
        smooth_iterations=smooth_iterations,
    )
    stream_features = _filter_long_stream_features(
        stream_features,
        max_outlet_length=min(outlet_stream_max_length, 550.0),
    )

    gdf_streams = _features_to_gdf(
        stream_features,
        [
            "geometry",
            "lake_id",
            "bekk_type",
            "lengde",
            "start_hoyde",
            "slutt_hoyde",
            "akkumulasjon",
            "valley_score",
            "start_tri",
            "climb_hoyde",
        ],
        crs,
    )
    gdf_lakes = _features_to_gdf(lake_features, ["geometry", "hoyde", "areal"], crs)
    gdf_myr = _features_to_gdf(myr_features, ["geometry", "areal", "snitt_helning"], crs)

    return {
        "gdf_elvbekk": gdf_streams,
        "gdf_innsjokant": gdf_lakes,
        "gdf_myrgrense": gdf_myr,
        "triangle_accumulation": accumulation,
        "triangle_slope_degrees": tri_data["slope_degrees"],
        "triangle_exit_edges": exit_edges,
        "crs": crs,
    }