#!/usr/bin/env python3
"""
testdaten_holen.py — die Testdaten für die Qualitätsprüfung holen (docs/TESTDATEN.md).

    python3 testdaten_holen.py            alles holen, was fehlt (rund 0,9 GB)
    python3 testdaten_holen.py --nur raw  nur einen Teil: raw, makro, langzeit, beispiele

Alles landet in testdata/ (steht in .gitignore, kommt nie ins Repository). Nur frei nutzbare
Quellen: raw.pixls.us (CC0), Wikimedia Commons (CC0), focus-stack (MIT), die eigenen
ForgePix-Beispieldaten. Vorhandene Dateien werden übersprungen. Nur Standardbibliothek.
"""
import argparse
import os
import sys
import urllib.request
import zipfile

HIER = os.path.dirname(os.path.abspath(__file__))
ZIEL = os.path.join(HIER, "testdata")
KENNUNG = {"User-Agent": "ForgePix-Testdaten/1.0 (https://github.com/samuelvoltarius/ForgePix)"}

RAW = [  # (Hersteller, Modell, Adresse) — raw.pixls.us, CC0
    ('Canon', 'EOS R5', 'https://raw.pixls.us/data/Canon/EOS%20R5/Canon_EOS_R5_CRAW_ISO_100_crop_nodual.CR3'),
    ('Canon', 'EOS 5D Mark III', 'https://raw.pixls.us/data/Canon/EOS%205D%20Mark%20III/5G4A9394.CR2'),
    ('Nikon', 'Z 6_2', 'https://raw.pixls.us/data/Nikon/Z%206_2/CZP_0302.NEF'),
    ('Sony', 'ILCE-7RM5', 'https://raw.pixls.us/data/Sony/ILCE-7RM5/7RM5-LosslessCompressedSmall.ARW'),
    ('Fujifilm', 'X-T4', 'https://raw.pixls.us/data/Fujifilm/X-T4/DSCF0268.RAF'),
    ('OM Digital Solutions', 'OM-5MarkII', 'https://raw.pixls.us/data/OM%20Digital%20Solutions/OM-5MarkII/OM_System_OM-5_2_hires_a.ORF'),
    ('Olympus', 'E-M1MarkIII', 'https://raw.pixls.us/data/Olympus/E-M1MarkIII/_3160529.ORF'),
    ('Panasonic', 'DC-G9', 'https://raw.pixls.us/data/Panasonic/DC-G9/P1000951.RW2'),
    ('Pentax', 'K-1 Mark II', 'https://raw.pixls.us/data/Pentax/K-1%20Mark%20II/_IMG2388.PEF'),
    ('Leica', 'Q2', 'https://raw.pixls.us/data/Leica/Q2/L1000750.DNG'),
    ('Hasselblad', 'X2D 100C', 'https://raw.pixls.us/data/Hasselblad/X2D%20100C/Job_0080.fff'),
    ('Phase One', 'IQ4 150MP', 'https://raw.pixls.us/data/Phase%20One/IQ4%20150MP/IQ4_150MP_L_14.iiq'),
    ('Sigma', 'fp', 'https://raw.pixls.us/data/Sigma/fp/A002_651_20240229_000001_2k_12bit.DNG'),
    ('Apple', 'iPhone 12 Pro', 'https://raw.pixls.us/data/Apple/iPhone%2012%20Pro/IMG_1361.DNG'),
    ('Google', 'Pixel 8 Pro', 'https://raw.pixls.us/data/Google/Pixel%208%20Pro/PXL_20240415_103400204.RAW-02.ORIGINAL.dng'),
    ('DJI', 'FC220', 'https://raw.pixls.us/data/DJI/FC220/DJI_0004.DNG'),
    ('GoPro', 'HERO5 Black', 'https://raw.pixls.us/data/GoPro/HERO5%20Black/GOPR0020.GPR'),
    ('Samsung', 'SM-G930F', 'https://raw.pixls.us/data/Samsung/SM-G930F/20200125_130015.dng'),
]
MAKRO = {  # focus-stack (MIT): Beispielreihen
    "focus-stack_pcb": "https://api.github.com/repos/PetteriAimonen/focus-stack/contents/examples/pcb",
    "focus-stack_depthmap": "https://api.github.com/repos/PetteriAimonen/focus-stack/contents/examples/depthmap",
}
LANGZEIT = [("Sahalie_Falls_during_Winter_jm1101.webm",
             "https://upload.wikimedia.org/wikipedia/commons/8/8b/Sahalie_Falls_during_Winter_jm1101.webm")]
BEISPIELE = "https://github.com/samuelvoltarius/ForgePix/releases/download/samples-v1/ForgePix-Samples.zip"


def laden(url, pfad):
    if os.path.exists(pfad) and os.path.getsize(pfad) > 10000:
        return False
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    teil = pfad + ".teil"
    with urllib.request.urlopen(urllib.request.Request(url, headers=KENNUNG), timeout=900) as r, open(teil, "wb") as fh:
        art = r.headers.get("Content-Type", "")
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            fh.write(block)
    if "html" in art.lower():
        os.remove(teil)
        raise RuntimeError("Statt einer Datei kam eine Webseite: %s" % url)
    os.replace(teil, pfad)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Testdaten für die Qualitätsprüfung holen (docs/TESTDATEN.md)")
    ap.add_argument("--nur", choices=["raw", "makro", "langzeit", "beispiele"])
    a = ap.parse_args(argv)
    fehler = []
    if a.nur in (None, "raw"):
        for hersteller, modell, url in RAW:
            name = modell.replace(" ", "_") + "__" + urllib.request.url2pathname(url.rsplit("/", 1)[1])
            try:
                neu = laden(url, os.path.join(ZIEL, "raw", hersteller.replace(" ", "_"), name))
                print("%-22s %-20s %s" % (hersteller, modell, "geladen" if neu else "schon da"))
            except Exception as e:
                fehler.append("%s %s: %s" % (hersteller, modell, e))
    if a.nur in (None, "makro"):
        import json
        for ordner, api in MAKRO.items():
            try:
                with urllib.request.urlopen(urllib.request.Request(api, headers=KENNUNG), timeout=60) as r:
                    for e in json.load(r):
                        if e["type"] == "file" and e["name"].lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
                            laden(e["download_url"], os.path.join(ZIEL, "makro", ordner, e["name"]))
                print("Makro", ordner, "ok")
            except Exception as e:
                fehler.append("Makro %s: %s" % (ordner, e))
    if a.nur in (None, "langzeit"):
        for name, url in LANGZEIT:
            try:
                laden(url, os.path.join(ZIEL, "langzeit", name)); print("Langzeit", name, "ok")
            except Exception as e:
                fehler.append("Langzeit %s: %s" % (name, e))
    if a.nur in (None, "beispiele"):
        zipdatei = os.path.join(ZIEL, "samples", "ForgePix-Samples.zip")
        try:
            laden(BEISPIELE, zipdatei)
            with zipfile.ZipFile(zipdatei) as z:
                z.extractall(os.path.join(ZIEL, "samples"))
            print("Beispieldaten ok")
        except Exception as e:
            fehler.append("Beispieldaten: %s" % e)
    for f in fehler:
        print("FEHLER:", f, file=sys.stderr)
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
