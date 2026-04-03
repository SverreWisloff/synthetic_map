import numpy as np
import geopandas as gpd
import shapely.geometry as geom
from scipy.spatial import Delaunay
from shapely.ops import unary_union
from scipy.interpolate import griddata
import rasterio
from rasterio.transform import from_origin
import os

# ---- parametrer ----
minx, miny, maxx, maxy = 500000, 6700000, 501000, 6701000
crs = "EPSG:25833"
seed = 42
np.random.seed(seed)

h_min, h_max = 70.0, 140.0
n_primary = 35
sec_per_tri = 5
ter_per_tri = 5
sec_delta = 3.0
ter_delta = 1.2
ekvidistanse = 1.0
raster_res = 1.0

out_gpkg = "synthetic_hoydekurve.gpkg"

# tilleggsfunksjoner
def in_triangle(pt, tri):
    p = geom.Point(pt)
    return p.within(geom.Polygon(tri))

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

# 6) Lag alle-punkter og 4. TIN for nivå 3 (kan hoppe hvis ikke nødvendig)
all_points = level2
tri3 = Delaunay(all_points[:, :2])

# 7) Rasteriser via griddata for kurvegenerering
xi = np.arange(minx, maxx+raster_res, raster_res)
yi = np.arange(miny, maxy+raster_res, raster_res)
xx, yy = np.meshgrid(xi, yi)
zz = griddata(all_points[:, :2], all_points[:, 2], (xx, yy), method="cubic", fill_value=h_min)

# 8) 1-m kurver via matplotlib
import matplotlib.pyplot as plt
cs = plt.contour(xx, yy, zz, levels=np.arange(h_min, h_max+ekvidistanse, ekvidistanse))
lines = []
for level, collection in zip(cs.levels, cs.collections):
    for path in collection.get_paths():
        verts = path.vertices
        if len(verts) < 2:
            continue
        lines.append({"geometry": geom.LineString([(x,y) for x,y in verts]), "hoyde": float(level)})
plt.close()

# 9) GeoDataFrames
gdf_pts = gpd.GeoDataFrame(all_points, columns=["x","y","hoyde"], geometry=[geom.Point(x,y) for x,y,_ in all_points], crs=crs)
gdf_tin = gpd.GeoDataFrame([{"geometry": geom.Polygon(all_points[s][:, :2]), "level":"all"} for s in tri3.simplices], crs=crs)
gdf_contours = gpd.GeoDataFrame(lines, crs=crs)

# 10) Skrive til GeoPackage
if os.path.exists(out_gpkg):
    os.remove(out_gpkg)
gdf_pts.to_file(out_gpkg, layer="terrain_points", driver="GPKG")
gdf_tin.to_file(out_gpkg, layer="terrain_tin", driver="GPKG")
gdf_contours.to_file(out_gpkg, layer="hoydekurver_1m", driver="GPKG")

print("Ferdig: syntetisk terreng og høydekurver i", out_gpkg)
print("Punkter:", len(gdf_pts), "TIN-triangler:", len(gdf_tin), "Kurver:", len(gdf_contours))