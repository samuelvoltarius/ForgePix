"""Restricted, floating-point image expressions; never executes Python code."""
import ast
import operator
import numpy as np


_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow}
_COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
            ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}
def _kanal(bild, index):
    """Einen Farbkanal als eigenes Bild, in derselben Form wie die Eingabe.

    Das Ergebnis behaelt drei Kanaele (alle gleich), damit sich Kanal- und Vollbildausdruecke
    frei mischen lassen: `rot(A) - blau(A)` und `A * 2` haben dieselbe Form. Ein Graubild
    kommt unveraendert zurueck.
    """
    a = np.asarray(bild)
    if a.ndim != 3 or a.shape[2] != 3:
        return a
    ebene = a[..., index]
    return np.repeat(ebene[..., None], 3, axis=2)


def _mische(b, g, r):
    """Drei Kanalbilder wieder zu einem Farbbild zusammensetzen (BGR-Reihenfolge)."""
    def eben(x, i):
        a = np.asarray(x)
        return a[..., i] if a.ndim == 3 and a.shape[2] == 3 else a
    return np.stack([eben(b, 0), eben(g, 1), eben(r, 2)], axis=-1)


# Kanalzugriff ueber FUNKTIONEN statt ueber Indizes: `A[..., 0]` wuerde Indexierung im Ausdruck
# erlauben, und die bleibt bewusst gesperrt (sie ist der uebliche Weg, aus so einem Rechner
# auszubrechen). `blau(A)` leistet dasselbe und ist ausserdem lesbar.
#
# Warum es das ueberhaupt braucht: kanalweise Arbeit ist in der Astrofotografie der Normalfall
# — Gruenstich daempfen, Ha nach Rot legen, OIII auf Blau und Gruen aufteilen. Ohne Kanalzugriff
# konnte der Rechner nur ganze Bilder skalieren und war damit fuer den haeufigsten Zweck blind.
_FUNCTIONS = {"abs": (np.abs, 1), "sqrt": (np.sqrt, 1), "log": (np.log, 1),
              "exp": (np.exp, 1), "min": (np.minimum, 2), "max": (np.maximum, 2),
              "clip": (np.clip, 3), "where": (np.where, 3),
              "blau": (lambda x: _kanal(x, 0), 1),
              "gruen": (lambda x: _kanal(x, 1), 1),
              "rot": (lambda x: _kanal(x, 2), 1),
              "blue": (lambda x: _kanal(x, 0), 1),
              "green": (lambda x: _kanal(x, 1), 1),
              "red": (lambda x: _kanal(x, 2), 1),
              "grau": (lambda x: np.repeat(np.asarray(x).mean(axis=2)[..., None], 3, axis=2)
                       if np.asarray(x).ndim == 3 else np.asarray(x), 1),
              "rgb": (lambda b, g, r: _mische(b, g, r), 3)}


def evaluate(expression, images):
    """Evaluate an expression against equal-shaped named images.

    Outputs preserve values outside [0,1]. Inputs are never mutated. Names must
    be identifiers, for example Ha, OIII and SII. Functions are element-wise.
    Attribute access, indexing, imports and arbitrary calls are unsupported.

    Farbkanaele ueber `blau(A)`, `gruen(A)`, `rot(A)` (englisch ebenso), zusammensetzen mit
    `rgb(b, g, r)`, Helligkeit mit `grau(A)`. Beispiele:
        gruen(A) * 0.9                      Gruenstich daempfen
        rgb(OIII, OIII, Ha)                 HOO von Hand
        A - max(gruen(A) - max(rot(A), blau(A)), 0)   SCNR-artig
    """
    if not isinstance(expression, str) or len(expression) > 4096:
        raise ValueError("Die Bildformel fehlt oder ist zu lang.")
    if not images:
        raise ValueError("Bitte mindestens ein Bild für die Formel auswählen.")
    arrays = {}
    shape = None
    for name, value in images.items():
        if not isinstance(name, str) or not name.isidentifier() or name in _FUNCTIONS:
            raise ValueError("Ungültiger oder reservierter Bildname.")
        array = np.asarray(value, dtype=np.float32)
        if array.ndim not in (2, 3) or array.size == 0 or not np.isfinite(array).all():
            raise ValueError("Die Bilder müssen gültige, endliche Pixelwerte enthalten.")
        shape = array.shape if shape is None else shape
        if array.shape != shape:
            raise ValueError("Alle Bilder müssen dieselbe Größe und Kanalzahl haben.")
        arrays[name] = array
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("Die Bildformel ist nicht gültig.") from exc
    if sum(1 for _ in ast.walk(tree)) > 128:
        raise ValueError("Die Bildformel ist zu komplex.")

    def visit(node):
        if isinstance(node, ast.Name) and node.id in arrays:
            return arrays[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (float, int):
            return np.float64(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return _BINARY[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE:
            return _COMPARE[type(node.ops[0])](visit(node.left), visit(node.comparators[0]))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = _FUNCTIONS.get(node.func.id)
            if function and len(node.args) == function[1] and not node.keywords:
                return function[0](*(visit(arg) for arg in node.args))
        raise ValueError("Unbekannter Bildname oder nicht erlaubte Rechenoperation.")

    try:
        with np.errstate(all="raise"):
            result = np.asarray(visit(tree.body), dtype=np.float32)
    except (FloatingPointError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError("Die Formel erzeugt ungültige Werte, etwa durch Division durch null.") from exc
    if not np.isfinite(result).all():
        raise ValueError("Die Formel erzeugt ungültige Pixelwerte.")
    return np.broadcast_to(result, shape).copy()
