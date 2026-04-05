import numpy as np
import geopandas as gpd
import shapely.geometry as geom
from scipy.spatial import Delaunay
import os

# ---- parametrer ----
minx, miny, maxx, maxy = 500000, 6700000, 502000, 6702000  # UTM-koordinater for området (påvirker størrelsen på kartet)
crs = "EPSG:25833"  # Koordinatsystem (UTM zone 33N for Norge)
seed = 42  # Tilfeldig seed for reproduserbarhet
np.random.seed(seed)

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

# 10) Skrive til GeoPackage
if os.path.exists(out_gpkg):
    os.remove(out_gpkg)
gdf_pts.to_file(out_gpkg, layer="terrain_points", driver="GPKG")
gdf_tin.to_file(out_gpkg, layer="terrain_tin", driver="GPKG")
gdf_contours.to_file(out_gpkg, layer="hoydekurver_1m", driver="GPKG")

print("Ferdig: syntetisk terreng og høydekurver i", out_gpkg)
print("Punkter:", len(gdf_pts), "TIN-triangler:", len(gdf_tin), "Kurver:", len(gdf_contours))