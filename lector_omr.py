"""
lector_omr.py — Motor de lectura de las hojas OMR (las que dibuja generador_pdf.py).

Estrategia:
  1. Detecta las 4 marcas de esquina (cuadrados negros) en la foto.
  2. Decide la orientación con la marca de orientación (la foto puede estar
     girada o de cabeza) y endereza la hoja con una homografía.
  3. Proyecta sobre la imagen enderezada las posiciones de layout_hoja.py.
  4. Binariza UNA sola vez (Otsu sobre el papel).
  5. Mide el relleno de cada burbuja y decide por contraste relativo.
  6. Lee el código del estudiante y compara con la clave.

La app (main.py) usa calificar_foto(): una foto → registro con la nota.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

import digitalizador as D
import layout_hoja as LH

# ─────────────────────────────────────────────────────────────────────────────
# Geometría de la hoja
# ─────────────────────────────────────────────────────────────────────────────
# Las posiciones de marcas y burbujas NO se definen aquí: salen de
# layout_hoja.py, el mismo archivo que usa generador_pdf.py para dibujar.
# Cada función recibe el formato de la hoja ("carta" o "media_carta");
# si no se indica, se asume "carta" (el formato original).

CM: float = LH.CM

# Escala de renderizado: píxeles por punto PDF (mayor = más preciso, más memoria)
RENDER_SCALE: float = 2.0

OPCIONES: tuple[str, ...] = LH.OPCIONES
LEER_CODIGO_ESTUDIANTE: bool = True
DIGITOS_CODIGO: int = LH.DIGITOS_CODIGO

# Dimensión máxima al cargar una foto (reduce fotos de celular sin perder precisión)
MAX_DIM: int = 2400

# Escala de calificación (lineal 0–10)
NOTA_MIN: float = 0.0
NOTA_MAX: float = 10.0
NOTA_APROBACION: float = 6.0
NOTA_PISO: float = 1.0   # ninguna nota baja de este valor (piso institucional)

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
    tenues:      list[int] = field(default_factory=list)  # relleno muy claro: SÍ cuenta, pero conviene mirar
    # Preguntas impresas en la hoja que NO son del examen (p. ej. 26 a 30 en un
    # examen de 25 hecho en hoja de 30) y que el estudiante marcó. No cuentan
    # para la nota, pero se avisa: puede que haya corrido sus respuestas.
    marcas_extra: list[int] = field(default_factory=list)
    preguntas_hoja: int = 0                                # preguntas impresas en la hoja
    # Qué tan bien calzó la cuadrícula de burbujas con la foto (0 a 1). Muy
    # bajo = la hoja fotografiada no es del formato que espera el examen.
    calce:       float = 1.0
    # False = ningún juego de marcas confirmó la marca de orientación (hoja
    # vieja que no la tiene, o algo raro): leer_foto prefiere otra lectura.
    orientacion_confirmada: bool = True
    # Posiciones de las burbujas ya ajustadas a la foto (ver _ajustar_bloques);
    # None = las del layout tal cual
    burbujas_codigo:    Optional[list[Burbuja]] = None
    burbujas_respuesta: Optional[list[Burbuja]] = None


@dataclass
class DatosExamen:
    nombre:          str
    total_preguntas: int
    clave:           dict[int, str]   # pregunta (1-based) → letra correcta
    formato:         str = "carta"    # formato de la hoja impresa (layout_hoja)
    # Preguntas que trae la hoja IMPRESA. Normalmente igual a total_preguntas;
    # mayor cuando se usa una hoja ya impresa con más preguntas (examen de 25
    # en hoja de 30): las que sobran se leen solo para avisar si se marcaron.
    preguntas_hoja:  int = 0

    def __post_init__(self):
        self.preguntas_hoja = LH.preguntas_en_hoja(self.total_preguntas,
                                                   self.preguntas_hoja, self.formato)


# ─────────────────────────────────────────────────────────────────────────────
# Geometría de la hoja (sale de layout_hoja.py)
# ─────────────────────────────────────────────────────────────────────────────

def esquinas_pdf(formato=None) -> np.ndarray:
    """
    Devuelve las 4 esquinas (centros de las marcas de referencia) en
    coordenadas de imagen PDF, orden: [arriba-izq, arriba-der, abajo-der, abajo-izq].
    """
    return np.float32(LH.obtener(formato).esquinas())


def calcular_burbujas(num_preguntas: int, formato=None) -> list[Burbuja]:
    """
    Calcula las posiciones de todas las burbujas de respuesta en
    coordenadas de imagen PDF (origen arriba-izquierda).
    """
    return [Burbuja(pregunta=i, opcion=opc, x_pt=x, y_pt=y)
            for i, opc, x, y in LH.obtener(formato).burbujas_respuesta(num_preguntas)]


def calcular_burbujas_codigo(formato=None) -> list[Burbuja]:
    """Calcula posiciones de burbujas del código de estudiante.
    En 'pregunta' va el índice de la columna (0, 1, 2)."""
    return [Burbuja(pregunta=col, opcion=dig, x_pt=x, y_pt=y)
            for col, dig, x, y in LH.obtener(formato).burbujas_codigo()]

# ─────────────────────────────────────────────────────────────────────────────
# Procesamiento de imagen
# ─────────────────────────────────────────────────────────────────────────────

def _mediana(img: np.ndarray) -> float:
    """np.median exacto, pero con un histograma: en imágenes uint8 es varias
    veces más rápido que ordenar millones de píxeles."""
    if img.dtype != np.uint8 or img.size == 0 or img.size >= 1 << 24:
        return float(np.median(img))
    # calcHist cuenta en float32: exacto mientras haya menos de 2^24 píxeles
    acum = np.cumsum(cv2.calcHist([img], [0], None, [256], [0, 256]).ravel().astype(np.int64))
    n = int(acum[-1])
    a = int(np.searchsorted(acum, (n - 1) // 2, side="right"))
    b = int(np.searchsorted(acum, n // 2, side="right"))
    return (a + b) / 2


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


# Relleno mínimo del rectángulo mínimo (girado) que encierra el blob. Las
# marcas son cuadradas (≈0.95 en fotos reales); una burbuja rellena es un
# círculo (≈0.78 = π/4) y antes se confundía con una marca de esquina.
RELLENO_CUADRADO: float = 0.85
# Segundo intento, más tolerante: una esquina doblada o curvada deforma la
# marca (≈0.81). Solo se acepta si además se confirma la marca de orientación.
RELLENO_CUADRADO_TOLERANTE: float = 0.78
# Al comprobar las marcas sobre la hoja enderezada (con luz pareja): un punto
# es "de la marca" si es más oscuro que esto × el papel. Con impresoras con
# poco tóner las marcas salen grises (0.5-0.7 del papel en fotos reales):
# con 0.6 se descartaban y la hoja no se leía.
FRACCION_MARCA: float = 0.75


@dataclass
class _Candidato:
    x: float
    y: float
    area: float
    cuadratura: float      # área / área del rectángulo mínimo (1 = cuadrado perfecto)


def _marcas_candidatos(bin_img: np.ndarray, pw: int,
                       cuadratura_min: float = RELLENO_CUADRADO) -> list[_Candidato]:
    """Blobs que parecen cuadrados negros sólidos, según un binario."""
    contornos, _ = cv2.findContours(bin_img, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
    area_min = (pw * 0.004) ** 2
    area_max = (pw * 0.060) ** 2
    out: list[_Candidato] = []
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
        (cx, cy), (rw, rh), _ = cv2.minAreaRect(cnt)
        cuadratura = area / max(rw * rh, 1e-6)
        if cuadratura < cuadratura_min:      # círculo relleno (burbuja), no marca
            continue
        out.append(_Candidato(float(cx), float(cy), float(area), float(cuadratura)))
    return out


def _combinaciones_por_zona(cands: list[_Candidato], px: int, py: int, pw: int, ph: int,
                            por_zona: int = 3) -> list[tuple[float, np.ndarray]]:
    """
    Busca, entre los candidatos cercanos a cada esquina del papel, las
    combinaciones de 4 que más parecen las marcas de la hoja: cuadradas,
    de tamaño parecido entre sí, y formando un cuadrilátero de lados opuestos
    parecidos. Devuelve [(puntaje, marcas)] de mejor a peor.

    Antes se tomaba sin más el candidato más cercano a cada esquina del papel:
    una mancha o un trozo de borde cerca de la esquina le ganaba a la marca real.
    """
    ZONA = 0.30
    zonas = [
        (px,      py,      px,               px + pw * ZONA, py,               py + ph * ZONA),
        (px + pw, py,      px + pw * (1 - ZONA), px + pw,     py,               py + ph * ZONA),
        (px + pw, py + ph, px + pw * (1 - ZONA), px + pw,     py + ph * (1 - ZONA), py + ph),
        (px,      py + ph, px,               px + pw * ZONA, py + ph * (1 - ZONA), py + ph),
    ]
    diag = float(np.hypot(pw, ph))
    por_esquina: list[list[tuple[_Candidato, float]]] = []
    for ref_x, ref_y, xmin, xmax, ymin, ymax in zonas:
        en_zona = [(c, float(np.hypot(c.x - ref_x, c.y - ref_y)) / diag) for c in cands
                   if xmin <= c.x <= xmax and ymin <= c.y <= ymax]
        if not en_zona:
            return []
        por_esquina.append(sorted(en_zona, key=lambda t: t[1])[:por_zona])

    import itertools
    out: list[tuple[float, np.ndarray]] = []
    for combo in itertools.product(*por_esquina):
        cs = [c for c, _ in combo]
        p = np.float32([[c.x, c.y] for c in cs])
        areas = [c.area for c in cs]
        disp_area = float(np.log(max(areas) / max(min(areas), 1e-6)))
        if disp_area > np.log(4.0):
            continue
        lados = [float(np.linalg.norm(p[(i + 1) % 4] - p[i])) for i in range(4)]
        if min(lados) < 1:
            continue
        r_h = abs(np.log(lados[0] / lados[2]))       # arriba vs abajo
        r_v = abs(np.log(lados[1] / lados[3]))       # derecha vs izquierda
        if max(r_h, r_v) > np.log(1.7):
            continue
        if not cv2.isContourConvex(p.reshape(-1, 1, 2)):
            continue
        puntaje = (float(np.mean([c.cuadratura for c in cs]))
                   - 0.25 * disp_area - 0.6 * (r_h + r_v)
                   - 0.3 * float(np.mean([d for _, d in combo])))
        out.append((puntaje, p))
    out.sort(key=lambda t: t[0], reverse=True)
    return out


def _binarios_marcas(img_gray: np.ndarray) -> tuple[tuple[int, int, int, int], list[np.ndarray]]:
    """
    Bounding box del papel + las binarizaciones (ya recortadas al papel y
    cerradas) donde se buscan las marcas. No dependen de la cuadratura
    exigida: se calculan una vez por foto y sirven para ambos intentos.
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
    cerrados = [cv2.morphologyEx(cv2.bitwise_and(b, mask), cv2.MORPH_CLOSE, kernel)
                for b in binarios]
    return (px, py, pw, ph), cerrados


# Lado de una marca de esquina respecto al lado mayor de la hoja (0.5 cm sobre
# 21.6 cm en media hoja, sobre 27.9 cm en hoja completa): para la "apertura".
LADO_MARCA_REL: float = 0.02


def _sin_grapas(binarios) -> tuple[tuple[int, int, int, int], list[np.ndarray]]:
    """
    Las mismas binarizaciones, pero "abiertas" (erosión + dilatación) con un
    cuadrado del orden de un tercio de la marca: borra todo lo DELGADO que
    toca a la marca (una grapa, un rayón, el borde de una sombra) y deja el
    cuadrado limpio, que vuelve a pasar por cuadrado. Es una segunda pasada:
    solo se usa si la foto no se pudo leer con las binarizaciones normales.
    """
    (px, py, pw, ph), cerrados = binarios
    lado = LADO_MARCA_REL * max(pw, ph)
    abiertos = []
    for fraccion in (0.25, 0.4):
        k = max(3, int(round(lado * fraccion))) | 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
        abiertos += [cv2.morphologyEx(c, cv2.MORPH_OPEN, kernel) for c in cerrados]
    return (px, py, pw, ph), abiertos


def candidatos_marcas(img_gray: np.ndarray, maximo: int = 6,
                      cuadratura_min: float = RELLENO_CUADRADO,
                      binarios=None) -> list[np.ndarray]:
    """
    Posibles juegos de 4 marcas de esquina, del más al menos creíble
    (sin repetidos). Prueba varias binarizaciones (Otsu, adaptativa para
    sombras, y umbrales fijos): tolera luz despareja, sombras y fondos de
    escritorio. Cada juego: array (4, 2) [arriba-izq, arriba-der, abajo-der,
    abajo-izq] según la FOTO.

    binarios: lo que devuelve _binarios_marcas(img_gray), para no repetirlo.
    """
    (px, py, pw, ph), cerrados = binarios or _binarios_marcas(img_gray)
    juegos: list[tuple[float, np.ndarray]] = []
    for closed in cerrados:
        candidatos = _marcas_candidatos(closed, pw, cuadratura_min)
        if len(candidatos) < 4:
            continue
        for puntaje, sel in _combinaciones_por_zona(candidatos, px, py, pw, ph):
            xs, ys = sel[:, 0], sel[:, 1]
            # Cordura: las 4 marcas deben abarcar buena parte del papel
            if (xs.max() - xs.min()) < pw * 0.45 or (ys.max() - ys.min()) < ph * 0.45:
                continue
            # La misma marca sale en varias binarizaciones: no repetir el juego
            if any(np.abs(sel - otro).max() < pw * 0.01 for _, otro in juegos):
                continue
            juegos.append((puntaje, sel))

    juegos.sort(key=lambda t: t[0], reverse=True)
    return [sel for _, sel in juegos[:maximo]]


def detectar_marcas(img_gray: np.ndarray) -> Optional[np.ndarray]:
    """El juego de 4 marcas más creíble (ver candidatos_marcas), o None."""
    juegos = candidatos_marcas(img_gray, maximo=1)
    return juegos[0] if juegos else None


def marcas_en_vivo(img_gray: np.ndarray, formato=None, a_fondo: bool = True
                   ) -> tuple[Optional[np.ndarray], list[tuple[float, float]]]:
    """
    Detección rápida para la vista previa de la cámara (cuadros pequeños,
    ~640 px): dice si YA se ven las 4 marcas de esquina, para tomar la foto
    con confianza. No lee nada ni cambia la calificación: la foto final pasa
    por leer_foto() como siempre.

    Devuelve (cuatro, sueltas):
      cuatro:  array (4, 2) con las 4 marcas [arriba-izq, arriba-der,
               abajo-der, abajo-izq] según el cuadro, o None si no están.
      sueltas: cuando no están las 4, los cuadrados negros que sí se ven
               cerca de las esquinas del papel [(x, y)], como guía.
    a_fondo=False se salta el segundo intento (escanear la hoja), que es
    varias veces más lento: la cámara lo alterna para no recalentar el celular.
    """
    f = LH.obtener(formato)
    binarios = _binarios_marcas(img_gray)
    marcas, confirmada = _cuatro_en_vivo(img_gray, f, binarios)
    if not _basta_en_vivo(confirmada, a_fondo):
        # Se busca un juego con la orientación confirmada; uno sin confirmar
        # (hoja vieja, o el cuadrito tomado como esquina) queda de reserva.
        intentos = (
            # Una grapa o un rayón pegado a una marca: se "limpian"
            lambda: _cuatro_en_vivo(img_gray, f, _sin_grapas(binarios)),
            # Igual que leer_foto: con sombra fuerte las marcas se pierden en la
            # foto tal cual, pero aparecen al "escanear" la hoja (recortada y
            # con luz pareja)
            lambda: _cuatro_en_vivo_escaneada(img_gray, f),
        )
        for intento in intentos:
            try:
                otras, conf = intento()
            except Exception:
                continue
            if otras is not None and (conf or marcas is None):
                marcas, confirmada = otras, conf
            if confirmada:
                break
    if marcas is not None:
        return marcas, []

    # Sin las 4: lo mejor que se ve cerca de cada esquina del papel
    (px, py, pw, ph), cerrados = binarios
    esquinas = [(px, py), (px + pw, py), (px + pw, py + ph), (px, py + ph)]
    radio = 0.22 * float(np.hypot(pw, ph))
    mejor: list[_Candidato] = []
    for cerrado in cerrados:
        cands = _marcas_candidatos(cerrado, pw)
        vistas = []
        for ex, ey in esquinas:
            cerca = [c for c in cands if np.hypot(c.x - ex, c.y - ey) < radio]
            if cerca:
                vistas.append(max(cerca, key=lambda c: c.cuadratura))
        # Las marcas son del mismo tamaño: lo que no se parece al resto es ruido
        if len(vistas) >= 2:
            area = float(np.median([c.area for c in vistas]))
            vistas = [c for c in vistas if area / 2.5 <= c.area <= area * 2.5]
        if len(vistas) > len(mejor):
            mejor = vistas
    return None, [(c.x, c.y) for c in mejor]


def _basta_en_vivo(confirmada: bool, a_fondo: bool) -> bool:
    """Para marcas_en_vivo: ¿basta con lo encontrado? Sí si la orientación
    está confirmada, o si en este cuadro no toca el intento a fondo."""
    return confirmada or not a_fondo


def _cuatro_en_vivo(img_gray: np.ndarray, f: LH.Formato,
                    binarios=None) -> tuple[Optional[np.ndarray], bool]:
    """(marcas, orientación confirmada): el primer juego de 4 marcas que pasa
    la comprobación, o (None, False).
    Se prefiere el que tiene la marca de orientación en su lugar; si un
    juego solo calza tomando la marca de orientación como esquina (una grapa
    tapó la de verdad), se devuelve con la esquina tapada ya reconstruida.
    Si nada confirma la orientación, el primero verificado (hoja vieja)."""
    binarios = binarios or _binarios_marcas(img_gray)
    primera = None
    for cuadratura_min in (RELLENO_CUADRADO, RELLENO_CUADRADO_TOLERANTE):
        for marcas in candidatos_marcas(img_gray, maximo=3,
                                        cuadratura_min=cuadratura_min,
                                        binarios=binarios):
            ok, confirmada = _marcas_en_vivo_verificadas(img_gray, marcas, f)
            if ok and confirmada:
                return marcas, True
            reales = _esquina_tapada(img_gray, marcas, f)
            if reales is not None:
                return reales, True
            if ok and primera is None:
                primera = marcas      # hoja vieja, sin marca de orientación
    return primera, False


def _cuatro_en_vivo_escaneada(img_gray: np.ndarray, f: LH.Formato
                              ) -> tuple[Optional[np.ndarray], bool]:
    """Busca las 4 marcas sobre la hoja recortada y con luz pareja (como hace
    el digitalizador) y las devuelve en coordenadas del cuadro original,
    con si se confirmó la orientación."""
    esquinas = D.detectar_hoja(cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR))
    if esquinas is None:
        return None, False
    tl, tr, br, bl = D.ordenar_esquinas(esquinas)
    ancho = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    alto = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if ancho < 50 or alto < 50:
        return None, False
    destino = np.float32([[0, 0], [ancho - 1, 0], [ancho - 1, alto - 1], [0, alto - 1]])
    M = cv2.getPerspectiveTransform(np.float32([tl, tr, br, bl]), destino)
    hoja = cv2.warpPerspective(img_gray, M, (ancho, alto),
                               borderMode=cv2.BORDER_REPLICATE)
    hoja = D.aplanar_iluminacion(hoja)
    marcas, confirmada = _cuatro_en_vivo(hoja, f)
    if marcas is None:
        return None, False
    return cv2.perspectiveTransform(marcas.reshape(1, 4, 2).astype(np.float32),
                                    np.linalg.inv(M)).reshape(4, 2), confirmada


def _marcas_en_vivo_verificadas(img_gray: np.ndarray, marcas: np.ndarray,
                                f: LH.Formato) -> tuple[bool, bool]:
    """Endereza el cuadro a 1 px/pt (pequeño y rápido) y comprueba que en las
    4 esquinas haya un cuadrado negro rodeado de papel.
    Devuelve (verificadas, orientación confirmada)."""
    try:
        orden = _orientar_marcas(img_gray, marcas, f)
        M = cv2.getPerspectiveTransform(orden, esquinas_pdf(f))
        recta = cv2.warpPerspective(img_gray, M, (int(f.ancho), int(f.alto)))
        gris = _gris_aplanado(recta, 1.0)
        if not (_marcas_verificadas(recta, 1.0, f.clave, gris)
                and _calce_codigo(gris, f) >= CALCE_SEGURO):
            return False, False
        return True, _orientacion_confirmada(recta, 1.0, f.clave, gris)
    except Exception:
        return False, False


def _calce_codigo(gris_1pt: np.ndarray, f: LH.Formato) -> float:
    """Qué tan bien calzan los círculos del CÓDIGO con la hoja enderezada a
    1 px/pt (0 a 1). Es la prueba final de que las 4 marcas son las de
    verdad: medido en fotos reales y simuladas, con las marcas correctas da
    0.43-0.69; con un juego equivocado (el cuadrito de orientación tomado
    como esquina, burbujas en una sombra), 0.26 o menos. Es pequeño y rápido."""
    oscuro = cv2.GaussianBlur(255 - gris_1pt, (3, 3), 0)
    _, calce = _ajustar_bloques(oscuro, calcular_burbujas_codigo(f), lambda b: 0,
                                1.0, f.radio)
    return calce


def _esquina_tapada(img_gray: np.ndarray, marcas: np.ndarray,
                    f: LH.Formato) -> Optional[np.ndarray]:
    """
    ¿Una grapa (o un dedo, o un doblez) tapó la marca superior-izquierda y lo
    que se tomó como esa esquina es en realidad la marca de orientación, que
    está justo debajo? Pasa con las hojas engrapadas: la marca deja de verse
    cuadrada y la de orientación, casi del mismo tamaño, le gana. Si se lee
    así, la cuadrícula queda corrida casi una fila y las respuestas no calzan.

    La hoja tiene 5 puntos de referencia (4 esquinas + orientación) y para
    enderezarla bastan 4. Se prueba la hipótesis "estos 4 puntos son la
    marca de orientación y las otras 3 esquinas", en los 4 giros: se acepta
    si las 3 esquinas son marcas de verdad, la esquina tapada es oscura (la
    marca, con la grapa encima), la orientación se confirma y los círculos
    del código calzan (ver _calce_codigo).

    Devuelve las 4 esquinas REALES en la foto [arriba-izq, arriba-der,
    abajo-der, abajo-izq] (la tapada, reconstruida), o None.
    """
    gray = cv2.cvtColor(img_gray, cv2.COLOR_BGR2GRAY) if img_gray.ndim == 3 else img_gray
    esquinas = esquinas_pdf(f)
    destino = esquinas.copy()
    ox, oy, _ = f.orientacion()
    destino[0] = (ox, oy)
    p = marcas.astype(np.float32)
    for g in range(4):
        cand = np.roll(p, -g, axis=0)
        try:
            M = cv2.getPerspectiveTransform(cand, destino)
            recta = cv2.warpPerspective(gray, M, (int(f.ancho), int(f.alto)))
        except cv2.error:
            continue
        gris = _gris_aplanado(recta, 1.0)
        if not (_marcas_verificadas(recta, 1.0, f.clave, gris, tapada=True)
                and _orientacion_confirmada(recta, 1.0, f.clave, gris)
                and _calce_codigo(gris, f) >= CALCE_SEGURO):
            continue
        try:
            inv = np.linalg.inv(M)
        except np.linalg.LinAlgError:
            continue
        return cv2.perspectiveTransform(esquinas.reshape(1, 4, 2), inv).reshape(4, 2)
    return None


def _relleno_cuadro(gray: np.ndarray, cx: float, cy: float, lado: float,
                    scale: float, umbral: float) -> float:
    """Fracción de píxeles oscuros en el centro de un cuadro (coords en pt)."""
    h = max(2, int(lado * scale * 0.3))
    x, y = int(cx * scale), int(cy * scale)
    roi = gray[max(0, y - h):y + h + 1, max(0, x - h):x + h + 1]
    return float(np.mean(roi < umbral)) if roi.size else 0.0


def _orientar_marcas(img: np.ndarray, marcas: np.ndarray, f: LH.Formato) -> np.ndarray:
    """
    Reordena las 4 marcas detectadas para que la primera sea la esquina
    superior-izquierda REAL de la hoja, aunque la foto esté girada o de cabeza.

    detectar_marcas() las devuelve según su posición en la FOTO. Si la hoja
    está girada 90° (p. ej. media hoja horizontal fotografiada con el celular
    vertical) o 180°, ese orden no corresponde al de la hoja.
      1. La forma del cuadrilátero dice si la hoja está derecha/de cabeza
         o girada de lado.
      2. Entre esas dos opciones, la marca de orientación (cuadrito bajo la
         marca superior-izquierda) decide. Las hojas viejas no la tienen: en
         ese caso se deja el orden tal cual, como siempre.
    """
    p = marcas.astype(np.float32)
    ancho_q = (np.linalg.norm(p[1] - p[0]) + np.linalg.norm(p[2] - p[3])) / 2
    alto_q = (np.linalg.norm(p[3] - p[0]) + np.linalg.norm(p[2] - p[1])) / 2
    esq = f.esquinas()
    prop_f = (esq[1][0] - esq[0][0]) / (esq[3][1] - esq[0][1])
    prop_q = ancho_q / max(alto_q, 1e-6)
    de_lado = abs(np.log(1 / prop_q / prop_f)) < abs(np.log(prop_q / prop_f))
    giros = (1, 3) if de_lado else (0, 2)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    ox, oy, lado = f.orientacion()
    destino = esquinas_pdf(f)                      # escala 1 px/pt: basta para revisar
    mejor, mejor_dif = giros[0], 0.0
    for g in giros:
        cand = np.roll(p, -g, axis=0)
        M = cv2.getPerspectiveTransform(cand, destino)
        w = cv2.warpPerspective(gray, M, (int(f.ancho), int(f.alto)))
        w = D.aplanar_iluminacion(w, int(1.1 * CM))
        umbral = FRACCION_MARCA * _mediana(w)
        dentro = _relleno_cuadro(w, ox, oy, lado, 1.0, umbral)
        opuesto = _relleno_cuadro(w, f.ancho - ox, f.alto - oy, lado, 1.0, umbral)
        if dentro >= 0.6 and dentro - opuesto > max(0.4, mejor_dif):
            mejor, mejor_dif = g, dentro - opuesto
    return np.roll(p, -mejor, axis=0)


def corregir_perspectiva(img: np.ndarray,
                         marcas_detectadas: np.ndarray,
                         formato=None) -> tuple[np.ndarray, float]:
    """
    Aplica homografía para proyectar la hoja fotografiada al espacio PDF,
    corrigiendo también si la foto está girada o de cabeza.

    Returns:
        Tupla (imagen_corregida_BGR, escala_px_por_pt).
    """
    f = LH.obtener(formato)
    dst_w = int(f.ancho * RENDER_SCALE)
    dst_h = int(f.alto * RENDER_SCALE)
    marcas_destino = esquinas_pdf(f) * RENDER_SCALE
    marcas_detectadas = _orientar_marcas(img, marcas_detectadas, f)

    M, _ = cv2.findHomography(marcas_detectadas, marcas_destino,
                               cv2.RANSAC, 5.0)
    if M is None:
        raise ValueError("No se pudo calcular la homografía con las marcas detectadas.")

    warped = cv2.warpPerspective(img, M, (dst_w, dst_h))
    return warped, RENDER_SCALE


FRACCION_PAPEL: float = 0.80   # más oscuro que esto (× brillo del papel) = marcado


def binarizar(img_gray: np.ndarray,
              bbox_papel: Optional[tuple[int,int,int,int]] = None,
              fraccion_papel: Optional[float] = None) -> np.ndarray:
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
    # Otsu separa papel de TINTA NEGRA: un relleno con lápiz suave o brillante
    # queda gris claro y caía del lado del papel (la burbuja parecía vacía).
    # Con la luz ya aplanada, todo lo que esté por debajo del 80 % del brillo
    # del papel cuenta como marca.
    if fraccion_papel is None:
        fraccion_papel = FRACCION_PAPEL
    umbral = max(float(umbral), fraccion_papel * _mediana(blurred_zona))

    # Aplicar umbral calculado a la imagen completa
    blurred = cv2.GaussianBlur(img_gray, (3, 3), 0)
    _, binaria = cv2.threshold(blurred, int(umbral), 255, cv2.THRESH_BINARY_INV)
    return binaria


def medir_fill_burbuja(binaria: np.ndarray,
                        x_pt: float, y_pt: float,
                        scale: float,
                        radio_pt: float = LH.CARTA.radio) -> float:
    """
    Mide la fracción de píxeles oscuros dentro de una burbuja.

    Args:
        binaria: Imagen ya binarizada (INV: oscuro = marcado = 255).
        x_pt, y_pt: Centro en puntos PDF.
        scale: Píxeles por punto PDF.
        radio_pt: Radio de la burbuja impresa, en puntos PDF.

    Returns:
        Fracción [0.0, 1.0] de píxeles marcados dentro del círculo.
    """
    cx = int(x_pt * scale)
    cy = int(y_pt * scale)
    r  = max(2, int(radio_pt * scale * 0.85))

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

AJUSTE_MAX_CM: float = 0.35   # corrimiento máximo que se busca por bloque de burbujas


def _ajustar_bloques(oscuro: np.ndarray, burbujas: list[Burbuja], bloque_de,
                     scale: float, radio_pt: float) -> tuple[list[Burbuja], float]:
    """
    Corre cada bloque de burbujas (el código, cada columna de preguntas) a
    donde de verdad están los círculos impresos en la foto.

    La homografía de las 4 marcas es exacta para una hoja PLANA; si la hoja
    está curvada, arrugada o con una esquina doblada, la cuadrícula queda
    corrida unos píxeles y las burbujas se miden sobre el borde. Para cada
    bloque se dibuja un "molde" con sus círculos y se busca (matchTemplate)
    el corrimiento que mejor calza dentro de ±AJUSTE_MAX_CM.

    oscuro: imagen en gris invertida (tinta = valores altos).

    Devuelve (burbujas ajustadas, calce): calce es el mejor parecido (0 a 1)
    entre el molde y la foto en el bloque que mejor calzó.
    """
    bloques: dict = {}
    for b in burbujas:
        bloques.setdefault(bloque_de(b), []).append(b)

    m = max(2, int(AJUSTE_MAX_CM * CM * scale))
    r = max(3, int(round(radio_pt * scale)))
    grosor = max(1, int(round(0.6 * scale)))
    h_img, w_img = oscuro.shape
    out: list[Burbuja] = []
    calce = -1.0            # -1 = ningún bloque se pudo comparar
    for bs in bloques.values():
        xs = [b.x_pt * scale for b in bs]
        ys = [b.y_pt * scale for b in bs]
        x0, y0 = int(min(xs)) - r - 2, int(min(ys)) - r - 2
        x1, y1 = int(max(xs)) + r + 3, int(max(ys)) + r + 3
        dx = dy = 0
        if x0 - m >= 0 and y0 - m >= 0 and x1 + m <= w_img and y1 + m <= h_img:
            molde = np.zeros((y1 - y0, x1 - x0), np.uint8)
            for x, y in zip(xs, ys):
                cv2.circle(molde, (int(x) - x0, int(y) - y0), r, 255, grosor, cv2.LINE_AA)
            zona = oscuro[y0 - m:y1 + m, x0 - m:x1 + m]
            res = cv2.matchTemplate(zona, molde, cv2.TM_CCOEFF_NORMED)
            _, mejor, _, (bx, by) = cv2.minMaxLoc(res)
            calce = max(calce, float(mejor))
            # Si los círculos no se reconocen bien, mejor no mover nada
            if mejor > 0.25:
                dx, dy = bx - m, by - m
        out.extend(Burbuja(b.pregunta, b.opcion, b.x_pt + dx / scale, b.y_pt + dy / scale)
                   for b in bs)
    return out, (calce if calce >= 0 else 1.0)


UMBRAL_RANGO:        float = 0.05   # contraste mínimo para considerar una marca válida
UMBRAL_RANGO_DUDOSO: float = 0.04   # contraste en zona gris: posible X fina o trazo débil
# Segunda pasada, solo para filas que salieron en blanco: un relleno con lápiz
# brillante puede verse gris muy claro y moteado. Con un umbral más sensible
# se acepta si UNA burbuja destaca con claridad sobre las demás.
# Calibrado con fotos reales: las filas vacías llegan a un margen de 0.09 (sombras,
# arrugas); un relleno claro real, a 0.20-0.29. Más sensible inventa respuestas.
FRACCION_TENUE:      float = 0.85
FILL_TENUE:          float = 0.50
RANGO_TENUE:         float = 0.15
FILL_MARCA:          float = 0.45   # relleno mínimo para que una burbuja cuente como marcada
RAZON_DOBLE:         float = 0.75   # la 2.ª marca debe contrastar al menos esto × la 1.ª
FILL_DOBLE:          float = 0.70   # y estar al menos así de rellena (un borrón o sombra no llega)


def _clasificar_fila(fills_fila: dict[str, float]) -> tuple[str, Optional[str]]:
    """
    Decide qué opción está marcada en una fila de burbujas.

    Devuelve (estado, opcion) con estado en:
      "ok"     → una sola opción destacada (opcion = esa letra/dígito)
      "doble"  → dos o más opciones claramente rellenas
      "dudosa" → hay algo marcado pero el trazo es débil
      "blanco" → nada marcado

    La doble marca se mide contra la burbuja MÁS VACÍA de la fila: si la segunda
    más rellena también contrasta fuerte con ella (al menos la mitad que la
    primera), son dos marcas. Así un borrón leve no cuenta como doble marca,
    pero dos círculos rellenos sí (antes se leían como "en blanco").
    """
    orden = sorted(fills_fila.items(), key=lambda x: x[1], reverse=True)
    f_max = orden[0][1]
    f_seg = orden[1][1] if len(orden) > 1 else 0.0
    f_min = orden[-1][1]

    # Una burbuja vacía nunca llega a FILL_MARCA (solo tiene la letra
    # impresa); sin eso, las arrugas y sombras de una fila vacía se leían
    # como "doble marca" o como una respuesta.
    if f_max < FILL_MARCA:
        return "blanco", None

    contraste_1 = f_max - f_min
    contraste_2 = f_seg - f_min
    if (len(orden) > 1 and f_seg >= FILL_DOBLE
            and contraste_2 >= max(UMBRAL_RANGO, RAZON_DOBLE * contraste_1)):
        return "doble", None

    rango = f_max - f_seg
    if rango < UMBRAL_RANGO:
        return "dudosa", None
    return "ok", orden[0][0]


def leer_respuestas(img_bgr: np.ndarray,
                    num_preguntas: int,
                    scale: float,
                    formato=None,
                    gris=None,
                    preguntas_hoja: Optional[int] = None) -> ResultadoLectura:
    """
    Lee todas las burbujas de la imagen corregida en un único pase.

    Lógica de detección por rango (max − segundo_mayor):
      Si la diferencia entre el fill más alto y el segundo más alto de una fila
      supera UMBRAL_RANGO, se considera que hay una burbuja marcada (la de mayor fill).
      Si todos los fills son similares → en blanco.
      Si hay dos candidatos que superan el umbral → doble marca.

      Esta estrategia es robusta ante variaciones de iluminación y fondos oscuros
      porque no depende de un umbral absoluto sino de contraste relativo entre opciones.

    gris: _gris_aplanado(img_bgr, scale) si ya se calculó.
    preguntas_hoja: preguntas IMPRESAS en la hoja, si son más que las del
      examen. Las que sobran no entran en 'respuestas': solo se revisa si el
      estudiante marcó alguna (marcas_extra).
    """
    f = LH.obtener(formato)
    n_hoja = LH.preguntas_en_hoja(num_preguntas, preguntas_hoja, f)
    # Luz pareja antes de binarizar: con un solo umbral para toda la hoja, una
    # sombra hacía que las burbujas vacías de la zona oscura parecieran rellenas.
    # El kernel (1.1 cm) es mayor que una burbuja rellena y que las marcas.
    img_gray  = _gris_aplanado(img_bgr, scale) if gris is None else gris
    bbox_papel = _detectar_bbox_hoja(img_gray)
    binaria    = binarizar(img_gray, bbox_papel)   # ← Otsu sobre el papel, no el fondo
    oscuro     = cv2.GaussianBlur(255 - img_gray, (3, 3), 0)

    # 1. Leer código del estudiante
    codigo_leido = ""
    burbujas_cod = None
    if LEER_CODIGO_ESTUDIANTE:
        burbujas_cod, calce_cod = _ajustar_bloques(oscuro, calcular_burbujas_codigo(f),
                                                   lambda b: "codigo", scale, f.radio)
        por_columna: dict[int, list[Burbuja]] = {}
        for b in burbujas_cod:
            por_columna.setdefault(b.pregunta, []).append(b)
        
        for col in range(DIGITOS_CODIGO):
            fills_col = {b.opcion: medir_fill_burbuja(binaria, b.x_pt, b.y_pt, scale, f.radio)
                         for b in por_columna[col]}
            # Mismo criterio estricto que las respuestas: un dígito solo se
            # acepta si destaca con claridad; doble marca o trazo débil → "?"
            estado, digito = _clasificar_fila(fills_col)
            codigo_leido += digito if estado == "ok" else "?"
    else:
        codigo_leido = "N/A"
        calce_cod = 1.0

    # 2. Leer respuestas
    # Se arma el molde con TODAS las preguntas impresas (no solo las del
    # examen): así cada columna calza con sus círculos completos.
    burbujas, calce_resp = _ajustar_bloques(
        oscuro, calcular_burbujas(n_hoja, f),
        lambda b: (b.pregunta - 1) // f.filas_por_columna, scale, f.radio)
    por_pregunta: dict[int, list[Burbuja]] = {}
    for b in burbujas:
        por_pregunta.setdefault(b.pregunta, []).append(b)

    respuestas:  dict[int, Optional[str]]       = {}
    fills:       dict[int, dict[str, float]]    = {}
    en_blanco:   list[int]                      = []
    doble_marca: list[int]                      = []
    dudosas:     list[int]                      = []
    tenues:      list[int]                      = []
    marcas_extra: list[int]                     = []
    binaria_tenue: Optional[np.ndarray]         = None

    for num_p in sorted(por_pregunta):
        fills_fila = {
            b.opcion: medir_fill_burbuja(binaria, b.x_pt, b.y_pt, scale, f.radio)
            for b in por_pregunta[num_p]
        }
        estado, opcion = _clasificar_fila(fills_fila)
        if num_p > num_preguntas:
            # Pregunta impresa que no es de este examen: no cuenta. Solo se
            # avisa si tiene una marca clara (una dudosa aquí no interesa).
            if estado in ("ok", "doble"):
                marcas_extra.append(num_p)
            continue
        fills[num_p] = fills_fila
        if estado == "blanco":
            if binaria_tenue is None:
                binaria_tenue = binarizar(img_gray, bbox_papel, FRACCION_TENUE)
            suaves = sorted(((medir_fill_burbuja(binaria_tenue, b.x_pt, b.y_pt, scale, f.radio),
                              b.opcion) for b in por_pregunta[num_p]), reverse=True)
            if suaves[0][0] >= FILL_TENUE and suaves[0][0] - suaves[1][0] >= RANGO_TENUE:
                estado, opcion = "tenue", suaves[0][1]
        respuestas[num_p] = opcion
        if estado == "tenue":
            tenues.append(num_p)
        elif estado == "blanco":
            en_blanco.append(num_p)
        elif estado == "dudosa":
            # Trazo débil (posible X, visto, borrado): no cuenta, se alerta al docente
            dudosas.append(num_p)
        elif estado == "doble":
            doble_marca.append(num_p)

    return ResultadoLectura(
        respuestas  = respuestas,
        fills       = fills,
        codigo_estudiante=codigo_leido,
        en_blanco   = en_blanco,
        doble_marca = doble_marca,
        dudosas     = dudosas,
        tenues      = tenues,
        marcas_extra = marcas_extra,
        preguntas_hoja = n_hoja,
        calce       = max(calce_cod, calce_resp),
        burbujas_codigo    = burbujas_cod,
        burbujas_respuesta = burbujas,
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


ALTO_PANEL: int = 195   # alto (px) de la franja de resultado bajo la hoja


def _dibujar_panel_resultado(img: np.ndarray,
                              correctas: int,
                              total: int,
                              en_blanco: list[int],
                              doble_marca: list[int],
                              dudosas: list[int],
                              nombre_examen: str,
                              codigo_estudiante: str,
                              tenues: Optional[list[int]] = None,
                              marcas_extra: Optional[list[int]] = None) -> np.ndarray:
    """
    Dibuja un panel semitransparente en la parte inferior de la imagen
    con: nombre del examen, aciertos, nota final y alertas.
    """
    h, w = img.shape[:2]
    nota  = _calcular_nota(correctas, total)
    aprueba = nota >= NOTA_APROBACION

    # ── Dimensiones del panel ────────────────────────────────────────
    PANEL_H    = ALTO_PANEL # código de estudiante + hasta 5 líneas de alertas
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
        sufijo = "..." if len(en_blanco) > 10 else ""
        cv2.putText(img, f"Sin resp: {nums}{sufijo}", (PADDING + 10, y_alerta),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (80, 200, 255), 1, cv2.LINE_AA)
        y_alerta += 20
    if doble_marca:
        nums = ", ".join(str(n) for n in doble_marca[:10])
        sufijo = "..." if len(doble_marca) > 10 else ""
        cv2.putText(img, f"Doble marca: {nums}{sufijo}", (PADDING + 10, y_alerta),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (60, 160, 255), 1, cv2.LINE_AA)
        y_alerta += 20
    if dudosas:
        nums = ", ".join(str(n) for n in dudosas[:10])
        sufijo = "..." if len(dudosas) > 10 else ""
        cv2.putText(img, f"REVISAR: preg. {nums}{sufijo} - marca debil, verificar",
                    (PADDING + 10, y_alerta),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 165, 255), 1, cv2.LINE_AA)
        y_alerta += 20
    if tenues:
        nums = ", ".join(str(n) for n in tenues[:10])
        sufijo = "..." if len(tenues) > 10 else ""
        cv2.putText(img, f"Marca tenue (contada, verificar): {nums}{sufijo}",
                    (PADDING + 10, y_alerta),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 220, 255), 1, cv2.LINE_AA)
        y_alerta += 20
    if marcas_extra:
        nums = ", ".join(str(n) for n in marcas_extra[:10])
        sufijo = "..." if len(marcas_extra) > 10 else ""
        cv2.putText(img, f"Marco fuera del examen (no cuenta): {nums}{sufijo}",
                    (PADDING + 10, y_alerta),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 165, 255), 1, cv2.LINE_AA)

    return img


def _velar_sobrantes(img: np.ndarray, sobrantes: dict[int, list[Burbuja]],
                     marcadas: set[int], f: LH.Formato, scale: float) -> None:
    """Sobre la hoja anotada, tapa con un velo gris las preguntas impresas
    que no son del examen (un bloque por columna) y resalta en naranja las
    que el estudiante marcó de todos modos."""
    r_px = max(3, int(f.radio * scale))
    columnas: dict[int, list[Burbuja]] = {}
    for p, bbs in sobrantes.items():
        columnas.setdefault((p - 1) // f.filas_por_columna, []).extend(bbs)
    velo = img.copy()
    cajas = []
    for bbs in columnas.values():
        xs = [b.x_pt * scale for b in bbs]
        ys = [b.y_pt * scale for b in bbs]
        x0 = int(min(xs) - f.sep_numero * scale - r_px)
        x1 = int(max(xs) + 2 * r_px)
        y0 = int(min(ys) - 0.5 * f.esp_y * scale)
        y1 = int(max(ys) + 0.5 * f.esp_y * scale)
        cv2.rectangle(velo, (x0, y0), (x1, y1), (225, 225, 225), -1)
        cajas.append((x0, y0, x1, y1))
    cv2.addWeighted(velo, 0.62, img, 0.38, 0, img)
    for x0, y0, x1, y1 in cajas:
        cv2.rectangle(img, (x0, y0), (x1, y1), (150, 150, 150), 1, cv2.LINE_AA)
        # Rótulo a la derecha del bloque (o encima, si no cabe): no tapa burbujas
        (tw, th), _ = cv2.getTextSize("NO CUENTAN", cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        if x1 + 10 + tw < img.shape[1]:
            donde = (x1 + 10, (y0 + y1 + th) // 2)
        else:
            donde = (x0, y0 - 6)
        cv2.putText(img, "NO CUENTAN", donde, cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 120, 230), 1, cv2.LINE_AA)
    for p in marcadas:
        for b in sobrantes.get(p, []):
            cv2.circle(img, (int(b.x_pt * scale), int(b.y_pt * scale)), r_px,
                       (0, 140, 255), 2, cv2.LINE_AA)


def dibujar_anotaciones(img_bgr:       np.ndarray,
                         resultado:     ResultadoLectura,
                         clave:         Optional[dict[int, str]],
                         scale:         float,
                         nombre_examen: str = "",
                         formato=None) -> np.ndarray:
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
    f = LH.obtener(formato)
    debug = img_bgr.copy()
    r_px      = max(3, int(f.radio * scale))

    # Dibujar Cuadrícula de Estudiante
    if LEER_CODIGO_ESTUDIANTE:
        burbujas_cod = resultado.burbujas_codigo or calcular_burbujas_codigo(f)
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
    burbujas_preg: list[Burbuja] = (resultado.burbujas_respuesta
                                    or calcular_burbujas(len(resultado.respuestas), f))
    por_pregunta: dict[int, list[Burbuja]] = {}
    for b in burbujas_preg:
        por_pregunta.setdefault(b.pregunta, []).append(b)

    # Preguntas impresas que no son de este examen (hoja con más preguntas
    # que el examen): se tapan con un velo gris y se rotulan, para que al
    # mirar la hoja quede claro que no se calificaron.
    sobrantes = {p: bbs for p, bbs in por_pregunta.items()
                 if p not in resultado.respuestas}
    if sobrantes:
        _velar_sobrantes(debug, sobrantes, set(resultado.marcas_extra), f, scale)

    correctas = 0

    for num_p, bbs in sorted(por_pregunta.items()):
        if num_p in sobrantes:
            continue
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
    esquinas = esquinas_pdf(f) * scale
    for pt in esquinas:
        cv2.circle(debug, (int(pt[0]), int(pt[1])), 15, (100, 255, 100), 2, cv2.LINE_AA)

    # Dibujar panel inferior en una franja AGREGADA debajo de la hoja, para que
    # no tape las últimas filas (en la media hoja quedaban ocultas)
    debug = cv2.copyMakeBorder(debug, 0, ALTO_PANEL, 0, 0, cv2.BORDER_CONSTANT,
                               value=(20, 20, 20))
    total_preg = len(clave) if clave else len(resultado.respuestas)
    _dibujar_panel_resultado(
        debug, correctas, total_preg,
        resultado.en_blanco, resultado.doble_marca, resultado.dudosas,
        nombre_examen, resultado.codigo_estudiante, resultado.tenues,
        resultado.marcas_extra
    )

    return debug


# ─────────────────────────────────────────────────────────────────────────────
# Manejo de archivos e I/O
# ─────────────────────────────────────────────────────────────────────────────

MENSAJE_SIN_MARCAS = ("No se vieron las 4 marcas negras de las esquinas. "
                      "Repite la foto con la hoja completa y buena luz.")


def _gris_aplanado(recta: np.ndarray, scale: float) -> np.ndarray:
    """Hoja enderezada en gris y con luz pareja (kernel 1.1 cm): la base de
    las verificaciones y de la lectura de burbujas."""
    gray = cv2.cvtColor(recta, cv2.COLOR_BGR2GRAY) if recta.ndim == 3 else recta
    return D.aplanar_iluminacion(gray, int(1.1 * CM * scale))


def _orientacion_confirmada(recta: np.ndarray, scale: float, formato=None,
                            gris=None) -> bool:
    """La marca de orientación está bajo la esquina superior-izquierda (y no
    en la opuesta) de la hoja ya enderezada. Las hojas viejas no la tienen.
    gris: _gris_aplanado(recta, scale) si ya se calculó."""
    f = LH.obtener(formato)
    gray = _gris_aplanado(recta, scale) if gris is None else gris
    umbral = FRACCION_MARCA * _mediana(gray)
    ox, oy, lado = f.orientacion()
    dentro = _relleno_cuadro(gray, ox, oy, lado, scale, umbral)
    opuesto = _relleno_cuadro(gray, f.ancho - ox, f.alto - oy, lado, scale, umbral)
    return dentro >= 0.6 and dentro - opuesto > 0.4


def _marcas_verificadas(recta: np.ndarray, scale: float, formato=None,
                        gris=None, tapada: bool = False) -> bool:
    """
    Sobre la hoja ya enderezada, comprueba que en las 4 esquinas haya de
    verdad un cuadrado negro rodeado de papel blanco. Si las "marcas" eran
    otra cosa (burbujas, manchas, un trozo de borde), la hoja enderezada sale
    deformada y esto falla, en vez de calificar con la cuadrícula corrida.

    tapada=True: la esquina superior-izquierda puede tener una grapa encima
    (ver _esquina_tapada). Ahí solo se pide que sea oscura y que alrededor
    haya sobre todo papel (la grapa es delgada; la mesa, no).
    """
    f = LH.obtener(formato)
    gray = _gris_aplanado(recta, scale) if gris is None else gris
    umbral = FRACCION_MARCA * _mediana(gray)
    oscuro = gray < umbral
    tam = f.tam_marca * scale
    for i, (cx, cy) in enumerate(esquinas_pdf(f) * scale):
        x, y = int(cx), int(cy)

        def caja(semi):
            s = max(1, int(semi))
            return oscuro[max(0, y - s):y + s + 1, max(0, x - s):x + s + 1]

        centro = caja(0.3 * tam)
        if centro.size == 0 or centro.mean() < 0.6:
            return False
        # Anillo alrededor de la marca (entre 0.8 y 1.0 lados del centro):
        # debe ser papel. Queda antes de la marca de orientación (a 1.1 lados).
        externo, interno = caja(1.0 * tam), caja(0.8 * tam)
        n_anillo = externo.size - interno.size
        if n_anillo <= 0:
            return False
        maximo = 0.5 if (tapada and i == 0) else 0.3
        if (externo.sum() - interno.sum()) / n_anillo > maximo:
            return False
    return True


def leer_hoja(img_bgr: np.ndarray, num_preguntas: int, formato=None,
              preguntas_hoja: Optional[int] = None
              ) -> tuple[np.ndarray, float, ResultadoLectura]:
    """
    Pipeline completo sobre una foto ya cargada:
      detectar las 4 marcas → enderezar (también si está girada o de cabeza)
      → comprobar que las marcas eran las de verdad → leer código y respuestas.

    Returns:
        (imagen_enderezada, escala_px_por_pt, ResultadoLectura)
    Raises:
        ValueError si no se ven las 4 marcas (mensaje listo para el docente).
    """
    img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    f = LH.obtener(formato)
    binarios = _binarios_marcas(img_gray)
    vistos: list[np.ndarray] = []      # juegos probados, para el último intento

    def juegos():
        # 1.ª pasada: binarizaciones normales. 2.ª: las mismas sin lo delgado
        # pegado a las marcas (grapas, rayones), solo si la 1.ª no bastó.
        for b in (binarios, None):
            b = b or _sin_grapas(binarios)
            for cuadratura_min in (RELLENO_CUADRADO, RELLENO_CUADRADO_TOLERANTE):
                for marcas in candidatos_marcas(img_gray, cuadratura_min=cuadratura_min,
                                                binarios=b):
                    if any(np.abs(marcas - v).max() < 3 for v in vistos):
                        continue
                    vistos.append(marcas)
                    yield marcas

    # Cada juego de marcas que pasa las comprobaciones da una lectura. Se
    # acepta de inmediato una con la orientación confirmada Y cuya cuadrícula
    # de burbujas calce bien con la foto (eso no pasa con marcas equivocadas:
    # p. ej. el cuadrito de orientación tomado como esquina deja la cuadrícula
    # corrida casi una fila). Si ninguna, se elige la mejor de todas.
    lecturas = []
    primera = None          # verificada sin orientación (hoja vieja), se lee al final

    def mejor_lectura():
        return max(lecturas, key=lambda t: (t[2].calce >= CALCE_SEGURO,
                                            t[2].orientacion_confirmada, t[2].calce))

    for marcas in juegos():
        try:
            recta, scale = corregir_perspectiva(img_bgr, marcas, formato)
        except ValueError:
            continue
        gris = _gris_aplanado(recta, scale)
        if not _marcas_verificadas(recta, scale, formato, gris):
            continue
        # Con la marca de orientación en su lugar no hay duda: es la hoja.
        # Si no aparece, puede ser una hoja vieja (no la tiene) o que se
        # tomó la marca de orientación como esquina (p. ej. con la esquina
        # engrapada o doblada): se sigue buscando.
        if _orientacion_confirmada(recta, scale, formato, gris):
            r = leer_respuestas(recta, num_preguntas, scale, formato, gris, preguntas_hoja)
            if r.calce >= CALCE_SEGURO:
                return recta, scale, r
            lecturas.append((recta, scale, r))
        elif primera is None:
            primera = (recta, scale, gris)

    # ¿Una grapa tapó la esquina superior-izquierda y se tomó la marca de
    # orientación en su lugar? Se reconstruye esa esquina con los otros 4
    # puntos de referencia (ver _esquina_tapada).
    for marcas in vistos:
        reales = _esquina_tapada(img_gray, marcas, f)
        if reales is None:
            continue
        try:
            recta, scale = corregir_perspectiva(img_bgr, reales, formato)
        except ValueError:
            continue
        gris = _gris_aplanado(recta, scale)
        if not (_marcas_verificadas(recta, scale, formato, gris, tapada=True)
                and _orientacion_confirmada(recta, scale, formato, gris)):
            continue
        r = leer_respuestas(recta, num_preguntas, scale, formato, gris, preguntas_hoja)
        lecturas.append((recta, scale, r))
        if r.calce >= CALCE_SEGURO:
            return mejor_lectura()

    if primera is not None:
        recta, scale, gris = primera
        r = leer_respuestas(recta, num_preguntas, scale, formato, gris, preguntas_hoja)
        r.orientacion_confirmada = False
        lecturas.append((recta, scale, r))
    if not lecturas:
        raise ValueError(MENSAJE_SIN_MARCAS)
    return mejor_lectura()


# Calce mínimo de la cuadrícula de burbujas con la foto. Medido con hojas de
# prueba: la hoja correcta da 0.5-0.7; una hoja del otro tamaño (media hoja
# leída como hoja completa, o al revés), menos de 0.1.
CALCE_MINIMO: float = 0.15
CALCE_SEGURO: float = 0.30


def _mensaje_otra_hoja(img_bgr: np.ndarray, formato) -> str:
    """La hoja de la foto no calza con el formato del examen: si calza con
    el otro tamaño, se dice cuál es."""
    f = LH.obtener(formato)

    def nombre(x: LH.Formato) -> str:
        return x.descripcion.split(" (")[0].lower()

    for otro in LH.FORMATOS.values():
        if otro.clave == f.clave:
            continue
        try:
            _, _, r = leer_hoja(img_bgr, 1, otro.clave)
        except ValueError:
            continue
        if r.calce >= CALCE_SEGURO:
            return (f"Esta hoja es una {nombre(otro)}, pero el examen está hecho para "
                    f"{nombre(f)}. Cambia la hoja del examen (en Exámenes, toca el "
                    "examen) o usa la hoja correcta.")
    return (f"La hoja de la foto no coincide con la de este examen ({nombre(f)}). "
            "Revisa que sea la hoja correcta y repite la foto.")


def leer_foto(img_bgr: np.ndarray, num_preguntas: int, formato=None,
              preguntas_hoja: Optional[int] = None
              ) -> tuple[np.ndarray, float, ResultadoLectura]:
    """
    Igual que leer_hoja, pero primero "escanea" la foto con el digitalizador
    (recorta el fondo y quita sombras). Si así no se ven las 4 marcas
    (p. ej. el digitalizador eligió mal el contorno), reintenta con la foto
    original. Es la función que usa la app, tanto para fotos cargadas como
    para las de la cámara.

    Si la cuadrícula de burbujas no calza con la foto (la hoja es de otro
    tamaño que el del examen), no se inventa una nota: ValueError con un
    mensaje que dice qué hoja es.
    """
    try:
        escaneada = D.alinear(img_bgr)
    except Exception as e:
        print(f"  ⚠️  Digitalizador: {e}")
        escaneada = None
    sin_calce = False
    reserva = None      # lectura sin la orientación confirmada, por si no hay otra
    if escaneada is not None:
        try:
            leida = leer_hoja(escaneada, num_preguntas, formato, preguntas_hoja)
            if leida[2].calce >= CALCE_MINIMO:
                if leida[2].orientacion_confirmada:
                    return leida
                reserva = leida
            else:
                sin_calce = True
        except ValueError:
            pass
    try:
        leida = leer_hoja(img_bgr, num_preguntas, formato, preguntas_hoja)
    except ValueError:
        if reserva is not None:
            return reserva
        if not sin_calce:
            raise
    else:
        if leida[2].calce >= CALCE_MINIMO and (leida[2].orientacion_confirmada
                                               or reserva is None):
            return leida
        if reserva is not None:
            return reserva
    raise ValueError(_mensaje_otra_hoja(img_bgr, formato))


def leer_imagen(ruta) -> Optional[np.ndarray]:
    """cv2.imread que también funciona con tildes/ñ en la ruta (en Windows
    cv2.imread devuelve None si la ruta tiene, p. ej., 'César')."""
    try:
        datos = np.fromfile(str(ruta), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(datos, cv2.IMREAD_COLOR) if datos.size else None


def guardar_imagen(ruta, img: np.ndarray, calidad: Optional[int] = None) -> bool:
    """cv2.imwrite que también funciona con tildes/ñ en la ruta.
    calidad: calidad JPEG (0-100); None = la de OpenCV (95)."""
    ext = Path(ruta).suffix or ".jpg"
    params = [cv2.IMWRITE_JPEG_QUALITY, int(calidad)] if calidad is not None else []
    ok, buf = cv2.imencode(ext, img, params)
    if ok:
        buf.tofile(str(ruta))
    return bool(ok)


def cargar_imagen(ruta: Path) -> np.ndarray:
    """Carga y reduce la imagen si es demasiado grande."""
    if not Path(ruta).exists():
        raise FileNotFoundError(f"Imagen no encontrada: {ruta}")

    img = leer_imagen(ruta)
    if img is None:
        raise ValueError(f"No se pudo abrir la imagen: {Path(ruta).name}")

    return _redimensionar_si_grande(img)


def cargar_datos_examen(ruta_json: Path) -> DatosExamen:
    """Lee la clave JSON de un examen."""
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
    # Las claves viejas no traen formato: todas eran de hoja completa
    formato = LH.obtener(datos.get("formato")).clave
    return DatosExamen(nombre, total, clave, formato, datos.get("preguntas_hoja") or 0)


# ─────────────────────────────────────────────────────────────────────────────
# Flujo de la app: una foto → nota
# ─────────────────────────────────────────────────────────────────────────────
# Carpetas dentro de profesores/<Profesor>/<Grado>/<Curso>/
SUB_CRUDOS     = "examenes_crudos"              # fotos tal como llegan
SUB_ARCHIVADOS = "examenes_crudos_archivados"   # fotos ya calificadas (originales)
SUB_RESULTADOS = "resultados"                   # imágenes marcadas + notas_<examen>.json

# La foto original se archiva reducida: la nota ya se leyó sobre la foto
# completa y la original solo sirve para volver a mirarla. Así pesa ~0.3 MB
# en vez de 3-5 MB (lo que sale de la cámara del celular).
LADO_ARCHIVO: int = 1600
CALIDAD_ARCHIVO: int = 80


def archivar_reducida(ruta: Path, carpeta: Path, img: Optional[np.ndarray] = None) -> Path:
    """
    Guarda en 'carpeta' una copia reducida (JPEG) de la foto 'ruta' y borra
    la foto grande. img: la foto ya cargada, para no volver a leerla.
    Si no se puede reducir (archivo dañado), se mueve tal cual.
    Devuelve la ruta del archivo archivado.
    """
    ruta, carpeta = Path(ruta), Path(carpeta)
    destino = carpeta / f"{ruta.stem}.jpg"
    if img is None:
        img = leer_imagen(ruta)
    if img is not None:
        h, w = img.shape[:2]
        f = LADO_ARCHIVO / max(h, w)
        if f < 1:
            img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
        temporal = destino.with_name(destino.stem + "_tmp.jpg")
        if guardar_imagen(temporal, img, CALIDAD_ARCHIVO):
            # Se reemplaza al final: si algo falla a medias, la original sigue ahí
            if ruta.resolve() != destino.resolve():
                ruta.unlink()
            temporal.replace(destino)
            return destino
    destino = carpeta / ruta.name
    if ruta.resolve() != destino.resolve():
        shutil.move(str(ruta), str(destino))
    return destino


def nombre_unico(nombre_original: str, prefijo: str = "") -> str:
    """
    Nombre de archivo que no choca con fotos anteriores: dos fotos llamadas
    'IMG_0001.jpg' tomadas en días distintos ya no se reemplazan entre sí.
    Ej.: 'IMG 0001.JPG' → 'IMG_0001_20261012-153012_a3f9.jpg'
    """
    import re
    import uuid
    from datetime import datetime
    p = Path(nombre_original)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", p.stem).strip("_") or "foto"
    stem = (prefijo + stem)[:40]
    sufijo = p.suffix.lower() or ".jpg"
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stem}_{marca}_{uuid.uuid4().hex[:4]}{sufijo}"


def calificar_foto(ruta_cruda: Path, ruta_json: Path, ruta_curso: Path,
                   datos: Optional[DatosExamen] = None) -> dict:
    """
    Califica UNA foto que ya está en '<curso>/examenes_crudos/'.

      1-2. La escanea con el digitalizador y la lee (ver leer_foto).
      3. Guarda la imagen anotada en '<curso>/resultados/'.
      4. Archiva la foto original (reducida, ver archivar_reducida), para
         que nunca se vuelva a calificar en otra corrida ni en otro examen.

    Devuelve el registro para notas_<examen>.json:
      {archivo, codigo, aciertos, total, respuestas, fecha, imagen, alertas}
    o, si no se pudo leer, {archivo, codigo: "ERROR", error, ...}.
    """
    from datetime import datetime
    ruta_cruda = Path(ruta_cruda)
    if datos is None:
        datos = cargar_datos_examen(ruta_json)

    archivados = ruta_curso / SUB_ARCHIVADOS
    salida     = ruta_curso / SUB_RESULTADOS
    for d in (archivados, salida):
        d.mkdir(parents=True, exist_ok=True)

    registro = {"archivo": ruta_cruda.name, "total": datos.total_preguntas,
                "fecha": datetime.now().isoformat(timespec="seconds")}

    resultado: Optional[ResultadoLectura] = None
    original: Optional[np.ndarray] = None
    ultimo_error = ""
    try:
        # 1-2. Escanear y leer (con la foto original como respaldo)
        original = cargar_imagen(ruta_cruda)
        recta, scale, resultado = leer_foto(original, datos.total_preguntas, datos.formato,
                                            datos.preguntas_hoja)
    except Exception as e:
        ultimo_error = str(e)

    # 3. Imagen anotada
    if resultado is not None:
        anotada = dibujar_anotaciones(recta, resultado, datos.clave, scale,
                                      datos.nombre, datos.formato)
        registro["imagen"] = f"{ruta_cruda.stem}_calificado.jpg"
        guardar_imagen(salida / registro["imagen"], anotada)

    # 4. Archivar la original, reducida
    archivada = None
    try:
        archivada = archivar_reducida(ruta_cruda, archivados, original)
    except Exception:
        pass

    if resultado is None:
        # No se pudo leer: queda lista para calificarla a mano mirando la
        # foto original (código y respuestas, ver main.py → GaleriaHojas)
        registro.update({"codigo": "ERROR", "aciertos": 0, "error": ultimo_error,
                         "sin_leer": True,
                         "respuestas": {str(q): None
                                        for q in range(1, datos.total_preguntas + 1)}})
        if archivada is not None:
            registro["foto_original"] = archivada.name
        return registro

    aciertos = sum(1 for p, r in resultado.respuestas.items()
                   if r is not None and r == datos.clave.get(p))
    registro.update({
        "codigo": resultado.codigo_estudiante,
        "aciertos": aciertos,
        "respuestas": {str(p): r for p, r in sorted(resultado.respuestas.items())},
    })
    # Lo que conviene mirar en la hoja (la app lo muestra junto a la nota)
    alertas = {"doble": resultado.doble_marca, "dudosas": resultado.dudosas,
               "tenues": resultado.tenues, "marcas_extra": resultado.marcas_extra,
               # Las burbujas no calzaron bien con la cuadrícula: puede que la
               # hoja se haya enderezado mal y las respuestas estén corridas
               "cuadricula": resultado.calce < CALCE_SEGURO}
    alertas = {k: v for k, v in alertas.items() if v}
    if alertas:
        registro["alertas"] = alertas
    return registro


def calidad_lectura(registro: dict) -> tuple:
    """
    Qué tan confiable es la lectura de una hoja, para elegir entre dos fotos
    del mismo estudiante (mayor = mejor; el que llame desempata con la más
    reciente).

      1. Una hoja que el docente ya revisó a mano (respuestas corregidas o
         calificada a mano) le gana a cualquier lectura automática.
      2. Luego, la que calzó bien con la cuadrícula.
      3. Luego, la que tiene MENOS avisos: preguntas sin marcar (en blanco,
         doble marca o marca débil: todas quedan sin respuesta) y marcas
         muy claras. No se mira la nota: puede subir o bajar.
    """
    alertas = registro.get("alertas") or {}
    respuestas = registro.get("respuestas") or {}
    sin_marcar = sum(1 for v in respuestas.values() if not v)
    avisos = sin_marcar + len(alertas.get("tenues") or [])
    revisada = bool(registro.get("respuestas_corregidas") or registro.get("a_mano"))
    return (revisada, not alertas.get("cuadricula"), -avisos)


def corregir_respuestas(registro: dict, nuevas: dict, clave: dict[int, str]) -> list[int]:
    """
    Corrección a mano de una mala lectura: cambia las respuestas de una hoja
    ya calificada y recalcula sus aciertos con la clave del examen.

    registro: el de notas_<examen>.json (se modifica aquí mismo).
    nuevas:   {pregunta: letra o None (en blanco)} con la lectura corregida.
    Devuelve las preguntas que cambiaron ([] = no se tocó nada).

    Se corrigen las RESPUESTAS y no la nota, porque los reportes vuelven a
    contar los aciertos desde las respuestas guardadas: así la nota queda
    igual en la app, en la planilla y en los reportes.
    """
    antes = {str(q): v for q, v in (registro.get("respuestas") or {}).items()}
    despues = dict(antes)
    despues.update({str(q): (v or None) for q, v in nuevas.items()})
    cambiadas = sorted(int(q) for q, v in despues.items() if v != antes.get(q))
    if not cambiadas:
        return []
    registro["respuestas"] = {q: despues[q] for q in sorted(despues, key=int)}
    registro["aciertos"] = sum(1 for q, v in despues.items()
                               if v is not None and v == clave.get(int(q)))
    registro["respuestas_corregidas"] = sorted(
        set(registro.get("respuestas_corregidas") or []) | set(cambiadas))
    # Lo que ya revisó el docente deja de ser una alerta
    alertas = dict(registro.get("alertas") or {})
    for tipo in ("doble", "dudosas", "tenues"):
        if tipo in alertas:
            alertas[tipo] = [q for q in alertas[tipo] if q not in cambiadas]
    alertas.pop("cuadricula", None)       # el docente ya revisó la hoja
    alertas = {k: v for k, v in alertas.items() if v}
    if alertas:
        registro["alertas"] = alertas
    else:
        registro.pop("alertas", None)
    return cambiadas
