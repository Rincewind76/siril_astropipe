#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AstroPipe -- Multi-Session-Stacking + optionales Postprocessing (Siril 1.4.4)
=============================================================================

GUI-Maxi-Skript. Home-Verzeichnis in Siril = Ueberordner des Objekts mit
Session-Unterordnern (beliebige Namen, z.B. "Session 2026-05", "Session a"):

  <Home>/
    Session 2026-05/   bias/ dark/ flat/ light/     (nur light ist Pflicht)
    Session 2026-07/   light/ ...
  -> auch Einzel-Session direkt im Home (bias/dark/flat/light) wird erkannt.

Ablauf: pro Session Master bauen + Lights kalibrieren (+ optional seqsubsky)
-> alle Sessions zu einer Sequenz zusammenlegen -> gemeinsame 2-Pass-
Registrierung mit -framing=min
(Auto-Crop auf die Schnittmenge aller Frames) -> Stack -> optionaler
Zusatz-Crop -> optional GraXpert (CLI) -> Plate-Solving -> SPCC -> Speichern
mit vollem Namen + FITS-Header-Attributen (TELESCOP/INSTRUME/FILTER/FOCALLEN).
Optional danach RC-Astro-Kette (BXT -> NXT leicht -> StarX -> NXT-Hauptpass)
-> Stars + Starless linear, fertig fuer VeraLux HMS / StarComposer.

STAPELMODUS (ersetzt autoprocess.py): Home = Ueberordner mit Objektordnern
(M51, M101, ...); jeder Objektordner enthaelt Sessions oder direkt
bias/dark/flat/light. Jedes Objekt wird nacheinander komplett verarbeitet;
ein Fehler bei einem Objekt stoppt den Stapel nicht.

Alle Ausgaben mit Endung .fits. Aus laufender Siril-Instanz starten.
"""

import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import sirilpy as s

s.ensure_installed("numpy")
s.ensure_installed("astropy")
import numpy as np
from astropy.io import fits as afits

# ============================================================================
# PRESETS & DEFAULTS
# ============================================================================
# SPCC-Sensornamen: exakte Strings einmalig mit `spcc_list oscsensor` pruefen!
SPCC_SENSOR_2600 = "Sony IMX571"
SPCC_SENSOR_585  = "Sony IMX585"

TELESCOPES = {
    "EdgeHD 800 + 0.7x Reducer": {"focal": "1422", "label": "EdgeHD800-0.7x"},
    "EdgeHD 800 (nativ)":        {"focal": "2032", "label": "EdgeHD800"},
    "Askar 120APO + 1x Flattener": {"focal": "840", "label": "Askar120APO"},
    "Seestar S30 Pro":           {"focal": "150",  "label": "SeestarS30Pro"},
    "aus FITS-Header":           {"focal": "",     "label": ""},
}
CAMERAS = {
    "Auto (aus INSTRUME)":       {"pixel": "",     "label": "",            "spcc": ""},
    "ASI2600MC Duo":             {"pixel": "3.76", "label": "ASI2600MCDuo", "spcc": SPCC_SENSOR_2600},
    "ASI585MC Air":              {"pixel": "2.9",  "label": "ASI585MC",    "spcc": SPCC_SENSOR_585},
    "Seestar S30 Pro (IMX585)":  {"pixel": "2.9",  "label": "SeestarS30",  "spcc": SPCC_SENSOR_585},
    "aus FITS-Header":           {"pixel": "",     "label": "",            "spcc": ""},
}
FILTERS = ["", "L-Pro", "SV220", "ALP-T", "Quad-Band", "UV/IR-Cut"]

SIGMA_LOW, SIGMA_HIGH = "3", "3"
FWHM_FILTER = "-filter-fwhm=90%"

DIR_BIAS, DIR_FLAT, DIR_DARK, DIR_LIGHT = "bias", "flat", "dark", "light"

RC_ASTRO_BIN = ""            # leer = PATH-Suche
BXT_SHARPEN_STARS, BXT_SHARPEN_NONSTELLAR, BXT_ADJUST_HALOS = "0.25", "0.60", "0.00"
NXT_LINEAR_DENOISE, NXT_MAIN_DENOISE = "0.25", "0.85"

GRAXPERT_BIN = ""            # leer = PATH-Suche ("graxpert"); sonst absoluter Pfad
GRAXPERT_SMOOTHING = "0.5"

# ============================================================================
# Basis-Helfer
# ============================================================================
def safe_path(p):
    ps = str(p)
    return ps if (ps.startswith('"') and ps.endswith('"')) else f'"{ps}"'

def out_arg(p):
    return f'"-out={p}"'

def qtok(t):
    return f'"{t}"'

def log(siril, msg):
    try:
        siril.log(msg)
    except Exception:
        print(msg)

def find_dir(parent, name):
    for child in Path(parent).iterdir():
        if child.is_dir() and child.name.lower() == name.lower() and any(child.iterdir()):
            return child
    return None

def sanitize(text):
    return re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|]', "", str(text)).strip())

def fmt_exposure(seconds):
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    h, rem = divmod(total, 3600)
    m = rem // 60
    if h and m:
        return f"{h}h{m:02d}m"
    if h:
        return f"{h}h"
    return f"{m}m" if m else f"{total}s"

def fmt_subs(hdr):
    try:
        n = int(round(float(hdr.get("STACKCNT", 0) or 0)))
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return ""
    sub = None
    try:
        live = hdr.get("LIVETIME")
        if live:
            sub = float(live) / n
    except (TypeError, ValueError):
        sub = None
    if not sub:
        try:
            sub = float(hdr.get("EXPTIME") or 0) or None
        except (TypeError, ValueError):
            sub = None
    if not sub or sub <= 0:
        return f"{n}subs"
    es = f"{int(round(sub))}" if abs(sub - round(sub)) < 0.5 else f"{sub:.1f}"
    return f"{n}x{es}s"

def run_ext(siril, args, outdir, what):
    """Externes Tool ausfuehren, neueste erzeugte Bilddatei zurueckgeben."""
    before = {p: p.stat().st_mtime for p in Path(outdir).glob("*")}
    log(siril, "  $ " + " ".join(str(a) for a in args))
    t0 = time.time()
    proc = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    for line in (proc.stdout or "").strip().splitlines():
        log(siril, "    " + line)
    if proc.returncode != 0:
        for line in (proc.stderr or "").strip().splitlines():
            log(siril, "    ERR " + line)
        raise RuntimeError(f"{what} fehlgeschlagen (Code {proc.returncode})")
    new = [p for p in Path(outdir).glob("*")
           if (p not in before or p.stat().st_mtime > before.get(p, 0))
           and p.suffix.lower() in (".tif", ".tiff", ".fit", ".fits")]
    if not new:
        raise RuntimeError(f"{what}: keine Ausgabedatei gefunden")
    out = max(new, key=lambda p: p.stat().st_mtime)
    log(siril, f"    -> {out.name}  ({time.time()-t0:.0f}s)")
    return out

def find_bin(configured, name):
    if configured.strip():
        return configured.strip()
    found = shutil.which(name)
    if found:
        return found
    for cand in (f"/usr/local/bin/{name}", f"/opt/homebrew/bin/{name}",
                 f"/Applications/{name}.app/Contents/MacOS/{name}"):
        if Path(cand).exists():
            return cand
    raise FileNotFoundError(f"'{name}' nicht gefunden -- Pfad im Skript setzen.")

# ---- Bild-I/O ----------------------------------------------------------------
def read_img(path):
    p = Path(path)
    if p.suffix.lower() in (".fit", ".fits"):
        data = afits.getdata(str(p)).astype(np.float32)
        if data.ndim == 3 and data.shape[0] in (1, 3):
            data = np.moveaxis(data, 0, -1)
        return data
    s.ensure_installed("tifffile")
    import tifffile
    data = tifffile.imread(str(p)).astype(np.float32)
    if data.max() > 2.0:
        data /= 65535.0
    return data

def write_fits(path, data):
    d = np.asarray(data, dtype=np.float32)
    if d.ndim == 3:
        d = np.moveaxis(d, -1, 0)
    afits.PrimaryHDU(np.clip(d, 0.0, 1.0)).writeto(str(path), overwrite=True)

def write_tiff(path, data):
    s.ensure_installed("tifffile")
    import tifffile
    tifffile.imwrite(str(path), np.asarray(np.clip(data, 0.0, 1.0), dtype=np.float32))

# ============================================================================
# Stacking-Engine (Multi-Session)
# ============================================================================
def discover_sessions(home):
    """Alle Unterordner mit light/; falls keiner: Home selbst als Einzel-Session."""
    sessions = [d for d in sorted(Path(home).iterdir())
                if d.is_dir() and find_dir(d, DIR_LIGHT) is not None]
    if not sessions and find_dir(home, DIR_LIGHT) is not None:
        sessions = [Path(home)]
    return sessions

def process_session(siril, session, tmp_s, use_subsky):
    """Master bauen + Lights kalibrieren. Gibt die Liste der kalibrierten
    Einzel-Frames dieser Session zurueck."""
    tmp_s.mkdir(parents=True, exist_ok=True)
    bias = find_dir(session, DIR_BIAS)
    flat = find_dir(session, DIR_FLAT)
    dark = find_dir(session, DIR_DARK)
    log(siril, f"  Bias {'ja' if bias else '--'} | Flat {'ja' if flat else '--'} | "
               f"Dark {'ja' if dark else '--'}")

    if bias:
        siril.cmd("cd", safe_path(bias))
        siril.cmd("convert", "bias", out_arg(tmp_s), "-fitseq")
        siril.cmd("cd", safe_path(tmp_s))
        siril.cmd("stack", "bias", "rej", "w", "3", "3", "-nonorm", "-out=bias_stacked")
    if flat:
        siril.cmd("cd", safe_path(flat))
        siril.cmd("convert", "flat", out_arg(tmp_s), "-fitseq")
        siril.cmd("cd", safe_path(tmp_s))
        if bias:
            siril.cmd("calibrate", "flat", "-bias=bias_stacked")
            siril.cmd("stack", "pp_flat", "rej", "w", "3", "3", "-norm=mul",
                      "-out=pp_flat_stacked")
        else:
            siril.cmd("stack", "flat", "rej", "w", "3", "3", "-norm=mul",
                      "-out=pp_flat_stacked")
    if dark:
        siril.cmd("cd", safe_path(dark))
        siril.cmd("convert", "dark", out_arg(tmp_s), "-fitseq")
        siril.cmd("cd", safe_path(tmp_s))
        siril.cmd("stack", "dark", "rej", "w", "3", "3", "-nonorm", "-out=dark_stacked")

    # Lights als EINZELBILDER konvertieren (kein -fitseq): nur so lassen sie sich
    # anschliessend zu EINER durchnummerierten Gesamt-Sequenz zusammenlegen.
    light = find_dir(session, DIR_LIGHT)
    siril.cmd("cd", safe_path(light))
    siril.cmd("convert", "light", out_arg(tmp_s))
    siril.cmd("cd", safe_path(tmp_s))

    cal = ["calibrate", "light"]
    if dark:
        cal += ["-dark=dark_stacked", "-cc=dark"]
    if flat:
        cal += ["-flat=pp_flat_stacked"]
    cal += ["-cfa", "-equalize_cfa", "-debayer"]
    siril.cmd(*cal)

    prefix = "pp_light"
    if use_subsky:
        siril.cmd("seqsubsky", "pp_light", "1")   # Poly Grad 1 pro Sub
        prefix = "bkg_pp_light"

    frames = sorted(p for p in tmp_s.glob(f"{prefix}_*")
                    if p.suffix.lower() in (".fits", ".fit"))
    if not frames:
        raise FileNotFoundError(
            f"Keine kalibrierten Frames '{prefix}_*' in {tmp_s} gefunden.")
    log(siril, f"  {len(frames)} kalibrierte Frames")
    return frames

def stack_all(siril, home, tmp, cfg):
    """Alle Sessions -> EIN Stack. Die kalibrierten Frames aller Sessions werden
    fortlaufend nach combined/all_NNNNN.fits verschoben (Rename, kein Kopieren)
    und bilden dort automatisch eine einzige Sequenz -- kein 'merge' noetig."""
    sessions = discover_sessions(home)
    if not sessions:
        raise FileNotFoundError("Keine Session mit 'light'-Ordner gefunden.")
    log(siril, f"{len(sessions)} Session(s): " + ", ".join(p.name for p in sessions))

    combined = tmp / "combined"
    combined.mkdir(parents=True, exist_ok=True)
    for old in combined.glob("*.seq"):        # alte Sequenzinfos verwerfen
        old.unlink()

    idx = 0
    for i, sess in enumerate(sessions, 1):
        log(siril, f"Session {i}: {sess.name}")
        frames = process_session(siril, sess, tmp / f"s{i:02d}", cfg["subsky"])
        for f in frames:
            idx += 1
            shutil.move(str(f), str(combined / f"all_{idx:05d}.fits"))
        log(siril, f"  -> combined (Gesamt bisher: {idx} Frames)")

    if idx == 0:
        raise FileNotFoundError("Keine kalibrierten Frames zum Stacken.")
    log(siril, f"Gesamt: {idx} Frames aus {len(sessions)} Session(s)")

    siril.cmd("cd", safe_path(combined))

    log(siril, "Registrierung (2-Pass, framing=min = Auto-Crop) ...")
    siril.cmd("register", "all_", "-2pass")
    try:
        siril.cmd("seqapplyreg", "all_", "-framing=min")
    except Exception as e:
        log(siril, f"  -framing=min nicht verfuegbar ({e}) -> Standard-Framing")
        siril.cmd("seqapplyreg", "all_")

    log(siril, "Stacking ...")
    args = ["stack", "r_all_", "rej", "w", SIGMA_LOW, SIGMA_HIGH,
            "-norm=addscale", "-output_norm", "-weight=wfwhm"]
    if FWHM_FILTER:
        args.append(FWHM_FILTER)
    args.append("-out=stack_result")
    siril.cmd(*args)

    for ext in (".fits", ".fit"):
        cand = combined / f"stack_result{ext}"
        if cand.exists():
            return cand
    raise FileNotFoundError("stack_result nicht gefunden.")

# ============================================================================
# Finalisierung: Crop, GraXpert, Plate-Solving, SPCC, Namen & Header
# ============================================================================
def detect_oscsensor(path, cfg):
    cam = CAMERAS[cfg["camera"]]
    if cam["spcc"]:
        return cam["spcc"], f"GUI-Auswahl: {cfg['camera']}"
    instr = str(afits.getheader(str(path)).get("INSTRUME", "")).strip()
    if "2600" in instr.upper():
        return SPCC_SENSOR_2600, f"ASI2600 erkannt ('{instr}')"
    return SPCC_SENSOR_585, f"585/Seestar angenommen ('{instr or 'INSTRUME leer'}')"

def build_name(path, cfg):
    hdr = afits.getheader(str(path))
    obj  = sanitize(hdr.get("OBJECT", "")) or "Objekt"
    date_obs = str(hdr.get("DATE-OBS", "")).strip()
    date = date_obs[:10] if len(date_obs) >= 10 else ""
    live = hdr.get("LIVETIME")
    if live is None:
        live = float(hdr.get("STACKCNT", 0) or 0) * float(hdr.get("EXPTIME", 0) or 0)
    filt = sanitize(cfg["filter"]) or sanitize(hdr.get("FILTER", ""))
    tele = TELESCOPES[cfg["telescope"]]["label"]
    cam  = CAMERAS[cfg["camera"]]["label"]
    parts = [p for p in (obj, date, fmt_exposure(live), fmt_subs(hdr),
                         filt, tele, cam) if p]
    return " - ".join(parts) + ".fits"

def update_header(path, cfg):
    """Teleskop/Kamera/Filter/Brennweite als FITS-Attribute hinterlegen."""
    with afits.open(str(path), mode="update") as hd:
        h = hd[0].header
        tele = TELESCOPES[cfg["telescope"]]
        cam  = CAMERAS[cfg["camera"]]
        if tele["label"]:
            h["TELESCOP"] = (cfg["telescope"], "Telescope + reducer (AstroPipe)")
        if tele["focal"]:
            h["FOCALLEN"] = (float(tele["focal"]), "[mm] effective focal length")
        if cam["label"]:
            h["INSTRUME"] = (cfg["camera"], "Camera (AstroPipe)")
        if cfg["filter"].strip():
            h["FILTER"] = (cfg["filter"].strip(), "Filter (AstroPipe)")

def finalize(siril, raw_stack, outdir, tmp, cfg):
    siril.cmd("load", safe_path(raw_stack))

    # Zusatz-Crop in % je Rand
    pct = float(cfg["crop_pct"] or 0)
    if pct > 0:
        data = afits.getdata(str(raw_stack))
        hgt, wid = (data.shape[-2], data.shape[-1])
        dx, dy = int(wid * pct / 100), int(hgt * pct / 100)
        siril.cmd("crop", str(dx), str(dy), str(wid - 2 * dx), str(hgt - 2 * dy))
        log(siril, f"Zusatz-Crop {pct}% je Rand: {wid}x{hgt} -> {wid-2*dx}x{hgt-2*dy}")

    # GraXpert (optional, dateibasiert)
    if cfg["graxpert"]:
        try:
            gx = find_bin(GRAXPERT_BIN, "graxpert")
            gx_in = tmp / "for_graxpert.fits"
            siril.cmd("save", safe_path(tmp / "for_graxpert"))
            out = run_ext(siril, [gx, "-cli", "-cmd", "background-extraction",
                                  str(gx_in), "-correction", "Subtraction",
                                  "-smoothing", GRAXPERT_SMOOTHING,
                                  "-output", str(tmp / "graxpert_out")],
                          tmp, "GraXpert")
            siril.cmd("load", safe_path(out))
            log(siril, "GraXpert-Hintergrundabzug OK")
        except Exception as e:
            log(siril, f"GraXpert uebersprungen: {e} "
                       f"(Syntax mit 'graxpert --help' pruefen)")

    # Plate-Solving
    if cfg["platesolve"]:
        ps = ["platesolve"]
        tele, cam = TELESCOPES[cfg["telescope"]], CAMERAS[cfg["camera"]]
        if tele["focal"]:
            ps.append(f"-focal={tele['focal']}")
        if cam["pixel"]:
            ps.append(f"-pixelsize={cam['pixel']}")
        try:
            siril.cmd(*ps)
            log(siril, "Plate-Solving OK")
        except Exception as e:
            log(siril, f"Plate-Solving uebersprungen: {e}")

    # SPCC
    if cfg["spcc"]:
        try:
            probe = tmp / "probe.fits"
            siril.cmd("save", safe_path(tmp / "probe"))
            sensor, note = detect_oscsensor(probe, cfg)
            log(siril, f"SPCC-Sensor: {note}")
            siril.cmd("spcc", qtok(f"-oscsensor={sensor}"))
            log(siril, "SPCC OK")
        except Exception as e:
            log(siril, f"SPCC uebersprungen: {e} (Namen: 'spcc_list oscsensor')")

    # Speichern mit finalem Namen + Header-Attribute
    tmp_final = tmp / "final_tmp.fits"
    siril.cmd("save", safe_path(tmp / "final_tmp"))
    final_path = Path(outdir) / build_name(tmp_final, cfg)
    shutil.copy(str(tmp_final), str(final_path))
    update_header(final_path, cfg)
    siril.cmd("load", safe_path(final_path))
    log(siril, f"Ergebnis: {final_path.name}")
    return final_path

# ============================================================================
# Postprocessing (RC-Astro-Kette, linear, ohne Stretch)
# ============================================================================
def postprocess(siril, final_path, outdir, tmp, cfg):
    rc = find_bin(RC_ASTRO_BIN, "rc-astro")
    work = tmp / "post"
    work.mkdir(parents=True, exist_ok=True)
    base = final_path.stem

    src = work / "00_input.tif"
    siril.cmd("load", safe_path(final_path))
    siril.cmd("savetif32", safe_path(work / "00_input"))
    if not src.exists():
        raise FileNotFoundError("savetif32 fehlgeschlagen.")

    log(siril, "Post 1: BlurXTerminator ...")
    bxt = run_ext(siril, [rc, "bxt", src,
                          "--sharpen-stars", BXT_SHARPEN_STARS,
                          "--sharpen-nonstellar", BXT_SHARPEN_NONSTELLAR,
                          "--adjust-star-halos", BXT_ADJUST_HALOS,
                          "--output", work], work, "BXT")
    log(siril, "Post 1: NoiseXTerminator (leicht) ...")
    nxt1 = run_ext(siril, [rc, "nxt", bxt, "--denoise", NXT_LINEAR_DENOISE,
                           "--output", work], work, "NXT")
    stage1 = read_img(nxt1)
    p1 = Path(outdir) / f"{base}_01_linear_bxt_nxt.fits"
    write_fits(p1, stage1)
    log(siril, f"  gespeichert: {p1.name}")

    log(siril, "Post 2: StarXTerminator ...")
    t1 = work / "01_for_sxt.tif"
    write_tiff(t1, stage1)
    sxt = run_ext(siril, [rc, "sxt", t1, "--output", work], work, "SXT")
    starless = np.clip(read_img(sxt), 0.0, 1.0)
    stars = np.clip(stage1 - starless, 0.0, 1.0)
    p2a = Path(outdir) / f"{base}_02_starless_linear.fits"
    p2b = Path(outdir) / f"{base}_02_stars_linear.fits"
    write_fits(p2a, starless)
    write_fits(p2b, stars)
    log(siril, f"  gespeichert: {p2a.name}, {p2b.name}")

    log(siril, "Post 3: NXT-Hauptpass auf Starless ...")
    t2 = work / "02_starless.tif"
    write_tiff(t2, starless)
    nxt2 = run_ext(siril, [rc, "nxt", t2, "--denoise", NXT_MAIN_DENOISE,
                           "--output", work], work, "NXT")
    p3 = Path(outdir) / f"{base}_03_starless_denoised.fits"
    write_fits(p3, np.clip(read_img(nxt2), 0.0, 1.0))
    log(siril, f"  gespeichert: {p3.name}")
    log(siril, "Bereit fuer VeraLux HMS (Starless) + Stretch der Sterne + StarComposer.")

# ============================================================================
# Pipeline-Runner
# ============================================================================
def run_object(siril, obj, outdir, tmp, cfg):
    """Ein Objekt komplett: Stack -> Finalisierung -> optional Post."""
    tmp.mkdir(parents=True, exist_ok=True)
    raw = stack_all(siril, obj, tmp, cfg)
    final = finalize(siril, raw, outdir, tmp, cfg)
    if cfg["post"]:
        postprocess(siril, final, outdir, tmp, cfg)
    return final


def run_pipeline(siril, cfg):
    try:
        home = Path(siril.get_siril_wd())
        log(siril, f"Home: {home}")
        tmp_root = home / "tmp_siril"

        siril.cmd("set32bits")
        siril.cmd("setext", "fits")

        if cfg["batch"]:
            objects = [d for d in sorted(home.iterdir())
                       if d.is_dir() and d.name.lower() != "tmp_siril"
                       and discover_sessions(d)]
            if not objects:
                log(siril, "Stapelmodus: keine Objektordner mit Daten gefunden.")
                return
            log(siril, f"Stapelmodus: {len(objects)} Objekt(e): "
                       + ", ".join(o.name for o in objects))
            done, failed = [], []
            for obj in objects:
                tmp = tmp_root / obj.name
                outdir = home if cfg["batch_to_parent"] else obj
                log(siril, "")
                log(siril, f"########## {obj.name} ##########")
                try:
                    run_object(siril, obj, outdir, tmp, cfg)
                    done.append(obj.name)
                except Exception as e:
                    log(siril, f"FEHLER bei {obj.name}: {e}")
                    failed.append(obj.name)
                finally:
                    if cfg["del_tmp"]:
                        shutil.rmtree(tmp, ignore_errors=True)
            log(siril, "")
            log(siril, f"=== Stapel fertig: {len(done)} OK, {len(failed)} Fehler ===")
            if done:
                log(siril, "OK: " + ", ".join(done))
            if failed:
                log(siril, "Fehler: " + ", ".join(failed))
        else:
            run_object(siril, home, home, tmp_root, cfg)

        if cfg["del_tmp"]:
            shutil.rmtree(tmp_root, ignore_errors=True)
            log(siril, "tmp_siril geloescht.")
        log(siril, "=== AstroPipe fertig ===")
    except Exception as e:
        log(siril, f"FEHLER: {e}")
        raise

# ============================================================================
# GUI
# ============================================================================
def main():
    siril = s.SirilInterface()
    try:
        siril.connect()
    except s.SirilConnectionError as e:
        print(f"Verbindung zu Siril fehlgeschlagen: {e}")
        return

    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("AstroPipe -- Multi-Session Stack & Post")
    try:
        from sirilpy import tksiril
        tksiril.match_theme_to_siril(root, siril)
    except Exception:
        pass

    frm = ttk.Frame(root, padding=12)
    frm.grid(sticky="nsew")

    def row(r, label, widget):
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
        widget.grid(row=r, column=1, sticky="ew", pady=3)

    v_tele = tk.StringVar(value=list(TELESCOPES)[0])
    v_cam  = tk.StringVar(value=list(CAMERAS)[0])
    v_filt = tk.StringVar(value="")
    v_crop = tk.StringVar(value="1.0")
    v_subsky, v_grax = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
    v_ps, v_spcc     = tk.BooleanVar(value=True),  tk.BooleanVar(value=True)
    v_post, v_del    = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
    v_batch, v_b2p   = tk.BooleanVar(value=False), tk.BooleanVar(value=True)

    row(0, "Teleskop / Reducer:",
        ttk.Combobox(frm, textvariable=v_tele, values=list(TELESCOPES), state="readonly"))
    row(1, "Kamera:",
        ttk.Combobox(frm, textvariable=v_cam, values=list(CAMERAS), state="readonly"))
    row(2, "Filter:",
        ttk.Combobox(frm, textvariable=v_filt, values=FILTERS))
    row(3, "Zusatz-Crop % je Rand:", ttk.Entry(frm, textvariable=v_crop, width=8))

    checks = [("Stapelmodus: alle Objektordner im Home verarbeiten", v_batch),
              ("Stapel-Ergebnisse gesammelt im Home (sonst je Objekt)", v_b2p),
              ("Hintergrund pro Sub (seqsubsky, pro Session)", v_subsky),
              ("GraXpert auf finalen Stack", v_grax),
              ("Plate-Solving", v_ps),
              ("SPCC-Farbkalibration", v_spcc),
              ("Postprocessing (BXT/NXT/StarX -> Stars+Starless)", v_post),
              ("Temp-Verzeichnis am Ende loeschen", v_del)]
    for i, (txt, var) in enumerate(checks, start=4):
        ttk.Checkbutton(frm, text=txt, variable=var).grid(
            row=i, column=0, columnspan=2, sticky="w", pady=2)

    status = ttk.Label(frm, text="Bereit. Home-Verzeichnis vorher in Siril setzen!")
    status.grid(row=13, column=0, columnspan=2, sticky="w", pady=(8, 4))

    btn = ttk.Button(frm, text="Start")
    btn.grid(row=14, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    frm.columnconfigure(1, weight=1)

    def start():
        cfg = dict(telescope=v_tele.get(), camera=v_cam.get(), filter=v_filt.get(),
                   crop_pct=v_crop.get(), subsky=v_subsky.get(), graxpert=v_grax.get(),
                   platesolve=v_ps.get(), spcc=v_spcc.get(), post=v_post.get(),
                   del_tmp=v_del.get(), batch=v_batch.get(),
                   batch_to_parent=v_b2p.get())
        btn.config(state="disabled")
        status.config(text="Laeuft... Fortschritt im Siril-Log.")

        def work():
            try:
                run_pipeline(siril, cfg)
                status.config(text="Fertig.")
            except Exception as e:
                status.config(text=f"FEHLER: {e}")
            finally:
                btn.config(state="normal")

        threading.Thread(target=work, daemon=True).start()

    btn.config(command=start)
    root.mainloop()


if __name__ == "__main__":
    main()
