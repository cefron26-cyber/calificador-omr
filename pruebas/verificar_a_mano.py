#!/usr/bin/env python3
"""
verificar_a_mano.py — Prueba, sin abrir la app, dos cosas del flujo Calificar:

  1. Hoja que NO se pudo leer: queda lista para calificarla a mano (con su
     foto original y las respuestas en blanco) y, al ponerle código y
     respuestas, se guarda como una nota más ("calificada a mano").
  2. Fotos repetidas del mismo alumno: se queda la MEJOR LEÍDA (menos
     preguntas sin marcar y marcas tenues); si quedan iguales, la última.

Usa la lógica real de main.py (CalificarScreen y GaleriaHojas) con Kivy
simulado, en una carpeta temporal.   python pruebas/verificar_a_mano.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI))


# ── Kivy de mentira: lo justo para poder importar main.py sin pantalla ──────
class _Nada:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Nada()
    def __getattr__(self, n): return _Nada()
    def __iter__(self): return iter(())
    def __bool__(self): return False
    def __mul__(self, o): return 0
    __rmul__ = __add__ = __radd__ = __sub__ = __rsub__ = __truediv__ = __mul__


class _Meta(type):
    def __getattr__(cls, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return _Nada()


class _Clase(metaclass=_Meta):      # base para "class X(Button)" etc.
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Nada()
    def bind(self, *a, **k): pass


_CLASES: dict[str, type] = {}


class _Modulo(types.ModuleType):
    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        if n in ("dp", "sp"):
            return lambda v: v
        if n == "platform":
            return "win"
        if n in ("mainthread",):
            return lambda f: f
        if n[:1].isupper():   # una clase distinta por nombre (herencia múltiple)
            return _CLASES.setdefault(n, type(n, (_Clase,), {}))
        return _Nada()


class _Importador:
    def find_module(self, nombre, path=None):
        return self if nombre == "kivy" or nombre.startswith("kivy.") else None

    def find_spec(self, nombre, path, target=None):
        if nombre == "kivy" or nombre.startswith("kivy."):
            import importlib.util
            return importlib.util.spec_from_loader(nombre, self)
        return None

    def create_module(self, spec):
        m = _Modulo(spec.name)
        m.__path__ = []
        return m

    def exec_module(self, m):
        pass


sys.meta_path.insert(0, _Importador())

import main as M          # noqa: E402
import lector_omr as L    # noqa: E402

FALLAS = []


def comprobar(cond, texto):
    print(("OK    " if cond else "FALLA ") + texto)
    if not cond:
        FALLAS.append(texto)


def preparar_curso(tmp):
    curso = tmp / "profesores" / "Prueba" / "6" / "4"
    (curso / "examenes_crudos").mkdir(parents=True)
    (curso / "estudiantes").mkdir(parents=True)
    clave = {"examen": "Ingles", "total_preguntas": 30, "formato": "media_carta",
             "clave_correctas": list("BCDCDBCDDBCADBCBABACAABDCABADC")}
    ruta_json = curso / "Ingles.json"
    ruta_json.write_text(json.dumps(clave), encoding="utf-8")
    return curso, ruta_json


class _App:
    def __init__(self, curso):
        self.ruta_curso = curso


def pantalla(curso, ruta_json):
    M.App.get_running_app = staticmethod(lambda: _App(curso))
    p = M.CalificarScreen.__new__(M.CalificarScreen)
    p.examen = "Ingles"
    p.errores = []
    p._mapa_claves = {"Ingles": ruta_json}
    p.construir = lambda: None
    p._lista_codigos = lambda: {}          # sin lista del curso: cualquier código vale
    return p


def calificar(curso, ruta_json, origen, nombre):
    destino = curso / "examenes_crudos" / L.nombre_unico(nombre)
    shutil.copy(origen, destino)
    return L.calificar_foto(destino, ruta_json, curso)


def galeria(p, hojas):
    g = M.GaleriaHojas.__new__(M.GaleriaHojas)
    g.pantalla, g.hojas, g.modo, g.descartadas = p, list(hojas), "revisar", set()
    g._lista, g._carpeta = {}, p._ruta_notas().parent
    return g


def main():
    tmp = Path(tempfile.mkdtemp(prefix="omr_a_mano_"))
    try:
        curso, ruta_json = preparar_curso(tmp)
        p = pantalla(curso, ruta_json)
        clave = L.cargar_datos_examen(ruta_json).clave

        # ── 1. Hoja que no se puede leer → calificar a mano ──────────────────
        print("1. Hoja que no se pudo leer")
        import numpy as np
        ilegible = tmp / "borrosa.jpg"
        L.guardar_imagen(ilegible, np.full((900, 600, 3), 200, np.uint8))
        r = calificar(curso, ruta_json, ilegible, "borrosa.jpg")
        comprobar(r["codigo"] == "ERROR" and r.get("sin_leer"), "queda como 'sin leer'")
        comprobar(p._ruta_original(r) is not None, "guarda su foto original para mirarla")
        comprobar(len(r.get("respuestas") or {}) == 30
                  and not any(r["respuestas"].values()), "trae las 30 preguntas en blanco")
        g = galeria(p, [r])
        comprobar(g._estado(0) == "error" and not g._conservadas(),
                  "sin tocarla, no se guarda")
        # El docente pone las respuestas (mira la foto) …
        r["a_mano"] = True
        L.corregir_respuestas(r, {"1": "B", "2": "C", "3": "A"}, clave)
        comprobar(g._estado(0) == "falta_codigo", "con respuestas pero sin código: lo pide")
        # … y el código
        r["codigo"] = "015"
        comprobar(g._estado(0) == "ok" and g._conservadas() == [r],
                  "con código y respuestas: se puede guardar")
        p._guardar_registros(g._conservadas())
        guardada = [x for x in p._leer_notas() if x["codigo"] == "015"]
        comprobar(len(guardada) == 1 and guardada[0]["aciertos"] == 2
                  and guardada[0].get("a_mano") and "sin_leer" not in guardada[0]
                  and "error" not in guardada[0],
                  "se guarda como nota (2 aciertos, 'calificada a mano')")
        comprobar(M.CalificarScreen._estado_hoja(guardada[0], set(), {}) == "ok",
                  "en la lista sale como una hoja normal")

        # Desde la lista (historial): se guarda apenas está completa
        r2 = calificar(curso, ruta_json, ilegible, "borrosa2.jpg")
        p.errores = [r2]
        r2["codigo"] = "016"
        p._completar_a_mano(r2)
        comprobar(p.errores == [r2], "historial: solo con código aún no se guarda")
        r2["a_mano"] = True
        p._completar_a_mano(r2)
        comprobar(not p.errores and any(x["codigo"] == "016" for x in p._leer_notas()),
                  "historial: con código y respuestas se guarda")

        # ── 2. Fotos repetidas del mismo alumno ──────────────────────────────
        print("\n2. Fotos repetidas del mismo alumno")

        def hoja(archivo, codigo, blancos=0, tenues=0, fecha="2026-11-14T10:00:00"):
            resp = {str(q): ("B" if q > blancos else None) for q in range(1, 31)}
            reg = {"archivo": archivo, "codigo": codigo, "total": 30, "fecha": fecha,
                   "respuestas": resp, "aciertos": 0}
            if tenues:
                reg["alertas"] = {"tenues": list(range(10, 10 + tenues))}
            return reg

        # En la misma tanda: la buena primero y la peor después
        buena, peor = hoja("a.jpg", "020"), hoja("b.jpg", "020", blancos=3)
        g = galeria(p, [buena, peor])
        comprobar(g._estado(0) == "ok" and g._estado(1) == "tapada",
                  "misma tanda: se marca la peor (3 sin marcar) como tapada")
        p._guardar_registros([buena, peor])
        quedan = [x["archivo"] for x in p._leer_notas() if x["codigo"] == "020"]
        comprobar(quedan == ["a.jpg"], "misma tanda: se guarda la mejor aunque sea la primera")

        # Iguales: gana la última
        x1, x2 = hoja("c.jpg", "021", tenues=1), hoja("d.jpg", "021", tenues=1)
        g = galeria(p, [x1, x2])
        comprobar(g._estado(0) == "tapada_igual" and g._estado(1) == "ok",
                  "iguales: se marca la primera como tapada")
        p._guardar_registros([x1, x2])
        quedan = [x["archivo"] for x in p._leer_notas() if x["codigo"] == "021"]
        comprobar(quedan == ["d.jpg"], "iguales: se guarda la última")

        # Contra una ya guardada: una peor no la reemplaza; una mejor, sí
        con_tenues = hoja("e.jpg", "021", tenues=2)
        g = galeria(p, [con_tenues])
        comprobar(g._estado(0) == "queda_guardada",
                  "ya guardada y mejor leída: la nueva (2 tenues) no la reemplaza")
        p._guardar_registros([con_tenues])
        quedan = [x["archivo"] for x in p._leer_notas() if x["codigo"] == "021"]
        comprobar(quedan == ["d.jpg"], "… y al confirmar se conserva la guardada")
        limpia = hoja("f.jpg", "021")
        g = galeria(p, [limpia])
        comprobar(g._estado(0) == "reemplaza", "una nueva sin avisos sí la reemplaza")
        p._guardar_registros([limpia])
        quedan = [x["archivo"] for x in p._leer_notas() if x["codigo"] == "021"]
        comprobar(quedan == ["f.jpg"], "… y al confirmar queda la nueva")

        # Una hoja revisada a mano le gana a una lectura automática
        revisada = hoja("g.jpg", "022", blancos=5)
        revisada["respuestas_corregidas"] = [1]
        auto = hoja("h.jpg", "022")
        p._guardar_registros([revisada, auto])
        quedan = [x["archivo"] for x in p._leer_notas() if x["codigo"] == "022"]
        comprobar(quedan == ["g.jpg"], "la revisada a mano le gana a la automática")

        # Cuadrícula que no calzó: pierde contra una que sí
        corrida = hoja("i.jpg", "023")
        corrida["alertas"] = {"cuadricula": True}
        bien = hoja("j.jpg", "023", blancos=2)
        p._guardar_registros([bien, corrida])
        quedan = [x["archivo"] for x in p._leer_notas() if x["codigo"] == "023"]
        comprobar(quedan == ["j.jpg"], "la de cuadrícula dudosa pierde")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nTodo bien." if not FALLAS else f"\n{len(FALLAS)} falla(s).")
    return len(FALLAS)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
