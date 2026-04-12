# Syntetisk kartgenerator – prosjektregler

Dersom du ser at det er naturlig å utvide instructions, gi meg
en beskjed om forslag, og hvorfor.

## Arkitektur

Prosjektet genererer syntetiske GIS-kartlag i GeoPackage-format.
Kjeden er: `terrain` → `water` → `roads` → `buildings` → `ar5`.

- `synthetic_map.py` er orkestrator og eneste sted for konfigurasjon
- Hver temamodul (`synthetic_*_module.py`) mottar parametre som argumenter – ingen hardkoding av verdier i modulene
- Moduler returnerer dict/GeoDataFrame, skriver ikke til disk selv

## Modulstruktur

- Hver temamodul eksponerer én hovedfunksjon: `generate_<tema>(...)`.
- Funksjonen mottar alltid parametre som argumenter – aldri fra globale variabler eller hardkodede verdier.
- Funksjonen returnerer en `dict` med nøkler som er `GeoDataFrame`-er. Den skriver **ikke** til disk.
- `synthetic_map.py` er det eneste stedet som kaller `.to_file(...)`.

## Navngiving

- Funksjons- og variabelnavn er på norsk eller nøytral-engelsk (bruk prosjektets eksisterende stil).
- GeoDataFrame-nøkler følger mønsteret `gdf_<lagnavn>`, f.eks. `gdf_innsjokant`, `gdf_contours`.
- Konfig-dicts navngis `<tema>_CONFIG` i `synthetic_map.py`.

## Parameterhåndtering

- All konfigurasjon og alle parametere samles i `synthetic_map.py`
- Legg aldri tallverdier direkte i modulkoden. Send dem alltid som parametere.
- Alle tallverdier som kan variere sendes via parametere, aldri hardkodet i modulen.
- Bruk `_merge_config(defaults, overrides)` for å slå sammen standardverdier med brukerparametre.
- Tilfeldig valg fra intervall brukes der variasjon er ønsket: `np.random.uniform(min, max)`.

## Pipeline og avhengigheter

```
terrain
water   → krever terrain
roads   → krever terrain
buildings → krever terrain + roads
ar5     → krever terrain + water + roads + buildings
```

Når du endrer ett lag, vurder om nedstrøms lag påvirkes.
AR5 skriver tilbake til `synthetic_vann.gpkg` hvis myr/ferskvann-geometri endres.

## Git-rutiner

- Commit-meldinger skrives på norsk
- Sjekk aldri inn `.gpkg`, `.gpkg-shm`, `.gpkg-wal`
- Kjør alltid `python synthetic_map.py` og verifiser at alle fem GeoPackage-filer genereres uten feil før commit
