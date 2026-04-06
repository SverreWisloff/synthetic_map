# Syntetisk Kart - Terrenggenerering

Et Python-skript som genererer syntetiske kartlar (terreng, høydekurver, vegnett) til GeoPackage-format.

## Arkitektur

Prosjektet er organisert i moduler for fleksibel og utvidbar kartgenerering:
- `synthetic_map.py` - Hovedprogram og orkestrering
- `synthetic_hoydekurve_module.py` - Terreng- og høydekurvegenerering
- `synthetic_vegnett_module.py` - Vegnettsenerering
- `synthetic_hoydekurve.py` - Legacy-versjon (kan slettes)

## Funksjoner

- Genererer syntetiske terrengpunkter med flere detaljnivåer (primær, sekundær, tertiær, kvaternær, kvintær)
- Lager TIN (Triangulert irregulær nettverk) mesh-representasjon
- Genererer ekvidistante konturlinjer på 1-meter intervaller direkte fra TIN (vektor-domene)
- **Modulell kartlagsgenerering** - velg hvilke lag som skal genereres
- Genererer to riksveger gjennom området med tangent-kontinuerlige buesegmenter
- Hovedriksveg går fra sørvest til nordøst
- Sekundærveg starter ved 25% av hovedvegen og går til nordvest-hjørnet
- Hvert point i veilinjen får høyde interpolert fra TIN-modellen
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

# Kun høydekurver
python synthetic_map.py --layers contours

# Kun vegenett
python synthetic_map.py --layers roads

# Terreng og vegnett
python synthetic_map.py --layers terrain,roads
```

**Tilgjengelige lag:**
- `terrain` - Terrengpunkter og TIN-triangler
- `contours` - Høydekurver
- `roads` - Vegnett (riksveier)
- `all` - Alt (standardvalg)

## Output

Skriptet genererer `synthetic_hoydekurve.gpkg` som inneholder:
- `terrain_points`: Genererte høydepunkter (når `terrain` er aktivert)
- `terrain_tin`: Triangulert irregulært nettverk (når `terrain` er aktivert)
- `hoydekurver_1m`: 1-meter ekvidistante konturlinjer (når `contours` er aktivert)
- `vegnett_riksveg`: Riksvegnett med 2 riksveger (når `roads` er aktivert)

Konsoll-output viser:
- Antall terrengpunkter
- Antall TIN-trekanter
- Antall konturlinjer
- Antall riksveger

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
