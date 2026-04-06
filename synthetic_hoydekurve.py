import numpy as np
import geopandas as gpd
import shapely.geometry as geom
from scipy.spatial import Delaunay
import os

np.random.seed(None)

# ---- parametrer ----
minx, miny, maxx, maxy = 500000, 6700000, 502000, 6702000  # UTM-koordinater for området (påvirker størrelsen på kartet)
crs = "EPSG:25833"  # Koordinatsystem (UTM zone 33N for Norge)

h_min, h_max = 100.0, 130.0  # Minimum og maksimum høyde for terrenget (definerer høydeområdet for punkter og kurver)
n_primary = 15  # Antall primære punkter (jo flere, jo mer detaljert og jevn basis-TIN)
sec_per_tri = 5  # Antall sekundære punkter per trekant i nivå 1 (øker tetthet og detalj på første nivå)
ter_per_tri = 3  # Antall tertiære punkter per trekant i nivå 2 (videre økning i tetthet)
qua_per_tri = 3  # Antall kvaternære punkter per trekant i nivå 3 (enda mer detalj)
qui_per_tri = 3  # Antall kvintære punkter per trekant i nivå 4 (fineste nivå for høy oppløsning)
sec_delta = 3.0  # Standardavvik for høydevariasjon i sekundære punkter (større verdi gir mer terrengvariasjon)
ter_delta = 1.0  # Standardavvik for tertiære punkter (mindre variasjon enn sekundære)
qua_delta = 0.4  # Standardavvik for kvaternære punkter (finjustering av detaljer)
qui_delta = 0.1  # Standardavvik for kvintære punkter (minimal variasjon for glatt terreng)
ekvidistanse = 1.0  # Avstand mellom høydekurver (1 meter ekvidistanse)

out_gpkg = "synthetic_hoydekurve.gpkg"

# tilleggsfunksjoner
def points_in_triangle(a, b, c, n):
    pts = []
    for _ in range(n):
        r1, r2 = np.random.rand(), np.random.rand()
        if r1 + r2 > 1:
            r1, r2 = 1 - r1, 1 - r2
        x = a[0] * (1 - r1 - r2) + b[0] * r1 + c[0] * r2
        y = a[1] * (1 - r1 - r2) + b[1] * r1 + c[1] * r2
        w0 = (1 - r1 - r2); w1=r1; w2=r2
        pts.append((x,y,w0,w1,w2))
    return pts

def add_level_points(points, tris, per_tri, delta):
    added = []
    for tri in tris:
        idx_a, idx_b, idx_c = tri
        a = points[idx_a]
        b = points[idx_b]
        c = points[idx_c]
        for xyw in points_in_triangle(a, b, c, per_tri):
            x, y, w0, w1, w2 = xyw
            z_base = a[2]*w0 + b[2]*w1 + c[2]*w2
            z = float(np.clip(z_base + np.random.normal(scale=delta), h_min, h_max))
            added.append((x, y, z))
    return added

def generate_contours_from_tin(points, triangles, levels):
    contours = []
    for level in levels:
        lines = []
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
                lines.append(geom.LineString(intersections))
        for line in lines:
            contours.append({"geometry": line, "hoyde": float(level)})
    return contours

# 1) primærpunkter
px = np.random.uniform(minx+20, maxx-20, n_primary)
py = np.random.uniform(miny+20, maxy-20, n_primary)
pz = np.random.uniform(h_min, h_max, n_primary)
primary = np.column_stack((px, py, pz))

# 2) TIN fra primær
tri0 = Delaunay(primary[:, :2])
sec = add_level_points(primary, tri0.simplices, sec_per_tri, sec_delta)
level1 = np.vstack([primary, np.array(sec)]) if len(sec) else primary

# 3) TIN nivå 1
tri1 = Delaunay(level1[:, :2])

# 4) sekundære -> tertiære
ter = add_level_points(level1, tri1.simplices, ter_per_tri, ter_delta)
level2 = np.vstack([level1, np.array(ter)]) if len(ter) else level1

# 5) TIN nivå 2
tri2 = Delaunay(level2[:, :2])

# 6) kvaternære punkter
qua = add_level_points(level2, tri2.simplices, qua_per_tri, qua_delta)
level3 = np.vstack([level2, np.array(qua)]) if len(qua) else level2

# 7) TIN nivå 3
tri3 = Delaunay(level3[:, :2])

# 8) kvaternære -> kvintære
qui = add_level_points(level3, tri3.simplices, qui_per_tri, qui_delta)
level4 = np.vstack([level3, np.array(qui)]) if len(qui) else level3

# 9) TIN nivå 4
tri4 = Delaunay(level4[:, :2])

# 10) Lag alle-punkter og 5. TIN for nivå 5
all_points = level4
tri5 = Delaunay(all_points[:, :2])

# 11) Generer høydekurver direkte fra TIN (vektor-domene)
levels = np.arange(h_min, h_max + ekvidistanse, ekvidistanse)
lines = generate_contours_from_tin(all_points, tri5.simplices, levels)

# 12) GeoDataFrames
gdf_pts = gpd.GeoDataFrame(all_points, columns=["x","y","hoyde"], geometry=[geom.Point(x,y) for x,y,_ in all_points], crs=crs)
gdf_tin = gpd.GeoDataFrame([{"geometry": geom.Polygon(all_points[s][:, :2]), "level":"all"} for s in tri5.simplices], crs=crs)
gdf_contours = gpd.GeoDataFrame(lines, crs=crs)

# ---- Vegnett-generering ----

def interpolate_height_from_tin(x, y, points, triangles):
    """Interpoler høyde basert på TIN ved hjelp av barysentriskekoordinater"""
    for simplex in triangles:
        tri_pts = points[simplex]
        # Sjekk om punktet er innenfor trekanten ved bruk av barysentriskekoordinater
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
    
    # Fallback: finn nærmeste punkt hvis ikke i noen trekant
    distances = np.sqrt((all_points[:, 0] - x)**2 + (all_points[:, 1] - y)**2)
    nearest_idx = np.argmin(distances)
    return float(all_points[nearest_idx][2])

def generate_road_segment(start_xy, end_xy, road_type, terrain_points=None, triangles=None, start_direction=None):
    """Generer et vegsegment med sekvens av rette deler og buer"""
    segment_points = []

    # Bestem radius basert på vegtype
    if road_type == "Riksveg":
        radius = np.random.uniform(100, 200)
    elif road_type == "Kommuneveg":
        radius = np.random.uniform(50, 150)
    else:  # Privatveg
        radius = np.random.uniform(20, 100)

    # Beregn total lengde og retning
    dx = end_xy[0] - start_xy[0]
    dy = end_xy[1] - start_xy[1]
    total_length = np.sqrt(dx**2 + dy**2)
    
    if start_direction is not None:
        # Bruk oppgitt startretning (for kontinuitet fra tidligere segment)
        direction = start_direction
    else:
        # Beregn retning fra start til slutt
        direction = np.arctan2(dy, dx)

    current_pos = np.array(start_xy)
    current_direction = direction
    remaining_length = total_length

    # Startpunkt
    z = interpolate_height_from_tin(current_pos[0], current_pos[1], terrain_points, triangles)
    segment_points.append((current_pos[0], current_pos[1], z))

    segment_type = "straight"  # Start med rett segment

    while remaining_length > 0:
        if segment_type == "straight":
            # Rett segment - maks 100 meter
            segment_length = min(remaining_length, 100.0, np.random.uniform(50, 100))

            # Beregn endepunkt for rett segment
            end_x = current_pos[0] + segment_length * np.cos(current_direction)
            end_y = current_pos[1] + segment_length * np.sin(current_direction)

            # Generer punkter langs rett linje
            num_points = max(5, int(segment_length / 10))  # Ca hvert 10. meter
            for i in range(1, num_points + 1):
                t = i / num_points
                x = current_pos[0] * (1 - t) + end_x * t
                y = current_pos[1] * (1 - t) + end_y * t
                z = interpolate_height_from_tin(x, y, terrain_points, triangles)
                segment_points.append((x, y, z))

            current_pos = np.array([end_x, end_y])
            remaining_length -= segment_length
            segment_type = "curve"

        else:  # curve
            # Bue segment - 45 grader
            arc_angle = np.radians(45)

            # Bestem svingretning basert på hvor vi er i forhold til målet
            # Dette sikrer at buen fører oss nærmere målet
            target_direction = np.arctan2(end_xy[1] - current_pos[1], end_xy[0] - current_pos[0])
            angle_diff = target_direction - current_direction

            # Normaliser vinkelen til [-pi, pi]
            while angle_diff > np.pi:
                angle_diff -= 2 * np.pi
            while angle_diff < -np.pi:
                angle_diff += 2 * np.pi

            # Velg svingretning som fører oss nærmest målet
            if abs(angle_diff) < np.pi/2:
                turn_direction = 1 if angle_diff > 0 else -1
            else:
                turn_direction = -1 if angle_diff > 0 else 1

            # Beregn buen som er tangent til nåværende retning
            # For en sirkulær bue som er tangent til innkommende retning
            center_x = current_pos[0] + radius * np.cos(current_direction + turn_direction * np.pi/2)
            center_y = current_pos[1] + radius * np.sin(current_direction + turn_direction * np.pi/2)

            # Startvinkel fra sentrum til nåværende posisjon
            start_angle = np.arctan2(current_pos[1] - center_y, current_pos[0] - center_x)

            # Generer punkter langs buen
            num_arc_points = 10
            for i in range(1, num_arc_points + 1):
                angle = start_angle + turn_direction * (i / num_arc_points) * arc_angle
                x = center_x + radius * np.cos(angle)
                y = center_y + radius * np.sin(angle)
                z = interpolate_height_from_tin(x, y, terrain_points, triangles)
                segment_points.append((x, y, z))

            # Oppdater posisjon og retning
            end_angle = start_angle + turn_direction * arc_angle
            current_pos[0] = center_x + radius * np.cos(end_angle)
            current_pos[1] = center_y + radius * np.sin(end_angle)
            current_direction += turn_direction * arc_angle

            # Beregn faktisk bue-lengde for å oppdatere remaining_length
            arc_length = radius * arc_angle
            remaining_length -= arc_length

            segment_type = "straight"

    # Sørg for at vi ender på sluttpunktet
    if segment_points:
        z = interpolate_height_from_tin(end_xy[0], end_xy[1], terrain_points, triangles)
        segment_points.append((end_xy[0], end_xy[1], z))

    return segment_points

def normalize_angle(angle):
    """Normaliser vinkel til intervallet [-pi, pi]"""
    while angle > np.pi:
        angle -= 2 * np.pi
    while angle < -np.pi:
        angle += 2 * np.pi
    return angle


def sample_arc(center, radius, start_angle, end_angle, num_points=12):
    angles = np.linspace(start_angle, end_angle, num_points)
    return [(center[0] + radius * np.cos(angle), center[1] + radius * np.sin(angle)) for angle in angles[1:]]


def compute_arc_center(start_point, direction, radius, turn_direction):
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
                    start=None, end=None):
    """Generer en riksveg som bygger seg som en sekvens av kontinuerlige segmenter."""
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
                "veg_type": "Riksveg",
                "veg_nummer": 1,
                "elevation_points": elevation_points
            }

    raise RuntimeError("Klarte ikke generere en enkel riksveg uten selvkrysning")


# Generer riksveg
bbox = (minx, miny, maxx, maxy)
main_riksveg = create_riksveg(all_points, tri5.simplices, bbox)
main_line = main_riksveg["geometry"]
branch_point = main_line.interpolate(main_line.length * 0.30)
branch_start = (branch_point.x, branch_point.y)
branch_end = np.array((minx + 20.0, maxy - 20.0))
branch_riksveg = None
for attempt in range(50):
    candidate = create_riksveg(all_points, tri5.simplices, bbox, start=branch_start, end=branch_end)
    if not candidate["geometry"].crosses(main_line) and not candidate["geometry"].overlaps(main_line):
        branch_riksveg = candidate
        branch_riksveg["veg_nummer"] = 2
        break

if branch_riksveg is None:
    raise RuntimeError("Klarte ikke generere en sekundær riksveg uten krysning")

# 10) Skrive til GeoPackage
if os.path.exists(out_gpkg):
    os.remove(out_gpkg)
gdf_pts.to_file(out_gpkg, layer="terrain_points", driver="GPKG")
gdf_tin.to_file(out_gpkg, layer="terrain_tin", driver="GPKG")
gdf_contours.to_file(out_gpkg, layer="hoydekurver_1m", driver="GPKG")

gdf_riksveg = gpd.GeoDataFrame([main_riksveg, branch_riksveg], crs=crs)
gdf_riksveg.to_file(out_gpkg, layer="vegnett_riksveg", driver="GPKG")

print("Ferdig: syntetisk terreng, høydekurver og riksveg i", out_gpkg)
print("Punkter:", len(gdf_pts), "TIN-triangler:", len(gdf_tin), "Kurver:", len(gdf_contours))
print("Riksveg:", 2)