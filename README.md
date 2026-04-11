# Syntetisk Kartgenerering

Et Python-skript som genererer syntetiske kartlag for terreng, vann, vegnett og bygninger til GeoPackage-format.

## Eksempel på resultat

![Syntetisk kart med høydekurver, vegnett og bygninger](images/Skjermbilde%202026-04-11.png)

## Arkitektur

Prosjektet er organisert i moduler:
- `synthetic_map.py` - Hovedprogram
- `synthetic_hoydekurve_module.py` - Terreng- og høydekurvegenerering
- `synthetic_vann_module.py` - Generering av innsjøer, bekker og myr
- `synthetic_vegnett_module.py` - Vegnettgenerering (riksveg, kommunalveg, private avkjørsler, vegkant)
- `synthetic_bygning_module.py` - Bygningsgenerering
- `synthetic_hoydekurve.py` - Legacy-versjon (kan slettes)

## Funksjoner

### Terreng

Modul: `synthetic_hoydekurve_module.py`

GeoPackage: `synthetic_terrain.gpkg`
- `terrain_points`: genererte høydepunkter brukt som grunnlag for terrengmodellen
- `terrain_tin`: triangulert irregulært nettverk (TIN) som beskriver terrengflatene
- `hoydekurver_1m`: 1-meters høydekurver avledet fra TIN

Algoritme:
- Terrenget bygges hierarkisk med primære, sekundære, tertiære, kvaternære og kvintære høydepunkter for å få både grove landformer og lokal detalj.
- Punktene trianguleres med Delaunay-triangulering til en TIN, som er den geometriske terrengmodellen resten av kartdataene bygger på.
- Høydekurvene genereres ved å skjære TIN-trianglene mot faste høydenivåer med 1 meters ekvidistanse.

### Vann

Modul: `synthetic_vann_module.py`

GeoPackage: `synthetic_vann.gpkg`
- `innsjokant`: lukkede polygoner for innsjøflater
- `elvbekk`: senterlinjer for bekker inn mot innsjøer
- `myrgrense`: lukkede polygoner for myrflater

Algoritme:
- Vannobjektene lages fra TIN-modellen, der hver trekant får beregnet helning, gradient og nedstrøms nabotrekant.
- Innsjøer identifiseres fra lukkede høydekurver: en lukket kurve blir innsjøkandidat når den omslutter 1–3 lavere lukkede kurver, slik at innsjøkanten følger en faktisk forsenkning i terrenget.
- Bekker genereres innsjøstyrt. For hver innsjø velges 0–2 innløpsbekker fra oppstrøms TIN-triangler som drenerer mot innsjøen, prioritert etter akkumulasjon og søkk-karakter. Eventuelle utløpsbekker følger TIN-gradienten ut fra innsjøkanten, men lange utløp filtreres bort.
- Myr genereres fra sammenhengende grupper av flate TIN-triangler. Innsjøflater trekkes ut, polygonene glattes, nærliggende myrflater slås sammen, og store flater deles ved behov for å holde seg innen maksareal.

### Veg

Modul: `synthetic_vegnett_module.py`

GeoPackage: `synthetic_vegnett.gpkg`
- `vegnett_riksveg`: senterlinjer for riksveger, kommunale veger og private avkjørsler
- `vegkant`: vegkanter avledet fra vegnettets bredde

Algoritme:
- Vegnettet genereres som et kontrollert linjenett med to riksveger og to kommunale veger, bygd opp av tangent-kontinuerlige segmenter slik at vegene får jevn kurvatur.
- Private avkjørsler legges ut fra kommunale veger med avstandsregler og fjernes dersom de skaper kryssinger eller konflikter.
- Vegkantene dannes som sideforskjøvne/bufrede geometrier rundt vegsenterlinjene, med ulik bredde per vegtype.
- Vegnettet tilordnes høyde ved interpolasjon mot terrengmodellen slik at linjene følger underliggende terreng.

### Bygninger

Modul: `synthetic_bygning_module.py`

GeoPackage: `synthetic_bygning.gpkg`
- `bygninger`: bygningspolygoner med rektangulære og L-formede grunnflater

Algoritme:
- Bygninger plasseres i små grupper ved enden av private avkjørsler, slik at de knyttes til vegsystemet i stedet for å ligge tilfeldig i terrenget.
- Hver bygning får en enkel syntetisk form og størrelse innen definerte intervaller.
- Kandidater som overlapper veg eller ligger for nær hovedveg, filtreres eller skyves bort for å gi mer realistisk plassering.

### Orkestrering

Modul: `synthetic_map.py`

- Modulene kjøres i rekkefølgen `terrain`, `water`, `roads`, `buildings`.
- Hvert lag skrives til sin egen GeoPackage, slik at kartdataene kan brukes separat i GIS-verktøy.
- Avhengigheter håndteres automatisk, slik at valg av et senere lag også genererer nødvendige forløpere.

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

# Terreng og vann
python synthetic_map.py --layers water

# Kun vegnett
python synthetic_map.py --layers roads

# Kun bygninger
python synthetic_map.py --layers buildings

# Terreng, vann og vegnett
python synthetic_map.py --layers terrain,water,roads
```

Avhengigheter mellom lagene er:
- `terrain`
- `water` krever `terrain`
- `roads` krever `terrain`
- `buildings` krever `terrain` og `roads`

Når du velger et lag, kjøres bare dette laget og nødvendige forløpere. Eksempler:
- `--layers terrain` kjører bare terreng
- `--layers water` kjører terreng og vann
- `--layers roads` kjører terreng og veg
- `--layers buildings` kjører terreng, veg og bygg

**Tilgjengelige lag:**
- `terrain` - Terrengpunkter, TIN-triangler og høydekurver
- `water` - Innsjøkant, elv/bekk og myr
- `roads` - Vegnett og vegkant
- `buildings` - Bygninger
- `all` - Alt (standardvalg)

## Output

Skriptet genererer fire GeoPackage-filer:

**`synthetic_terrain.gpkg`:**
- `terrain_points`: Genererte høydepunkter
- `terrain_tin`: Triangulert irregulært nettverk
- `hoydekurver_1m`: 1-meter ekvidistante konturlinjer

**`synthetic_vann.gpkg`:**
- `innsjokant`: Innsjøpolygoner
- `elvbekk`: Bekkesenterlinjer
- `myrgrense`: Myrpolygoner

**`synthetic_vegnett.gpkg`:**
- `vegnett_riksveg`: Vegnett med riksveger, kommunale veger og private avkjørsler
- `vegkant`: Vegkantlinjer basert på vegbredde

**`synthetic_bygning.gpkg`:**
- `bygninger`: Rektangulære og L-formede bygninger

## Konfigurasjon

Rediger parametrene i `synthetic_map.py`:
- `BBOX`: UTM-koordinater for området (påvirker størrelsen på kartet)
- `CRS`: Koordinatsystem (standard: EPSG:25833, UTM sone 33N for Norge)
- `TERRAIN_CONFIG`: Terrengparametre:
  - `h_min, h_max`: Min/maks høyde
  - `n_primary`: Antall primære punkter
  - `sec/ter/qua/qui_per_tri`: Punkter per trekant på hvert nivå
  - `sec/ter/qua/qui_delta`: Standardavvik for høydevariasjon per nivå
  - `ekvidistanse`: Avstand mellom høydekurver
- `WATER_CONFIG`: Parametre for innsjø, bekk og myr:
  - `min/max_lake_area`: Minste og største innsjøareal
  - `max_lake_count`: Maks antall innsjøer
  - `inlet/outlet_stream_*`: Lengde- og klatreregler for bekker
  - `min/max_myr_area`: Minste og største myrareal
  - `max_myr_count`: Maks antall myrflater
  - `myr_merge_distance`: Avstand for sammenslåing av nærliggende myrflater

## Lisens

MIT
