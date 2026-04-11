# Samlet Instruksjon (Retrospektivt)

Lag et Python-program som genererer et komplett syntetisk kartdatasett for et avgrenset område i Norge (UTM), med realistisk intern sammenheng mellom terreng, vann, vegnett, bygninger og AR5-arealtyper.

## Mål

Programmet skal produsere GIS-klare data i GeoPackage-format, der hvert tema ligger i egen fil og med konsistent geometri mellom lagene.

## Teknologi og rammer

- Språk: Python 3.9+
- Avhengigheter: GeoPandas, Shapely, NumPy, SciPy (Delaunay), Pandas/Fiona etter behov
- CRS: EPSG:25833
- Input: Ingen eksterne datasett (alt skal være syntetisk generert)
- Output: fem GeoPackage-filer

## Overordnet arkitektur

Bygg løsningen modulært med én orkestrator og temamoduler:

- `synthetic_map.py`: orkestrerer kjøring, konfig, avhengigheter og lagring
- `synthetic_hoydekurve_module.py`: terrengpunkter, TIN, høydekurver
- `synthetic_vann_module.py`: innsjøer, bekker/elv, myr
- `synthetic_vegnett_module.py`: vegsenterlinjer og vegkant
- `synthetic_bygning_module.py`: bygningsflater
- `synthetic_ar5_module.py`: heldekkende AR5-flater med prioritet og clipping

## Funksjonelle krav

1. Terreng
- Generer hierarkiske høydepunkter (flere detaljnivåer).
- Trianguler punktene til TIN.
- Generer høydekurver med 1 m ekvidistanse.

2. Vann
- Finn innsjøkandidater fra lukkede høydekurver i forsenkninger.
- Generer innløps-/utløpsbekker basert på terrengdrenering.
- Generer myr fra flate terrengområder, med sammenslåing/splitting etter arealkrav.
- Sikre at vannlag klippes innenfor BBOX og er topologisk gyldig.

Ønsker å lage et geopackage for Vann.
Denne skal genereres etter Terreng.
I Vann vil jeg ha generert følgende objekttyper:
- Innsjøkant: Lukket polygon
- ElvBekk: Senterlinje, kurve
- MyrGrense: Lukket polygon

Innsjøkant:
Områder som er en grop, eller "lukket" lavpunkt, er kandidat for innsjø.
Objekttypen Innsjøkant er et lukket polygon.
Høydekurver som er lukket, og som har 1, 2 eller 3 lukkede høydekurver inni seg med lavere høyde er kandidat for innsjø. La da Innsjøkant følge denne høydekurven.
Store Innsjøkant-polygoner, reduseres ved å bruke en av de høydekurvene som ligger inni som Innsjøkant. 

ElvBekk:
Jeg har en syntetisk terrengmodell. Både TIN og høydekurver. Ønsker å generere vann og bekk. Ikke raster, men vektor. Hvordan? Hvilke algoritmer? Har hørt om ‘TIN-based Flow Accumulation’.

Inn til hver sjø rener det 0,1 eller 2 bekker. De er plassert oppover, men ikke langs rygger, men helst i søkk. 
Lengden på bekk inn til sjø er mellom 100m og 500m
Ut fra hvert vann kan det renne 1 bekk. Ettersom innsjøen er i grop, må det noen ganger klatres opp en høydekurve eller to før en finner en vei nedover. Denne skal følge avrenning, altså fallretningene fra gradienten på TIN-trekanten. 
Lengden på bekk ut av en sjø er mellom 300m og 700m 

MyrGrense:
Noen av de aller flateste områdene defineres som myr
Noen ganger kommer to myr-flater rett ved siden av hverandre. Slå disse sammen til en flate


Organiser alle parametre samlet i hoved-skriptet. 
Dokumenter alle parametre i readme


3. Vegnett
- Generer 2 riksveger + 2 kommunale veger med jevn kurvatur.
- Legg private avkjørsler langs kommunale veger med avstandsregler.
- Unngå uønskede kryssinger; bruk retry-strategi ved konflikt.
- Generer vegkant fra vegbredder per vegtype.

4. Bygninger
- Plasser bygninger i grupper ved private avkjørsler.
- Bruk minst to bygningstyper (rektangulær, L-formet).
- Filtrer/sanér bygg som kolliderer med veg eller ligger for nær hovedveg.

Generer Bygninger i eget kartlag: synthetic_bygning.gpkg
To typer Bygninger: Rektangulært, og L-formet. 
Parametre for husstørrelse er BygningSizeMin=6 meter, BygningSizeMax=30 meter. AvstandMellomBygningGruppe=8 meter
Retningen på en bygning er tilfeldig.
Lag Bygningsgrupper på 2 eller 3 bygninger. Avstandene mellom bygningene innad i en Bygningsgruppe er AvstandMellomBygningGruppe.
For hver PrivatAvkjørsel genereres en Bygningsgruppe.
Dersom to bygninger overlapper hverandre, slettes den minste Bygningen
Dersom en bygninger overlapper med veg, slettes Bygningen
Bygninger som er nærmere enn 8 meter fra RiksVeg eller KommunalVeg flyttes tilsvarende bort fra vegen

Avstanden fra veg til Bygningsgruppe er 10 meter
Avstanden fra Bygningsgruppe til neste Bygningsgruppe er 100 meter
Avstanden fra Bygningsgruppe til nærmeste veg-ende er 200 meter
Generer Bygningsgruppe langs en side av alle Kommunale veger


5. AR5 (heldekkende)
- Generer heldekkende AR5-klasser: `Fulldyrka jord`, `Barskog`, `Bebygd`, `Samferdsel`, `Myr`, `Ferskvann`.
- Bruk fast prioritet i overlapping:
  1. `Samferdsel`
  2. `Bebygd`
  3. `Ferskvann`
  4. `Myr`
  5. `Fulldyrka jord`
  6. `Barskog` (restareal)
AR5 er et heldekkende arealressursdatasett som beskriver alt areal. 

Ønsker å lage et geopackage for AR5.
Denne skal genereres sist av alle kartlag.
I AR5 vil jeg ha generert følgende objekttyper(AR-flater):
-Fulldyrka jord
-Barskog
-Bebygd
-Samferdsel
-Myr
-Ferskvann

Alle objekttypene er lukket polygon.

#### Myr: 
Hant alle Vann-myrgrense polygoner til AR5-Myr 

#### Ferskvann: 
Hant alle Vann-Innsjøkant polygoner til AR5-Ferskvann 

#### Samferdsel: 
Lag buffer rundt alle senterlinje-veg med vegbredden fra parametrene. Disse flatene lagres som Samferdsel i AR5. 
Alle arealer for veger slås sammen til Samferdsel.
Om det er andre AR-Flater som overlappes med Samferdsel, skal Samferdsel bli, og de andre AR5-flatene klippes bort.

#### Bebygd: 
Rundt alle bygg lages buffer på 100m. 
Slå bufferene sammen. 
Nærliggende Bebygd-flater slås sammen.
Dersom Bebygd overlapper med Samferdsel, reduseres Bebygd tilsvarende.
Dersom Bebygd overlapper med Myr, reduseres Myr tilsvarende.
Dersom Bebygd overlapper med Ferskvann, fjærnes hele Ferskvann.

#### Fulldyrka jord:
Av det gjenværende arealet, finn noen relativt flate områder > 20.000m2. Disse lagres i AR5 som FulldyrkaJord

#### Barskog: 
Resten av arealene er lagres som Barskog

Like AF-flater som ligger inntil hverandre slås sammen.
Kontroll: Ingen overlappende AR-flater. 
Kontroll: Hele området degget av AR-flater

Noen AR-flater er hentet og modifiserte. Oppdater disse i andre kartbaser:
Dersom ulik polygon Vann-myrgrense og AR5-Myr, erstattes Vann-myrgrense av AR5-Myr
Dersom ulik polygon Vann-Innsjøkant og AR5-Ferskvann, erstattes Vann-Innsjøkant av AR5-Ferskvann

Til slutt litt kosmetikk i hovedskriptet:
Slett høydekurver som er innenfor Innsjøkant.


## Datastruktur og output

Programmet skal skrive disse filene:

- `synthetic_terrain.gpkg` med lagene `terrain_points`, `terrain_tin`, `hoydekurver_1m`
- `synthetic_vann.gpkg` med lagene `innsjokant`, `elvbekk`, `myrgrense`
- `synthetic_vegnett.gpkg` med lagene `vegnett_riksveg`, `vegkant`
- `synthetic_bygning.gpkg` med laget `bygninger`
- `synthetic_ar5.gpkg` med laget `ar5_areal`

## Kjøring og CLI

`synthetic_map.py` skal støtte:

- Standard: kjør alt
- `--layers terrain|water|roads|buildings|ar5|all`
- Automatisk oppløsning av avhengigheter:
  - `water` krever `terrain`
  - `roads` krever `terrain`
  - `buildings` krever `terrain` + `roads`
  - `ar5` krever alle foregående

## Kvalitetskrav

- Geometrier skal være gyldige (bruk reparasjon ved behov, f.eks. `buffer(0)` der det er forsvarlig).
- Resultatet skal være robust for flere kjøringer med ulike tilfeldige utfall.
- Programmet skal skrive kort statistikk per lag etter generering.
- Kode skal være modulær, lesbar og dokumentert med korte docstrings.
- Ingen legacy-skript eller duplisert kjernelogikk.

## Konfigurasjon

Samle sentrale parametre i `synthetic_map.py`:

- BBOX, CRS
- `TERRAIN_CONFIG`
- `WATER_CONFIG`
- `ROAD_CONFIG`
- `ROAD_EDGE_CONFIG`
- `AR5_CONFIG`

Parametre skal være enkle å justere uten å endre algoritmekode.

## Validering før levering

1. Kjør full pipeline: `python synthetic_map.py`
2. Verifiser at alle fem GeoPackage-filer opprettes.
3. Verifiser at AR5-arealdekning matcher BBOX-areal innen liten toleranse.
4. Verifiser at det ikke finnes uønskede midlertidige filer i git.
5. Oppdater README med arkitektur, bruk, output og konfigurasjon.

## Leveranseformat

Lever en ryddig repository-struktur med:

- kildekode i modulene over
- oppdatert README
- `requirements.txt`
- `.gitignore` som ignorerer miljø- og låsefiler
