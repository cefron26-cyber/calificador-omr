#!/usr/bin/env python3
"""
verificar_hoja_mayor.py — Comprueba el caso "examen con MENOS preguntas que la
hoja impresa" (p. ej. un examen de 25 en la hoja de 30 de la institución).

Crea hojas de 30 preguntas ya rellenas, las "fotografía" y las califica como
un examen de 25, en los dos formatos (media hoja y hoja completa):
  • las preguntas 26 a 30 NO cuentan para la nota;
  • si el estudiante marcó alguna, sale el aviso "marcó fuera del examen";
  • la lectura de las 25 primeras no cambia.

Se ejecuta desde la carpeta del proyecto:  python pruebas/verificar_hoja_mayor.py
(solo PC; no entra en el APK). Deja las hojas marcadas en pruebas/hoja_mayor/.
"""
from __future__ import annotations

import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI))
import layout_hoja as LH            # noqa: E402
import lector_omr as L              # noqa: E402
import generador_pdf as G           # noqa: E402
import generar_pruebas as GP        # noqa: E402

N_EXAMEN = 25
N_HOJA = 30
CLAVE = "ACBDBADCABCDDCBABDACBDACA"      # 25 respuestas correctas

# (código, título, incorrectas, en blanco, marcas fuera del examen {pregunta: letra})
CASOS = [
    ("001", "Todas correctas, 26-30 en blanco", set(), set(), {}),
    ("002", "20 correctas, 26-30 en blanco", {3, 8, 13, 18, 23}, set(), {}),
    ("003", "Marco tambien la 26 y la 27", {5, 25}, set(), {26: "A", 27: "C"}),
    ("004", "Relleno las 30 (5 de mas)", {1, 2}, set(),
     {26: "B", 27: "B", 28: "D", 29: "A", 30: "C"}),
    ("005", "Dejo la 25 en blanco y marco la 30", set(), {25}, {30: "D"}),
    ("006", "Foto de cabeza, marco la 28", {10, 20}, set(), {28: "A"}),
]
FOTO = {5: {"giro": 180}}       # ajustes de la foto por número de caso (0-based)


def _malo(q):
    return "ABCD"[("ABCD".index(CLAVE[q - 1]) + 1) % 4]


def _dibujar(pdf, f, y0, logo, caso):
    """La hoja real de la app (30 preguntas) + las marcas del estudiante."""
    codigo, _titulo, malas, blancas, extra = caso
    G._dibujar_hoja(pdf, f, y0, N_HOJA, logo)

    def Y(y):
        return pdf.H - (y0 + y)

    burb = {(col, dig): (x, Y(y)) for col, dig, x, y in f.burbujas_codigo()}
    for col, dig in enumerate(codigo):
        GP._marcar(pdf, *burb[(col, dig)], f.radio, "lleno")
    pos = {(q, o): (x, Y(y)) for q, o, x, y in f.burbujas_respuesta(N_HOJA)}
    for q in range(1, N_EXAMEN + 1):
        if q in blancas:
            continue
        GP._marcar(pdf, *pos[(q, _malo(q) if q in malas else CLAVE[q - 1])], f.radio, "lleno")
    for q, letra in extra.items():
        GP._marcar(pdf, *pos[(q, letra)], f.radio, "lleno")


def fotos_de(f, esc=3.6):
    """[(caso, foto)] de las hojas del formato f, ya 'fotografiadas'."""
    logo_png = AQUI.parent / "assets" / "logo_pdf.png"
    out = []
    for k, caso in enumerate(CASOS):
        pdf = GP.PDFPrueba(LH.CARTA_W, LH.CARTA_H)
        _dibujar(pdf, f, 0, G._cargar_logo(pdf), caso)
        pagina = GP.rasterizar(b"".join(pdf._ops), esc, logo_png)
        hoja = pagina[:int(f.alto * esc)]
        out.append((caso, GP.fotografiar(hoja, FOTO.get(k, {}), semilla=300 + k)))
    return out


def main():
    salida = AQUI / "hoja_mayor"
    salida.mkdir(exist_ok=True)
    clave = {i + 1: x for i, x in enumerate(CLAVE)}
    fallos = []
    for f in (LH.MEDIA_CARTA, LH.CARTA):
        print(f"\n{f.descripcion}: examen de {N_EXAMEN} en hoja de {N_HOJA}")
        for k, (caso, foto) in enumerate(fotos_de(f), start=1):
            codigo, titulo, malas, blancas, extra = caso
            foto = L._redimensionar_si_grande(foto)
            recta, scale, r = L.leer_foto(foto, N_EXAMEN, f.clave, N_HOJA)
            aciertos = sum(1 for p, x in r.respuestas.items() if x == clave.get(p))
            esperado = dict(codigo=codigo, aciertos=N_EXAMEN - len(malas) - len(blancas),
                            preguntas=N_EXAMEN, extra=sorted(extra), blanco=sorted(blancas))
            leido = dict(codigo=r.codigo_estudiante, aciertos=aciertos,
                         preguntas=len(r.respuestas), extra=sorted(r.marcas_extra),
                         blanco=sorted(r.en_blanco))
            ok = esperado == leido and not (r.doble_marca or r.dudosas or r.tenues)
            print(f"  {k:02d} {'OK ' if ok else 'MAL'} {codigo}  {aciertos:>2} de {N_EXAMEN}  "
                  f"nota {L._calcular_nota(aciertos, N_EXAMEN):.1f}  "
                  f"fuera del examen: {leido['extra'] or '-'}  ·  {titulo}")
            if not ok:
                fallos.append((f.clave, k, esperado, leido))
            anotada = L.dibujar_anotaciones(recta, r, clave, scale, "Prueba 25 en 30", f.clave)
            L.guardar_imagen(salida / f"{f.clave}_{k:02d}_calificada.jpg", anotada)
    if fallos:
        print("\nDIFERENCIAS:")
        for formato, k, esp, leido in fallos:
            print(f"  {formato} hoja {k:02d}\n    esperado: {esp}\n    leído:    {leido}")
    else:
        print(f"\nLas {2 * len(CASOS)} hojas se leen bien: las preguntas {N_EXAMEN + 1} a "
              f"{N_HOJA} no cuentan y se avisa cuando están marcadas.")
    return fallos


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
