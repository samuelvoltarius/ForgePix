"""Own mono restoration v2: richer simulations, observed scenes, fixed tiles.

Weights are trained here, not downloaded. Every colour channel is processed
independently by the same mono model. This avoids a colour-averaging shortcut.
Training quality and release qualification remain different questions.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
import torch
import torch.nn.functional as F
from training.vendor.nafnet_upstream import NAFNet

TASKS = ("denoise", "background", "deblur", "starless")

# Gemessene Vollskala-Spanne der echten Kameras. Faellt die Datei aus, bleibt der alte,
# willkuerliche Bereich — ein fehlender Messwert darf kein Training verhindern.
try:
    from . import sensoren as _sensoren
except ImportError:
    try:
        import sensoren as _sensoren
    except ImportError:
        _sensoren = None
_SENSOR_BEREICH = _sensoren.bereich() if _sensoren is not None else (250.0, 125000.0)
# Grundform. `--width` und `--channels` ueberschreiben sie; die Vorgabe bleibt, was bisher
# trainiert wurde, damit alte Laeufe reproduzierbar bleiben.
#
# Zum Groessenvergleich, an den ausgelieferten Dateien gemessen (07.09.2026): GraXperts
# Entrausch-Modell 3.0.2 ist 455,6 MB gross und dreikanalig, unseres 1,8 MB und einkanalig —
# Faktor 244. Als die Trainingsdaten von HST-Aufnahmen auf eigene Kameras umgestellt wurden,
# aenderte sich am Ergebnis nichts (Rauschen 0,77-fach gegen 0,75-fach). Das legt nahe, dass
# nicht die Daten die Grenze sind, sondern die Kapazitaet.
CONFIG = dict(img_channel=1, width=16, middle_blk_num=2,
              enc_blk_nums=[1, 1, 2], dec_blk_nums=[1, 1, 1])
CONTRACT = dict(channels=1, tile_size=256, halo=32,
                normalization="affine_percentile_v1", output="complete_target")


# Eigener Generator fuer das Ziehen aus der Bank im Hauptspeicher. Aus einem festen
# Startwert, damit ein Lauf wiederholbar bleibt.
_cpu_generator = torch.Generator().manual_seed(9241773)


def echte_paare(batch, device, generator, banken, channels):
    """Einen Stapel aus ECHTEN Paaren ziehen: eine Aufnahme gegen das Mittel der uebrigen.

    Der Unterschied zum synthetischen Weg ist nicht klein. Ein Modell, das nur gegen
    kuenstliches Rauschen trainiert, kann gelernt haben, genau dieses umzukehren — gemessen:
    ein Lauf meldete am synthetischen Pruefstand MSE-Faktor 73,4 und tat an einer echten
    Aufnahme nichts (1,05).

    Die Paare sind dreikanalig (Farbkameras). Fuer ein einkanaliges Modell wird EIN Kanal
    gezogen, nicht der Mittelwert: der Mittelwert haette weniger Rauschen als das, was das
    Modell spaeter zu sehen bekommt, und das Modell lernte eine zu leichte Aufgabe.
    """
    laut, rein = banken
    idx = torch.randint(len(laut), (batch,), generator=_cpu_generator)
    x = laut[idx].to(device, non_blocking=True)
    y = rein[idx].to(device, non_blocking=True)
    if x.ndim == 4 and x.shape[-1] == 3:                      # (N,H,W,3) -> (N,3,H,W)
        x = x.permute(0, 3, 1, 2).contiguous()
        y = y.permute(0, 3, 1, 2).contiguous()
    if channels == 1 and x.shape[1] == 3:
        k = torch.randint(3, (1,), generator=_cpu_generator).item()
        x, y = x[:, k:k+1], y[:, k:k+1]
    # Dieselben Spiegelungen wie im synthetischen Weg — sie kosten nichts und vervielfachen
    # die Vielfalt. Beide Seiten IDENTISCH spiegeln, sonst passt das Paar nicht mehr zusammen.
    if float(torch.rand(1, generator=_cpu_generator).item()) < .5:
        x, y = x.flip(-1), y.flip(-1)
    if float(torch.rand(1, generator=_cpu_generator).item()) < .5:
        x, y = x.transpose(-1, -2), y.transpose(-1, -2)
    return x, y


def sample(batch, device, generator, task, scene_bank=None):
    """Return physical signed mono input and target, plus diffuse target.

Includes Gaussian/Moffat elliptical stars, weak curved filaments, diffraction
spikes, Poisson/read/row/correlated noise, positive and negative gradients,
anisotropic blur and 15% identity cases. These are observing *simulations*,
not calibrated manufacturer camera profiles or real aberration ground truth.
"""
    size = 256
    def rand(*shape):
        return torch.rand(shape, device=device, generator=generator)
    def normal(shape):
        return torch.randn(shape, device=device, generator=generator)
    coord = torch.linspace(-1, 1, size, device=device)
    yy, xx = torch.meshgrid(coord, coord, indexing="ij")
    shape = (batch, 1, 1, 1)
    diffuse = ((rand(*shape) - .25) * .025).expand(batch, 1, size, size).clone()
    for _ in range(4):
        cx, cy = rand(*shape) * 2 - 1, rand(*shape) * 2 - 1
        sx, sy = rand(*shape) * .5 + .025, rand(*shape) * .4 + .035
        blob = torch.exp(-((xx-cx).square()/sx.square() + (yy-cy).square()/sy.square())/2)
        diffuse += blob * rand(*shape) * .12
    # Curved narrow filaments, so tiny features are not synonymous with stars.
    for _ in range(2):
        centre = torch.sin(xx * (rand(*shape) * 5 + 1) + rand(*shape) * 6) * .35
        centre += rand(*shape) * 1.4 - .7
        width = rand(*shape) * .025 + .006
        diffuse += torch.exp(-(yy-centre).square()/(2*width.square())) * rand(*shape) * .028
    stars = torch.zeros_like(diffuse)
    for index in range(28):
        cx, cy = rand(*shape) * 2 - 1, rand(*shape) * 2 - 1
        angle = rand(*shape) * math.pi
        dx, dy = xx-cx, yy-cy
        u, v = dx*angle.cos()+dy*angle.sin(), -dx*angle.sin()+dy*angle.cos()
        sx = (rand(*shape)*3.5+.65)*2/size
        sy = sx*(rand(*shape)*.6+.7)
        r2 = (u/sx).square()+(v/sy).square()
        gaussian = torch.exp(-r2/2)
        moffat = (1+r2/(rand(*shape)*2+1)).pow(-(rand(*shape)*2+2))
        amplitude = 10 ** (rand(*shape)*2.2-2.1)
        stars += (gaussian if index % 2 else moffat) * amplitude
        if index % 7 == 0:
            spike = torch.exp(-u.abs()/.08-v.abs()/.003)+torch.exp(-v.abs()/.08-u.abs()/.003)
            stars += spike * amplitude * .015
    clean = diffuse + stars
    if scene_bank is not None and task != "starless":
        # Die Bank liegt im Hauptspeicher (siehe `_bank`). Indizes darum auf der CPU ziehen
        # und nur den Stapel hinueberschieben — sonst scheitert die Indizierung daran, dass
        # Indizes und Daten auf verschiedenen Geraeten liegen.
        # `device` kommt als Text ("cuda"/"cpu"), nicht als torch.device — darum str().
        if scene_bank.device.type == "cpu" and str(device) != "cpu":
            indices = torch.randint(len(scene_bank), (batch,), generator=_cpu_generator)
            scenes = scene_bank[indices].to(device, non_blocking=True)
        else:
            indices = torch.randint(len(scene_bank), (batch,), device=device,
                                    generator=generator)
            scenes = scene_bank[indices]
        if float(rand(1).item()) < .5:
            scenes = scenes.flip(-1)
        if float(rand(1).item()) < .5:
            scenes = scenes.transpose(-1, -2)
        # JE KACHEL auf einen vergleichbaren Bereich bringen. Die Bank normiert je BILD mit
        # den 0,1/99,9-Perzentilen, und in einem Feld mit grossem Helligkeitsumfang (heller
        # Kern plus schwacher Hintergrund) landet der Kern dann weit ueber 1. An der grossen
        # Hubble-Bank gemessen: Werte bis 1036,8; 45 % der Kacheln haben ein Maximum ueber 2,
        # 17 % ueber 10, 1,1 % ueber 100.
        #
        # Auf so einer Kachel ist der quadratische Fehler millionenfach groesser als auf einer
        # normalen — diese wenigen bestimmen Verlust und Gradienten allein. Sichtbar daran,
        # dass width 128 und width 256 fast identische Verlustwerte lieferten (0,00520/0,01598/
        # 0,00505 gegen 0,00514/0,01596/0,00513): zwei verschieden grosse Modelle koennen das
        # nicht zufaellig, der Verlust kam von den Daten.
        #
        # Skaliert wird mit einem robusten Mass (99,9-Perzentil je Kachel), nicht mit dem
        # Maximum — ein einzelnes heisses Pixel soll die ganze Kachel nicht dunkel machen.
        # Kacheln werden dabei NICHT verworfen; die Auswahl bleibt unverzerrt.
        _flach = scenes.reshape(len(scenes), -1)
        _skala = torch.quantile(_flach.float(), 0.999, dim=1).clamp_min(1e-3)
        scenes = scenes / _skala.view(-1, 1, 1, 1)
        scenes = scenes * (rand(*shape)*.5+.05) + (rand(*shape)-.5)*.025
        use_real = rand(*shape) < .25
        clean = torch.where(use_real, scenes, clean)
    identity = rand(*shape) < .15
    if task == "background":
        gradient = xx*(rand(*shape)-.5)*.16 + yy*(rand(*shape)-.5)*.16
        gradient += (xx.square()+yy.square())*(rand(*shape)-.5)*.07
        glow = torch.exp(-((xx-(rand(*shape)*3-1.5)).square()+
                           (yy-(rand(*shape)*3-1.5)).square())/(rand(*shape)*.8+.1))
        gradient += glow*(rand(*shape)-.3)*.15
        inp, target = clean+gradient, clean
    elif task == "deblur":
        # Per-sample elliptical PSF with known, unit-sum flux normalization.
        axis = torch.arange(-6, 7, device=device)
        ky, kx = torch.meshgrid(axis, axis, indexing="ij")
        angle = rand(batch, 1, 1)*math.pi
        u, v = kx*angle.cos()+ky*angle.sin(), -kx*angle.sin()+ky*angle.cos()
        sx, sy = rand(batch, 1, 1)*1.6+.4, rand(batch, 1, 1)*1.6+.4
        kernel = torch.exp(-((u/sx).square()+(v/sy).square())/2)
        kernel = (kernel/kernel.sum((-2,-1),keepdim=True))[:,None]
        inp = F.conv2d(F.pad(clean.transpose(0,1),(6,6,6,6),mode="reflect"),
                       kernel,groups=batch).transpose(0,1)
        inp += normal(inp.shape)*(rand(*shape)*.002)
        target = clean
    elif task == "starless":
        inp, target = clean, diffuse
        # Identity cases have no stars; never label a stellar input as starless.
        return torch.where(identity, diffuse, inp), target
    else:
        # Vollskala in Elektronen aus den GEMESSENEN Kameras statt aus einem willkuerlichen
        # Bereich. Vorher: 10**(rand*2.7+2.4), also 250 bis 125000 Elektronen — Faktor 500,
        # ueber den ein Modell seine Kapazitaet verteilen muss. Gemessen liegen die drei
        # Kameras zwischen 5243 (Seestar S30) und 18415 (ASI533MC Pro); mit Streuung wird
        # daraus rund 2400 bis 40000, Faktor 17. Siehe training/sensoren.py fuer das
        # Messverfahren und warum ein erster Anlauf ohne Sockelabzug falsch war.
        _lo, _hi = _SENSOR_BEREICH
        electrons = 10 ** (rand(*shape)*(math.log10(_hi)-math.log10(_lo))+math.log10(_lo))
        sigma = 10 ** (rand(*shape)*1.6-3.5)
        shot = torch.poisson(clean.clamp_min(0)*electrons,generator=generator)/electrons
        inp = clean + shot-clean.clamp_min(0) + normal(clean.shape)*sigma
        white = normal(clean.shape)
        correlated = F.avg_pool2d(F.pad(white,(1,1,1,1),mode="reflect"),3,1)*3
        inp += correlated*sigma*.35 + normal((batch,1,size,1))*sigma*.1
        # Hotpixel. Gemessen: ASI294 0,0071 %, Seestar 0,031 %, ASI533 0,144 % — also ueber
        # zwei Groessenordnungen. Sie fehlten im Rauschmodell vollstaendig, und ein Modell,
        # das sie nie gesehen hat, laesst sie stehen oder verschmiert sie zu Flecken.
        _anteil = 10 ** (rand(*shape)*2.3-4.15)          # 0,007 % bis 1,4 %
        _treffer = (torch.rand(inp.shape, device=device, generator=generator) < _anteil).float()
        inp = inp + _treffer * (torch.rand(inp.shape, device=device, generator=generator)*.7+.05)
        target = clean
    return torch.where(identity, target, inp), target


def normalize(inp, target):
    limits = torch.quantile(inp.flatten(1), torch.tensor([.001,.999],device=inp.device),dim=1)
    offset = limits[0,:,None,None,None]
    scale = (limits[1]-limits[0]).clamp_min(1e-6)[:,None,None,None]
    return (inp-offset)/scale, (target-offset)/scale, offset, scale


def loss_function(prediction, target, robust=False):
    """Fehlermass. `robust=True` ersetzt den quadratischen Term durch Charbonnier.

    Warum es das gibt: der quadratische Fehler wird von den HELLSTEN Pixeln bestimmt. Bei
    Astro-Daten ist der Helligkeitsumfang riesig — synthetische Sterne laufen bis Amplitude
    1,26 und werden zwoelffach aufsummiert, und die Hubble-Szenenbank enthaelt Kacheln mit
    Werten bis 1036. Gemessen aeusserte sich das darin, dass zwei verschieden grosse Modelle
    (width 128 und 256) fast identische Verlustwerte lieferten: der Verlust kam von wenigen
    hellen Kacheln, nicht vom Modell.

    Charbonnier (Wurzel aus Fehler^2 + eps^2) verhaelt sich bei kleinen Fehlern wie der
    quadratische und bei grossen wie der absolute — die hellen Stellen zaehlen dann mit,
    dominieren aber nicht mehr.
    """
    error = prediction-target
    if robust:
        mse = (error.square() + 1e-6).sqrt().mean()
    else:
        mse = error.square().mean()
    # Edge preservation and local average flux constrain errors that global
    # MSE alone can hide. These losses are not a scientific quality certificate.
    edges = (error[:,:,:,1:]-error[:,:,:,:-1]).abs().mean()
    edges += (error[:,:,1:,:]-error[:,:,:-1,:]).abs().mean()
    flux = F.avg_pool2d(error,16,16).square().mean()
    bias = error.mean((-2,-1)).square().mean()
    return mse + .015*edges + .2*flux + .1*bias


@torch.no_grad()
def evaluate(model, task, device, bank=None, paare=None, channels=1):
    gen = torch.Generator(device=device).manual_seed(830122)
    measurements = []
    for _ in range(16):
        if paare is not None:
            inp, target = echte_paare(4, device, gen, paare, channels)
        else:
            inp,target = sample(4,device,gen,task,bank)
        x,y,offset,scale = normalize(inp,target)
        pred = model(x)*scale+offset
        measurements.append([float((pred-target).square().mean()),
                             float((inp-target).square().mean()),
                             float((pred-target).mean()),
                             float((pred-target).abs().mean())])
    return dict(zip(("output_mse","input_mse","mean_bias","mae"),
                    np.mean(measurements,axis=0).tolist()),samples=64)


def train(args):
    if args.steps < 1 or args.batch < 1:
        raise ValueError("Positive steps and batch required")
    args.output.mkdir(parents=True,exist_ok=False)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(4)
    torch.manual_seed(609061)
    gen = torch.Generator(device=device).manual_seed(609061)
    train_bank = val_bank = None
    scene_manifest = None
    # ECHTE Paare, falls verlangt. Sie werden in Trainings- und Pruefteil zerlegt, und zwar
    # NACH SERIE, nicht zufaellig: Kacheln derselben Serie zeigen dieselbe Stelle des Himmels,
    # und laegen sie auf beiden Seiten, wuerde die Pruefung auswendig Gelerntes belohnen.
    paare_train = paare_val = None
    if args.echte_paare:
        _laut = torch.from_numpy(np.load(Path(args.echte_paare) / "rauschig.npy"))
        _rein = torch.from_numpy(np.load(Path(args.echte_paare) / "sauber.npy"))
        if len(_laut) != len(_rein):
            raise SystemExit("rauschig.npy und sauber.npy haben verschiedene Laengen")
        _m = json.loads((Path(args.echte_paare) / "manifest.json").read_text(encoding="utf-8"))
        _je = [s_["genutzte_frames"] * s_["kacheln"] for s_ in _m["serien"]]
        _grenze, _summe = 0, 0
        for _n in _je:                       # die letzten Serien werden zur Pruefung
            if _summe >= 0.85 * len(_laut):
                break
            _summe += _n
            _grenze = _summe
        paare_train = (_laut[:_grenze], _rein[:_grenze])
        paare_val = (_laut[_grenze:], _rein[_grenze:])
        print("Echte Paare: %d zum Trainieren, %d zum Pruefen (nach Serie getrennt)"
              % (_grenze, len(_laut) - _grenze), flush=True)
    if args.scenes and args.task != "starless":
        scene_manifest = json.loads((args.scenes/"manifest.json").read_text())
        def _bank(name):
            """Kacheln laden und in (N, C, H, W) bringen.

            Eine Mono-Bank liegt als (N, H, W) vor und braucht eine Kanalachse; eine Farbbank
            als (N, H, W, 3) und muss umsortiert werden. Ohne diese Unterscheidung scheiterte
            der erste Farb-Lauf mit "weight of size [64, 3, 3, 3], expected input[1, 1, 256,
            256] to have 3 channels, but got 1 channels instead" — das Modell war dreikanalig,
            die Daten nicht.
            """
            a = torch.from_numpy(np.load(args.scenes/name))
            if a.ndim == 3:
                a = a[:, None]
            elif a.ndim == 4 and a.shape[-1] in (1, 3):
                a = a.permute(0, 3, 1, 2).contiguous()
            if a.shape[1] != args.channels:
                raise SystemExit(
                    "Die Szenenbank hat %d Kanal/Kanaele, --channels sagt %d. "
                    "Eine Farbbank baut `prepare_scenes_eigene.py --farbe`."
                    % (a.shape[1], args.channels))
            # NICHT `.to(device)`: die Bank ist 12,8 GB gross und wuerde neben dem Modell
            # liegen, obwohl je Schritt nur `batch` Kacheln gebraucht werden. Sie bleibt hier
            # und `sample` holt sich den Stapel.
            return a

        train_bank = _bank("train.npy")
        val_bank = _bank("validation.npy")
    config = dict(CONFIG, width=args.width, img_channel=args.channels,
                  middle_blk_num=args.bloecke)
    contract = dict(CONTRACT, channels=args.channels)
    model = NAFNet(**config).to(device)
    _par = sum(p.numel() for p in model.parameters())
    print(json.dumps({"modell": "NAFNet", "width": args.width, "channels": args.channels,
                      "bloecke": args.bloecke, "parameter": _par}), flush=True)
    # Exact identity initialization; an untrained model must not invent structure.
    torch.nn.init.zeros_(model.ending.weight)
    torch.nn.init.zeros_(model.ending.bias)
    # Lernrate einstellbar. 2e-4 war fuer width 16 (1,8 Mio Parameter) richtig; bei width 256
    # (107 Mio) und kleiner Stapelgroesse schlingert das Training: der Verlust sprang zwischen
    # 0,00016 und 0,0153 von Schritt zu Schritt, und die Pruefung fiel von Faktor 1,38 auf 0,86 —
    # das Modell machte das Bild schlechter als es hereinkam. Grosse Netze brauchen entweder
    # eine kleinere Lernrate oder groessere Stapel (weniger verrauschte Gradienten), am besten
    # beides.
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,args.steps,eta_min=2e-5)
    best, best_step = float("inf"),0
    start = time.perf_counter()
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with (args.output/"metrics.jsonl").open("w") as logfile:
        for step in range(1,args.steps+1):
            model.train()
            if paare_train is not None:
                inp, target = echte_paare(args.batch, device, gen, paare_train, args.channels)
            else:
                inp,target = sample(args.batch,device,gen,args.task,train_bank)
            x,y,_,_ = normalize(inp,target)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(x), y, robust=args.robuster_verlust)
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
            optimizer.step()
            scheduler.step()
            if step == 1 or step % 100 == 0:
                row = dict(step=step,loss=float(loss),seconds=time.perf_counter()-start)
                print(json.dumps(row),flush=True)
                logfile.write(json.dumps(row)+"\n"); logfile.flush()
            if step % args.validate_every == 0 or step == args.steps:
                model.eval()
                val = evaluate(model, args.task, device, val_bank, paare_val, args.channels)
                print(json.dumps(dict(step=step,validation=val)),flush=True)
                if val["output_mse"] < best:
                    best,best_step = val["output_mse"],step
                    torch.save(dict(model=model.state_dict(),config=config,contract=contract,
                        report=dict(task=args.task,step=step,validation=val,release_approved=False)),
                        args.output/"checkpoint.pt")
    checkpoint = torch.load(args.output/"checkpoint.pt",map_location=device,weights_only=False)
    report = dict(schema_version=1,task=args.task,status="experimental",
        release_approved=False,steps=args.steps,best_step=best_step,batch=args.batch,
        config=config,contract=contract,seed=609061,development_validation_seed=830122,
        seconds=time.perf_counter()-start,torch_version=str(torch.__version__),
        validation=checkpoint["report"]["validation"],training_source_sha256=source_hash,
        scene_counts=scene_manifest["counts"] if scene_manifest else {},
        trainingsdaten=("echte Rauschig/Sauber-Paare aus eigenen Aufnahmen"
                        if args.echte_paare else "synthetische Degradation auf Szenenkacheln"),
        echte_paare=(dict(quelle=str(args.echte_paare), train=len(paare_train[0]),
                          pruefung=len(paare_val[0])) if paare_train is not None else None),
        limitations=("Echte Paare: die saubere Seite ist der Mittelwert der uebrigen Aufnahmen "
                     "derselben Serie und hat Restrauschen (sqrt(N-1) geringer); Eingang und "
                     "Wahrheit teilen das feste Muster des Sensors. Keine Freigabe."
                     if args.echte_paare else
                     "Synthetic and added-degradation HST scene tests; no real independent clean/noisy pairs, held-out camera or astrophotometric release qualification"))
    (args.output/"report.json").write_text(json.dumps(report,indent=2))
    if scene_manifest:
        (args.output/"scene_manifest.json").write_text(json.dumps(scene_manifest,indent=2))
    print(json.dumps(report),flush=True)


if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--task",choices=TASKS,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--scenes",type=Path)
    ap.add_argument("--steps",type=int,default=4000)
    ap.add_argument("--batch",type=int,default=4)
    ap.add_argument("--validate-every",type=int,default=1000)
    ap.add_argument("--width",type=int,default=16,
                    help="Breite des Netzes. 16 ist die bisherige Groesse (~1,8 MB ONNX); "
                         "GraXperts Entrauscher ist 455 MB gross.")
    ap.add_argument("--channels",type=int,default=1,choices=(1,3),
                    help="1 = mono, jeder Farbkanal einzeln (bisher). 3 = farbig. Mono war "
                         "gewaehlt, damit das Netz nicht die Kanaele mitteln und so die Farbe "
                         "zerstoeren kann; GraXpert entrauscht dagegen dreikanalig.")
    ap.add_argument("--echte-paare", default=None, metavar="ORDNER",
                    help="Auf ECHTEN Rauschig/Sauber-Paaren trainieren statt auf kuenstlichem "
                         "Rauschen. Der Ordner kommt von `prepare_paare_echt.py` und enthaelt "
                         "rauschig.npy und sauber.npy. Schliesst --scenes aus.")
    ap.add_argument("--robuster-verlust", action="store_true",
                    help="Charbonnier statt quadratischem Fehler. Bei grossem Helligkeitsumfang "
                         "bestimmen sonst die hellsten Pixel das Training allein.")
    ap.add_argument("--lr", type=float, default=2e-4,
                    help="Lernrate (Vorgabe 2e-4; bei width>=128 eher 5e-5 bis 1e-4)")
    ap.add_argument("--bloecke",type=int,default=2,
                    help="Bloecke im mittleren Teil (Vorgabe 2).")
    options=ap.parse_args()
    if options.validate_every < 1:
        ap.error("validate-every must be positive")
    train(options)
