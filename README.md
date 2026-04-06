# Syntetisk Kartgenerering

Et Python-skript som genererer syntetiske kartlag (terreng, høydekurver, vegnett, bygninger) til GeoPackage-format.

## Eksempel på resultat

![Syntetisk kart med høydekurver, vegnett og bygninger](Skjermbilde%202026-04-06.png)

## Arkitektur

Prosjektet er organisert i moduler:
- `synthetic_map.py` - Hovedprogram
- `synthetic_hoydekurve_module.py` - Terreng- og høydekurvegenerering
- `synthetic_vegnett_module.py` - Vegnettgenerering (riksveg, kommunalveg, private avkjørsler, vegkant)
- `synthetic_bygning_module.py` - Bygningsgenerering
- `synthetic_hoydekurve.py` - Legacy-versjon (kan slettes)

## Funksjoner

### Terreng

- Genererer syntetiske terrengpunkter med flere detaljnivåer
- Lager en TIN (Triangulert irregulær nettverk) mesh for terrengmodellering
- Genererer ekvidistante konturlinjer på 1-meter intervaller fra TIN
- Skriver terrengpunkter, TIN og konturlinjer til GeoPackage

### Veg

- Genererer to riksveger (RiksvegA, RiksvegB) og to kommunale veger (KommunalVegA, KommunalVegB)
- Vegene består av tangent-kontinuerlige segmenter med jevne kurver (maks ett rettlinjet segment på rad)
- Private avkjørsler genereres vinkelrett fra kommunale veger (10–50 m lange, 50–100 m mellomrom)
- Avkjørsler som krysser andre veger fjernes automatisk
- Vegkant genereres som buffer rundt senterlinjen (Riksveg 10 m, KommunalVeg 5 m, PrivatAvkjørsel 4 m)
- Vegnettet får høyde interpolert fra terrengmodellen
- Skriver vegnett og vegkant til en egen GeoPackage

### Bygninger

- Genererer rektangulære og L-formede bygninger (6–30 m)
- Bygninger plasseres i grupper på 2–3 ved enden av private avkjørsler
- Bygninger som overlapper riksveg/kommunalveg fjernes
- Bygninger nærmere enn 13 m fra riksveg/kommunalveg skyves bort
- Skriver bygninger til en egen GeoPackage

### Generelt

- Modulær kartlagsgenerering: velg hvilke lag som skal genereres
- Output skrives til GeoPackage-format for GIS-applikasjoner

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

### Kjør hele genereringen
```bash
python synthetic_map.py
```

### Kjør spesifikke kartlag
```bash
# Kun terreng
python synthetic_map.py --layers terrain

# Kun vegnett
python synthetic_map.py --layers roads

# Kun bygninger
python synthetic_map.py --layers buildings

# Terreng og vegnett
python synthetic_map.py --layers terrain,roads
```

**Tilgjengelige lag:**
- `terrain` - Terrengpunkter, TIN-triangler og høydekurver
- `roads` - Vegnett og vegkant
- `buildings` - Bygninger
- `all` - Alt (standardvalg)

## Output

Skriptet genererer tre GeoPackage-filer:

**`synthetic_terrain.gpkg`:**
- `terrain_points`: Genererte høydepunkter
- `terrain_tin`: Triangulert irregulært nettverk
- `hoydekurver_1m`: 1-meter ekvidistante konturlinjer

**`synthetic_vegnett.gpkg`:**
- `vegnett_riksveg`: Vegnett med riksveger, kommunale veger og private avkjørsler
- `vegkant`: Vegkantlinjer basert på vegbredde

**`synthetic_bygning.gpkg`:**
- `bygninger`: Rektangulære og L-formede bygninger

## Konfigurasjon

Rediger parametrene i `synthetic_map.py`:
- `BBOX`: UTM-koordinater for området (påvirker størrelsen på kartet)
- `CRS`: Koordinatsystem (standard: EPSG:25833, UTM sone 33N for Norge)
- `TERRAIN_PARAMS`: Terrengparametre:
  - `h_min, h_max`: Min/maks høyde
  - `n_primary`: Antall primære punkter
  - `sec/ter/qua/qui_per_tri`: Punkter per trekant på hvert nivå
  - `sec/ter/qua/qui_delta`: Standardavvik for høydevariasjon per nivå
  - `ekvidistanse`: Avstand mellom høydekurver

## Lisens

MIT
