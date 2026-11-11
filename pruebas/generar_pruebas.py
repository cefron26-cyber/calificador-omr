#!/usr/bin/env python3
"""
generar_pruebas.py — Crea las 20 hojas de prueba (media hoja, 20 preguntas).

Deja en esta carpeta:
  • hojas_para_imprimir.pdf      10 páginas carta = 20 medias hojas ya rellenas
  • fotos/NN_*.jpg               cada media hoja "fotografiada" (para cargar
                                 desde la galería sin imprimir nada)
  • lista_estudiantes_prueba.xlsx  lista del curso para importar (16 alumnos)
  • resultado_esperado/          lo que la app debe mostrar (imagen marcada)
  • resultados_esperados.xlsx    nota, alertas y mensajes esperados de cada hoja

Se ejecuta desde la carpeta del proyecto:  python pruebas/generar_pruebas.py
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
import generador_pdf as G      # noqa: E402
import layout_hoja as LH       # noqa: E402

F = LH.MEDIA_CARTA
N_PREG = 20
CLAVE = "ACBDBADCABCDDCBABDAC"           # respuestas correctas de la 1 a la 20
OPC = "ABCD"
NOMBRES = ["Ana María Pérez", "Bruno Díaz Ríos", "Carla Núñez Soto", "Daniel Ortiz Vega",
           "Elena Ruiz Mora", "Felipe Gómez Lara", "Gabriela Peña Cruz", "Héctor Mejía Rojas",
           "Isabel Castro León", "Julián Herrera Paz", "Karen Salazar Gil", "Luis Fernando Arias",
           "Mariana Torres Vélez", "Nicolás Restrepo Cano", "Olga Lucía Prieto", "Pablo Andrés Duque"]


def mal(q):
    """Una respuesta INCORRECTA para la pregunta q (la siguiente letra)."""
    return OPC[(OPC.index(CLAVE[q - 1]) + 1) % 4]


def bien(q):
    return CLAVE[q - 1]


# ─────────────────────────────────────────────────────────────────────────────
# Las 20 situaciones. resp[q] = una de:
#   "A".."D"            relleno normal          None        en blanco
#   ("doble", x, y)     dos burbujas rellenas   ("tenue", x) relleno muy claro
#   ("x", x)            una equis encima        ("medio", x) medio círculo relleno
#   ("dos_medios", x, y) dos burbujas a medio rellenar (borrón / duda)
# codigo: "001" | None (sin código) | ("doble_ultimo", "00", "0", "4")
# foto: ajustes de la foto simulada
# ─────────────────────────────────────────────────────────────────────────────
def todas(f=bien):
    return {q: f(q) for q in range(1, N_PREG + 1)}


def con_malas(malas):
    return {q: (mal(q) if q in malas else bien(q)) for q in range(1, N_PREG + 1)}


def solo_buenas(buenas):
    return {q: (bien(q) if q in buenas else mal(q)) for q in range(1, N_PREG + 1)}


CASOS = []


def caso(codigo, titulo, resp, foto=None, esquina_rota=False):
    CASOS.append(dict(n=len(CASOS) + 1, codigo=codigo, titulo=titulo, resp=resp,
                      foto=foto or {}, esquina_rota=esquina_rota))


caso("001", "Todas correctas", todas())
caso("002", "15 correctas y 5 incorrectas", con_malas({3, 7, 11, 15, 19}))
caso("003", "Justo en el límite: 12 correctas", con_malas({1, 2, 5, 9, 13, 14, 17, 20}))
caso("004", "Reprueba por poco: 11 correctas", con_malas({2, 4, 6, 8, 10, 12, 14, 16, 18}))
caso("005", "Solo 7 correctas", solo_buenas({1, 4, 7, 10, 13, 16, 19}))
caso("006", "Todas incorrectas (piso de nota 1.0)", todas(mal))
r = todas(); r.update({17: None, 18: None, 19: None, 20: None})
caso("007", "Dejó en blanco las preguntas 17 a 20", r)
r = todas(); r.update({3: ("doble", bien(3), mal(3)), 9: ("doble", bien(9), mal(9))})
caso("008", "Doble marca en las preguntas 3 y 9", r)
r = todas(); r.update({q: ("tenue", bien(q)) for q in (2, 5, 8, 11, 14)})
caso("009", "Relleno muy claro (lápiz suave) en 2, 5, 8, 11 y 14", r)
r = todas(); r.update({q: ("x", bien(q)) for q in (4, 12, 18)})
caso("010", "Marcó con equis (X) en 4, 12 y 18", r)
r = todas(); r.update({6: ("medio", bien(6)), 15: ("medio", bien(15)),
                       10: ("dos_medios", bien(10), mal(10)), 20: ("dos_medios", bien(20), mal(20))})
caso("011", "Medio relleno en 6 y 15; dos burbujas a medias en 10 y 20", r)
caso(None, "No rellenó el código del estudiante", con_malas({3, 6, 9, 12, 15, 18}))
caso(("doble_ultimo", "00", "0", "4"), "Código con doble marca en el último dígito",
     con_malas({5, 10, 15, 20}))
caso("099", "Código que no está en la lista del curso", solo_buenas(set(range(1, 11))))
caso("001", "Segunda hoja del alumno 001 (repetida)", con_malas({2, 5, 8, 11, 14, 17, 20}))
caso("012", "Foto de cabeza (girada 180°)", con_malas({1, 8, 16}), foto={"giro": 180})
caso("013", "Foto de lado (girada 90°)", con_malas({11}), foto={"giro": 90})
caso("014", "Sombra fuerte y foto inclinada", con_malas({2, 6, 10, 14, 18}),
     foto={"sombra": True, "inclinada": True})
caso("015", "Esquina rota: falta la marca de abajo a la derecha", todas(), esquina_rota=True)
caso("016", "Entregó la hoja en blanco (solo el código)", {q: None for q in range(1, N_PREG + 1)})


# ─────────────────────────────────────────────────────────────────────────────
# PDF: la hoja real de la app + las marcas del "estudiante"
# ─────────────────────────────────────────────────────────────────────────────
class PDFPrueba(G._PDF):
    def poligono(self, pts, rellenar=True):
        p = pts[0]
        self._ops.append(b"%.2f %.2f m\n" % p)
        for x, y in pts[1:]:
            self._ops.append(b"%.2f %.2f l\n" % (x, y))
        self._ops.append(b"h f\n" if rellenar else b"h S\n")


def _circulo_pts(cx, cy, r, a0=0.0, a1=2 * math.pi, n=36):
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n))
            for k in range(n + 1)]


LAPIZ = 0.13      # gris del relleno normal (grafito)
TENUE = 0.83      # relleno muy claro: entre el 80 % y el 85 % del brillo del papel


def _marcar(pdf, x, y, r, tipo):
    """Dibuja una marca del estudiante en la burbuja (x, y en coords del PDF)."""
    if tipo == "lleno":
        pdf.color_relleno(LAPIZ, LAPIZ, LAPIZ)
        pdf.poligono(_circulo_pts(x, y, r * 0.92))
    elif tipo == "tenue":
        pdf.color_relleno(TENUE, TENUE, TENUE)
        pdf.poligono(_circulo_pts(x, y, r * 0.95))
    elif tipo == "medio":          # mitad izquierda (≈ 55 % de la burbuja)
        pdf.color_relleno(LAPIZ, LAPIZ, LAPIZ)
        pdf.poligono([(x + r * 0.15, y)] + _circulo_pts(x, y, r * 0.92, math.pi / 2,
                                                         3 * math.pi / 2) + [(x + r * 0.15, y)])
    elif tipo == "x":
        pdf.color_linea(LAPIZ, LAPIZ, LAPIZ)
        pdf.grosor_linea(1.1)
        d = r * 0.85
        pdf.linea(x - d, y - d, x + d, y + d)
        pdf.linea(x - d, y + d, x + d, y - d)


def _dibujar_caso(pdf, c, y0, logo):
    G._dibujar_hoja(pdf, F, y0, N_PREG, logo)

    def Y(y):
        return pdf.H - (y0 + y)

    # Nombre "escrito" en la hoja (para reconocerla al imprimir)
    cod = c["codigo"]
    alumno = (NOMBRES[int(cod) - 1] if isinstance(cod, str) and cod.isdigit()
              and 1 <= int(cod) <= len(NOMBRES) else "—")
    pdf.texto(F.x_texto + 3.9 * LH.CM, Y(F.y_nombre) + 1.5, f"PRUEBA {c['n']:02d}  ·  {alumno}",
              10, bold=True, color=(0.1, 0.25, 0.6))

    # Código
    burb = {(col, dig): (x, Y(y)) for col, dig, x, y in F.burbujas_codigo()}
    if isinstance(cod, str):
        for col, dig in enumerate(cod):
            _marcar(pdf, *burb[(col, dig)], F.radio, "lleno")
    elif isinstance(cod, tuple):            # ("doble_ultimo", "00", "0", "4")
        _, pref, d1, d2 = cod
        for col, dig in enumerate(pref):
            _marcar(pdf, *burb[(col, dig)], F.radio, "lleno")
        for dig in (d1, d2):
            _marcar(pdf, *burb[(len(pref), dig)], F.radio, "lleno")

    # Respuestas
    pos = {(q, o): (x, Y(y)) for q, o, x, y in F.burbujas_respuesta(N_PREG)}
    for q, v in c["resp"].items():
        if v is None:
            continue
        if isinstance(v, str):
            _marcar(pdf, *pos[(q, v)], F.radio, "lleno")
        elif v[0] == "doble":
            for o in v[1:]:
                _marcar(pdf, *pos[(q, o)], F.radio, "lleno")
        elif v[0] in ("tenue", "x", "medio"):
            _marcar(pdf, *pos[(q, v[1])], F.radio, v[0])
        elif v[0] == "dos_medios":
            for o in v[1:]:
                _marcar(pdf, *pos[(q, o)], F.radio, "medio")

    # Esquina rota: se "arranca" la esquina inferior derecha (con su marca)
    if c["esquina_rota"]:
        pdf.color_relleno(1, 1, 1)
        lado = F.margen_marca + F.tam_marca + 0.5 * LH.CM
        pdf.poligono([(F.ancho, Y(F.alto)), (F.ancho - lado * 1.6, Y(F.alto)),
                      (F.ancho - lado * 0.4, Y(F.alto - lado * 0.8)),
                      (F.ancho, Y(F.alto - lado * 1.5))])


def generar_pdf(salida):
    pdf = PDFPrueba(LH.CARTA_W, LH.CARTA_H)
    logo = G._cargar_logo(pdf)
    for k, c in enumerate(CASOS):
        if k and k % 2 == 0:
            pdf.nueva_pagina()
        _dibujar_caso(pdf, c, (k % 2) * F.alto, logo)
        if k % 2 == 1:      # línea de corte
            pdf.color_linea(0.55, 0.55, 0.55)
            pdf.grosor_linea(0.6)
            pdf.punteado(4, 3)
            pdf.linea(0.5 * LH.CM, pdf.H - F.alto, pdf.W - 0.5 * LH.CM, pdf.H - F.alto)
            pdf.punteado()
    Path(salida).write_bytes(pdf.to_bytes())
    return pdf


# ─────────────────────────────────────────────────────────────────────────────
# "Imprimir" una media hoja como imagen (interpreta el contenido del PDF)
# ─────────────────────────────────────────────────────────────────────────────
_TOKEN = re.compile(rb"\((?:\\.|[^\\)])*\)|/[A-Za-z0-9]+|\[[^\]]*\]|-?\d+\.?\d*|[A-Za-z]+")


def _cadena(tok):
    s = tok[1:-1]
    s = re.sub(rb"\\(.)", rb"\1", s)
    return s.decode("cp1252")


def rasterizar(contenido, esc, logo_png):
    """Dibuja con Pillow los operadores que escribe generador_pdf (rellenos,
    líneas, círculos Bézier, polígonos, textos y el logo)."""
    W, H = int(LH.CARTA_W * esc), int(LH.CARTA_H * esc)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    P = lambda x, y: (x * esc, (LH.CARTA_H - y) * esc)
    fuentes = {}

    def fuente(bold, size):
        k = (bold, max(1, round(size * esc)))
        if k not in fuentes:
            fuentes[k] = ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", k[1])
        return fuentes[k]

    rel, lin, ancho = (0, 0, 0), (0, 0, 0), 1.0
    sub, camino, pila = [], [], []
    fuente_act, matriz, logo = (False, 10), None, Image.open(logo_png).convert("RGB")
    col = lambda v: tuple(int(round(float(c) * 255)) for c in v)
    for tok in _TOKEN.findall(contenido):
        if tok[:1] in b"(/[" or re.match(rb"-?\d", tok):
            pila.append(tok)
            continue
        op, a = tok.decode(), pila
        if op == "rg":
            rel = col(a[-3:])
        elif op == "RG":
            lin = col(a[-3:])
        elif op == "w":
            ancho = float(a[-1])
        elif op == "re":
            x, y, w, h = map(float, a[-4:])
            camino.append([P(x, y), P(x + w, y), P(x + w, y + h), P(x, y + h), P(x, y)])
        elif op == "m":
            sub = [P(float(a[-2]), float(a[-1]))]
            camino.append(sub)
        elif op == "l":
            sub.append(P(float(a[-2]), float(a[-1])))
        elif op == "c":
            x0, y0 = sub[-1]
            c1, c2, p3 = (P(float(a[-6 + 2 * i]), float(a[-5 + 2 * i])) for i in range(3))
            for k in range(1, 9):
                t = k / 8
                sub.append(tuple((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * q1 + 3 * (1 - t) * t ** 2 * q2
                                 + t ** 3 * q3 for p0, q1, q2, q3 in zip((x0, y0), c1, c2, p3)))
        elif op in ("f", "B", "S"):
            for s in camino:
                if op in ("f", "B") and len(s) > 2:
                    d.polygon(s, fill=rel)
                if op in ("S", "B"):
                    d.line(s, fill=lin, width=max(1, round(ancho * esc)), joint="curve")
            camino = []
        elif op == "Tf":
            fuente_act = (a[-2] == b"/F2", float(a[-1]))
        elif op == "Td":
            pos = P(float(a[-2]), float(a[-1]))
        elif op == "Tj":
            d.text(pos, _cadena(a[-1]), font=fuente(*fuente_act), fill=rel, anchor="ls")
        elif op == "cm":
            matriz = list(map(float, a[-6:]))
        elif op == "Do" and matriz:
            w, _, _, h, x, y = matriz
            img.paste(logo.resize((max(1, int(w * esc)), max(1, int(h * esc)))),
                      tuple(int(v) for v in P(x, y + h)))
        pila = []
    return np.array(img)[:, :, ::-1].copy()


# ─────────────────────────────────────────────────────────────────────────────
# "Fotografiar": hoja sobre una mesa, con perspectiva, luz y ruido de cámara
# ─────────────────────────────────────────────────────────────────────────────
def fotografiar(hoja, ajustes, semilla):
    rng = np.random.default_rng(semilla)
    h, w = hoja.shape[:2]
    W, H = int(w * 1.22), int(h * 1.32)
    # Mesa: madera gris-café con veta suave
    veta = (np.sin(np.linspace(0, 40, W))[None, :] * 9 + rng.normal(0, 6, (H, W))).astype(np.float32)
    mesa = np.dstack([np.full((H, W), v, np.float32) + veta for v in (88, 104, 122)])
    # Perspectiva: esquinas de la hoja algo corridas
    m = 0.07 if ajustes.get("inclinada") else 0.025
    dx, dy = (W - w) / 2, (H - h) / 2
    dst = np.float32([[dx, dy], [dx + w, dy], [dx + w, dy + h], [dx, dy + h]])
    dst += rng.uniform(-m, m, (4, 2)).astype(np.float32) * np.float32([w, h])
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), dst)
    papel = cv2.warpPerspective(hoja.astype(np.float32) * 0.93, M, (W, H),
                                flags=cv2.INTER_AREA, borderValue=(0, 0, 0))
    mascara = cv2.warpPerspective(np.ones((h, w), np.float32), M, (W, H), flags=cv2.INTER_AREA)
    foto = mesa * (1 - mascara[..., None]) + papel * mascara[..., None]
    # Luz despareja (y sombra fuerte si se pide)
    xx = np.linspace(0, 1, W)[None, :]
    yy = np.linspace(0, 1, H)[:, None]
    luz = 1.0 - 0.10 * xx - 0.06 * yy
    if ajustes.get("sombra"):
        luz = luz * np.where(xx + 0.35 * yy < 0.55, 0.58, 1.0)
        luz = cv2.GaussianBlur(luz.astype(np.float32), (0, 0), W / 60)
    foto = foto * luz[..., None]
    foto = cv2.GaussianBlur(foto, (0, 0), 1.1) + rng.normal(0, 3.0, foto.shape)
    foto = np.clip(foto, 0, 255).astype(np.uint8)
    giro = ajustes.get("giro")
    if giro == 180:
        foto = cv2.rotate(foto, cv2.ROTATE_180)
    elif giro == 90:
        foto = cv2.rotate(foto, cv2.ROTATE_90_CLOCKWISE)
    return foto


def nombre_archivo(c):
    base = re.sub(r"[^a-z0-9]+", "_", c["titulo"].lower()
                  .translate(str.maketrans("áéíóúñ°", "aeioun "))).strip("_")
    return f"{c['n']:02d}_{base[:48]}"


def generar_fotos(pdf, carpeta, esc=3.6):
    carpeta.mkdir(exist_ok=True)
    paginas = pdf._paginas + [b"".join(pdf._ops)]
    logo_png = AQUI.parent / "assets" / "logo_pdf.png"
    rutas = []
    for k, c in enumerate(CASOS):
        if k % 2 == 0:
            pagina = rasterizar(paginas[k // 2], esc, logo_png)
        alto = int(F.alto * esc)
        hoja = pagina[(k % 2) * alto:(k % 2 + 1) * alto]
        foto = fotografiar(hoja, c["foto"], semilla=100 + k)
        ruta = carpeta / f"{nombre_archivo(c)}.jpg"
        ok, buf = cv2.imencode(".jpg", foto, [cv2.IMWRITE_JPEG_QUALITY, 90])
        buf.tofile(str(ruta))
        rutas.append(ruta)
    return rutas


def generar_lista(salida):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Estudiantes"
    ws.append(["N°", "Nombre"])
    for i, n in enumerate(NOMBRES, start=1):
        ws.append([i, n])
    ws["A1"].font = ws["B1"].font = Font(bold=True)
    ws.column_dimensions["B"].width = 30
    wb.save(salida)


if __name__ == "__main__":
    pdf = generar_pdf(AQUI / "hojas_para_imprimir.pdf")
    rutas = generar_fotos(pdf, AQUI / "fotos")
    generar_lista(AQUI / "lista_estudiantes_prueba.xlsx")
    print(f"{len(CASOS)} hojas: hojas_para_imprimir.pdf + fotos/ ({len(rutas)} fotos)")
