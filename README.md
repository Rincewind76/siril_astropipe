# AstroPipe for Siril

**[Deutsch](#deutsch) · [English](#english)**

Ein Python-Skript mit grafischer Oberfläche für [Siril](https://siril.org) ≥ 1.4, das OSC-Daten (One-Shot-Color) von den Rohdaten bis zum linearen, farbkalibrierten Stack verarbeitet – für ein Objekt, mehrere Sessions oder viele Objekte im Stapel. Optional folgt eine RC-Astro-Kette (BlurXTerminator, NoiseXTerminator, StarXTerminator), die getrennte lineare Stars- und Starless-Bilder liefert.

A Python script with a graphical interface for [Siril](https://siril.org) ≥ 1.4 that takes OSC (one-shot colour) data from raw frames to a linear, colour-calibrated stack – for one target, multiple sessions or many targets in batch. An optional RC Astro chain (BlurXTerminator, NoiseXTerminator, StarXTerminator) produces separate linear stars and starless images.

---

<a id="deutsch"></a>

## 🇩🇪 Deutsch

### Inhalt

- [Funktionen](#funktionen)
- [Ablauf](#ablauf)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Ordnerstruktur](#ordnerstruktur)
- [Bedienung](#bedienung)
- [Ausgabe](#ausgabe)
- [Konfiguration im Skript](#konfiguration-im-skript)
- [Speicherbedarf](#speicherbedarf)
- [Hinweise und Einschränkungen](#hinweise-und-einschränkungen)

### Funktionen

- **Multi-Session-Stacking:** Jede Session wird mit ihren eigenen Bias-, Flat- und Dark-Frames kalibriert. Danach werden alle Sessions gemeinsam registriert und zu einem Bild gestackt.
- **Stapelmodus:** Verarbeitet alle Objektordner im Siril-Arbeitsverzeichnis nacheinander. Ein Fehler bei einem Objekt stoppt den Stapel nicht.
- **Kalibrierung:** Master-Bias, Master-Flat und Master-Dark pro Session (jeweils optional), Cosmetic Correction aus dem Dark, CFA-Equalisierung, Debayer.
- **Optionaler Hintergrundabzug pro Sub** (`seqsubsky`, Polynom 1. Grades).
- **Registrierung:** 2-Pass mit `-framing=min` – das Ergebnis wird automatisch auf den Bereich beschnitten, den alle Frames abdecken.
- **Stacking:** Winsorized Sigma Clipping (σ 3/3), additive Normalisierung mit Skalierung, wFWHM-Gewichtung, die schlechtesten 10 % der Subs nach FWHM werden verworfen.
- **Zusätzlicher Randbeschnitt** in Prozent je Seite.
- **Optional GraXpert** (KI-Hintergrundextraktion per Kommandozeile).
- **Plate-Solving** mit Brennweite und Pixelgröße aus Presets oder dem FITS-Header.
- **SPCC** mit automatischer Sensorerkennung (ASI2600 → IMX571, sonst IMX585).
- **Sprechende Dateinamen und FITS-Header** (`TELESCOP`, `INSTRUME`, `FILTER`, `FOCALLEN`).
- **Optionales Postprocessing** mit der RC-Astro-Kommandozeile: BXT → NXT (leicht) → StarX → NXT-Hauptpass auf dem Starless-Bild. Alles bleibt linear und ist bereit für VeraLux HMS und StarComposer.

### Ablauf

```
pro Session:   Master Bias/Flat/Dark → Lights kalibrieren → (optional seqsubsky)
                          │
alle Sessions: zu einer Sequenz zusammenlegen
                          │
               2-Pass-Registrierung (framing=min) → Stack
                          │
               Zusatz-Crop → (optional GraXpert) → Plate-Solving → SPCC
                          │
               Speichern mit Namen + FITS-Header      ← Ergebnis 1: linearer Stack
                          │
(optional)     BXT → NXT leicht → StarX → NXT-Hauptpass
                                                        ← Ergebnis 2: Stars / Starless linear
```

### Voraussetzungen

| Komponente | Wofür | Pflicht |
|---|---|---|
| Siril **≥ 1.4** (entwickelt mit 1.4.4) mit Python-Unterstützung (`sirilpy`) | alles | ja |
| `numpy`, `astropy` | FITS-Ein-/Ausgabe | ja – werden beim Start automatisch installiert |
| `tkinter` | Bedienoberfläche | ja – muss in Sirils Python verfügbar sein |
| `tifffile` | Postprocessing | nur für Postprocessing – wird automatisch installiert |
| Internet **oder** lokale Gaia-DR3-Kataloge | Plate-Solving, SPCC | wenn aktiviert |
| [GraXpert](https://github.com/Steffenhir/GraXpert) | Hintergrundextraktion | optional |
| [RC-Astro-Kommandozeile](https://www.rc-astro.com/stand-alone-rc-astro-tools/) (`rc-astro`) mit gültigen BXT-, NXT- und SXT-Lizenzen | Postprocessing | optional |

### Installation

1. `astropipe.py` in einen Ordner kopieren.
2. Diesen Ordner in Siril als Skript-Verzeichnis eintragen (*Einstellungen → Skripte*).
3. Skriptliste aktualisieren oder Siril neu starten – `astropipe` erscheint im Menü *Skripte*.
4. Optional: GraXpert und/oder die RC-Astro-Kommandozeile installieren. Werden sie nicht über den `PATH` gefunden, `GRAXPERT_BIN` bzw. `RC_ASTRO_BIN` im Skript setzen (siehe [Konfiguration](#konfiguration-im-skript)).
5. Einmalig in der Siril-Konsole prüfen, ob die SPCC-Sensornamen stimmen: `spcc_list oscsensor`.

### Ordnerstruktur

Nur `light/` ist Pflicht; `bias/`, `flat/` und `dark/` sind optional. Die Ordnernamen sind unabhängig von Groß-/Kleinschreibung, leere Ordner werden ignoriert. Session- und Objektordner dürfen beliebig heißen, auch mit Leerzeichen.

**A – Ein Objekt, eine Session**

```
<Home>/
├── bias/  flat/  dark/
└── light/
```

**B – Ein Objekt, mehrere Sessions**

```
<Home>/                         ← z. B. M51
├── Session 2026-05/
│   ├── bias/  flat/  dark/  light/
└── Session 2026-07/
    └── flat/  light/
```

**C – Stapelmodus, mehrere Objekte** (Checkbox *Stapelmodus* aktivieren)

```
<Home>/
├── M51/
│   ├── Session 2026-05/   bias/ flat/ dark/ light/
│   └── Session 2026-07/   light/ ...
├── M101/
│   └── bias/ flat/ dark/ light/      ← Einzel-Session direkt im Objektordner
└── tmp_siril/                        ← wird ignoriert
```

> **Achtung:** Ohne Stapelmodus wird **jeder** Unterordner mit `light/` als Session **desselben** Objekts behandelt. Wer Struktur C vergisst, den Stapelmodus zu aktivieren, bekommt z. B. M51 und M101 in einen gemeinsamen Stack. Enthält das Home sowohl Session-Unterordner als auch ein eigenes `light/`, werden nur die Unterordner verwendet.

### Bedienung

1. In Siril das Arbeitsverzeichnis (*Home*) auf den Objekt- bzw. Überordner setzen.
2. Im Menü *Skripte* `astropipe` starten.
3. Einstellungen wählen, auf **Start** klicken und den Fortschritt im Siril-Log verfolgen.

| Einstellung | Standard | Beschreibung |
|---|---|---|
| Teleskop / Reducer | EdgeHD 800 + 0.7x Reducer | Preset für Brennweite (Plate-Solving) und Dateinamen; „aus FITS-Header“ = Werte aus dem Header |
| Kamera | Auto (aus INSTRUME) | Preset für Pixelgröße und SPCC-Sensor; „Auto“ erkennt den Sensor am FITS-Keyword `INSTRUME` |
| Filter | leer | Für Dateinamen und FITS-Header; Liste oder freie Eingabe; leer = `FILTER` aus dem Header |
| Zusatz-Crop % je Rand | 1.0 | Zusätzlicher Beschnitt je Seite nach dem Auto-Crop; 0 = aus |
| Stapelmodus | aus | Alle Objektordner im Home verarbeiten (Struktur C) |
| Stapel-Ergebnisse gesammelt im Home | an | Nur im Stapelmodus: Ergebnisse ins Home statt in den jeweiligen Objektordner |
| Hintergrund pro Sub (seqsubsky) | aus | Gradientenabzug auf jedem kalibrierten Sub, pro Session |
| GraXpert auf finalen Stack | aus | KI-Hintergrundextraktion (Subtraktion, Glättung 0.5) |
| Plate-Solving | an | Astrometrische Lösung des Stacks |
| SPCC-Farbkalibration | an | Spectrophotometric Color Calibration (setzt Plate-Solving voraus) |
| Postprocessing | aus | RC-Astro-Kette → Stars + Starless |
| Temp-Verzeichnis am Ende löschen | aus | Löscht `tmp_siril` nach dem Lauf |

### Ausgabe

**Stack** (linear, plate-gelöst, farbkalibriert):

```
<Objekt> - <Datum> - <Gesamtbelichtung> - <Anzahl>x<Sub> - <Filter> - <Teleskop> - <Kamera>.fits
```

Beispiel: `M51 - 2026-05-14 - 6h15m - 125x180s - L-Pro - EdgeHD800-0.7x - ASI2600MCDuo.fits`

Fehlende Angaben entfallen. Das Datum stammt aus `DATE-OBS` des Stacks. Zusätzlich werden – sofern ein Preset gewählt wurde – `TELESCOP`, `FOCALLEN`, `INSTRUME` und `FILTER` in den FITS-Header geschrieben.

**Postprocessing** (alle linear, im selben Ordner):

| Datei | Inhalt |
|---|---|
| `<Name>_01_linear_bxt_nxt.fits` | nach BlurXTerminator und leichtem NXT |
| `<Name>_02_starless_linear.fits` | Starless (StarXTerminator) |
| `<Name>_02_stars_linear.fits` | nur Sterne (Bild − Starless) |
| `<Name>_03_starless_denoised.fits` | Starless nach NXT-Hauptpass |

Empfohlener nächster Schritt: Starless mit VeraLux HMS strecken, Sterne separat strecken, beides mit StarComposer zusammenführen.

**Ablageort:** Ohne Stapelmodus im Home. Im Stapelmodus im Home (Standard) oder im jeweiligen Objektordner. Zwischendateien liegen in `<Home>/tmp_siril/`.

### Konfiguration im Skript

Presets und Parameter stehen am Anfang von `astropipe.py`.

| Konstante | Standard | Beschreibung |
|---|---|---|
| `TELESCOPES` | EdgeHD 800 (+0.7x), Askar 120APO, Seestar S30 Pro | Name → Brennweite in mm + Kürzel für den Dateinamen |
| `CAMERAS` | ASI2600MC Duo, ASI585MC Air, Seestar S30 Pro | Name → Pixelgröße in µm, Kürzel, SPCC-Sensor |
| `FILTERS` | L-Pro, SV220, ALP-T, Quad-Band, UV/IR-Cut | Auswahlliste in der Oberfläche |
| `SPCC_SENSOR_2600` / `_585` | `Sony IMX571` / `Sony IMX585` | Exakte SPCC-Sensornamen |
| `SIGMA_LOW`, `SIGMA_HIGH` | `3`, `3` | Grenzen für das Sigma Clipping |
| `FWHM_FILTER` | `-filter-fwhm=90%` | Anteil der Subs, die nach FWHM behalten werden; `""` = aus |
| `DIR_BIAS` … `DIR_LIGHT` | `bias`, `flat`, `dark`, `light` | Namen der Unterordner |
| `GRAXPERT_BIN` | `""` | Pfad zu GraXpert; leer = Suche im `PATH`, `/usr/local/bin`, `/opt/homebrew/bin`, `/Applications` |
| `GRAXPERT_SMOOTHING` | `0.5` | GraXpert-Glättung (0–1) |
| `RC_ASTRO_BIN` | `""` | Pfad zu `rc-astro`; leer = gleiche Suche wie oben |
| `BXT_SHARPEN_STARS` | `0.25` | BXT Sternschärfung |
| `BXT_SHARPEN_NONSTELLAR` | `0.60` | BXT Schärfung von Nicht-Stern-Strukturen |
| `BXT_ADJUST_HALOS` | `0.00` | BXT Halo-Anpassung |
| `NXT_LINEAR_DENOISE` | `0.25` | NXT leichter Durchgang (vor StarX) |
| `NXT_MAIN_DENOISE` | `0.85` | NXT-Hauptpass auf Starless |

Auf macOS liegt GraXpert unter `/Applications/GraXpert.app/Contents/MacOS/GraXpert` – am sichersten ist es, diesen Pfad explizit in `GRAXPERT_BIN` einzutragen.

### Speicherbedarf

Die Frames werden als 32-Bit-Float und nach dem Debayern dreifarbig gespeichert, zusätzlich kalibriert, registriert und ggf. hintergrundkorrigiert. Grobe Richtwerte für `tmp_siril` pro Sub:

| Kamera | pro Sub | 100 Subs |
|---|---|---|
| ASI2600MC (26 MP) | ca. 0,7–1,0 GB | ca. 70–100 GB |
| ASI585MC (8,3 MP) | ca. 0,2–0,3 GB | ca. 20–30 GB |

Vor großen Läufen freien Speicher prüfen und `tmp_siril` nach erfolgreichem Lauf löschen (Checkbox oder manuell).

### Hinweise und Einschränkungen

- Ausgelegt auf **OSC-Kameras**. Mono-Kameras und LRGB/SHO-Workflows werden nicht unterstützt.
- **SPCC mit Filtern:** Übergeben wird nur der Sensor (`-oscsensor`), nicht der Filter. Mit Breitbandfiltern (L-Pro, Quad-Band) wird die Kalibrierung dadurch ungenauer. Für Dualband-/Schmalbandfilter (SV220, ALP-T) SPCC besser deaktivieren.
- Bias wird nur für die Flats verwendet; die Lights werden mit dem Master-Dark kalibriert (enthält den Offset). Ohne Dark wird kein Offset abgezogen. Flat-Darks werden nicht unterstützt.
- Die Postprocessing-Dateien enthalten **keinen FITS-Header** (keine WCS-Astrometrie, keine Metadaten) und sind auf den Bereich 0–1 begrenzt.
- Schlägt Plate-Solving, SPCC oder GraXpert fehl, wird der Schritt übersprungen und der Stack trotzdem gespeichert. Fehler in der Kalibrierung oder beim Stacken brechen das jeweilige Objekt ab.
- Das Skript muss aus einer laufenden Siril-Instanz gestartet werden.

---

<a id="english"></a>

## 🇬🇧 English

### Contents

- [Features](#features)
- [Pipeline](#pipeline)
- [Requirements](#requirements)
- [Installation](#installation-1)
- [Folder structure](#folder-structure)
- [Usage](#usage)
- [Output](#output)
- [Script configuration](#script-configuration)
- [Disk space](#disk-space)
- [Notes and limitations](#notes-and-limitations)

### Features

- **Multi-session stacking:** each session is calibrated with its own bias, flat and dark frames; all sessions are then registered together and stacked into one image.
- **Batch mode:** processes every target folder in the Siril working directory in turn. An error on one target does not stop the batch.
- **Calibration:** master bias, master flat and master dark per session (each optional), cosmetic correction from the dark, CFA equalisation, debayer.
- **Optional per-sub background removal** (`seqsubsky`, first-degree polynomial).
- **Registration:** two-pass with `-framing=min` – the result is automatically cropped to the area covered by all frames.
- **Stacking:** winsorized sigma clipping (σ 3/3), additive normalisation with scaling, wFWHM weighting, the worst 10 % of subs by FWHM are rejected.
- **Extra edge crop** in percent per side.
- **Optional GraXpert** (AI background extraction via the command line).
- **Plate solving** using focal length and pixel size from presets or the FITS header.
- **SPCC** with automatic sensor detection (ASI2600 → IMX571, otherwise IMX585).
- **Descriptive file names and FITS header** (`TELESCOP`, `INSTRUME`, `FILTER`, `FOCALLEN`).
- **Optional post-processing** with the RC Astro command-line tool: BXT → NXT (light) → StarX → main NXT pass on the starless image. Everything stays linear, ready for VeraLux HMS and StarComposer.

### Pipeline

```
per session:   master bias/flat/dark → calibrate lights → (optional seqsubsky)
                          │
all sessions:  merge into one sequence
                          │
               two-pass registration (framing=min) → stack
                          │
               extra crop → (optional GraXpert) → plate solving → SPCC
                          │
               save with name + FITS header           ← result 1: linear stack
                          │
(optional)     BXT → light NXT → StarX → main NXT pass
                                                       ← result 2: linear stars / starless
```

### Requirements

| Component | Used for | Required |
|---|---|---|
| Siril **≥ 1.4** (developed with 1.4.4) with Python support (`sirilpy`) | everything | yes |
| `numpy`, `astropy` | FITS I/O | yes – installed automatically on start |
| `tkinter` | user interface | yes – must be available in Siril's Python |
| `tifffile` | post-processing | post-processing only – installed automatically |
| Internet **or** local Gaia DR3 catalogues | plate solving, SPCC | when enabled |
| [GraXpert](https://github.com/Steffenhir/GraXpert) | background extraction | optional |
| [RC Astro command-line tool](https://www.rc-astro.com/stand-alone-rc-astro-tools/) (`rc-astro`) with valid BXT, NXT and SXT licences | post-processing | optional |

### Installation

1. Copy `astropipe.py` into a folder.
2. Add that folder to Siril's script paths (*Preferences → Scripts*).
3. Refresh the script list or restart Siril – `astropipe` appears in the *Scripts* menu.
4. Optional: install GraXpert and/or the RC Astro command-line tool. If they are not found on the `PATH`, set `GRAXPERT_BIN` or `RC_ASTRO_BIN` in the script (see [configuration](#script-configuration)).
5. Check once in the Siril console that the SPCC sensor names are correct: `spcc_list oscsensor`.

### Folder structure

Only `light/` is required; `bias/`, `flat/` and `dark/` are optional. Folder names are case-insensitive, empty folders are ignored. Session and target folders can have any name, including spaces.

**A – One target, one session**

```
<Home>/
├── bias/  flat/  dark/
└── light/
```

**B – One target, multiple sessions**

```
<Home>/                         ← e.g. M51
├── Session 2026-05/
│   ├── bias/  flat/  dark/  light/
└── Session 2026-07/
    └── flat/  light/
```

**C – Batch mode, multiple targets** (enable the *batch mode* checkbox)

```
<Home>/
├── M51/
│   ├── Session 2026-05/   bias/ flat/ dark/ light/
│   └── Session 2026-07/   light/ ...
├── M101/
│   └── bias/ flat/ dark/ light/      ← single session directly in the target folder
└── tmp_siril/                        ← ignored
```

> **Caution:** without batch mode, **every** subfolder containing `light/` is treated as a session of the **same** target. If you use structure C and forget to enable batch mode, M51 and M101 end up in one combined stack. If the home folder contains both session subfolders and its own `light/`, only the subfolders are used.

### Usage

1. In Siril, set the working directory (*Home*) to the target or parent folder.
2. Run `astropipe` from the *Scripts* menu.
3. Choose your settings, click **Start** and follow the progress in the Siril log.

The interface is in German. Settings:

| Setting (label in the UI) | Default | Description |
|---|---|---|
| Telescope / reducer (*Teleskop / Reducer*) | EdgeHD 800 + 0.7x Reducer | Preset for focal length (plate solving) and file name; *aus FITS-Header* = values from the header |
| Camera (*Kamera*) | Auto (from INSTRUME) | Preset for pixel size and SPCC sensor; *Auto* detects the sensor from the FITS keyword `INSTRUME` |
| Filter | empty | For file name and FITS header; pick from list or type; empty = `FILTER` from the header |
| Extra crop % per side (*Zusatz-Crop % je Rand*) | 1.0 | Additional crop per side after the auto-crop; 0 = off |
| Batch mode (*Stapelmodus*) | off | Process all target folders in Home (structure C) |
| Collect batch results in Home (*Stapel-Ergebnisse gesammelt im Home*) | on | Batch mode only: results go to Home instead of each target folder |
| Background per sub (*Hintergrund pro Sub*) | off | Gradient removal on each calibrated sub, per session |
| GraXpert on final stack | off | AI background extraction (subtraction, smoothing 0.5) |
| Plate solving | on | Astrometric solution of the stack |
| SPCC colour calibration | on | Spectrophotometric Color Calibration (requires plate solving) |
| Post-processing | off | RC Astro chain → stars + starless |
| Delete temp folder at the end (*Temp-Verzeichnis … löschen*) | off | Deletes `tmp_siril` after the run |

### Output

**Stack** (linear, plate-solved, colour-calibrated):

```
<Object> - <Date> - <Total exposure> - <Count>x<Sub> - <Filter> - <Telescope> - <Camera>.fits
```

Example: `M51 - 2026-05-14 - 6h15m - 125x180s - L-Pro - EdgeHD800-0.7x - ASI2600MCDuo.fits`

Missing values are omitted. The date comes from the stack's `DATE-OBS`. If a preset is selected, `TELESCOP`, `FOCALLEN`, `INSTRUME` and `FILTER` are also written to the FITS header.

**Post-processing** (all linear, same folder):

| File | Content |
|---|---|
| `<Name>_01_linear_bxt_nxt.fits` | after BlurXTerminator and light NXT |
| `<Name>_02_starless_linear.fits` | starless (StarXTerminator) |
| `<Name>_02_stars_linear.fits` | stars only (image − starless) |
| `<Name>_03_starless_denoised.fits` | starless after main NXT pass |

Suggested next step: stretch the starless image with VeraLux HMS, stretch the stars separately and recombine both with StarComposer.

**Location:** without batch mode in Home; in batch mode in Home (default) or in each target folder. Intermediate files go to `<Home>/tmp_siril/`.

### Script configuration

Presets and parameters are at the top of `astropipe.py`.

| Constant | Default | Description |
|---|---|---|
| `TELESCOPES` | EdgeHD 800 (+0.7x), Askar 120APO, Seestar S30 Pro | name → focal length in mm + short label for file name |
| `CAMERAS` | ASI2600MC Duo, ASI585MC Air, Seestar S30 Pro | name → pixel size in µm, label, SPCC sensor |
| `FILTERS` | L-Pro, SV220, ALP-T, Quad-Band, UV/IR-Cut | drop-down list in the UI |
| `SPCC_SENSOR_2600` / `_585` | `Sony IMX571` / `Sony IMX585` | exact SPCC sensor names |
| `SIGMA_LOW`, `SIGMA_HIGH` | `3`, `3` | sigma clipping limits |
| `FWHM_FILTER` | `-filter-fwhm=90%` | share of subs kept by FWHM; `""` = off |
| `DIR_BIAS` … `DIR_LIGHT` | `bias`, `flat`, `dark`, `light` | subfolder names |
| `GRAXPERT_BIN` | `""` | path to GraXpert; empty = search `PATH`, `/usr/local/bin`, `/opt/homebrew/bin`, `/Applications` |
| `GRAXPERT_SMOOTHING` | `0.5` | GraXpert smoothing (0–1) |
| `RC_ASTRO_BIN` | `""` | path to `rc-astro`; empty = same search as above |
| `BXT_SHARPEN_STARS` | `0.25` | BXT star sharpening |
| `BXT_SHARPEN_NONSTELLAR` | `0.60` | BXT non-stellar sharpening |
| `BXT_ADJUST_HALOS` | `0.00` | BXT halo adjustment |
| `NXT_LINEAR_DENOISE` | `0.25` | light NXT pass (before StarX) |
| `NXT_MAIN_DENOISE` | `0.85` | main NXT pass on starless |

On macOS, GraXpert lives at `/Applications/GraXpert.app/Contents/MacOS/GraXpert` – setting this path explicitly in `GRAXPERT_BIN` is the safest option.

### Disk space

Frames are stored as 32-bit float, three-channel after debayering, and written again after calibration, registration and optionally background removal. Rough figures for `tmp_siril`:

| Camera | per sub | 100 subs |
|---|---|---|
| ASI2600MC (26 MP) | approx. 0.7–1.0 GB | approx. 70–100 GB |
| ASI585MC (8.3 MP) | approx. 0.2–0.3 GB | approx. 20–30 GB |

Check free space before large runs and delete `tmp_siril` after a successful run (checkbox or manually).

### Notes and limitations

- Designed for **OSC cameras**. Mono cameras and LRGB/SHO workflows are not supported.
- **SPCC with filters:** only the sensor (`-oscsensor`) is passed, not the filter. With broadband filters (L-Pro, Quad-Band) calibration is therefore less accurate. For dual-band/narrowband filters (SV220, ALP-T), disabling SPCC is recommended.
- Bias is only used for the flats; lights are calibrated with the master dark (which contains the offset). Without a dark no offset is subtracted. Flat darks are not supported.
- Post-processing files carry **no FITS header** (no WCS astrometry, no metadata) and are clipped to 0–1.
- If plate solving, SPCC or GraXpert fails, that step is skipped and the stack is still saved. Errors during calibration or stacking abort the affected target.
- The script must be launched from a running Siril instance.
