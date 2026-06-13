#!/usr/bin/env python3
"""
generador_pdf.py — Generador de Hojas de Respuesta OMR para el Liceo Sahagún.

Organiza todo dentro de la estructura por profesor/grado/curso:

    profesores/<Profesor>/<Grado>/<Curso>/
        examenes_claves/   ← clave JSON del examen   (la lee lector_omr.py)
        hojas_pdf/         ← PDF para imprimir

IMPORTANTE: el diseño geométrico de esta hoja (posición de las marcas de
esquina y de cada burbuja) coincide EXACTAMENTE con el motor de lectura de
lector_omr.py. No cambies las constantes de layout sin actualizar ambos
archivos a la vez, o la lectura se desalineará.
"""

import os
import json
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm

# ─────────────────────────────────────────────────────────────────────────────
# RUTAS
# ─────────────────────────────────────────────────────────────────────────────
BASE_PROFESORES = Path("profesores")

# El logo se busca junto a este script y, si no, en el directorio actual.
_RUTAS_LOGO = [Path(__file__).resolve().parent / "logo.png", Path("logo.png")]


def _ruta_logo() -> Path | None:
    for r in _RUTAS_LOGO:
        if r.exists():
            return r
    return None


# ─────────────────────────────────────────────────────────────────────────────
# DIBUJO DE LA HOJA OMR  (layout idéntico al esperado por lector_omr.py)
# ─────────────────────────────────────────────────────────────────────────────
def generar_hoja_omr(archivo_salida: Path, num_preguntas: int) -> None:
    """Genera el PDF de la hoja OMR alineado al lector."""
    c = canvas.Canvas(str(archivo_salida), pagesize=letter)
    ancho, alto = letter

    # 1. MARCAS DE REFERENCIA (cuadrados negros de las 4 esquinas)
    c.setFillColorRGB(0, 0, 0)
    margen = 1.5 * cm
    tamano_marca = 0.5 * cm
    c.rect(margen, margen, tamano_marca, tamano_marca, fill=1)
    c.rect(ancho - margen - tamano_marca, margen, tamano_marca, tamano_marca, fill=1)
    c.rect(margen, alto - margen - tamano_marca, tamano_marca, tamano_marca, fill=1)
    c.rect(ancho - margen - tamano_marca, alto - margen - tamano_marca, tamano_marca, tamano_marca, fill=1)

    # 2. ENCABEZADO
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margen + 1.0 * cm, alto - 2.5 * cm, "Liceo Sahagún - Hoja de Respuestas")

    c.setFont("Helvetica", 11)
    c.drawString(margen + 1.0 * cm, alto - 3.8 * cm, "Nombres y Apellidos: _____________________________________________")
    c.drawString(margen + 1.0 * cm, alto - 4.8 * cm, "Grado y Curso: __________________   Asignatura: __________________")

    # 3. CAJA DEL LOGO
    ruta_logo = _ruta_logo()
    logo_w = 4.0 * cm
    logo_h = 3.5 * cm
    pos_logo_x = ancho - margen - logo_w - 1.5 * cm
    pos_logo_y = alto - 5.0 * cm

    if ruta_logo is not None:
        c.drawImage(str(ruta_logo), pos_logo_x, pos_logo_y, width=logo_w, height=logo_h, preserveAspectRatio=True)
    else:
        c.setStrokeColorRGB(0, 0, 0)
        c.setFillColorRGB(0.92, 0.92, 0.92)
        c.rect(pos_logo_x, pos_logo_y, logo_w, logo_h, stroke=1, fill=1)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(pos_logo_x + (logo_w / 2), pos_logo_y + (logo_h / 2) - 0.1 * cm, "[ LOGO ]")

    # 4. INSTRUCCIONES DE MARCADO
    y_instrucciones = alto - 6.2 * cm
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margen + 1.0 * cm, y_instrucciones, "INSTRUCCIONES DE MARCADO:")

    c.setFont("Helvetica", 8.5)
    c.drawString(margen + 1.0 * cm, y_instrucciones - 0.5 * cm, "Use lápiz o lapicero negro. Rellene COMPLETAMENTE el círculo sin salirse.")
    c.drawString(margen + 1.0 * cm, y_instrucciones - 0.9 * cm, "• Modo Correcto: [ ■ ]   Modos Incorrectos: [ ✘ ] [ ✓ ]")
    c.drawString(margen + 1.0 * cm, y_instrucciones - 1.3 * cm, "• El código de estudiante se rellena con tres dígitos brindados por el docente NO LLENAR ANTES DE ESO")

    # 5. TÍTULOS DE COLUMNAS
    y_titulos = y_instrucciones - 2.5 * cm
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 10)

    inicio_x_codigo = margen + 1.0 * cm
    c.drawString(inicio_x_codigo, y_titulos, "CÓDIGO ALUMNO")

    inicio_x_preguntas = margen + 6.5 * cm
    c.drawString(inicio_x_preguntas, y_titulos, "RESPUESTAS")

    # Parámetros visuales de las burbujas
    radio_burbuja = 0.22 * cm
    espacio_y = 0.58 * cm
    espacio_x = 0.65 * cm
    y_inicio_burbujas = y_titulos - 1.0 * cm

    # Flecha minimalista
    c.setStrokeColorRGB(0.2, 0.2, 0.2)
    c.setLineWidth(1)
    x_start = inicio_x_codigo + 0.3 * cm
    x_end = x_start + (2 * espacio_x)
    y_flecha = y_titulos - 0.35 * cm
    c.line(x_start, y_flecha, x_end, y_flecha)
    c.line(x_end, y_flecha, x_end - 0.15 * cm, y_flecha + 0.1 * cm)
    c.line(x_end, y_flecha, x_end - 0.15 * cm, y_flecha - 0.1 * cm)

    # 6. MATRIZ: CÓDIGO ALUMNO (3 columnas, dígitos 0-9)
    for fila in range(10):
        for col in range(3):
            x = inicio_x_codigo + 0.3 * cm + (col * espacio_x)
            y = y_inicio_burbujas - (fila * espacio_y)
            c.setStrokeColorRGB(0, 0, 0)
            c.circle(x, y, radio_burbuja, stroke=1, fill=0)
            c.setFillColorRGB(0.4, 0.4, 0.4)
            c.setFont("Helvetica", 7.5)
            c.drawCentredString(x, y - 0.08 * cm, str(fila))

    # 7. MATRIZ: RESPUESTAS (A, B, C, D)
    opciones = ['A', 'B', 'C', 'D']
    columna_actual = 0
    fila_actual = 0
    max_filas_por_columna = 25

    for i in range(1, num_preguntas + 1):
        if fila_actual >= max_filas_por_columna:
            fila_actual = 0
            columna_actual += 1

        y = y_inicio_burbujas - (fila_actual * espacio_y)
        x_base = inicio_x_preguntas + (columna_actual * 4.6 * cm)

        c.setFont("Helvetica", 9.5)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(x_base, y - 0.1 * cm, f"{i:02d}.")

        for j, opc in enumerate(opciones):
            x_burbuja = x_base + 0.8 * cm + (j * espacio_x)
            c.setStrokeColorRGB(0, 0, 0)
            c.circle(x_burbuja, y, radio_burbuja, stroke=1, fill=0)
            c.setFillColorRGB(0.4, 0.4, 0.4)
            c.setFont("Helvetica", 7.5)
            c.drawCentredString(x_burbuja, y - 0.08 * cm, opc)

        fila_actual += 1

    c.save()


# ─────────────────────────────────────────────────────────────────────────────
# SELECCIÓN DE PROFESOR / GRADO / CURSO
# ─────────────────────────────────────────────────────────────────────────────
def _subdirs(ruta: Path) -> list[str]:
    if not ruta.exists():
        return []
    return sorted(d.name for d in ruta.iterdir() if d.is_dir())


def _elegir_o_crear(ruta_padre: Path, titulo: str, etiqueta: str,
                    transform=lambda s: s.strip()) -> Path:
    """Lista subcarpetas de ruta_padre; permite elegir una o crear nueva."""
    existentes = _subdirs(ruta_padre)
    print(f"\n[ {titulo} ]")
    for i, nombre in enumerate(existentes, 1):
        print(f"  {i}. {nombre.replace('_', ' ')}")
    print(f"  {len(existentes) + 1}. [Crear nuevo]")

    while True:
        try:
            op = int(input("👉 Opción: ").strip())
        except ValueError:
            print("⚠️ Ingresa un número.")
            continue
        if 1 <= op <= len(existentes):
            return ruta_padre / existentes[op - 1]
        if op == len(existentes) + 1:
            nuevo = transform(input(f"   Nombre del {etiqueta}: "))
            while not nuevo:
                nuevo = transform(input(f"   ⚠️ No puede ir vacío. {etiqueta}: "))
            ruta = ruta_padre / nuevo
            ruta.mkdir(parents=True, exist_ok=True)
            return ruta
        print("⚠️ Opción inválida.")


def seleccionar_curso() -> Path:
    """Devuelve la ruta del curso elegido, creando lo que falte."""
    BASE_PROFESORES.mkdir(parents=True, exist_ok=True)
    ruta_prof = _elegir_o_crear(
        BASE_PROFESORES, "Paso 1: Profesor", "profesor",
        transform=lambda s: s.strip().replace(" ", "_"))
    ruta_grado = _elegir_o_crear(
        ruta_prof, "Paso 2: Grado (Ej: 11)", "grado",
        transform=lambda s: s.strip())
    ruta_curso = _elegir_o_crear(
        ruta_grado, "Paso 3: Curso/Salón (Ej: A)", "curso",
        transform=lambda s: s.strip().upper())
    return ruta_curso


# ─────────────────────────────────────────────────────────────────────────────
# PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("🎓 GENERADOR DE EXÁMENES OMR — Liceo Sahagún")
    print("=" * 60)

    ruta_curso = seleccionar_curso()
    dir_claves = ruta_curso / "examenes_claves"
    dir_pdf = ruta_curso / "hojas_pdf"
    dir_claves.mkdir(parents=True, exist_ok=True)
    dir_pdf.mkdir(parents=True, exist_ok=True)

    # Nombre del examen
    nombre_examen = input("\n📝 Nombre del examen (Ej: Mat_11A): ").strip()
    while not nombre_examen:
        nombre_examen = input("⚠️ El nombre no puede estar vacío: ").strip()
    nombre_examen = nombre_examen.replace(" ", "_")

    # Cantidad de preguntas (hasta 50: 2 columnas de 25)
    while True:
        try:
            cantidad = int(input("❓ Cantidad de preguntas (1-50): "))
            if 1 <= cantidad <= 50:
                break
            print("⚠️ Debe estar entre 1 y 50.")
        except ValueError:
            print("⚠️ Ingresa un número entero válido.")

    # Clave de respuestas
    print(f"\n🔑 Clave para {cantidad} preguntas.")
    print("Escribe las opciones correctas seguidas, sin espacios (Ej: ABDC...)")
    respuestas_str = input("Respuestas correctas: ").strip().upper()
    while len(respuestas_str) != cantidad or not all(l in "ABCD" for l in respuestas_str):
        print(f"❌ Debes ingresar exactamente {cantidad} letras (solo A, B, C o D).")
        respuestas_str = input("Respuestas correctas: ").strip().upper()

    array_respuestas = list(respuestas_str)

    ruta_pdf = dir_pdf / f"{nombre_examen}_hoja.pdf"
    ruta_json = dir_claves / f"respuestas_{nombre_examen}.json"

    datos_examen = {
        "examen": nombre_examen,
        "total_preguntas": cantidad,
        "clave_correctas": array_respuestas,
    }

    try:
        with open(ruta_json, "w", encoding="utf-8") as f:
            json.dump(datos_examen, f, indent=4, ensure_ascii=False)

        print("\n🎨 Dibujando hoja de respuestas PDF...")
        generar_hoja_omr(ruta_pdf, cantidad)

        print("\n" + "═" * 50)
        print("✅ ¡PROCESO COMPLETADO!")
        print("═" * 50)
        print(f"📁 Curso:        {ruta_curso}")
        print(f"📄 Plantilla PDF: {ruta_pdf}")
        print(f"🔑 Clave JSON:    {ruta_json}")
        print("═" * 50 + "\n")
    except Exception as e:
        print(f"\n❌ Error al guardar los archivos: {e}")


if __name__ == "__main__":
    main()