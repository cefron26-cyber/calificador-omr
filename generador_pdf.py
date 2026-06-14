#!/usr/bin/env python3
"""
generador_pdf.py — Generador de Hojas de Respuesta OMR para el Liceo Sahagún.

** Versión 100% Python puro: NO depende de reportlab, fpdf2 ni fontTools. **
Escribe el PDF byte a byte, por lo que funciona en cualquier dispositivo
(incluido Android ARM) sin librerías que compilen.

El diseño geométrico (marcas de esquina y burbujas) coincide EXACTAMENTE con el
motor de lectura de lector_omr.py: usa el sistema de coordenadas estándar del
PDF (origen abajo-izquierda, en puntos), igual que el generador original.
"""

import os
import json
from pathlib import Path

BASE_PROFESORES = Path("profesores")

# Anchos estándar de la fuente Helvetica (Adobe AFM, en milésimas de em).
# Solo se usan para CENTRAR texto; los caracteres fuera de rango usan 556.
_HELV_W = {
    ' ': 278, '!': 278, '"': 355, '#': 556, '$': 556, '%': 889, '&': 667,
    "'": 191, '(': 333, ')': 333, '*': 389, '+': 584, ',': 278, '-': 333,
    '.': 278, '/': 278, '0': 556, '1': 556, '2': 556, '3': 556, '4': 556,
    '5': 556, '6': 556, '7': 556, '8': 556, '9': 556, ':': 278, ';': 278,
    '<': 584, '=': 584, '>': 584, '?': 556, '@': 1015, 'A': 667, 'B': 667,
    'C': 722, 'D': 722, 'E': 667, 'F': 611, 'G': 778, 'H': 722, 'I': 278,
    'J': 500, 'K': 667, 'L': 556, 'M': 833, 'N': 722, 'O': 778, 'P': 667,
    'Q': 778, 'R': 722, 'S': 667, 'T': 611, 'U': 722, 'V': 667, 'W': 944,
    'X': 667, 'Y': 667, 'Z': 611, '[': 278, '\\': 278, ']': 278, '^': 469,
    '_': 556, '`': 333, 'a': 556, 'b': 556, 'c': 500, 'd': 556, 'e': 556,
    'f': 278, 'g': 556, 'h': 556, 'i': 222, 'j': 222, 'k': 500, 'l': 222,
    'm': 833, 'n': 556, 'o': 556, 'p': 556, 'q': 556, 'r': 333, 's': 500,
    't': 278, 'u': 556, 'v': 500, 'w': 722, 'x': 500, 'y': 500, 'z': 500,
    '{': 334, '|': 260, '}': 334, '~': 584,
}


def _ancho_texto(s, size):
    total = sum(_HELV_W.get(ch, 556) for ch in s)
    return total * size / 1000.0


def _escape_pdf(s):
    """Codifica el texto a bytes (WinAnsi/cp1252) y escapa los caracteres
    especiales del formato PDF, devolviendo la cadena entre paréntesis."""
    b = s.encode("cp1252", "replace")
    b = b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return b"(" + b + b")"


class _PDF:
    """Mini-escritor de PDF de una sola página (carta), con Helvetica."""

    def __init__(self, ancho=612.0, alto=792.0):
        self.W = ancho
        self.H = alto
        self._ops = []  # lista de bytes (operadores del contenido)
        self._img = None  # imagen opcional (logo)

    # -- operadores de dibujo (coordenadas con origen abajo-izquierda) --
    def color_relleno(self, r, g, b):
        self._ops.append(b"%.3f %.3f %.3f rg\n" % (r, g, b))

    def color_linea(self, r, g, b):
        self._ops.append(b"%.3f %.3f %.3f RG\n" % (r, g, b))

    def grosor_linea(self, w):
        self._ops.append(b"%.2f w\n" % w)

    def rect_relleno(self, x, y, w, h):
        self._ops.append(b"%.2f %.2f %.2f %.2f re f\n" % (x, y, w, h))

    def rect_caja(self, x, y, w, h):
        self._ops.append(b"%.2f %.2f %.2f %.2f re B\n" % (x, y, w, h))

    def linea(self, x1, y1, x2, y2):
        self._ops.append(b"%.2f %.2f m %.2f %.2f l S\n" % (x1, y1, x2, y2))

    def circulo(self, cx, cy, r):
        k = 0.5522847498 * r
        self._ops.append(b"%.2f %.2f m\n" % (cx + r, cy))
        self._ops.append(b"%.2f %.2f %.2f %.2f %.2f %.2f c\n"
                         % (cx + r, cy + k, cx + k, cy + r, cx, cy + r))
        self._ops.append(b"%.2f %.2f %.2f %.2f %.2f %.2f c\n"
                         % (cx - k, cy + r, cx - r, cy + k, cx - r, cy))
        self._ops.append(b"%.2f %.2f %.2f %.2f %.2f %.2f c\n"
                         % (cx - r, cy - k, cx - k, cy - r, cx, cy - r))
        self._ops.append(b"%.2f %.2f %.2f %.2f %.2f %.2f c\n"
                         % (cx + k, cy - r, cx + r, cy - k, cx + r, cy))
        self._ops.append(b"S\n")

    def texto(self, x, y, s, size, bold=False, color=(0, 0, 0)):
        fuente = b"/F2" if bold else b"/F1"
        r, g, b = color
        self._ops.append(
            b"BT %b %.2f Tf %.3f %.3f %.3f rg %.2f %.2f Td %b Tj ET\n"
            % (fuente, size, r, g, b, x, y, _escape_pdf(s)))

    def texto_centrado(self, x, y, s, size, bold=False, color=(0, 0, 0)):
        self.texto(x - _ancho_texto(s, size) / 2.0, y, s, size, bold, color)

    def imagen(self, ruta, x, y, w, h):
        """Incrusta una imagen (PNG/JPG) en (x,y) con tamaño w×h usando PIL.
        Devuelve True si lo logró; False si PIL no está o falla."""
        try:
            from PIL import Image
            import zlib
            im = Image.open(ruta).convert("RGB")
            maxpx = 500  # reducir para no inflar el PDF
            if max(im.size) > maxpx:
                f = maxpx / float(max(im.size))
                im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))))
            datos = zlib.compress(im.tobytes())
            self._img = {"w": im.width, "h": im.height, "data": datos}
            self._ops.append(b"q %.2f 0 0 %.2f %.2f %.2f cm /ImLogo Do Q\n"
                             % (w, h, x, y))
            return True
        except Exception:
            return False

    def to_bytes(self):
        contenido = b"".join(self._ops)
        tiene_img = self._img is not None
        xobj = b" /XObject << /ImLogo 7 0 R >>" if tiene_img else b""
        objetos = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.0f %.0f] "
             b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >>%b >> "
             b"/Contents 6 0 R >>" % (self.W, self.H, xobj)),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
            b"<< /Length %d >>\nstream\n%b\nendstream" % (len(contenido), contenido),
        ]
        if tiene_img:
            im = self._img
            objetos.append(
                b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
                b"/Length %d >>\nstream\n" % (im["w"], im["h"], len(im["data"]))
                + im["data"] + b"\nendstream")
        salida = bytearray(b"%PDF-1.4\n")
        offsets = []
        for i, obj in enumerate(objetos, start=1):
            offsets.append(len(salida))
            salida += b"%d 0 obj\n%b\nendobj\n" % (i, obj)
        inicio_xref = len(salida)
        n = len(objetos) + 1
        salida += b"xref\n0 %d\n" % n
        salida += b"0000000000 65535 f \n"
        for off in offsets:
            salida += b"%010d 00000 n \n" % off
        salida += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                   % (n, inicio_xref))
        return bytes(salida)


_RUTAS_LOGO = [Path(__file__).resolve().parent / "logo.png", Path("logo.png")]


def generar_hoja_omr(archivo_salida, num_preguntas: int) -> None:
    """Genera el PDF de la hoja OMR (Python puro). Misma geometría que el lector."""
    CM = 28.3464567
    pdf = _PDF(612.0, 792.0)
    W, H = pdf.W, pdf.H

    GRIS = (0.4, 0.4, 0.4)
    NEGRO = (0.0, 0.0, 0.0)

    margen = 1.5 * CM
    tamano_marca = 0.5 * CM

    # 1. MARCAS DE REFERENCIA (cuadrados negros en las 4 esquinas)
    pdf.color_relleno(0, 0, 0)
    pdf.rect_relleno(margen, margen, tamano_marca, tamano_marca)
    pdf.rect_relleno(W - margen - tamano_marca, margen, tamano_marca, tamano_marca)
    pdf.rect_relleno(margen, H - margen - tamano_marca, tamano_marca, tamano_marca)
    pdf.rect_relleno(W - margen - tamano_marca, H - margen - tamano_marca,
                     tamano_marca, tamano_marca)

    # 2. ENCABEZADO
    pdf.texto(margen + 1.0 * CM, H - 2.5 * CM,
              "Liceo Sahagún - Hoja de Respuestas", 16, bold=True)
    pdf.texto(margen + 1.0 * CM, H - 3.8 * CM,
              "Nombres y Apellidos: _____________________________________________", 11)
    pdf.texto(margen + 1.0 * CM, H - 4.8 * CM,
              "Grado y Curso: __________________   Asignatura: __________________", 11)

    # 3. LOGO (se incrusta si existe; si no, casilla marcador)
    logo_w = 4.0 * CM
    logo_h = 3.5 * CM
    pos_logo_x = W - margen - logo_w - 1.5 * CM
    pos_logo_y = H - 5.0 * CM
    ruta_logo = None
    for _r in _RUTAS_LOGO:
        if _r.exists():
            ruta_logo = _r
            break
    colocado = False
    if ruta_logo is not None:
        lado = min(logo_w, logo_h)  # el logo es cuadrado: se centra sin deformar
        lx = pos_logo_x + (logo_w - lado) / 2.0
        ly = pos_logo_y + (logo_h - lado) / 2.0
        colocado = pdf.imagen(str(ruta_logo), lx, ly, lado, lado)
    if not colocado:
        pdf.color_linea(0, 0, 0)
        pdf.grosor_linea(1)
        pdf.color_relleno(0.92, 0.92, 0.92)
        pdf.rect_caja(pos_logo_x, pos_logo_y, logo_w, logo_h)
        pdf.texto_centrado(pos_logo_x + logo_w / 2,
                           pos_logo_y + logo_h / 2 - 0.1 * CM, "[ LOGO ]", 10, bold=True)

    # 4. INSTRUCCIONES DE MARCADO
    y_instrucciones = H - 6.2 * CM
    pdf.texto(margen + 1.0 * CM, y_instrucciones, "INSTRUCCIONES DE MARCADO:", 9, bold=True)
    pdf.texto(margen + 1.0 * CM, y_instrucciones - 0.5 * CM,
              "Use lápiz o lapicero negro. Rellene COMPLETAMENTE el círculo sin salirse.", 8.5)
    pdf.texto(margen + 1.0 * CM, y_instrucciones - 0.9 * CM,
              "- Forma correcta: el círculo totalmente relleno. Evite equis, chulos o medio relleno.", 8.5)
    pdf.texto(margen + 1.0 * CM, y_instrucciones - 1.3 * CM,
              "- El código del estudiante se rellena con los tres dígitos que indique el docente.", 8.5)

    # 5. TÍTULOS DE COLUMNAS
    y_titulos = y_instrucciones - 2.5 * CM
    inicio_x_codigo = margen + 1.0 * CM
    inicio_x_preguntas = margen + 6.5 * CM
    pdf.texto(inicio_x_codigo, y_titulos, "CÓDIGO ALUMNO", 10, bold=True)
    pdf.texto(inicio_x_preguntas, y_titulos, "RESPUESTAS", 10, bold=True)

    radio_burbuja = 0.22 * CM
    espacio_y = 0.58 * CM
    espacio_x = 0.65 * CM
    y_inicio_burbujas = y_titulos - 1.0 * CM

    # Flecha minimalista
    pdf.color_linea(0.2, 0.2, 0.2)
    pdf.grosor_linea(1)
    x_start = inicio_x_codigo + 0.3 * CM
    x_end = x_start + (2 * espacio_x)
    y_flecha = y_titulos - 0.35 * CM
    pdf.linea(x_start, y_flecha, x_end, y_flecha)
    pdf.linea(x_end, y_flecha, x_end - 0.15 * CM, y_flecha + 0.1 * CM)
    pdf.linea(x_end, y_flecha, x_end - 0.15 * CM, y_flecha - 0.1 * CM)

    # 6. MATRIZ: CÓDIGO ALUMNO (3 columnas, dígitos 0-9)
    pdf.color_linea(0, 0, 0)
    pdf.grosor_linea(0.8)
    for fila in range(10):
        for col in range(3):
            x = inicio_x_codigo + 0.3 * CM + (col * espacio_x)
            y = y_inicio_burbujas - (fila * espacio_y)
            pdf.circulo(x, y, radio_burbuja)
            pdf.texto_centrado(x, y - 0.08 * CM, str(fila), 7.5, color=GRIS)

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
        x_base = inicio_x_preguntas + (columna_actual * 4.6 * CM)
        pdf.texto(x_base, y - 0.1 * CM, f"{i:02d}.", 9.5, color=NEGRO)
        for j, opc in enumerate(opciones):
            x_burbuja = x_base + 0.8 * CM + (j * espacio_x)
            pdf.color_linea(0, 0, 0)
            pdf.grosor_linea(0.8)
            pdf.circulo(x_burbuja, y, radio_burbuja)
            pdf.texto_centrado(x_burbuja, y - 0.08 * CM, opc, 7.5, color=GRIS)
        fila_actual += 1

    salida = Path(archivo_salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_bytes(pdf.to_bytes())


# ─────────────────────────────────────────────────────────────────────────────
# SELECCIÓN DE PROFESOR / GRADO / CURSO  (uso por consola en PC)
# ─────────────────────────────────────────────────────────────────────────────
def _subdirs(ruta: Path) -> list:
    if not ruta.exists():
        return []
    return sorted(d.name for d in ruta.iterdir() if d.is_dir())


def _elegir_o_crear(ruta_padre: Path, titulo: str, etiqueta: str,
                    transform=lambda s: s.strip()) -> Path:
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


def main() -> None:
    print("=" * 60)
    print("🎓 GENERADOR DE EXÁMENES OMR — Liceo Sahagún")
    print("=" * 60)
    ruta_curso = seleccionar_curso()
    dir_claves = ruta_curso / "examenes_claves"
    dir_pdf = ruta_curso / "hojas_pdf"
    dir_claves.mkdir(parents=True, exist_ok=True)
    dir_pdf.mkdir(parents=True, exist_ok=True)

    nombre_examen = input("\n📝 Nombre del examen (Ej: Mat_11A): ").strip()
    while not nombre_examen:
        nombre_examen = input("⚠️ El nombre no puede estar vacío: ").strip()
    nombre_examen = nombre_examen.replace(" ", "_")

    while True:
        try:
            cantidad = int(input("❓ Cantidad de preguntas (1-50): "))
            if 1 <= cantidad <= 50:
                break
            print("⚠️ Debe estar entre 1 y 50.")
        except ValueError:
            print("⚠️ Ingresa un número entero válido.")

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
        print("\n✅ ¡PROCESO COMPLETADO!")
        print(f"📄 Plantilla PDF: {ruta_pdf}")
        print(f"🔑 Clave JSON:    {ruta_json}")
    except Exception as e:
        print(f"\n❌ Error al guardar los archivos: {e}")


if __name__ == "__main__":
    main()
