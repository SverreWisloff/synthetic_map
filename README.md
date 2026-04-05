# Syntetisk Kart - Terrenggenerering

Et Python-skript som genererer syntetiske terrengdata ved hjelp av Delaunay-triangulering og vektor-basert konturlinje-generering.

## Funksjoner

- Genererer syntetiske terrengpunkter med flere detaljnivåer (primær, sekundær, tertiær, kvaternær, kvintær)
- Lager TIN (Triangulert irregulær nettverk) mesh-representasjon
- Genererer ekvidistante konturlinjer på 1-meter intervaller direkte fra TIN (vektor-domene)
- Utskrift av resultater til GeoPackage-format for GIS-applikasjoner

## Krav

- Python 3.9+
- Avhengigheter listet i `requirements.txt`

## Installasjon

1. Klon dette repositoriet:
```bash
git clone https://github.com/SverreWisloff/synthetic_map.git
cd synthetic_map
```

2. Lag et virtuelt miljø:
```bash
python -m venv .venv
source .venv/bin/activate  # På macOS/Linux
# eller
.venv\Scripts\activate  # På Windows
```

3. Installer avhengigheter:
```bash
pip install -r requirements.txt
```

## Bruk

Kjør skriptet for å generere syntetisk terreng:
```bash
python synthetic_hoydekurve.py
```

Dette vil lage `synthetic_hoydekurve.gpkg` som inneholder:
- `terrain_points`: Genererte høydepunkter
- `terrain_tin`: Triangulert irregulært nettverk
- `hoydekurver_1m`: 1-meter ekvidistante konturlinjer

## Konfigurasjon

Rediger parametrene øverst i `synthetic_hoydekurve.py`:
- `minx, miny, maxx, maxy`: UTM-koordinater for området (påvirker størrelsen på kartet)
- `crs`: Koordinatsystem (standard: EPSG:25833, UTM sone 33N for Norge)
- `seed`: Tilfeldig seed for reproduserbarhet
- `h_min, h_max`: Minimum og maksimum høyde for terrenget (definerer høydeområdet for punkter og kurver)
- `n_primary`: Antall primære punkter (jo flere, jo mer detaljert og jevn basis-TIN)
- `sec_per_tri`: Antall sekundære punkter per trekant i nivå 1 (øker tetthet og detalj på første nivå)
- `ter_per_tri`: Antall tertiære punkter per trekant i nivå 2 (videre økning i tetthet)
- `qua_per_tri`: Antall kvaternære punkter per trekant i nivå 3 (enda mer detalj)
- `qui_per_tri`: Antall kvintære punkter per trekant i nivå 4 (fineste nivå for høy oppløsning)
- `sec_delta`: Standardavvik for høydevariasjon i sekundære punkter (større verdi gir mer terrengvariasjon)
- `ter_delta`: Standardavvik for tertiære punkter (mindre variasjon enn sekundære)
- `qua_delta`: Standardavvik for kvaternære punkter (finjustering av detaljer)
- `qui_delta`: Standardavvik for kvintære punkter (minimal variasjon for glatt terreng)
- `ekvidistanse`: Avstand mellom høydekurver (standard: 1 meter)

## Output

Skriptet genererer en GeoPackage-fil med statistikk skrevet til konsollen:
- Antall terrengpunkter
- Antall TIN-trekant
- Antall konturlinjer

## Lisens

MIT
