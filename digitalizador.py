#!/usr/bin/env python3
"""
digitalizador.py — Digitalizador y alineador de hojas de respuestas OMR.
Optimizado para el flujo de trabajo de Cesar Franco Oviedo.

Funcionamiento:
  1. Permite seleccionar de forma interactiva el Grado y el Curso/Salón.
  2. Busca imágenes sin procesar dentro de '[Curso]/examenes_crudos/'.
  3. Detecta el contorno de la hoja de papel, corrige la perspectiva y la recorta.
  4. Guarda la imagen plana resultante en '[Curso]/examenes_procesados/'.
  5. Mueve la foto original a '[Curso]/examenes_crudos_archivados/' para evitar reprocesarla.
"""

import cv2
import numpy as np
import argparse
import os
import shutil
from pathlib import Path
import sys

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE RUTA BASE DEL DOCENTE
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path("profesores")


def order_points(pts: np.ndarray) -> np.ndarray:
    """
    Ordena 4 puntos en el siguiente orden estricto:
    arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda.
    """
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Aplica una transformación de perspectiva para obtener una vista plana y recta de la hoja."""
    rect = order_points(pts)
    (tl, tr, br, bl) = rect

    # Calcular el ancho de la nueva imagen
    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))

    # Calcular el alto de la nueva imagen
    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))

    # Construir puntos de destino para la vista "plana"
    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]
    ], dtype="float32")

    # Calcular y aplicar la matriz de transformación de perspectiva
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped


def procesar_alineacion_imagen(ruta_origen: Path, ruta_destino: Path) -> bool:
    """
    Detecta los bordes de la hoja de papel, aplica corrección de perspectiva
    y la guarda en el destino indicado.
    """
    image = cv2.imread(str(ruta_origen))
    if image is None:
        print(f"❌ No se pudo cargar la imagen: {ruta_origen}")
        return False

    orig = image.copy()
    # Redimensionar la imagen para un procesamiento rápido de contornos
    ratio = image.shape[0] / 500.0
    image_resized = cv2.resize(image, (int(image.shape[1] / ratio), 500))

    # Preprocesamiento de imagen
    gray = cv2.cvtColor(image_resized, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 75, 200)

    # Encontrar contornos en la imagen con bordes
    contornos, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contornos = sorted(contornos, key=cv2.contourArea, reverse=True)[:5]

    screen_cnt = None
    for c in contornos:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)

        # Si el contorno aproximado tiene 4 puntos, asumimos que encontramos la hoja
        if len(approx) == 4:
            screen_cnt = approx
            break

    # Si no se detectó un contorno rectangular claro, usamos la imagen completa
    if screen_cnt is None:
        print("⚠️ No se detectó un contorno claro de 4 puntos. Se procesará la imagen completa sin recortar.")
        warped = orig
    else:
        # Re-escalar el contorno detectado a la resolución de la imagen original
        pts = screen_cnt.reshape(4, 2) * ratio
        warped = four_point_transform(orig, pts)

    # Guardar el resultado en la carpeta de exámenes procesados
    ruta_destino.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(ruta_destino), warped)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# MENÚ INTERACTIVO LOCAL
# ─────────────────────────────────────────────────────────────────────────────

def interactivo_menu_local() -> tuple[Path, Path, Path]:
    """
    Asistente interactivo en consola para seleccionar Grado y Curso.
    Retorna:
      - carpeta_crudos (Path)
      - carpeta_procesados (Path)
      - carpeta_archivados (Path)
    """
    if not BASE_DIR.exists():
        print(f"\n⚠️ ERROR: No se encontró la carpeta 'profesores' en: {BASE_DIR.resolve()}")
        print("Por favor, ejecuta primero el generador de PDF o el gestor de salones.")
        sys.exit(1)

    print("\n" + "="*55)
    print("      DIGITALIZADOR DE EXÁMENES OMR — LICEO SAHAGÚN")
    print("="*55)

    # 1. Seleccionar Profesor
    profesores = sorted([d.name for d in BASE_DIR.iterdir() if d.is_dir()])
    if not profesores:
        print("⚠️ No hay profesores registrados. Ejecuta primero gestor_salones.py o generador_pdf.py.")
        sys.exit(1)

    print("\n[ Paso 1: Selecciona el Profesor ]")
    for i, p in enumerate(profesores, 1):
        print(f"  {i}. {p.replace('_', ' ')}")
    prof_idx = int(input("\n👉 Opción: ").strip()) - 1
    ruta_prof = BASE_DIR / profesores[prof_idx]

    # 2. Seleccionar Grado
    grados = sorted([d.name for d in ruta_prof.iterdir() if d.is_dir()])
    if not grados:
        print("⚠️ Ese profesor no tiene grados creados.")
        sys.exit(1)

    print("\n[ Paso 2: Selecciona el Grado ]")
    for i, g in enumerate(grados, 1):
        print(f"  {i}. Grado {g}")
    grado_idx = int(input("\n👉 Opción: ").strip()) - 1
    ruta_grado = ruta_prof / grados[grado_idx]

    # 2. Seleccionar Curso / Salón
    cursos = sorted([d.name for d in ruta_grado.iterdir() if d.is_dir()])
    if not cursos:
        print("⚠️ No hay cursos o salones registrados en este grado.")
        sys.exit(1)

    print(f"\n[ Paso 3: Selecciona el Salón/Curso ]")
    for i, c in enumerate(cursos, 1):
        print(f"  {i}. Curso {c}")
    curso_idx = int(input("\n👉 Opción: ").strip()) - 1
    ruta_curso = ruta_grado / cursos[curso_idx]

    # 3. Definir y asegurar rutas de digitalización del curso seleccionado
    carpeta_crudos = ruta_curso / "examenes_crudos"
    carpeta_procesados = ruta_curso / "examenes_procesados"
    carpeta_archivados = ruta_curso / "examenes_crudos_archivados"

    carpeta_crudos.mkdir(parents=True, exist_ok=True)
    carpeta_procesados.mkdir(parents=True, exist_ok=True)
    carpeta_archivados.mkdir(parents=True, exist_ok=True)

    return carpeta_crudos, carpeta_procesados, carpeta_archivados


# ─────────────────────────────────────────────────────────────────────────────
# CONTROLADOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Digitalizador y Alineador OMR — Cesar Franco Oviedo"
    )
    parser.add_argument("-i", "--input", default=None, help="Ruta directa de una imagen (opcional)")
    args = parser.parse_args()

    # Si se pasa una imagen específica por comando, se procesa directamente
    if args.input:
        archivo_entrada = Path(args.input)
        if not archivo_entrada.exists():
            print(f"❌ El archivo indicado no existe: {args.input}")
            sys.exit(1)
        
        archivo_salida = archivo_entrada.parent / f"{archivo_entrada.stem}_digitalizado.png"
        print(f"⚡ Procesando imagen directa: {archivo_entrada.name}")
        if procesar_alineacion_imagen(archivo_entrada, archivo_salida):
            print(f"✅ Guardado en: {archivo_salida}")
        sys.exit(0)

    # De lo contrario, iniciar el flujo automatizado local por salones
    carpeta_crudos, carpeta_procesados, carpeta_archivados = interactivo_menu_local()

    # Buscar imágenes en la carpeta 'examenes_crudos'
    formatos_admitidos = [".jpg", ".jpeg", ".png"]
    imagenes_encontradas = [
        f for f in carpeta_crudos.iterdir() 
        if f.is_file() and f.suffix.lower() in formatos_admitidos
    ]

    if not imagenes_encontradas:
        print(f"\n📂 La carpeta 'examenes_crudos' está vacía.")
        print(f"📌 Ruta para depositar tus fotos: {carpeta_crudos.resolve()}")
        print("Agrega allí las fotos tomadas por tu cámara y vuelve a ejecutar este script.")
        sys.exit(0)

    print(f"\n🚀 Se encontraron {len(imagenes_encontradas)} exámenes sin procesar.")
    input("Presiona ENTER para iniciar la digitalización en lote...")

    correctos = 0
    for idx, img_path in enumerate(imagenes_encontradas, 1):
        print(f"\n📸 [{idx}/{len(imagenes_encontradas)}] Procesando: {img_path.name}...")
        
        # El nombre del archivo de salida tendrá el sufijo '_scanned' para identificarlo
        ruta_salida = carpeta_procesados / f"{img_path.stem}_scanned.png"
        
        # 1. Ejecutar alineación
        exito = procesar_alineacion_imagen(img_path, ruta_salida)
        
        if exito:
            correctos += 1
            # 2. Mover la foto original (cruda) a la carpeta de archivados
            ruta_destino_archivado = carpeta_archivados / img_path.name
            try:
                shutil.move(str(img_path), str(ruta_destino_archivado))
                print(f"✔️ Imagen corregida guardada en: {ruta_salida.name}")
                print(f"📦 Foto original archivada en: {carpeta_archivados.name}/")
            except Exception as e:
                print(f"⚠️ No se pudo archivar la foto original: {e}")
        else:
            print(f"❌ Falló la alineación de {img_path.name}")

    print("\n" + "═"*50)
    print("🏁 PROCESAMIENTO FINALIZADO")
    print("═"*50)
    print(f"📂 Exámenes procesados con éxito: {correctos} / {len(imagenes_encontradas)}")
    print(f"📥 Ubicación de resultados listos para el lector: {carpeta_procesados.resolve()}")
    print("═"*50 + "\n")


if __name__ == "__main__":
    main()