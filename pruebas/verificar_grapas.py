#!/usr/bin/env python3
"""
verificar_grapas.py — Califica las hojas engrapadas (las 10 simuladas y las
fotos reales) y comprueba, pregunta por pregunta, que la cuadrícula no quedó
corrida por la grapa.

Antes: python pruebas/generar_grapas.py      Luego: python pruebas/verificar_grapas.py
Deja las hojas marcadas en pruebas/grapas/resultado/.
"""
from __future__ import annotations

import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI))
import lector_omr as L        # noqa: E402
import generar_grapas as GG   # noqa: E402

CLAVE = {i + 1: v for i, v in enumerate(GG.CLAVE)}

# Fotos reales que mandó el docente (hojas de 6.°4, media hoja de 30). Lo
# esperado se revisó a ojo sobre cada hoja; las notas a mano del docente en
# las hojas 3 y 4 (21/30 y 25/30) coinciden.
REALES = {
    "1.jpg": ("012", "BDDCBABADACADBCBABACBCADCBBADC"),
    "2.jpg": ("022", "ACDCADBBCDDDABCCCABCACBCDABADC"),
    "3.jpg": ("???", "BCDCBACBDBCACBCBABACADCBBBBADC"),   # no rellenó el código
    "4.jpg": ("002", "BCDCDCCDDBCADBCAABACACBDABBADC"),
}


def leer(ruta):
    img = L.cargar_imagen(ruta)
    recta, scale, r = L.leer_foto(img, GG.N_PREG, GG.F.clave)
    return recta, scale, r


def comparar(nombre, codigo, esperadas, r, salida, recta, scale):
    leidas = "".join(r.respuestas[q] or "-" for q in range(1, GG.N_PREG + 1))
    aciertos = sum(1 for q, v in r.respuestas.items() if v and v == CLAVE[q])
    malas = [q for q in range(1, GG.N_PREG + 1) if leidas[q - 1] != esperadas[q - 1]]
    ok = not malas and r.codigo_estudiante == codigo
    anotada = L.dibujar_anotaciones(recta, r, CLAVE, scale, "Grapas", GG.F.clave)
    L.guardar_imagen(salida / f"{Path(nombre).stem}_calificada.jpg", anotada)
    print(f"{'OK   ' if ok else 'FALLA'} {nombre[:58]:58} código {r.codigo_estudiante}  "
          f"{aciertos:2d}/30  calce {r.calce:.2f}"
          + (f"\n      esperado código {codigo}; preguntas distintas: {malas}" if not ok else ""))
    return ok


def main():
    salida = GG.CARPETA / "resultado"
    salida.mkdir(parents=True, exist_ok=True)
    fallas = 0

    print("Hojas simuladas")
    for c in GG.CASOS:
        ruta = GG.CARPETA / "fotos" / f"{GG.GP.nombre_archivo(c)}.jpg"
        esperadas = "".join((v if isinstance(v, str) else v[1]) if v else "-"
                            for _, v in sorted(c["resp"].items()))
        try:
            recta, scale, r = leer(ruta)
        except ValueError as e:
            print(f"FALLA {ruta.name[:58]:58} no se leyó: {e}")
            fallas += 1
            continue
        fallas += not comparar(ruta.name, c["codigo"], esperadas, r, salida, recta, scale)

    print("\nFotos reales")
    for nombre, (codigo, esperadas) in REALES.items():
        ruta = GG.CARPETA / "reales" / nombre
        if not ruta.exists():
            continue
        try:
            recta, scale, r = leer(ruta)
        except ValueError as e:
            print(f"FALLA {nombre:58} no se leyó: {e}")
            fallas += 1
            continue
        fallas += not comparar(nombre, codigo, esperadas, r, salida, recta, scale)

    print("\nTodo bien." if not fallas else f"\n{fallas} hoja(s) con diferencias.")
    return fallas


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
