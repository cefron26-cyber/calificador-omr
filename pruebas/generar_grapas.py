#!/usr/bin/env python3
"""
generar_grapas.py — Hojas de prueba con GRAPAS sobre las marcas de las esquinas.

Media hoja de 30 preguntas, con la clave del examen de 6.° (Claves_6th_1-30).
Simula lo que pasa con las hojas engrapadas: la grapa atraviesa la marca
superior-izquierda (o queda entre ella y la marca de orientación, o en otra
esquina) y antes el lector tomaba la marca de orientación como esquina: la
cuadrícula quedaba corrida una fila y las respuestas no calzaban.

Deja en pruebas/grapas/:
  • fotos/NN_*.jpg     10 fotos simuladas (mesa, perspectiva, luz, ruido)
  • hojas_grapas.pdf   las mismas hojas para imprimir (sin la grapa: se
                       engrapan a mano)
Las fotos reales que mandó el docente están en pruebas/grapas/reales/.
Luego:  python pruebas/verificar_grapas.py

Se ejecuta desde la carpeta del proyecto:  python pruebas/generar_grapas.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI))
import generador_pdf as G      # noqa: E402
import generar_pruebas as GP   # noqa: E402
import layout_hoja as LH       # noqa: E402

F = LH.MEDIA_CARTA
N_PREG = 30
CLAVE = "BCDCDBCDDBCADBCBABACAABDCABADC"   # Claves_6th_1-30.docx
OPC = "ABCD"
CARPETA = AQUI / "grapas"
ESC = 3.6                                  # px por punto al "imprimir"


def mal(q):
    return OPC[(OPC.index(CLAVE[q - 1]) + 1) % 4]


def respuestas(malas=(), blanco=(), tenues=()):
    r = {}
    for q in range(1, N_PREG + 1):
        if q in blanco:
            r[q] = None
        elif q in tenues:
            r[q] = ("tenue", CLAVE[q - 1])
        else:
            r[q] = mal(q) if q in malas else CLAVE[q - 1]
    return r


# Cada caso: grapas = [(esquina, x_cm, y_cm, ángulo°, largo_cm, tipo)], con
# (x_cm, y_cm) el centro de la grapa relativo al centro de la marca de esa
# esquina ("ti" = arriba-izq, "td" = arriba-der). tipo: "oscura" (sombra de
# la grapa) o "brillante" (el metal refleja: corta la marca con una línea clara).
CASOS = [
    dict(codigo="101", titulo="Grapa en diagonal sobre la marca de arriba a la izquierda",
         resp=respuestas(malas={3, 9, 14, 22, 27}),
         grapas=[("ti", 0.1, 0.0, -35, 1.3, "oscura")]),
    dict(codigo="102", titulo="Grapa horizontal sobre la marca, saliendo hacia el título",
         resp=respuestas(malas={1, 2, 3, 4, 5, 6, 7, 8, 9}),
         grapas=[("ti", 0.55, -0.05, -4, 1.4, "oscura")]),
    dict(codigo="103", titulo="Grapa entre la marca y el cuadrito de orientación",
         resp=respuestas(malas={11, 12, 13}),
         grapas=[("ti", 0.05, 0.42, -12, 1.2, "oscura")]),
    dict(codigo="104", titulo="Grapa brillante que parte la marca en dos",
         resp=respuestas(malas={30}),
         grapas=[("ti", 0.0, 0.0, 40, 1.2, "brillante")]),
    dict(codigo="105", titulo="Grapa y foto de lado (como las fotos reales)",
         resp=respuestas(malas={2, 4, 6, 8, 10, 12, 14}),
         grapas=[("ti", 0.15, -0.05, -25, 1.3, "oscura")], foto={"giro": 90}),
    dict(codigo="106", titulo="Grapa y foto de cabeza",
         resp=respuestas(malas={5, 15, 25}),
         grapas=[("ti", 0.0, 0.05, 30, 1.3, "oscura")], foto={"giro": 180}),
    dict(codigo="107", titulo="Grapa e impresora con poco tóner (marcas grises)",
         resp=respuestas(malas={7, 17, 27}),
         grapas=[("ti", 0.1, 0.0, -30, 1.3, "oscura")], toner=0.55),
    dict(codigo="108", titulo="Grapa con sombra fuerte y foto inclinada",
         resp=respuestas(malas={20, 21, 22, 23}),
         grapas=[("ti", 0.1, 0.05, -40, 1.3, "oscura")],
         foto={"sombra": True, "inclinada": True}),
    dict(codigo="109", titulo="Grapa en la esquina de arriba a la derecha",
         resp=respuestas(malas={1, 10, 19, 28}),
         grapas=[("td", -0.1, 0.0, 35, 1.3, "oscura")]),
    dict(codigo="110", titulo="Dos grapas, preguntas en blanco y marcas tenues",
         resp=respuestas(malas={16}, blanco={29, 30}, tenues={4, 18}),
         grapas=[("ti", 0.1, 0.0, -35, 1.3, "oscura"),
                 ("ti", 0.3, 0.75, -15, 1.2, "oscura")]),
]
for n, c in enumerate(CASOS, start=1):
    c.update(n=n, esquina_rota=False)
    c.setdefault("foto", {})


def aciertos_esperados(c):
    return sum(1 for q, v in c["resp"].items() if v is not None and
               (v if isinstance(v, str) else v[1]) == CLAVE[q - 1])


def _grapa(img, cx, cy, ang, largo, tipo, rng):
    """Dibuja una grapa (vista de arriba): barra metálica delgada con su
    sombra, y las dos patitas dobladas en los extremos."""
    px_cm = LH.CM * ESC
    L = largo * px_cm / 2
    grosor = max(3, int(0.075 * px_cm))
    a = math.radians(ang)
    ux, uy = math.cos(a), math.sin(a)
    p1 = (int(cx - L * ux), int(cy - L * uy))
    p2 = (int(cx + L * ux), int(cy + L * uy))
    sombra = (int(0.04 * px_cm), int(0.05 * px_cm))
    capa = img.copy()
    # Sombra (más ancha y difusa) y el metal
    cv2.line(capa, (p1[0] + sombra[0], p1[1] + sombra[1]),
             (p2[0] + sombra[0], p2[1] + sombra[1]), (60, 60, 60), grosor + 4, cv2.LINE_AA)
    img[:] = cv2.addWeighted(capa, 0.5, img, 0.5, 0)
    metal = (95, 95, 100) if tipo == "oscura" else (225, 225, 230)
    cv2.line(img, p1, p2, metal, grosor, cv2.LINE_AA)
    brillo = (170, 170, 175) if tipo == "oscura" else (250, 250, 252)
    cv2.line(img, p1, p2, brillo, max(1, grosor // 3), cv2.LINE_AA)
    # Patitas (se ven como dos rayitas cortas perpendiculares)
    for (x, y) in (p1, p2):
        q = (int(x - 0.12 * px_cm * uy), int(y + 0.12 * px_cm * ux))
        cv2.line(img, (x, y), q, metal, max(2, grosor - 1), cv2.LINE_AA)


def _engrapar(hoja, c, semilla):
    rng = np.random.default_rng(semilla)
    esq = dict(zip(("ti", "td", "bd", "bi"), F.esquinas()))
    for nombre, dx, dy, ang, largo, tipo in c["grapas"]:
        x, y = esq[nombre]
        cx = (x + dx * LH.CM) * ESC
        cy = (y + dy * LH.CM) * ESC
        _grapa(hoja, cx, cy, ang, largo, tipo, rng)
    return hoja


def generar():
    # generar_pruebas dibuja con sus globales: se ajustan a este examen
    GP.N_PREG, GP.CLAVE = N_PREG, CLAVE
    pdf = GP.PDFPrueba(LH.CARTA_W, LH.CARTA_H)
    logo = G._cargar_logo(pdf)
    for k, c in enumerate(CASOS):
        if k and k % 2 == 0:
            pdf.nueva_pagina()
        GP._dibujar_caso(pdf, c, (k % 2) * F.alto, logo)
    CARPETA.mkdir(exist_ok=True)
    (CARPETA / "hojas_grapas.pdf").write_bytes(pdf.to_bytes())

    fotos = CARPETA / "fotos"
    fotos.mkdir(exist_ok=True)
    paginas = pdf._paginas + [b"".join(pdf._ops)]
    logo_png = AQUI.parent / "assets" / "logo_pdf.png"
    alto = int(F.alto * ESC)
    for k, c in enumerate(CASOS):
        if k % 2 == 0:
            pagina = GP.rasterizar(paginas[k // 2], ESC, logo_png)
        hoja = pagina[(k % 2) * alto:(k % 2 + 1) * alto].copy()
        if c.get("toner"):
            # Poco tóner: todo lo impreso sale gris (el papel sigue blanco)
            hoja = (255 - (255 - hoja.astype(np.float32)) * c["toner"]).astype(np.uint8)
        hoja = _engrapar(hoja, c, 500 + k)
        foto = GP.fotografiar(hoja, c["foto"], semilla=300 + k)
        ruta = fotos / f"{GP.nombre_archivo(c)}.jpg"
        ok, buf = cv2.imencode(".jpg", foto, [cv2.IMWRITE_JPEG_QUALITY, 88])
        buf.tofile(str(ruta))
    print(f"{len(CASOS)} fotos con grapas en {fotos}")


if __name__ == "__main__":
    generar()
