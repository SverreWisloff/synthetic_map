# Synthetic Map - Terrain Generation

A Python script that generates synthetic terrain data using Delaunay triangulation and contour line generation.

## Features

- Generates synthetic terrain points with multiple levels of detail (primary, secondary, tertiary)
- Creates TIN (Triangulated Irregular Network) mesh representation
- Generates equidistant contour lines at 1-meter intervals
- Outputs results to GeoPackage format for GIS applications

## Requirements

- Python 3.9+
- Dependencies listed in `requirements.txt`

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/synthetic_map.git
cd synthetic_map
```

2. Create a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate  # On Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

Run the script to generate synthetic terrain:
```bash
python synthetic_hoydekurve.py
```

This will create `synthetic_hoydekurve.gpkg` containing:
- `terrain_points`: Generated elevation points
- `terrain_tin`: Triangulated irregular network
- `hoydekurver_1m`: 1-meter equidistant contour lines

## Configuration

Edit the parameters at the top of `synthetic_hoydekurve.py`:
- `minx, miny, maxx, maxy`: Bounding box coordinates
- `crs`: Coordinate Reference System (default: EPSG:25833)
- `h_min, h_max`: Height range (70-140 meters)
- `n_primary`: Number of primary elevation points
- `sec_per_tri`, `ter_per_tri`: Secondary and tertiary points per triangle
- `ekvidistanse`: Contour line interval (default: 1 meter)

## Output

The script generates a GeoPackage file with statistics printed to console:
- Number of terrain points
- Number of TIN triangles
- Number of contour lines

## License

MIT
