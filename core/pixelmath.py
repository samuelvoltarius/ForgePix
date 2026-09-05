"""Restricted, floating-point image expressions; never executes Python code."""
import ast
import operator
import numpy as np


_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow}
_COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
            ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}
_FUNCTIONS = {"abs": (np.abs, 1), "sqrt": (np.sqrt, 1), "log": (np.log, 1),
              "exp": (np.exp, 1), "min": (np.minimum, 2), "max": (np.maximum, 2),
              "clip": (np.clip, 3), "where": (np.where, 3)}


def evaluate(expression, images):
    """Evaluate an expression against equal-shaped named images.

    Outputs preserve values outside [0,1]. Inputs are never mutated. Names must
    be identifiers, for example Ha, OIII and SII. Functions are element-wise.
    Attribute access, indexing, imports and arbitrary calls are unsupported.
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
