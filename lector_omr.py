"""
lector_omr.py — Lector OMR para hojas generadas por generador_pdf.py

Estrategia:
  1. Detecta las 4 marcas de esquina (cuadrados negros) en la foto.
  2. Calcula una transformación de perspectiva (homografía) para "enderezar"
     la hoja al tamaño estándar Letter.
  3. Proyecta las coordenadas exactas del PDF sobre la imagen corregida.
  4. Pre-binariza la imagen UNA sola vez con umbral Otsu global.
  5. Mide el relleno de cada burbuja con umbral adaptativo por pregunta.
  6. Compara con la clave JSON y reporta el puntaje.
  7. Lee el código de estudiante (burbujas de identificación).

Uso:
    python lector_omr.py <imagen_foto> [json_clave] [--guardar]

    Ejemplo:
        python lector_omr.py foto_examen.jpg hojas_de_respuesta/respuestas_Mat_11A.json

    Solo lectura (sin calificar):
        python lector_omr.py foto_examen.jpg

    Guardar imagen anotada:
        python lector_omr.py foto_examen.jpg respuestas.json --guardar

    Modo interactivo (menú):
        python lector_omr.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# Constantes del layout PDF (deben coincidir con generador_pdf.py)
# ─────────────────────────────────────────────────────────────────────────────

# Tamaño Letter en puntos PDF (1 pt = 1/72 pulgada)
PDF_W_PT: float = 612.0
PDF_H_PT: float = 792.0

# 1 cm en puntos PDF
CM: float = 28.3465

# Escala de renderizado: píxeles por punto PDF (mayor = más preciso, más memoria)
RENDER_SCALE: float = 2.0

# Parámetros de layout (deben coincidir con generador_pdf.py)
MARGEN:         float = 1.5  * CM
TAMANO_MARCA:   float = 0.5  * CM
RADIO_BURBUJA:  float = 0.22 * CM
ESPACIO_Y:      float = 0.58 * CM
ESPACIO_X:      float = 0.65 * CM
MAX_FILAS_COL:  int   = 25

# Posición Y de inicio de burbujas (calculada igual que en generador_pdf.py)
_Y_INSTRUCCIONES:  float = PDF_H_PT - 6.2 * CM
_Y_TITULOS:        float = _Y_INSTRUCCIONES - 2.5 * CM
Y_INICIO_BURB:     float = _Y_TITULOS - 1.0 * CM

INICIO_X_PREGUNTAS: float = MARGEN + 6.5 * CM
OPCIONES: tuple[str, ...] = ("A", "B", "C", "D")

# Layout de CÓDIGO DE ESTUDIANTE
# Coordenadas calculadas igual que en generador_pdf.py:
#   inicio_x_codigo = margen + 1.0*cm  →  x = inicio_x_codigo + 0.3*cm + col*espacio_x
#   ∴ INICIO_X_CODIGO = MARGEN + 1.0*CM + 0.3*CM = MARGEN + 1.3*CM
LEER_CODIGO_ESTUDIANTE: bool = True
DIGITOS_CODIGO: int = 3
INICIO_X_CODIGO: float = MARGEN + 1.3 * CM   # ← espeja generador_pdf.py exactamente
Y_INICIO_CODIGO: float = Y_INICIO_BURB
ESPACIO_X_CODIGO: float = ESPACIO_X            # igual que las burbujas de respuesta
ESPACIO_Y_CODIGO: float = ESPACIO_Y            # igual que las burbujas de respuesta
OPCIONES_CODIGO: tuple[str, ...] = tuple(str(i) for i in range(10))  # "0" a "9"

# Dimensión máxima al cargar una foto (reduce fotos de celular sin perder precisión)
MAX_DIM: int = 2400

# Escala de calificación (lineal 0–10)
NOTA_MIN: float = 0.0
NOTA_MAX: float = 10.0
NOTA_APROBACION: float = 6.0
NOTA_PISO: float = 1.0   # ninguna nota baja de este valor (piso institucional)

# Extensiones de imagen aceptadas
EXTENSIONES_IMAGEN: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
)

# ─────────────────────────────────────────────────────────────────────────────
# Tipos de datos
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Burbuja:
    pregunta: int  # O el índice de columna en el caso del código
    opcion:   str
    x_pt:     float   # coordenada X en puntos PDF (coords imagen, origen arriba)
    y_pt:     float   # coordenada Y en puntos PDF (coords imagen, origen arriba)


@dataclass
class ResultadoLectura:
    """Resultado completo de procesar una hoja OMR."""
    respuestas:  dict[int, Optional[str]]        # pregunta → letra o None
    fills:       dict[int, dict[str, float]]      # pregunta → {opción → fracción relleno}
    codigo_estudiante: str = "???"                     # Identificador leído
    en_blanco:   list[int] = field(default_factory=list)
    doble_marca: list[int] = field(default_factory=list)
    dudosas:     list[int] = field(default_factory=list)  # marca débil, revisar manualmente


@dataclass
class DatosExamen:
    nombre:          str
    total_preguntas: int
    clave:           dict[int, str]   # pregunta (1-based) → letra correcta


# ─────────────────────────────────────────────────────────────────────────────
# Geometría del PDF
# ─────────────────────────────────────────────────────────────────────────────

def _pdf_a_img_y(y_pdf: float) -> float:
    """Convierte coordenada Y de espacio PDF (abajo=0) a imagen (arriba=0)."""
    return PDF_H_PT - y_pdf


def esquinas_pdf() -> np.ndarray:
    """
    Devuelve las 4 esquinas (centros de las marcas de referencia) en
    coordenadas de imagen PDF, orden: [arriba-izq, arriba-der, abajo-der, abajo-izq].
    """
    cx_izq = MARGEN + TAMANO_MARCA / 2
    cx_der = PDF_W_PT - MARGEN - TAMANO_MARCA / 2
    cy_top = _pdf_a_img_y(PDF_H_PT - MARGEN - TAMANO_MARCA / 2)
    cy_bot = _pdf_a_img_y(MARGEN + TAMANO_MARCA / 2)

    return np.float32([
        [cx_izq, cy_top],   # arriba-izquierda
        [cx_der, cy_top],   # arriba-derecha
        [cx_der, cy_bot],   # abajo-derecha
        [cx_izq, cy_bot],   # abajo-izquierda
    ])


def calcular_burbujas(num_preguntas: int) -> list[Burbuja]:
    """
    Calcula las posiciones de todas las burbujas de respuesta en
    coordenadas de imagen PDF (origen arriba-izquierda).
    """
    burbujas: list[Burbuja] = []
    for i in range(1, num_preguntas + 1):
        col  = (i - 1) // MAX_FILAS_COL
        fila = (i - 1) %  MAX_FILAS_COL

        y_pt = _pdf_a_img_y(Y_INICIO_BURB - fila * ESPACIO_Y)
        x_base = INICIO_X_PREGUNTAS + col * 4.6 * CM

        for j, opc in enumerate(OPCIONES):
            burbujas.append(Burbuja(
                pregunta = i,
                opcion   = opc,
                x_pt     = x_base + 0.8 * CM + j * ESPACIO_X,
                y_pt     = y_pt,
            ))
    return burbujas

def calcular_burbujas_codigo() -> list[Burbuja]:
    """Calcula posiciones de burbujas del código de estudiante."""
    burbujas: list[Burbuja] = []
    for col in range(DIGITOS_CODIGO):
        x_pt = INICIO_X_CODIGO + col * ESPACIO_X_CODIGO
        for fila, digito in enumerate(OPCIONES_CODIGO):
            y_pt = _pdf_a_img_y(Y_INICIO_CODIGO - fila * ESPACIO_Y_CODIGO)
            # Usamos 'pregunta' para almacenar el índice de la columna (0, 1, 2)
            burbujas.append(Burbuja(pregunta=col, opcion=digito, x_pt=x_pt, y_pt=y_pt))
    return burbujas

# ─────────────────────────────────────────────────────────────────────────────
# Procesamiento de imagen
# ─────────────────────────────────────────────────────────────────────────────

def _redimensionar_si_grande(img: np.ndarray) -> np.ndarray:
    """Reduce la imagen si alguna dimensión supera MAX_DIM, preservando aspecto."""
    h, w = img.shape[:2]
    mayor = max(h, w)
    if mayor <= MAX_DIM:
        return img
    factor = MAX_DIM / mayor
    return cv2.resize(img, (int(w * factor), int(h * factor)),
                      interpolation=cv2.INTER_AREA)


def _detectar_bbox_hoja(img_gray: np.ndarray) -> tuple[int, int, int, int]:
    """
    Detecta el bounding box del papel blanco dentro de la foto.
    Devuelve (x, y, w, h) en píxeles. Si no lo encuentra, devuelve
    el tamaño completo de la imagen.
    """
    h, w = img_gray.shape

    # Umbral: el papel es claro, el fondo (mesa, escritorio) es más oscuro
    _, thresh = cv2.threshold(img_gray, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    contornos, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return 0, 0, w, h

    # El papel es el contorno más grande
    cnt = max(contornos, key=cv2.contourArea)
    area = cv2.contourArea(cnt)

    # Solo confiar si ocupa al menos el 40 % de la imagen
    if area < w * h * 0.40:
        return 0, 0, w, h

    bx, by, bw, bh = cv2.boundingRect(cnt)
    return bx, by, bw, bh


def _marcas_candidatos(bin_img: np.ndarray, pw: int) -> list[tuple[float, float]]:
    """Centros de blobs que parecen cuadrados negros sólidos, según un binario."""
    contornos, _ = cv2.findContours(bin_img, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
    area_min = (pw * 0.004) ** 2
    area_max = (pw * 0.060) ** 2
    out: list[tuple[float, float]] = []
    for cnt in contornos:
        area = cv2.contourArea(cnt)
        if not (area_min < area < area_max):
            continue
        bx, by, bw, bh = cv2.boundingRect(cnt)
        if bw == 0 or bh == 0:
            continue
        if not (0.45 < bw / bh < 2.2):       # ~cuadrado (tolerante a perspectiva)
            continue
        if area / (bw * bh) < 0.6:           # relleno sólido (descarta letras/aros)
            continue
        out.append((bx + bw / 2.0, by + bh / 2.0))
    return out


def _marcas_por_zona(pts: np.ndarray, px: int, py: int, pw: int, ph: int
                     ) -> Optional[np.ndarray]:
    """De una nube de candidatos, elige el más cercano a cada esquina del papel."""
    ZONA = 0.30
    zonas = [
        (px,      py,      px,               px + pw * ZONA, py,               py + ph * ZONA),
        (px + pw, py,      px + pw * (1 - ZONA), px + pw,     py,               py + ph * ZONA),
        (px + pw, py + ph, px + pw * (1 - ZONA), px + pw,     py + ph * (1 - ZONA), py + ph),
        (px,      py + ph, px,               px + pw * ZONA, py + ph * (1 - ZONA), py + ph),
    ]
    seleccionados: list[np.ndarray] = []
    for ref_x, ref_y, xmin, xmax, ymin, ymax in zonas:
        en_zona = [p for p in pts if xmin <= p[0] <= xmax and ymin <= p[1] <= ymax]
        if not en_zona:
            return None
        ref = np.float32([ref_x, ref_y])
        seleccionados.append(min(en_zona, key=lambda p: float(np.linalg.norm(p - ref))))
    return np.array(seleccionados, dtype=np.float32)


def detectar_marcas(img_gray: np.ndarray) -> Optional[np.ndarray]:
    """
    Detecta los 4 cuadrados negros de las esquinas, robusto a fotos de celular.

    Prueba varias binarizaciones (Otsu, adaptativa para sombras, y umbrales
    fijos) y se queda con la primera que produzca 4 marcas válidas, una por
    esquina del papel. Esto tolera iluminación despareja, sombras y fondos de
    escritorio.

    Returns:
        Array (4, 2) [arriba-izq, arriba-der, abajo-der, abajo-izq] o None.
    """
    h_img, w_img = img_gray.shape

    # Paso 0: bounding box del papel (para ignorar la mesa)
    px, py, pw, ph = _detectar_bbox_hoja(img_gray)

    # Suavizado leve para reducir ruido de cámara/JPEG
    suave = cv2.GaussianBlur(img_gray, (3, 3), 0)

    # Construir varias binarizaciones (marca = blanco sobre negro)
    binarios: list[np.ndarray] = []
    _, b_otsu = cv2.threshold(suave, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binarios.append(b_otsu)

    # Adaptativa: clave para sombras / luz despareja
    block = max(31, (pw // 8) | 1)           # impar
    b_adap = cv2.adaptiveThreshold(suave, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, block, 12)
    binarios.append(b_adap)

    # Umbrales fijos de respaldo
    for thv in (60, 90, 120, 150):
        _, bf = cv2.threshold(suave, thv, 255, cv2.THRESH_BINARY_INV)
        binarios.append(bf)

    # Máscara del papel (con margen) para ignorar lo que esté fuera de la hoja
    mask = np.zeros_like(img_gray)
    mx = int(pw * 0.04)
    cv2.rectangle(mask, (max(0, px - mx), max(0, py - mx)),
                  (min(w_img, px + pw + mx), min(h_img, py + ph + mx)), 255, -1)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    for b in binarios:
        b = cv2.bitwise_and(b, mask)
        closed = cv2.morphologyEx(b, cv2.MORPH_CLOSE, kernel)
        candidatos = _marcas_candidatos(closed, pw)
        if len(candidatos) < 4:
            continue
        pts = np.array(candidatos, dtype=np.float32)
        sel = _marcas_por_zona(pts, px, py, pw, ph)
        if sel is None:
            continue
        xs, ys = sel[:, 0], sel[:, 1]
        # Cordura: las 4 marcas deben abarcar buena parte del papel
        if (xs.max() - xs.min()) < pw * 0.45 or (ys.max() - ys.min()) < ph * 0.45:
            continue
        return sel

    return None


def corregir_perspectiva(img: np.ndarray,
                         marcas_detectadas: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Aplica homografía para proyectar la hoja fotografiada al espacio PDF.

    Returns:
        Tupla (imagen_corregida_BGR, escala_px_por_pt).
    """
    dst_w = int(PDF_W_PT * RENDER_SCALE)
    dst_h = int(PDF_H_PT * RENDER_SCALE)
    marcas_destino = esquinas_pdf() * RENDER_SCALE

    M, _ = cv2.findHomography(marcas_detectadas, marcas_destino,
                               cv2.RANSAC, 5.0)
    if M is None:
        raise ValueError("No se pudo calcular la homografía con las marcas detectadas.")

    warped = cv2.warpPerspective(img, M, (dst_w, dst_h))
    return warped, RENDER_SCALE


def binarizar(img_gray: np.ndarray,
              bbox_papel: Optional[tuple[int,int,int,int]] = None) -> np.ndarray:
    """
    Binariza la imagen con umbral Otsu calculado SOLO sobre el papel.

    Si se provee bbox_papel (x, y, w, h), el umbral se calcula exclusivamente
    sobre esa región, eliminando el efecto de fondos oscuros o franjas negras
    que distorsionan el histograma global.

    Debe llamarse UNA sola vez por imagen y reutilizar el resultado.
    """
    h, w = img_gray.shape

    if bbox_papel is not None:
        bx, by, bw, bh = bbox_papel
        # Recortar con un margen interior del 3 % para evitar el borde del papel
        mx, my = max(int(bw * 0.03), 4), max(int(bh * 0.03), 4)
        x0 = max(bx + mx, 0);  y0 = max(by + my, 0)
        x1 = min(bx + bw - mx, w);  y1 = min(by + bh - my, h)
        zona = img_gray[y0:y1, x0:x1]
    else:
        # Fallback: zona interior del 8 %
        mx, my = int(w * 0.08), int(h * 0.08)
        zona = img_gray[my:h - my, mx:w - mx]

    blurred_zona = cv2.GaussianBlur(zona, (3, 3), 0)
    umbral, _ = cv2.threshold(blurred_zona, 0, 255,
                              cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Aplicar umbral calculado a la imagen completa
    blurred = cv2.GaussianBlur(img_gray, (3, 3), 0)
    _, binaria = cv2.threshold(blurred, int(umbral), 255, cv2.THRESH_BINARY_INV)
    return binaria


def medir_fill_burbuja(binaria: np.ndarray,
                        x_pt: float, y_pt: float,
                        scale: float) -> float:
    """
    Mide la fracción de píxeles oscuros dentro de una burbuja.

    Args:
        binaria: Imagen ya binarizada (INV: oscuro = marcado = 255).
        x_pt, y_pt: Centro en puntos PDF.
        scale: Píxeles por punto PDF.

    Returns:
        Fracción [0.0, 1.0] de píxeles marcados dentro del círculo.
    """
    cx = int(x_pt * scale)
    cy = int(y_pt * scale)
    r  = max(2, int(RADIO_BURBUJA * scale * 0.85))

    # Extraer ROI cuadrada para no operar sobre la imagen completa
    x0, y0 = max(cx - r, 0), max(cy - r, 0)
    x1, y1 = min(cx + r + 1, binaria.shape[1]), min(cy + r + 1, binaria.shape[0])
    roi = binaria[y0:y1, x0:x1]

    # Máscara circular local (relativa al ROI)
    mask = np.zeros(roi.shape, dtype=np.uint8)
    cv2.circle(mask, (cx - x0, cy - y0), r, 255, -1)

    total   = cv2.countNonZero(mask)
    relleno = cv2.countNonZero(cv2.bitwise_and(roi, roi, mask=mask))

    return relleno / total if total > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Lógica de lectura y calificación
# ─────────────────────────────────────────────────────────────────────────────

def leer_respuestas(img_bgr: np.ndarray,
                    num_preguntas: int,
                    scale: float) -> ResultadoLectura:
    """
    Lee todas las burbujas de la imagen corregida en un único pase.

    Lógica de detección por rango (max − segundo_mayor):
      Si la diferencia entre el fill más alto y el segundo más alto de una fila
      supera UMBRAL_RANGO, se considera que hay una burbuja marcada (la de mayor fill).
      Si todos los fills son similares → en blanco.
      Si hay dos candidatos que superan el umbral → doble marca.

      Esta estrategia es robusta ante variaciones de iluminación y fondos oscuros
      porque no depende de un umbral absoluto sino de contraste relativo entre opciones.
    """
    UMBRAL_RANGO       = 0.08   # rango mínimo para considerar una marca válida
    UMBRAL_RANGO_DUDOSO = 0.04  # rango en zona gris: posible X fina o trazo débil

    img_gray   = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    bbox_papel = _detectar_bbox_hoja(img_gray)
    binaria    = binarizar(img_gray, bbox_papel)   # ← Otsu sobre el papel, no el fondo

    # 1. Leer código del estudiante
    codigo_leido = ""
    if LEER_CODIGO_ESTUDIANTE:
        burbujas_cod = calcular_burbujas_codigo()
        por_columna: dict[int, list[Burbuja]] = {}
        for b in burbujas_cod:
            por_columna.setdefault(b.pregunta, []).append(b)
        
        for col in range(DIGITOS_CODIGO):
            fills_col = {b.opcion: medir_fill_burbuja(binaria, b.x_pt, b.y_pt, scale) for b in por_columna[col]}
            sorted_fills = sorted(fills_col.items(), key=lambda x: x[1], reverse=True)
            f_max = sorted_fills[0][1]
            f_seg = sorted_fills[1][1] if len(sorted_fills) > 1 else 0.0
            
            if f_max - f_seg > UMBRAL_RANGO_DUDOSO:
                codigo_leido += sorted_fills[0][0]
            else:
                codigo_leido += "?" # Dudoso o en blanco
    else:
        codigo_leido = "N/A"

    # 2. Leer respuestas
    burbujas    = calcular_burbujas(num_preguntas)
    por_pregunta: dict[int, list[Burbuja]] = {}
    for b in burbujas:
        por_pregunta.setdefault(b.pregunta, []).append(b)

    respuestas:  dict[int, Optional[str]]       = {}
    fills:       dict[int, dict[str, float]]    = {}
    en_blanco:   list[int]                      = []
    doble_marca: list[int]                      = []
    dudosas:     list[int]                      = []

    for num_p in sorted(por_pregunta):
        fills_fila = {
            b.opcion: medir_fill_burbuja(binaria, b.x_pt, b.y_pt, scale)
            for b in por_pregunta[num_p]
        }
        fills[num_p] = fills_fila

        # Ordenar opciones por fill descendente
        sorted_fills = sorted(fills_fila.items(), key=lambda x: x[1], reverse=True)
        fill_max     = sorted_fills[0][1]
        fill_segundo = sorted_fills[1][1] if len(sorted_fills) > 1 else 0.0
        rango        = fill_max - fill_segundo

        if rango < UMBRAL_RANGO_DUDOSO:
            # Rango muy bajo → definitivamente en blanco
            respuestas[num_p] = None
            en_blanco.append(num_p)
        elif rango < UMBRAL_RANGO:
            # Zona gris: hay algo marcado pero el trazo es débil (posible X, visto, borrado)
            # No se cuenta como respuesta pero se alerta al docente
            respuestas[num_p] = None
            dudosas.append(num_p)
        else:
            # Hay una opción que destaca; verificar si hay doble marca
            # (dos opciones con fill cercano al máximo)
            marcadas = [opc for opc, f in fills_fila.items()
                        if fill_max - f < UMBRAL_RANGO]
            if len(marcadas) > 1:
                respuestas[num_p] = None
                doble_marca.append(num_p)
            else:
                respuestas[num_p] = sorted_fills[0][0]

    return ResultadoLectura(
        respuestas  = respuestas,
        fills       = fills,
        codigo_estudiante=codigo_leido,
        en_blanco   = en_blanco,
        doble_marca = doble_marca,
        dudosas     = dudosas,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Visualización
# ─────────────────────────────────────────────────────────────────────────────

def _calcular_nota(correctas: int, total: int) -> float:
    """
    Nota lineal en escala NOTA_MIN–NOTA_MAX, TRUNCADA a 1 decimal (no redondea),
    con piso en NOTA_PISO: si el resultado es inferior a 1.0, se reemplaza por 1.0.
    Ej.: 0 de 3 → 0.0 → 1.0 ; 1 de 3 → 3.3 ; 2 de 3 → 6.6.
    """
    if total == 0:
        return NOTA_MIN
    valor = NOTA_MIN + (NOTA_MAX - NOTA_MIN) * (correctas / total)
    # Truncar a 1 decimal (el epsilon evita que 9.0 caiga a 8.9 por error de float)
    nota = int(valor * 10 + 1e-9) / 10.0
    # Piso institucional: ninguna nota baja de 1.0
    return max(NOTA_PISO, nota)


def _dibujar_panel_resultado(img: np.ndarray,
                              correctas: int,
                              total: int,
                              en_blanco: list[int],
                              doble_marca: list[int],
                              dudosas: list[int],
                              nombre_examen: str,
                              codigo_estudiante: str) -> np.ndarray:
    """
    Dibuja un panel semitransparente en la parte inferior de la imagen
    con: nombre del examen, aciertos, nota final y alertas.
    """
    h, w = img.shape[:2]
    nota  = _calcular_nota(correctas, total)
    aprueba = nota >= NOTA_APROBACION

    # ── Dimensiones del panel ────────────────────────────────────────
    PANEL_H    = 150 # Aumentado para el código de estudiante
    PADDING    = 18
    y_panel    = h - PANEL_H

    # Fondo semitransparente oscuro
    overlay = img.copy()
    cv2.rectangle(overlay, (0, y_panel), (w, h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.82, img, 0.18, 0, img)

    # ── Barra de color según resultado (izquierda) ───────────────────
    barra_color = (60, 180, 60) if aprueba else (50, 50, 210)
    cv2.rectangle(img, (0, y_panel), (10, h), barra_color, -1)

    # ── Texto: nombre del examen ─────────────────────────────────────
    y_txt = y_panel + PADDING + 16
    if nombre_examen:
        cv2.putText(img, nombre_examen.upper(), (PADDING + 10, y_txt),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)
        y_txt += 24

    # Dibujar Código de Estudiante
    texto_estudiante = f"Estudiante: {codigo_estudiante}"
    cv2.putText(img, texto_estudiante, (PADDING + 10, y_txt),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 255, 255), 1, cv2.LINE_AA)
    y_txt += 26

    # ── Texto: aciertos / total ──────────────────────────────────────
    texto_aciertos = f"Aciertos: {correctas} / {total}"
    cv2.putText(img, texto_aciertos, (PADDING + 10, y_txt),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (230, 230, 230), 1, cv2.LINE_AA)

    # ── Nota grande (derecha del panel) ─────────────────────────────
    texto_nota  = f"{nota:.1f}"
    texto_label = "NOTA"
    color_nota  = (80, 220, 80) if aprueba else (80, 80, 230)

    # Posición: pegado a la derecha
    (tw, th), _ = cv2.getTextSize(texto_nota, cv2.FONT_HERSHEY_SIMPLEX, 2.2, 3)
    x_nota = w - tw - PADDING - 10
    y_nota = y_panel + PANEL_H - PADDING - 4
    cv2.putText(img, texto_nota, (x_nota, y_nota),
                cv2.FONT_HERSHEY_SIMPLEX, 2.2, color_nota, 3, cv2.LINE_AA)

    # Etiqueta "NOTA" encima del número
    (lw, _), _ = cv2.getTextSize(texto_label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.putText(img, texto_label, (x_nota + (tw - lw) // 2, y_panel + PADDING + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1, cv2.LINE_AA)

    # Estado APROBADO / REPROBADO
    estado_txt   = "APROBADO" if aprueba else "REPROBADO"
    estado_color = (80, 220, 80) if aprueba else (80, 80, 230)
    y_estado = y_nota - th - 6
    cv2.putText(img, estado_txt, (x_nota, y_estado),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, estado_color, 1, cv2.LINE_AA)

    # ── Alertas (en blanco / doble marca) ────────────────────────────
    y_alerta = y_txt + 26
    if en_blanco:
        nums = ", ".join(str(n) for n in en_blanco[:10])
        sufijo = "…" if len(en_blanco) > 10 else ""
        cv2.putText(img, f"Sin resp: {nums}{sufijo}", (PADDING + 10, y_alerta),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (80, 200, 255), 1, cv2.LINE_AA)
        y_alerta += 20
    if doble_marca:
        nums = ", ".join(str(n) for n in doble_marca[:10])
        sufijo = "…" if len(doble_marca) > 10 else ""
        cv2.putText(img, f"Doble marca: {nums}{sufijo}", (PADDING + 10, y_alerta),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (60, 160, 255), 1, cv2.LINE_AA)
        y_alerta += 20
    if dudosas:
        nums = ", ".join(str(n) for n in dudosas[:10])
        sufijo = "…" if len(dudosas) > 10 else ""
        cv2.putText(img, f"REVISAR: preg. {nums}{sufijo} — marca debil, verificar",
                    (PADDING + 10, y_alerta),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 165, 255), 1, cv2.LINE_AA)

    return img


def dibujar_anotaciones(img_bgr:       np.ndarray,
                         resultado:     ResultadoLectura,
                         clave:         Optional[dict[int, str]],
                         scale:         float,
                         nombre_examen: str = "") -> np.ndarray:
    """
    Dibuja sobre la imagen corregida:
      • Círculos de color en cada burbuja (verde=correcto, rojo=incorrecto, azul=sin clave)
      • Panel inferior con nota (escala 0–10), aciertos y alertas.

    Reutiliza los fills de ResultadoLectura — no reprocesa la imagen.

    Colores de burbuja:
      Verde  → marcada y correcta   (con clave)
      Rojo   → marcada e incorrecta (con clave)
      Azul   → marcada              (sin clave)
      Gris   → sin marcar
    """
    debug = img_bgr.copy()
    r_px      = max(3, int(RADIO_BURBUJA * scale))

    # Dibujar Cuadrícula de Estudiante
    if LEER_CODIGO_ESTUDIANTE:
        burbujas_cod = calcular_burbujas_codigo()
        for b in burbujas_cod:
            cx, cy = int(b.x_pt * scale), int(b.y_pt * scale)
            marcada = False
            
            # Verificamos si esta burbuja es parte del código leído
            if resultado.codigo_estudiante and "?" not in resultado.codigo_estudiante:
                if b.pregunta < len(resultado.codigo_estudiante):
                    if b.opcion == resultado.codigo_estudiante[b.pregunta]:
                        marcada = True
                        
            if marcada:
                cv2.circle(debug, (cx, cy), r_px, (220, 180, 0), 3, cv2.LINE_AA) # Cian suave
            else:
                cv2.circle(debug, (cx, cy), r_px, (200, 200, 200), 1, cv2.LINE_AA) # Gris


    # Dibujar Cuadrícula de Preguntas
    burbujas_preg: list[Burbuja] = calcular_burbujas(len(resultado.respuestas))
    por_pregunta: dict[int, list[Burbuja]] = {}
    for b in burbujas_preg:
        por_pregunta.setdefault(b.pregunta, []).append(b)

    correctas = 0

    for num_p, bbs in sorted(por_pregunta.items()):
        resp_alumno = resultado.respuestas.get(num_p)
        resp_clave  = clave.get(num_p) if clave else None

        if resp_alumno == resp_clave and resp_alumno is not None:
            correctas += 1

        for b in bbs:
            cx = int(b.x_pt * scale)
            cy = int(b.y_pt * scale)

            marcada = (b.opcion == resp_alumno)
            es_correcta_clave = (b.opcion == resp_clave)

            # Lógica de colores
            if clave:
                if marcada and es_correcta_clave:
                    color = (0, 200, 0)      # Verde
                    grosor = 3
                elif marcada and not es_correcta_clave:
                    color = (0, 0, 220)      # Rojo
                    grosor = 3
                elif not marcada and es_correcta_clave:
                    color = (0, 150, 0)      # Verde oscuro (la correcta que no marcó)
                    grosor = 2
                else:
                    color = (200, 200, 200)  # Gris (ignorada)
                    grosor = 1
            else:
                # Si no hay clave, solo marcamos en azul las seleccionadas
                if marcada:
                    color = (220, 100, 0)    # Azul (BGR)
                    grosor = 3
                else:
                    color = (200, 200, 200)
                    grosor = 1

            cv2.circle(debug, (cx, cy), r_px, color, grosor, cv2.LINE_AA)

    # Destacar las 4 marcas de esquina con círculos verdes suaves
    esquinas = esquinas_pdf() * scale
    for pt in esquinas:
        cv2.circle(debug, (int(pt[0]), int(pt[1])), 15, (100, 255, 100), 2, cv2.LINE_AA)

    # Dibujar panel inferior
    total_preg = len(clave) if clave else len(resultado.respuestas)
    _dibujar_panel_resultado(
        debug, correctas, total_preg,
        resultado.en_blanco, resultado.doble_marca, resultado.dudosas,
        nombre_examen, resultado.codigo_estudiante
    )

    return debug


# ─────────────────────────────────────────────────────────────────────────────
# Manejo de archivos e I/O
# ─────────────────────────────────────────────────────────────────────────────

def cargar_imagen(ruta: Path) -> np.ndarray:
    """Carga y reduce la imagen si es demasiado grande."""
    if not ruta.exists():
        raise FileNotFoundError(f"Imagen no encontrada: {ruta}")

    img = cv2.imread(str(ruta))
    if img is None:
        raise ValueError(f"No se pudo decodificar la imagen: {ruta}")

    return _redimensionar_si_grande(img)


def cargar_datos_examen(ruta_json: Path) -> DatosExamen:
    """Lee el JSON generado por generador_pdf.py."""
    if not ruta_json.exists():
        raise FileNotFoundError(f"Archivo de clave no encontrado: {ruta_json}")

    with ruta_json.open('r', encoding='utf-8') as f:
        datos = json.load(f)

    try:
        nombre = datos["examen"]
        total  = int(datos["total_preguntas"])
        arr_correctas = datos["clave_correctas"]
    except KeyError as e:
        raise ValueError(f"JSON inválido, falta clave: {e}")

    clave = {i + 1: val for i, val in enumerate(arr_correctas)}
    return DatosExamen(nombre, total, clave)


def imprimir_reporte(resultado: ResultadoLectura,
                     datos_examen: Optional[DatosExamen] = None) -> None:
    """Imprime el resultado detallado en consola."""
    print("\n" + "═" * 50)
    print("  📊 RESULTADO OMR")
    print("═" * 50)
    print(f"  🧑‍🎓 CÓDIGO ESTUDIANTE: {resultado.codigo_estudiante}")
    print("─" * 50)
    
    if datos_examen:
        print(f"  📝 Examen:    {datos_examen.nombre}")
        total = datos_examen.total_preguntas
        correctas = sum(
            1 for p, resp in resultado.respuestas.items()
            if resp == datos_examen.clave.get(p)
        )
        nota = _calcular_nota(correctas, total)
        print(f"  ✅ Aciertos:  {correctas} / {total}")
        print(f"  ⭐ Nota:      {nota:.1f}")
    else:
        print("  (Modo lectura libre, sin clave JSON)")

    print("\n  [Alertas]")
    if resultado.en_blanco:
        print(f"  ⚠️ En blanco:   {', '.join(map(str, resultado.en_blanco))}")
    if resultado.doble_marca:
        print(f"  ⚠️ Doble marca: {', '.join(map(str, resultado.doble_marca))}")
    if resultado.dudosas:
        print(f"  ❓ Dudosas:     {', '.join(map(str, resultado.dudosas))} (revisar manualmente)")
    if not any([resultado.en_blanco, resultado.doble_marca, resultado.dudosas]):
        print("  ✅ Todo leído correctamente.")
    print("═" * 50 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Controladores de Flujo Principal
# ─────────────────────────────────────────────────────────────────────────────

def _pedir_num_preguntas() -> int:
    """Pide al usuario la cantidad de preguntas si no hay clave JSON."""
    while True:
        try:
            num = int(input("  ¿Cuántas preguntas tiene la hoja? (1-100): ").strip())
            if 1 <= num <= 100:
                return num
            print("  ⚠️ El número debe estar entre 1 y 100.")
        except ValueError:
            print("  ⚠️ Ingresa un número válido.")


def procesar(ruta_imagen: Path | str,
             ruta_json:   Optional[Path | str] = None,
             guardar:     bool = False) -> ResultadoLectura:
    """
    Procesa una hoja OMR completa:
      carga → detecta marcas → corrige perspectiva → lee burbujas → reporta.

    Returns:
        ResultadoLectura con respuestas, fills y alertas.
    """
    ruta_imagen = Path(ruta_imagen)
    ruta_json   = Path(ruta_json) if ruta_json else None

    # 1. Cargar imagen
    img = cargar_imagen(ruta_imagen)

    # 2. Cargar JSON de clave (opcional)
    datos_examen: Optional[DatosExamen] = None
    if ruta_json:
        try:
            datos_examen = cargar_datos_examen(ruta_json)
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(1)

    # 3. Determinar número de preguntas
    if datos_examen:
        num_preguntas = datos_examen.total_preguntas
    else:
        num_preguntas = _pedir_num_preguntas()

    # 4. Encontrar marcas de esquina
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    marcas = detectar_marcas(img_gray)

    if marcas is None:
        print("\n❌ ERROR: No se detectaron las 4 marcas negras de las esquinas.")
        print("   Asegúrate de que toda la hoja sea visible, la iluminación sea buena")
        print("   y no haya sombras muy fuertes sobre las esquinas.")
        sys.exit(1)

    # 5. Enderezar hoja
    try:
        img_corr, scale = corregir_perspectiva(img, marcas)
    except ValueError as e:
        print(f"\n❌ ERROR de geometría: {e}")
        sys.exit(1)

    # 6. Leer burbujas
    print("\n  🔍 Analizando respuestas y código de estudiante...")
    resultado = leer_respuestas(img_corr, num_preguntas, scale)

    # 7. Reporte en consola
    imprimir_reporte(resultado, datos_examen)

    # 8. Guardar imagen anotada en carpeta examenes_calificados/ (siempre)
    clave         = datos_examen.clave  if datos_examen else None
    nombre_examen = datos_examen.nombre if datos_examen else ""
    debug = dibujar_anotaciones(img_corr, resultado, clave, scale, nombre_examen)

    carpeta_salida = Path("examenes_calificados")
    carpeta_salida.mkdir(exist_ok=True)
    nombre_out = carpeta_salida / (ruta_imagen.stem.replace("_scanned", "") + "_calificado.jpg")
    cv2.imwrite(str(nombre_out), debug)
    print(f"💾 Examen calificado guardado en: {nombre_out}")

    # 9. Mover/eliminar de procesados para que el flujo avance
    try:
        if ruta_imagen.exists() and "examenes_procesados" in str(ruta_imagen):
            ruta_imagen.unlink()
            print(f"🧹 Imagen '{ruta_imagen.name}' removida de la cola de procesados.")
    except Exception as e:
        print(f"⚠️ No se pudo remover la imagen original: {e}")

    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# Gestor de Salones — navegación Grado → Salón → Examen
# ─────────────────────────────────────────────────────────────────────────────
#
# Estructura de carpetas esperada:
#
#   examenes_procesados/
#     grado_10/
#       salon_A/
#         simulacro_ingles/      ← imágenes de hojas escaneadas aquí
#         parcial_matematicas/
#       salon_B/
#         ...
#     grado_11/
#       ...
#
#   hojas_de_respuesta/
#     grado_10/
#       salon_A/
#         respuestas_simulacro_ingles.json
#       salon_B/
#         ...
#     grado_11/
#       ...
#
#   examenes_calificados/        ← se crea automáticamente, misma jerarquía
#     grado_10/
#       salon_A/
#         simulacro_ingles/
#           alumno_001_calificado.jpg
#           ...
# ─────────────────────────────────────────────────────────────────────────────

ROOT_PROCESADOS:  str = "examenes_procesados"
ROOT_RESPUESTAS:  str = "hojas_de_respuesta"
ROOT_CALIFICADOS: str = "examenes_calificados"

SEP = "─" * 55
SEP2 = "═" * 55


def _menu_seleccion(titulo: str,
                    opciones: list[str],
                    prompt: str = "  Selecciona una opción",
                    con_salir: bool = True) -> int:
    """
    Muestra un menú numerado y devuelve el índice 1-based elegido,
    o 0 si el usuario elige Salir / Volver.
    """
    print(f"\n{SEP2}")
    print(f"  {titulo}")
    print(SEP2)
    if con_salir:
        print("  [ 0]  ← Volver / Salir")
        print(SEP)
    for i, op in enumerate(opciones, start=1):
        print(f"  [{i:>2}]  {op}")
    print(SEP)

    while True:
        try:
            val = int(input(f"{prompt} (0–{len(opciones)}): ").strip())
            if 0 <= val <= len(opciones):
                return val
            print(f"  ⚠️  Número entre 0 y {len(opciones)}.")
        except ValueError:
            print("  ⚠️  Solo números, por favor.")


def _listar_subdirs(carpeta: Path) -> list[Path]:
    """Devuelve subdirectorios ordenados alfabéticamente."""
    if not carpeta.exists():
        return []
    return sorted(p for p in carpeta.iterdir() if p.is_dir())


def _listar_imagenes(carpeta: Path) -> list[Path]:
    """Devuelve imágenes dentro de una carpeta, ordenadas por nombre."""
    if not carpeta.exists():
        return []
    return sorted(p for p in carpeta.iterdir()
                  if p.suffix.lower() in EXTENSIONES_IMAGEN)


def _buscar_json_examen(nombre_examen: str,
                        grado: str,
                        salon: str) -> Optional[Path]:
    """
    Busca el JSON de respuestas en la ruta estructurada:
      hojas_de_respuesta/<grado>/<salon>/respuestas_<nombre_examen>.json
    Si no existe ahí, cae a la raíz de hojas_de_respuesta/ como fallback.
    """
    # Ruta preferida: carpeta del salón
    ruta_directa = (Path(ROOT_RESPUESTAS) / grado / salon
                    / f"respuestas_{nombre_examen}.json")
    if ruta_directa.exists():
        return ruta_directa

    # Fallback: raíz de hojas_de_respuesta/
    raiz = Path(ROOT_RESPUESTAS)
    if raiz.exists():
        candidatos = list(raiz.glob(f"**/respuestas_{nombre_examen}.json"))
        if candidatos:
            return candidatos[0]

    return None


def _seleccionar_json_manual(grado: str, salon: str) -> Optional[Path]:
    """Lista todos los JSON disponibles para elegir manualmente."""
    raiz = Path(ROOT_RESPUESTAS)
    jsons = sorted(raiz.glob("**/*.json")) if raiz.exists() else []

    if not jsons:
        return None

    nombres = [str(j.relative_to(raiz)) for j in jsons]
    idx = _menu_seleccion(
        "SELECCIONAR CLAVE DE RESPUESTAS MANUALMENTE",
        nombres,
        "  Elige la clave",
    )
    if idx == 0:
        return None
    return jsons[idx - 1]


def _crear_estructura_ejemplo() -> None:
    """
    Crea las carpetas mínimas para que el usuario entienda la estructura
    esperada la primera vez que ejecuta el programa.
    """
    for base in (ROOT_PROCESADOS, ROOT_RESPUESTAS, ROOT_CALIFICADOS):
        ejemplo = Path(base) / "grado_10" / "salon_A" / "ejemplo_examen"
        ejemplo.mkdir(parents=True, exist_ok=True)
    print(f"""
  📁 Se crearon carpetas de ejemplo. Estructura esperada:

  {ROOT_PROCESADOS}/
    grado_10/
      salon_A/
        simulacro_ingles/   ← coloca aquí las imágenes escaneadas
      salon_B/
    grado_11/
      ...

  {ROOT_RESPUESTAS}/
    grado_10/
      salon_A/
        respuestas_simulacro_ingles.json   ← generado por generador_pdf.py

  Los resultados se guardarán en '{ROOT_CALIFICADOS}/' con la misma jerarquía.
""")


# ── Niveles del menú ──────────────────────────────────────────────────────────

def _elegir_grado() -> Optional[str]:
    """Nivel 1: elegir grado."""
    raiz = Path(ROOT_PROCESADOS)
    grados = [d.name for d in _listar_subdirs(raiz)]

    if not grados:
        print(f"\n⚠️  No hay grados en '{ROOT_PROCESADOS}'.")
        _crear_estructura_ejemplo()
        return None

    idx = _menu_seleccion("LICEO SAHAGÚN — CALIFICADOR OMR  |  Selecciona el Grado",
                          grados, "  Grado")
    if idx == 0:
        return None
    return grados[idx - 1]


def _elegir_salon(grado: str) -> Optional[str]:
    """Nivel 2: elegir salón dentro del grado."""
    carpeta_grado = Path(ROOT_PROCESADOS) / grado
    salones = [d.name for d in _listar_subdirs(carpeta_grado)]

    if not salones:
        print(f"\n⚠️  No hay salones dentro de '{grado}'.")
        print(f"   Crea subcarpetas como: {ROOT_PROCESADOS}/{grado}/salon_A/")
        return None

    idx = _menu_seleccion(f"GRADO: {grado.upper()}  |  Selecciona el Salón",
                          salones, "  Salón")
    if idx == 0:
        return None
    return salones[idx - 1]


def _elegir_examen(grado: str, salon: str) -> Optional[str]:
    """Nivel 3: elegir examen (subcarpeta con imágenes)."""
    carpeta_salon = Path(ROOT_PROCESADOS) / grado / salon
    examenes = [d.name for d in _listar_subdirs(carpeta_salon)]

    if not examenes:
        print(f"\n⚠️  No hay exámenes en '{grado}/{salon}'.")
        print(f"   Crea subcarpetas como: {ROOT_PROCESADOS}/{grado}/{salon}/simulacro_ingles/")
        return None

    idx = _menu_seleccion(
        f"GRADO: {grado.upper()}  |  SALÓN: {salon.upper()}  |  Selecciona el Examen",
        examenes, "  Examen"
    )
    if idx == 0:
        return None
    return examenes[idx - 1]


def _calificar_examen(grado: str, salon: str, nombre_examen: str) -> None:
    """
    Califica todas las imágenes de la carpeta del examen seleccionado.
    Guarda resultados en examenes_calificados/<grado>/<salon>/<nombre_examen>/
    """
    carpeta_imgs = Path(ROOT_PROCESADOS) / grado / salon / nombre_examen
    imagenes = _listar_imagenes(carpeta_imgs)

    if not imagenes:
        print(f"\n⚠️  No hay imágenes en '{carpeta_imgs}'.")
        print(f"   Extensiones soportadas: {', '.join(sorted(EXTENSIONES_IMAGEN))}")
        return

    # Buscar clave JSON
    ruta_json_sel = _buscar_json_examen(nombre_examen, grado, salon)

    if ruta_json_sel:
        print(f"\n  🔑 Clave encontrada: {ruta_json_sel}")
    else:
        print(f"\n  ⚠️  No se encontró clave automática para '{nombre_examen}'.")
        ruta_json_sel = _seleccionar_json_manual(grado, salon)
        if ruta_json_sel:
            print(f"  🔑 Usando clave: {ruta_json_sel.name}")
        else:
            print("  ℹ️  Continuando en modo solo lectura (sin calificación).")

    # Carpeta de salida para calificados
    carpeta_salida = Path(ROOT_CALIFICADOS) / grado / salon / nombre_examen
    carpeta_salida.mkdir(parents=True, exist_ok=True)

    print(f"\n{SEP2}")
    print(f"  📋  {grado.upper()} · {salon.upper()} · {nombre_examen.upper()}")
    print(f"  📂  {len(imagenes)} hoja(s) para calificar")
    print(SEP2)

    for i, img_path in enumerate(imagenes, start=1):
        print(f"\n  [{i}/{len(imagenes)}] Procesando: {img_path.name}")
        try:
            _procesar_con_salida(img_path, ruta_json_sel, carpeta_salida)
        except Exception as e:
            print(f"  ❌ Error procesando '{img_path.name}': {e}")

    print(f"\n  ✅ Listo. Resultados en: {carpeta_salida}")


def _procesar_con_salida(ruta_imagen: Path,
                         ruta_json:   Optional[Path],
                         carpeta_salida: Path) -> ResultadoLectura:
    """
    Igual que `procesar` pero la carpeta de salida se pasa como parámetro
    (para que respete la jerarquía grado/salón/examen).
    No elimina la imagen fuente.
    """
    # 1. Cargar imagen
    img = cargar_imagen(ruta_imagen)

    # 2. Clave JSON
    datos_examen: Optional[DatosExamen] = None
    if ruta_json:
        try:
            datos_examen = cargar_datos_examen(ruta_json)
        except (ValueError, FileNotFoundError) as e:
            print(f"  ❌ {e}")

    # 3. Número de preguntas
    if datos_examen:
        num_preguntas = datos_examen.total_preguntas
    else:
        num_preguntas = _pedir_num_preguntas()

    # 4. Detectar marcas
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    marcas = detectar_marcas(img_gray)
    if marcas is None:
        print("  ❌ No se detectaron las 4 marcas de esquina. Revisa la imagen.")
        raise ValueError("Marcas no detectadas")

    # 5. Corregir perspectiva
    img_corr, scale = corregir_perspectiva(img, marcas)

    # 6. Leer burbujas
    print("     🔍 Analizando burbujas...")
    resultado = leer_respuestas(img_corr, num_preguntas, scale)

    # 7. Reporte en consola
    imprimir_reporte(resultado, datos_examen)

    # 8. Guardar imagen anotada
    clave         = datos_examen.clave  if datos_examen else None
    nombre_examen = datos_examen.nombre if datos_examen else ruta_imagen.stem
    debug = dibujar_anotaciones(img_corr, resultado, clave, scale, nombre_examen)

    nombre_out = carpeta_salida / (ruta_imagen.stem.replace("_scanned", "")
                                   + "_calificado.jpg")
    cv2.imwrite(str(nombre_out), debug)
    print(f"  💾 Guardado: {nombre_out}")

    return resultado


def modo_interactivo(carpeta_examenes: str = ROOT_PROCESADOS,
                     carpeta_json:     str = ROOT_RESPUESTAS,
                     guardar:          bool = False) -> None:
    """
    Menú principal con navegación Grado → Salón → Examen.
    Reemplaza al menú plano anterior.
    """
    while True:
        # ── Nivel 1: Grado ────────────────────────────────────────────
        grado = _elegir_grado()
        if grado is None:
            print("\n  Hasta luego.\n")
            sys.exit(0)

        # ── Nivel 2: Salón ────────────────────────────────────────────
        salon = _elegir_salon(grado)
        if salon is None:
            continue   # Volver a elegir grado

        # ── Nivel 3: Examen ───────────────────────────────────────────
        nombre_examen = _elegir_examen(grado, salon)
        if nombre_examen is None:
            continue   # Volver a elegir grado

        # ── Calificar ────────────────────────────────────────────────
        _calificar_examen(grado, salon, nombre_examen)

        otra = input("\n  ¿Calificar otro examen? (s/n): ").strip().lower()
        if otra not in ("s", "si", "sí", "yes", "y"):
            print("\n  Hasta luego.\n")
            break


def _pedir_seleccion(max_val: int) -> int:
    """Solicita un número de selección entre 0 y max_val."""
    while True:
        try:
            num = int(input("\n  Selecciona el número: ").strip())
            if 0 <= num <= max_val:
                return num
            print(f"  ⚠️  Número entre 0 y {max_val}.")
        except ValueError:
            print("  ⚠️  Solo números.")


# ─────────────────────────────────────────────────────────────────────────────
# Punto de entrada
# ─────────────────────────────────────────────────────────────────────────────

# =============================================================================
# NAVEGACIÓN POR PROFESOR → GRADO → CURSO  (estructura del proyecto)
# =============================================================================
#
# Estructura esperada (creada por gestor_salones.py / generador_pdf.py):
#
#   profesores/<Profesor>/<Grado>/<Curso>/
#       examenes_procesados/   ← imágenes alineadas por digitalizador.py (entrada)
#       examenes_claves/       ← claves JSON del curso
#       resultados/            ← salida de este lector (se crea sola)
#
# La GEOMETRÍA de lectura (coordenadas de burbujas, marcas, homografía) es la
# misma del motor probado: coincide exactamente con generador_pdf.py.
# Aquí solo cambian las RUTAS, que era lo único que se debía modificar.
# -----------------------------------------------------------------------------

BASE_PROFESORES = Path("profesores")

SUB_PROCESADOS = "examenes_procesados"          # imágenes ya alineadas (entrada del lector)
SUB_CLAVES     = "examenes_claves"              # claves JSON del curso
SUB_RESULTADOS = "resultados"                   # salida de este lector
SUB_CRUDOS     = "examenes_crudos"              # fotos sin alinear (las toma el digitalizador)
SUB_ARCHIVADOS = "examenes_crudos_archivados"   # fotos crudas ya procesadas

# Formatos de imagen que el digitalizador puede tomar como foto cruda
_FORMATOS_CRUDOS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}


def auto_digitalizar(ruta_curso: Path) -> int:
    """
    Antes de calificar, alinea automáticamente cualquier foto cruda del curso.

    Toma las imágenes de '<curso>/examenes_crudos/', les corrige la perspectiva
    usando digitalizador.py, las deja en '<curso>/examenes_procesados/' con el
    sufijo '_scanned' y archiva el original en '<curso>/examenes_crudos_archivados/'.

    Devuelve la cantidad de fotos alineadas con éxito. Si no hay fotos crudas o
    no se puede cargar el digitalizador, simplemente no hace nada (devuelve 0).
    """
    crudos     = ruta_curso / SUB_CRUDOS
    procesados = ruta_curso / SUB_PROCESADOS
    archivados = ruta_curso / SUB_ARCHIVADOS

    # Asegurar que la carpeta de fotos crudas exista (para que el docente sepa
    # dónde dejar las fotos), aunque por ahora esté vacía.
    crudos.mkdir(parents=True, exist_ok=True)

    pendientes = [
        f for f in sorted(crudos.iterdir())
        if f.is_file() and f.suffix.lower() in _FORMATOS_CRUDOS
    ]
    if not pendientes:
        return 0

    # Cargar el digitalizador como módulo (debe estar junto a este archivo)
    try:
        import digitalizador as D
    except Exception as e:
        print(f"\n  ⚠️  Hay fotos sin alinear pero no se pudo cargar digitalizador.py: {e}")
        print("     Ejecútalo manualmente o coloca digitalizador.py junto a lector_omr.py.")
        return 0

    procesados.mkdir(parents=True, exist_ok=True)
    archivados.mkdir(parents=True, exist_ok=True)

    print(f"\n  🧹 Hay {len(pendientes)} foto(s) cruda(s). Alineando automáticamente...")
    ok = 0
    for img in pendientes:
        destino = procesados / f"{img.stem}_scanned.png"
        try:
            if D.procesar_alineacion_imagen(img, destino):
                shutil.move(str(img), str(archivados / img.name))
                print(f"     ✓ {img.name} → {destino.name}")
                ok += 1
            else:
                print(f"     ✗ No se pudo alinear {img.name} (se deja en examenes_crudos).")
        except Exception as e:
            print(f"     ✗ Error alineando {img.name}: {e}")

    print(f"  🧹 Alineadas {ok}/{len(pendientes)}. Listas para calificar.")
    return ok


def _elegir(titulo: str, opciones: list[str], etiqueta: str) -> Optional[int]:
    """Muestra un menú y devuelve el índice 0-based, o None si vuelve/sale."""
    idx = _menu_seleccion(titulo, opciones, f"  {etiqueta}", con_salir=True)
    return None if idx == 0 else idx - 1


def menu_profesores_local() -> tuple[Path, Path, Optional[Path], list[Path]]:
    """
    Navega profesores/<Profesor>/<Grado>/<Curso> y devuelve:
      (ruta_curso, dir_resultados, ruta_clave_json|None, lista_imagenes)
    """
    if not BASE_PROFESORES.exists():
        print(f"\n⚠️  No se encontró la carpeta '{BASE_PROFESORES}'.")
        print("   Ejecuta primero gestor_salones.py o generador_pdf.py.")
        sys.exit(1)

    print("\n" + SEP2)
    print("      LECTOR EXÁMENES OMR — LICEO SAHAGÚN")
    print(SEP2)

    # 1. Profesor
    profesores = [d.name for d in _listar_subdirs(BASE_PROFESORES)]
    if not profesores:
        print("\n⚠️  No hay profesores registrados.")
        sys.exit(1)
    i = _elegir("Paso 1 · Selecciona el PROFESOR",
                [p.replace('_', ' ') for p in profesores], "Profesor")
    if i is None:
        sys.exit(0)
    ruta_prof = BASE_PROFESORES / profesores[i]
    nombre_prof = profesores[i].replace('_', ' ')

    # 2. Grado
    grados = [d.name for d in _listar_subdirs(ruta_prof)]
    if not grados:
        print(f"\n⚠️  {nombre_prof} no tiene grados.")
        sys.exit(1)
    i = _elegir(f"Paso 2 · {nombre_prof}  |  Selecciona el GRADO", grados, "Grado")
    if i is None:
        sys.exit(0)
    ruta_grado = ruta_prof / grados[i]
    grado = grados[i]

    # 3. Curso
    cursos = [d.name for d in _listar_subdirs(ruta_grado)]
    if not cursos:
        print(f"\n⚠️  El grado {grado} no tiene cursos.")
        sys.exit(1)
    i = _elegir(f"Paso 3 · Grado {grado}  |  Selecciona el CURSO", cursos, "Curso")
    if i is None:
        sys.exit(0)
    ruta_curso = ruta_grado / cursos[i]
    curso = cursos[i]

    # Carpetas del curso
    dir_imgs   = ruta_curso / SUB_PROCESADOS
    dir_claves = ruta_curso / SUB_CLAVES
    dir_salida = ruta_curso / SUB_RESULTADOS
    dir_imgs.mkdir(parents=True, exist_ok=True)
    dir_claves.mkdir(parents=True, exist_ok=True)

    # ── Auto-digitalización: alinear fotos crudas antes de calificar ──────────
    auto_digitalizar(ruta_curso)

    # 4. Imágenes a calificar (si no hay, avisar antes de pedir la clave)
    imagenes = _listar_imagenes(dir_imgs)
    if not imagenes:
        dir_crudos = ruta_curso / SUB_CRUDOS
        dir_crudos.mkdir(parents=True, exist_ok=True)
        print(f"\n⚠️  No hay hojas para calificar en este curso todavía.")
        print(f"\n   👉 Coloca las FOTOS de los exámenes (tal como salen de la cámara")
        print(f"      o el celular) dentro de esta carpeta:\n")
        print(f"      {dir_crudos.resolve()}\n")
        print(f"   Luego vuelve a ejecutar 'python lector_omr.py': el lector las")
        print(f"   alineará automáticamente y las calificará en un solo paso.")
        sys.exit(1)

    # 5. Clave JSON: del curso y, como respaldo, de la raíz del profesor
    claves: dict[str, Path] = {}
    for clv in sorted(dir_claves.glob("*.json")) + sorted(ruta_prof.glob("*.json")):
        claves.setdefault(clv.name, clv)
    lista_claves = list(claves.values())

    ruta_json: Optional[Path] = None
    if lista_claves:
        i = _elegir(f"Paso 4 · {grado}°{curso}  |  Selecciona la CLAVE del examen",
                    [c.name for c in lista_claves], "Clave")
        if i is None:
            print("  ℹ️  Sin clave: se calificará en modo solo lectura.")
        else:
            ruta_json = lista_claves[i]
    else:
        print(f"\n⚠️  No hay claves JSON en '{dir_claves}'. Modo solo lectura.")

    return ruta_curso, dir_salida, ruta_json, imagenes


def calificar_curso() -> None:
    """Califica en lote todas las imágenes procesadas del curso elegido."""
    ruta_curso, dir_salida, ruta_json, imagenes = menu_profesores_local()
    dir_salida.mkdir(parents=True, exist_ok=True)

    # Datos del examen (para calcular aciertos y nombrar el registro)
    datos_examen = None
    if ruta_json:
        try:
            datos_examen = cargar_datos_examen(Path(ruta_json))
        except Exception:
            datos_examen = None
    examen = datos_examen.nombre if datos_examen else "sin_clave"

    print(f"\n{SEP2}")
    print(f"  📂  {len(imagenes)} hoja(s) para calificar")
    if ruta_json:
        print(f"  🔑  Clave: {ruta_json.name}")
    print(SEP2)

    ok = 0
    nuevos: list[dict] = []
    for n, img_path in enumerate(imagenes, start=1):
        print(f"\n  [{n}/{len(imagenes)}] {img_path.name}")
        try:
            res = _procesar_con_salida(img_path, ruta_json, dir_salida)
            ok += 1
            # Registrar la nota de esta hoja (se cruzará por código, no por orden)
            if datos_examen:
                aciertos = sum(1 for p, r in res.respuestas.items()
                               if r == datos_examen.clave.get(p))
                total = datos_examen.total_preguntas
            else:
                aciertos, total = 0, 0
            nuevos.append({
                "archivo": img_path.name,
                "codigo": res.codigo_estudiante,
                "aciertos": aciertos,
                "total": total,
            })
        except Exception as e:
            print(f"  ❌ Error en '{img_path.name}': {e}")

    # ── Persistir notas del examen (merge por archivo: re-calificar actualiza) ──
    notas_path = dir_salida / f"notas_{examen}.json"
    registros: dict[str, dict] = {}
    if notas_path.exists():
        try:
            for r in json.loads(notas_path.read_text(encoding="utf-8")):
                registros[r.get("archivo", "")] = r
        except Exception:
            pass
    for r in nuevos:
        registros[r["archivo"]] = r
    notas_path.write_text(
        json.dumps(list(registros.values()), indent=2, ensure_ascii=False),
        encoding="utf-8")

    print(f"\n  ✅ {ok}/{len(imagenes)} calificadas.")
    print(f"  📥 Resultados en: {dir_salida.resolve()}")

    # ── Generar el registro de notas (Excel) automáticamente ──────────────────
    try:
        import registro_notas as RN
        salida = RN.generar_registro(ruta_curso, examen)
        if salida:
            print(f"  📊 Registro de notas: {salida.resolve()}")
    except Exception as e:
        print(f"  ⚠️ No se pudo generar el registro de notas automáticamente: {e}")
        print("     Puedes generarlo aparte con: python registro_notas.py")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Lector OMR — Liceo Sahagún")
    parser.add_argument("imagen", nargs="?", default=None,
                        help="Foto a procesar. Si se omite, abre el menú por profesor.")
    parser.add_argument("json", nargs="?", default=None,
                        help="JSON con la clave de respuestas (opcional en modo directo).")
    args = parser.parse_args()

    if args.imagen:
        procesar(args.imagen, args.json)
    else:
        calificar_curso()


if __name__ == "__main__":
    main()