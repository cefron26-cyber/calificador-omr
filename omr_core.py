#!/usr/bin/env python3
"""
omr_core.py — Núcleo de calificación OMR, SIN entrada/salida.

Una sola función pura: recibe una imagen (arreglo de la foto) y la clave de
respuestas, y devuelve un diccionario con código, respuestas, aciertos y nota.
No usa consola, ni archivos, ni rutas. Sirve para:
  • el PC (lo que ya tienes),
  • envolverlo en una API,
  • y como REFERENCIA EXACTA para traducir el algoritmo a JavaScript/opencv.js.

Reutiliza el motor ya probado de lector_omr.py (detección de marcas,
corrección de perspectiva y lectura de burbujas). El equivalente en JS debe
replicar, en este orden:

    1) cvtColor BGR→GRAY
    2) detectar_marcas(gray)              → 4 esquinas
    3) corregir_perspectiva(bgr, marcas)  → imagen recta + 'scale'
    4) leer_respuestas(recta, N, scale)   → código + respuestas
    5) comparar con la clave → aciertos → nota (escala 0–10, truncada, piso 1.0)

Las CONSTANTES de geometría (escala, posiciones de burbujas, umbrales) están
en lector_omr.py y se copian tal cual a la versión JS.
"""

from __future__ import annotations

from typing import Optional, Union

import numpy as np
import cv2

import lector_omr as engine


def _normalizar_clave(clave) -> Optional[dict[int, str]]:
    """Acepta lista ['A','B',...] o dict {1:'A',...} y devuelve {pregunta:letra}."""
    if clave is None:
        return None
    if isinstance(clave, dict):
        return {int(k): str(v).strip().upper() for k, v in clave.items()}
    return {i + 1: str(v).strip().upper() for i, v in enumerate(clave)}


def procesar_imagen(
    imagen_bgr: np.ndarray,
    clave: Optional[Union[list, dict]] = None,
    num_preguntas: Optional[int] = None,
) -> dict:
    """
    Procesa UNA hoja OMR ya capturada (sin tocar disco).

    Args:
        imagen_bgr:   foto como arreglo BGR (lo que entrega cv2 / la cámara).
        clave:        respuestas correctas, lista o dict (opcional).
        num_preguntas: cuántas preguntas leer; si hay clave, se infiere de ella.

    Returns (dict):
        {
          "ok": bool,
          "error": str|None,
          "codigo": "004",
          "respuestas": {1:"B", 2:"B", 3:"A"},   # letra o None
          "total": 3,
          "aciertos": 1|None,                      # None si no hay clave
          "nota": 3.3|None,                        # escala 0–10, piso 1.0
          "en_blanco": [...], "doble_marca": [...], "dudosas": [...],
        }
    """
    clave_norm = _normalizar_clave(clave)
    if num_preguntas is None:
        num_preguntas = len(clave_norm) if clave_norm else 0
    if not num_preguntas:
        return {"ok": False, "error": "Falta la clave o el número de preguntas.",
                "codigo": "???", "respuestas": {}, "total": 0,
                "aciertos": None, "nota": None,
                "en_blanco": [], "doble_marca": [], "dudosas": []}

    if imagen_bgr is None or getattr(imagen_bgr, "size", 0) == 0:
        return {"ok": False, "error": "Imagen vacía o no válida.",
                "codigo": "???", "respuestas": {}, "total": num_preguntas,
                "aciertos": None, "nota": None,
                "en_blanco": [], "doble_marca": [], "dudosas": []}

    # 1) escala de grises
    gray = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2GRAY)

    # 2) detectar las 4 marcas de esquina
    marcas = engine.detectar_marcas(gray)
    if marcas is None:
        return {"ok": False,
                "error": "No se detectaron las 4 marcas de esquina. "
                         "Revisa que salgan completas y con buena luz.",
                "codigo": "???", "respuestas": {}, "total": num_preguntas,
                "aciertos": None, "nota": None,
                "en_blanco": [], "doble_marca": [], "dudosas": []}

    # 3) enderezar (homografía a las marcas del PDF)
    recta, scale = engine.corregir_perspectiva(imagen_bgr, marcas)

    # 4) leer código + respuestas
    res = engine.leer_respuestas(recta, num_preguntas, scale)

    # 5) calificar contra la clave
    aciertos: Optional[int] = None
    nota: Optional[float] = None
    if clave_norm:
        aciertos = sum(1 for p, letra in res.respuestas.items()
                       if letra is not None and letra == clave_norm.get(p))
        nota = engine._calcular_nota(aciertos, num_preguntas)

    return {
        "ok": True,
        "error": None,
        "codigo": res.codigo_estudiante,
        "respuestas": dict(res.respuestas),
        "total": num_preguntas,
        "aciertos": aciertos,
        "nota": nota,
        "en_blanco": list(res.en_blanco),
        "doble_marca": list(res.doble_marca),
        "dudosas": list(res.dudosas),
    }


# Pequeña ayuda opcional para entornos donde solo hay bytes de imagen
def procesar_bytes(data: bytes, clave=None, num_preguntas=None) -> dict:
    """Igual que procesar_imagen pero a partir de los bytes de un archivo de imagen."""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return procesar_imagen(img, clave, num_preguntas)