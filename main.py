#!/usr/bin/env python3
"""
main.py — Calificador OMR (Kivy).

PASO 1: Configuración inicial (una vez) + menú con desplegables.
PASO 2: Estudiantes — lista del curso con código automático.
PASO 3: Exámenes — crear la clave de respuestas y (opcional) el PDF de la hoja.

Reutiliza gestor_salones.py y generador_pdf.py. La clave se guarda en el mismo
formato que lee lector_omr.py / registro_notas.py.
"""

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.checkbox import CheckBox
from kivy.uix.image import Image
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.lang import Builder
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.widget import Widget
from kivy.utils import platform
from kivy.uix.floatlayout import FloatLayout
from kivy.graphics.texture import Texture

import os
import json
import shutil
import tempfile
from pathlib import Path
import gestor_salones as GS

BASE = GS.BASE_DIR  # carpeta "profesores"

ARCHIVO_LISTA = "lista_estudiantes.xlsx"
ESTUDIANTES_PRUEBA = ["Jesus", "Maria", "Jose"]


# ─────────────────────────────────────────────────────────────────────────────
# TEMA VISUAL · Estilo A "Institucional clásico" (solo apariencia, no lógica)
# ─────────────────────────────────────────────────────────────────────────────
AZUL     = (0.122, 0.220, 0.392, 1)   # #1F3864  (azul del escudo)
AZUL_OSC = (0.078, 0.157, 0.298, 1)   # #14284C  (azul al presionar)
DORADO   = (0.949, 0.718, 0.020, 1)   # #F2B705  (acento dorado)
FONDO    = (0.937, 0.945, 0.961, 1)   # #EFF1F5  (fondo gris claro)
BLANCO   = (1, 1, 1, 1)
# Colores "con significado" para texto con markup (formato hexadecimal):
VERDE = "2E7D32"   # aprobó
ROJO  = "C62828"   # reprobó / error
AMBAR = "F9A825"   # por revisar

_DIR = Path(__file__).resolve().parent


def _registrar_fuentes():
    """Si hay fuentes en assets/fonts, reemplaza la fuente por defecto.
    Detecta el archivo sin importar el nombre exacto (Inter-Regular.ttf,
    Inter_18pt-Regular.ttf, etc.). Si no hay, la app sigue con la letra estándar."""
    base = _DIR / "assets" / "fonts"
    if not base.exists():
        return
    ttfs = list(base.glob("*.ttf"))
    if not ttfs:
        return

    def _buscar(*claves):
        for t in ttfs:
            n = t.name.lower()
            if all(k in n for k in claves):
                return t
        return None

    regular = _buscar("regular") or ttfs[0]
    bold = _buscar("semibold") or _buscar("bold") or regular
    try:
        LabelBase.register(name="Roboto",
                           fn_regular=str(regular),
                           fn_bold=str(bold))
    except Exception:
        pass


def _ruta_logo():
    for r in (_DIR / "assets" / "logo.png", _DIR / "logo.png"):
        if r.exists():
            return str(r)
    return ""


LOGO = _ruta_logo()


def _vibrar(duracion: float = 0.02):
    """Vibración corta SOLO en Android. En PC no hace nada (no rompe la prueba)."""
    try:
        if platform == "android":
            from plyer import vibrator  # type: ignore  # solo existe en Android
            vibrator.vibrate(duracion)
    except Exception:
        pass


def _solicitar_permisos_android():
    """Pide permisos en tiempo de ejecución. Solo corre en Android."""
    try:
        if platform != "android":
            return
        from android.permissions import request_permissions, Permission  # type: ignore  # solo existe en Android
        request_permissions([
            Permission.CAMERA,
            Permission.WRITE_EXTERNAL_STORAGE,
            Permission.READ_EXTERNAL_STORAGE,
        ])
    except Exception:
        pass


class Encabezado(BoxLayout):
    """Barra azul con el escudo, el título y el subtítulo de cada pantalla."""

    def __init__(self, titulo, subtitulo="Liceo Sahagún", **kw):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=dp(64), padding=[dp(12), dp(10)],
                         spacing=dp(12), **kw)
        with self.canvas.before:
            Color(rgba=AZUL)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size,
                                        radius=[dp(12)])
        self.bind(pos=self._sync, size=self._sync)

        # Escudo "LS" (cuadro azul oscuro con borde dorado)
        badge = AnchorLayout(size_hint=(None, 1), width=dp(42))
        with badge.canvas.before:
            Color(rgba=(0.086, 0.165, 0.290, 1))
            badge._r = RoundedRectangle(pos=badge.pos, size=badge.size,
                                        radius=[dp(6), dp(6), dp(13), dp(13)])
            Color(rgba=DORADO)
            badge._l = Line(width=1.4, rounded_rectangle=(0, 0, dp(42), dp(42), dp(6)))
        badge.bind(pos=self._badge_sync, size=self._badge_sync)
        self._badge = badge
        badge.add_widget(Label(text="LS", bold=True, color=DORADO, font_size="15sp"))
        self.add_widget(badge)

        # Título + línea dorada + subtítulo
        caja = BoxLayout(orientation="vertical", spacing=dp(2))
        lbl_t = Label(text=titulo, bold=True, color=BLANCO, font_size="18sp",
                      halign="left", valign="bottom", shorten=True)
        sub = Label(text=subtitulo, color=(0.62, 0.71, 0.86, 1), font_size="12sp",
                    halign="left", valign="top")
        for lb in (lbl_t, sub):
            lb.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, i.height)))
        linea = Widget(size_hint=(None, None), size=(dp(46), dp(3)))
        with linea.canvas:
            Color(rgba=DORADO)
            linea._r = RoundedRectangle(pos=linea.pos, size=linea.size, radius=[dp(2)])
        linea.bind(pos=lambda w, *_: setattr(w._r, "pos", w.pos),
                   size=lambda w, *_: setattr(w._r, "size", w.size))
        caja.add_widget(lbl_t)
        caja.add_widget(linea)
        caja.add_widget(sub)
        self.add_widget(caja)

    def _sync(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _badge_sync(self, *_):
        b = self._badge
        b._r.pos = b.pos
        b._r.size = b.size
        b._l.rounded_rectangle = (b.x, b.y, b.width, b.height, dp(6))


class BotonMenu(Button):
    """Botón del menú principal con un ícono vectorial dorado a la izquierda."""

    def __init__(self, icono="", **kw):
        super().__init__(**kw)
        self._icono = icono
        self.halign = "left"
        self.valign = "middle"
        self.bind(pos=self._redibujar, size=self._redibujar)

    def on_press(self):
        _vibrar()

    def _redibujar(self, *_):
        self.text_size = (self.width - dp(58), self.height)
        self.padding = [dp(50), 0, dp(10), 0]
        self.canvas.after.clear()
        s = dp(20)
        x = self.x + dp(16)
        y = self.center_y - s / 2
        with self.canvas.after:
            Color(rgba=DORADO)
            self._dibujar_icono(self._icono, x, y, s)

    @staticmethod
    def _dibujar_icono(nombre, x, y, s):
        w = 1.6
        if nombre == "estudiantes":
            Line(circle=(x + s * 0.32, y + s * 0.74, s * 0.16), width=w)
            Line(circle=(x + s * 0.70, y + s * 0.74, s * 0.16), width=w)
            Line(rounded_rectangle=(x + s * 0.08, y + s * 0.04,
                                    s * 0.46, s * 0.40, s * 0.12), width=w)
            Line(rounded_rectangle=(x + s * 0.46, y + s * 0.04,
                                    s * 0.46, s * 0.40, s * 0.12), width=w)
        elif nombre == "examenes":
            Line(rounded_rectangle=(x + s * 0.16, y, s * 0.68, s, s * 0.08), width=w)
            Line(points=[x + s * 0.30, y + s * 0.72, x + s * 0.70, y + s * 0.72], width=w)
            Line(points=[x + s * 0.30, y + s * 0.52, x + s * 0.70, y + s * 0.52], width=w)
            Line(points=[x + s * 0.30, y + s * 0.32, x + s * 0.56, y + s * 0.32], width=w)
        elif nombre == "calificar":
            Line(points=[x + s * 0.16, y + s * 0.50, x + s * 0.42, y + s * 0.22,
                         x + s * 0.86, y + s * 0.80], width=2.0)
        elif nombre == "registro":
            Line(rounded_rectangle=(x, y, s, s, s * 0.08), width=w)
            Line(points=[x, y + s * 0.5, x + s, y + s * 0.5], width=w)
            Line(points=[x + s * 0.5, y, x + s * 0.5, y + s], width=w)


class Pildora(Label):
    """Etiqueta con fondo azul claro redondeado (para 'Curso actual')."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.color = AZUL
        self.font_size = "13sp"
        self.halign = "left"
        self.valign = "middle"
        self.padding = [dp(12), 0, dp(12), 0]
        with self.canvas.before:
            Color(rgba=(0.906, 0.937, 0.984, 1))
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(8)])
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._r.pos = self.pos
        self._r.size = self.size
        self.text_size = (self.width - dp(24), self.height)


class BotonSalir(Button):
    """Botón minimalista 'Cerrar' con ícono de puerta y flecha (dibujado en canvas)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.halign = "center"
        self.valign = "middle"
        self.bind(pos=self._redibujar, size=self._redibujar)

    def on_press(self):
        _vibrar()

    def _redibujar(self, *_):
        self.text_size = (self.width, self.height)
        self.padding = [dp(34), 0, dp(8), 0]
        self.canvas.after.clear()
        s = dp(18)
        x = self.x + dp(14)
        y = self.center_y - s / 2
        with self.canvas.after:
            Color(rgba=(0.42, 0.47, 0.55, 1))
            # Marco de la puerta
            Line(rounded_rectangle=(x, y, s * 0.55, s, s * 0.06), width=1.6)
            # Flecha saliendo hacia afuera
            Line(points=[x + s * 0.28, y + s * 0.5, x + s * 1.06, y + s * 0.5], width=1.6)
            Line(points=[x + s * 0.84, y + s * 0.74, x + s * 1.08, y + s * 0.5,
                         x + s * 0.84, y + s * 0.26], width=1.6)


def _caption(texto):
    """Etiqueta pequeña gris que va encima de un campo."""
    lb = Label(text=texto, color=(0.42, 0.47, 0.55, 1), font_size="12sp",
               size_hint_y=None, height=dp(18), halign="left", valign="middle")
    lb.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, i.height)))
    return lb


# Tema visual (embebido para no depender de un archivo .kv externo) -------------
_TEMA_KV = """
#:set C_AZUL      (0.122, 0.220, 0.392, 1)
#:set C_AZUL_OSC  (0.078, 0.157, 0.298, 1)
#:set C_DORADO    (0.949, 0.718, 0.020, 1)
#:set C_DORADO_OSC (0.984, 0.788, 0.290, 1)
#:set C_DORADO_TXT (0.227, 0.169, 0.0, 1)
#:set C_ROJO      (0.780, 0.160, 0.160, 1)
#:set C_ROJO_OSC  (0.620, 0.120, 0.120, 1)
#:set C_TEXTO     (0.106, 0.129, 0.176, 1)
#:set C_GRIS      (0.42, 0.47, 0.55, 1)
#:set C_BORDE     (0.79, 0.83, 0.89, 1)
#:set C_BLANCO    (1, 1, 1, 1)

<Label>:
    color: C_TEXTO
    font_size: '15sp'

<Button>:
    background_normal: ''
    background_down: ''
    background_disabled_normal: ''
    background_color: 0, 0, 0, 0
    color: C_BLANCO
    font_size: '15sp'
    canvas.before:
        Color:
            rgba: C_AZUL if self.state == 'normal' else C_AZUL_OSC
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [10,]

<BotonAccion@Button>:
    color: C_DORADO_TXT
    bold: True
    canvas.before:
        Color:
            rgba: C_DORADO if self.state == 'normal' else C_DORADO_OSC
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [10,]

<BotonPeligro@Button>:
    color: C_BLANCO
    canvas.before:
        Color:
            rgba: C_ROJO if self.state == 'normal' else C_ROJO_OSC
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [10,]

<BotonOutline@Button>:
    color: C_DORADO_TXT
    bold: True
    canvas.before:
        Color:
            rgba: (1, 1, 1, 1) if self.state == 'normal' else (0.98, 0.96, 0.88, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [10,]
        Color:
            rgba: C_DORADO
        Line:
            rounded_rectangle: (self.x + 1, self.y + 1, self.width - 2, self.height - 2, 10)
            width: 1.4

<BotonSalir>:
    color: C_GRIS
    bold: False
    canvas.before:
        Color:
            rgba: (1, 1, 1, 1) if self.state == 'normal' else (0.95, 0.96, 0.98, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [10,]
        Color:
            rgba: C_BORDE
        Line:
            rounded_rectangle: (self.x + 1, self.y + 1, self.width - 2, self.height - 2, 10)
            width: 1.2

<Spinner>:
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: C_AZUL
    font_size: '14sp'
    canvas.before:
        Color:
            rgba: C_BLANCO
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [10,]
    canvas.after:
        Color:
            rgba: C_BORDE
        Line:
            rounded_rectangle: (self.x + 1, self.y + 1, self.width - 2, self.height - 2, 10)
            width: 1.2

<TextInput>:
    background_color: C_BLANCO
    foreground_color: C_TEXTO
    cursor_color: C_DORADO
    hint_text_color: C_GRIS
    font_size: '15sp'
    padding: [12, 12, 12, 12]
    canvas.after:
        Color:
            rgba: C_DORADO if self.focus else C_BORDE
        Line:
            rounded_rectangle: (self.x + 1, self.y + 1, self.width - 2, self.height - 2, 8)
            width: 1.3

<Popup>:
    background_color: 0, 0, 0, 0
    title_color: C_AZUL
    title_size: '17sp'
    separator_color: C_DORADO
    separator_height: '2dp'
    canvas.before:
        Color:
            rgba: C_BLANCO
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [14,]
"""

Builder.load_string(_TEMA_KV)


def _subdirs(p):
    return sorted(d.name for d in p.iterdir() if d.is_dir()) if p.exists() else []


def aviso(titulo, mensaje):
    cont = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
    lbl = Label(text=str(mensaje), halign="center", valign="top", size_hint_y=None)
    lbl.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
    lbl.bind(texture_size=lambda i, ts: setattr(i, "height", ts[1]))
    scroll = ScrollView()
    scroll.add_widget(lbl)
    cont.add_widget(scroll)
    btn = Button(text="Cerrar", size_hint_y=None, height=dp(46))
    cont.add_widget(btn)
    popup = Popup(title=titulo, content=cont, size_hint=(0.9, 0.6))
    btn.bind(on_release=popup.dismiss)
    popup.open()


def codigo_de(posicion: int) -> str:
    return f"{posicion:03d}"


def nota_local(aciertos, total):
    """Nota 0-10 truncada a 1 decimal, con piso 1.0 (igual que el lector)."""
    if not total:
        return 0.0
    nota = 10.0 * aciertos / total
    nota = int(nota * 10 + 1e-9) / 10.0
    return max(1.0, nota)


# ─────────────────────────────────────────────────────────────────────────────
# Planilla de estudiantes (mismo formato que registro_notas.py)
# ─────────────────────────────────────────────────────────────────────────────
def leer_lista_estudiantes(ruta_curso):
    archivo = ruta_curso / "estudiantes" / ARCHIVO_LISTA
    if not archivo.exists():
        return []
    from openpyxl import load_workbook
    ws = load_workbook(archivo).active
    nombres = []
    for fila in ws.iter_rows(min_row=2, values_only=True):
        if len(fila) > 2 and fila[2] and str(fila[2]).strip():
            nombres.append(str(fila[2]).strip())
    return nombres


def guardar_lista_estudiantes(ruta_curso, nombres):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    carpeta = ruta_curso / "estudiantes"
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / ARCHIVO_LISTA
    wb = Workbook()
    ws = wb.active
    ws.title = "Estudiantes"
    ws.append(["N° Lista", "Código", "Nombre"])
    for c in range(1, 4):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", start_color="1F3864")
        cell.alignment = Alignment(horizontal="center")
    for pos, nombre in enumerate(nombres, start=1):
        ws.append([pos, codigo_de(pos), nombre])
        cod = ws.cell(row=pos + 1, column=2)
        cod.number_format = "@"
        cod.alignment = Alignment(horizontal="center")
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 34
    wb.save(archivo)
    return archivo


def _openpyxl_disponible():
    try:
        import openpyxl  # noqa: F401
        return True
    except ImportError:
        return False


def importar_planilla(ruta_archivo):
    """
    Lee los nombres de los estudiantes desde un archivo .xlsx o .csv.
    - Si hay una columna con encabezado que contenga 'nombre', usa esa.
    - Si no, usa la columna con más texto (nombres).
    Devuelve una lista de nombres (en orden de aparición).
    """
    ruta = Path(ruta_archivo)
    ext = ruta.suffix.lower()
    filas = []
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        ws = load_workbook(ruta, data_only=True).active
        filas = [list(r) for r in ws.iter_rows(values_only=True)]
    elif ext == ".csv":
        import csv as _csv
        with open(ruta, newline="", encoding="utf-8-sig") as f:
            filas = [row for row in _csv.reader(f)]
    else:
        return []

    filas = [f for f in filas if f and any(c not in (None, "") for c in f)]
    if not filas:
        return []

    # Buscar columna por encabezado "nombre"
    encabezado = [str(c).strip().lower() if c is not None else "" for c in filas[0]]
    col = next((i for i, h in enumerate(encabezado) if "nombre" in h), None)
    inicio = 1 if col is not None else 0

    if col is None:
        # Sin encabezado claro: columna con más texto no numérico
        ncols = max(len(f) for f in filas)
        mejor, mejor_count = 0, -1
        for i in range(ncols):
            count = sum(1 for f in filas
                        if i < len(f) and isinstance(f[i], str)
                        and f[i].strip() and not f[i].strip().isdigit())
            if count > mejor_count:
                mejor, mejor_count = i, count
        col = mejor

    nombres = []
    for f in filas[inicio:]:
        if col < len(f) and f[col] is not None:
            v = str(f[col]).strip()
            if v and v.lower() != "nombre":
                nombres.append(v)
    return nombres


# ─────────────────────────────────────────────────────────────────────────────
# Exámenes (clave JSON + PDF opcional)
# ─────────────────────────────────────────────────────────────────────────────
def listar_examenes(ruta_curso):
    carpeta = ruta_curso / "examenes_claves"
    if not carpeta.exists():
        return []
    out = []
    for f in sorted(carpeta.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append((f, d.get("examen", f.stem), d.get("total_preguntas", "?")))
        except Exception:
            continue
    return out


def guardar_clave(ruta_curso, nombre, cantidad, clave_letras):
    carpeta = ruta_curso / "examenes_claves"
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = nombre.replace(" ", "_")
    datos = {"examen": nombre, "total_preguntas": cantidad,
             "clave_correctas": clave_letras}
    archivo = carpeta / f"respuestas_{nombre}.json"
    archivo.write_text(json.dumps(datos, indent=4, ensure_ascii=False), encoding="utf-8")
    return archivo


def generar_pdf_hoja(ruta_curso, nombre, cantidad):
    import generador_pdf as GP  # importación tardía (necesita reportlab)
    carpeta = ruta_curso / "hojas_pdf"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_pdf = carpeta / f"{nombre.replace(' ', '_')}_hoja.pdf"
    GP.generar_hoja_omr(ruta_pdf, cantidad)
    return ruta_pdf


def _guardar_en_descargas(src: Path, filename: str) -> str:
    """
    Copia 'src' a la carpeta de DESCARGAS del dispositivo y devuelve una ruta legible.
    - Android: MediaStore (Android 10+) y, si falla, /storage/emulated/0/Download.
    - iOS: carpeta de documentos de la app (accesible desde la app Archivos).
    - PC: la carpeta Descargas/Downloads del usuario.
    """
    if platform == "android":
        # 1) MediaStore (recomendado en Android moderno)
        try:
            from jnius import autoclass  # type: ignore  # lo provee pyjnius en Android
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            ContentValues = autoclass("android.content.ContentValues")
            MediaColumns = autoclass("android.provider.MediaStore$MediaColumns")
            Downloads = autoclass("android.provider.MediaStore$Downloads")
            activity = PythonActivity.mActivity
            resolver = activity.getContentResolver()
            values = ContentValues()
            values.put(MediaColumns.DISPLAY_NAME, filename)
            values.put(MediaColumns.MIME_TYPE, "application/pdf")
            values.put(MediaColumns.RELATIVE_PATH, "Download")
            uri = resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
            stream = resolver.openOutputStream(uri)
            stream.write(src.read_bytes())
            stream.flush()
            stream.close()
            return "Descargas/" + filename
        except Exception:
            pass
        # 2) Copia directa (Android 9 o con almacenamiento heredado)
        destino = Path("/storage/emulated/0/Download") / filename
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(src), str(destino))
        return str(destino)

    if platform == "ios":
        destino = Path(App.get_running_app().user_data_dir) / filename
        shutil.copy(str(src), str(destino))
        return str(destino)

    # PC
    base = None
    if platform == "win" or os.name == "nt":
        # Pregunta a Windows cuál es la carpeta "Descargas" real (respeta OneDrive)
        try:
            import winreg
            sub = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            guid = "{374DE290-123F-4565-9164-39C4925E467B}"  # known folder: Downloads
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as k:
                val, _ = winreg.QueryValueEx(k, guid)
            base = Path(os.path.expandvars(val))
        except Exception:
            base = None
    if base is None or not base.exists():
        base = Path.home() / "Downloads"
        if not base.exists():
            alt = Path.home() / "Descargas"
            base = alt if alt.exists() else base
    base.mkdir(parents=True, exist_ok=True)
    destino = base / filename
    shutil.copy(str(src), str(destino))
    return str(destino)


def generar_pdf_a_descargas(nombre, cantidad) -> str:
    """Genera la hoja PDF en un temporal y la deja SOLO en Descargas. La clave JSON
    se sigue guardando internamente con guardar_clave()."""
    import generador_pdf as GP  # importación tardía (necesita reportlab)
    nombre_arch = f"{nombre.replace(' ', '_')}_hoja.pdf"
    try:
        base_tmp = Path(App.get_running_app().user_data_dir)
    except Exception:
        base_tmp = Path(tempfile.gettempdir())
    tmp = base_tmp / nombre_arch
    GP.generar_hoja_omr(tmp, cantidad)
    destino = _guardar_en_descargas(tmp, nombre_arch)
    try:
        tmp.unlink()
    except Exception:
        pass
    return destino


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: CONFIGURACIÓN INICIAL
# ─────────────────────────────────────────────────────────────────────────────
class SetupScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(12))
        root.add_widget(Encabezado("Configuración inicial"))

        intro = Label(text="Esto se hace una sola vez.", size_hint_y=None,
                      height=dp(24), font_size="13sp", color=(0.42, 0.47, 0.55, 1),
                      halign="center", valign="middle")
        intro.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, i.height)))
        root.add_widget(intro)

        root.add_widget(_caption("¿Cómo te llamas?"))
        self.in_nombre = TextInput(hint_text="Nombre y apellido", multiline=False,
                                   size_hint_y=None, height=dp(50))
        root.add_widget(self.in_nombre)

        root.add_widget(_caption("Tus grados y cuántos cursos tiene cada uno"))
        self.filas_box = BoxLayout(orientation="vertical", size_hint_y=None,
                                   spacing=dp(10))
        self.filas_box.bind(minimum_height=self.filas_box.setter("height"))
        scroll = ScrollView()
        scroll.add_widget(self.filas_box)
        root.add_widget(scroll)

        self.filas = []
        self._agregar_fila()

        btn_add = Factory.BotonOutline(text="+ Agregar otro grado", size_hint_y=None,
                                       height=dp(50))
        btn_add.bind(on_release=lambda *_: self._agregar_fila())
        root.add_widget(btn_add)

        btn_crear = Factory.BotonAccion(text="Crear y continuar", size_hint_y=None,
                                        height=dp(56))
        btn_crear.bind(on_release=self._crear)
        root.add_widget(btn_crear)
        self.add_widget(root)

    def _agregar_fila(self):
        fila = BoxLayout(size_hint_y=None, height=dp(74), spacing=dp(12))

        col_g = BoxLayout(orientation="vertical", spacing=dp(4))
        col_g.add_widget(_caption("Grado"))
        in_grado = TextInput(hint_text="ej. 11", multiline=False, input_filter="int",
                             size_hint_y=None, height=dp(48))
        col_g.add_widget(in_grado)

        col_c = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_x=0.55)
        col_c.add_widget(_caption("Cursos"))
        sp = Spinner(text="1", values=[str(i) for i in range(1, 11)],
                     size_hint_y=None, height=dp(48))
        col_c.add_widget(sp)

        fila.add_widget(col_g)
        fila.add_widget(col_c)
        self.filas_box.add_widget(fila)
        self.filas.append((in_grado, sp))

    def _crear(self, *_):
        nombre = self.in_nombre.text.strip()
        if not nombre:
            aviso("Falta el nombre", "Escribe tu nombre para continuar.")
            return
        grados_cursos = []
        for in_grado, sp in self.filas:
            g = in_grado.text.strip()
            if g:
                grados_cursos.append((g, int(sp.text)))
        if not grados_cursos:
            aviso("Faltan grados", "Agrega al menos un grado con sus cursos.")
            return
        GS.inicializar_sistema()
        ruta_prof = GS.crear_profesor(nombre)
        for grado, n in grados_cursos:
            ruta_grado = GS.crear_grado(ruta_prof, grado)
            for i in range(n):
                GS.crear_curso(ruta_grado, chr(65 + i))
        App.get_running_app().ir_a_home()


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: MENÚ PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
class HomeScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.contenedor = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        self.add_widget(self.contenedor)

    def on_pre_enter(self, *_):
        self.construir()

    def construir(self):
        self.contenedor.clear_widgets()
        b = self.contenedor
        b.add_widget(Encabezado("Calificador OMR"))

        profesores = _subdirs(BASE)
        b.add_widget(_caption("Profesor"))
        self.sp_prof = Spinner(text=profesores[0] if profesores else "",
                               values=profesores, size_hint_y=None, height=dp(46))
        self.sp_prof.bind(text=lambda *_: self._refrescar_grados())
        b.add_widget(self.sp_prof)

        fila_gc = BoxLayout(size_hint_y=None, height=dp(70), spacing=dp(10))
        col_g = BoxLayout(orientation="vertical", spacing=dp(4))
        col_g.add_widget(_caption("Grado"))
        self.sp_grado = Spinner(text="", values=[], size_hint_y=None, height=dp(46))
        self.sp_grado.bind(text=lambda *_: self._refrescar_cursos())
        col_g.add_widget(self.sp_grado)
        col_c = BoxLayout(orientation="vertical", spacing=dp(4))
        col_c.add_widget(_caption("Curso"))
        self.sp_curso = Spinner(text="", values=[], size_hint_y=None, height=dp(46))
        self.sp_curso.bind(text=lambda *_: self._guardar_seleccion())
        col_c.add_widget(self.sp_curso)
        fila_gc.add_widget(col_g)
        fila_gc.add_widget(col_c)
        b.add_widget(fila_gc)

        self.lbl_actual = Pildora(text="", size_hint_y=None, height=dp(32))
        b.add_widget(self.lbl_actual)

        b.add_widget(Widget())  # espacio flexible: empuja el botón principal abajo

        btn_cal = Factory.BotonAccion(text="Calificar", size_hint_y=None, height=dp(54))
        btn_cal.bind(on_press=lambda *_: _vibrar())
        btn_cal.bind(on_release=lambda *_: self._entrar())
        b.add_widget(btn_cal)

        btn_add = Factory.BotonOutline(text="+ Agregar grado o curso",
                                       size_hint_y=None, height=dp(46))
        btn_add.bind(on_release=lambda *_: self._popup_agregar())
        b.add_widget(btn_add)

        self._refrescar_grados()

    def _entrar(self):
        app = App.get_running_app()
        if app.ruta_curso is None:
            aviso("Falta el curso", "Selecciona grado y curso primero.")
            return
        app.sm.current = "dashboard"

    def _refrescar_grados(self):
        prof = self.sp_prof.text
        grados = _subdirs(BASE / prof) if prof else []
        self.sp_grado.values = grados
        self.sp_grado.text = grados[0] if grados else ""
        self._refrescar_cursos()

    def _refrescar_cursos(self):
        prof, grado = self.sp_prof.text, self.sp_grado.text
        cursos = _subdirs(BASE / prof / grado) if (prof and grado) else []
        self.sp_curso.values = cursos
        self.sp_curso.text = cursos[0] if cursos else ""
        self._guardar_seleccion()

    def _guardar_seleccion(self):
        app = App.get_running_app()
        app.profesor = self.sp_prof.text
        app.grado = self.sp_grado.text
        app.curso = self.sp_curso.text
        if app.profesor and app.grado and app.curso:
            app.ruta_curso = BASE / app.profesor / app.grado / app.curso
            self.lbl_actual.text = (f"Curso actual: {app.grado}°{app.curso}"
                                    f"  ·  {app.profesor.replace('_', ' ')}")
        else:
            app.ruta_curso = None
            self.lbl_actual.text = "Selecciona grado y curso."

    def _popup_agregar(self):
        cont = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        cont.add_widget(Label(text="Agregar un grado nuevo (con sus cursos)",
                              size_hint_y=None, height=dp(28)))
        fila = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        fila.add_widget(Label(text="Grado:", size_hint_x=0.35))
        in_g = TextInput(hint_text="ej. 10", multiline=False, input_filter="int")
        fila.add_widget(in_g)
        cont.add_widget(fila)
        fila2 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        fila2.add_widget(Label(text="# Cursos:", size_hint_x=0.35))
        sp = Spinner(text="1", values=[str(i) for i in range(1, 11)])
        fila2.add_widget(sp)
        cont.add_widget(fila2)
        btn = Button(text="Crear", size_hint_y=None, height=dp(46))
        cont.add_widget(btn)
        pop = Popup(title="Agregar grado o curso", content=cont, size_hint=(0.9, 0.6))

        def _crear(*_):
            g = in_g.text.strip()
            if not g:
                return
            ruta_prof = BASE / self.sp_prof.text
            ruta_grado = GS.crear_grado(ruta_prof, g)
            inicio = len(_subdirs(ruta_grado))
            for i in range(int(sp.text)):
                GS.crear_curso(ruta_grado, chr(65 + inicio + i))
            pop.dismiss()
            self.construir()

        btn.bind(on_release=_crear)
        pop.open()


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: PANEL DEL CURSO (Dashboard)
# ─────────────────────────────────────────────────────────────────────────────
class DashboardScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.contenedor = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        self.add_widget(self.contenedor)

    def on_pre_enter(self, *_):
        self.construir()

    def construir(self):
        app = App.get_running_app()
        b = self.contenedor
        b.clear_widgets()
        b.add_widget(Encabezado("Panel del curso"))

        # Banner persistente "Actualmente estás calificando: Grado - Curso"
        banner = BoxLayout(size_hint_y=None, height=dp(48), padding=[dp(12), dp(6)])
        with banner.canvas.before:
            Color(rgba=DORADO)
            banner._r = RoundedRectangle(pos=banner.pos, size=banner.size,
                                         radius=[dp(10)])
        banner.bind(pos=lambda w, *_: setattr(w._r, "pos", w.pos),
                    size=lambda w, *_: setattr(w._r, "size", w.size))
        lbl = Label(markup=True, color=(0.227, 0.169, 0.0, 1),
                    halign="center", valign="middle", font_size="15sp",
                    text=f"Actualmente estás calificando:  [b]{app.grado}\u00b0 {app.curso}[/b]")
        lbl.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, i.height)))
        banner.add_widget(lbl)
        b.add_widget(banner)

        acciones = {
            "Estudiantes": ("estudiantes", "estudiantes"),
            "Exámenes": ("examenes", "examenes"),
            "Calificar": ("calificar", "calificar"),
            "Registro de notas": ("registro", "registro"),
        }
        for texto, (icono, destino) in acciones.items():
            btn = BotonMenu(icono=icono, text=texto, size_hint_y=None, height=dp(56))
            btn.bind(on_release=lambda inst, d=destino: self._ir(d))
            b.add_widget(btn)

        b.add_widget(Widget())  # espacio flexible

        btn_cambiar = Button(text="\u2190 Cambiar curso", size_hint_y=None, height=dp(46))
        btn_cambiar.bind(on_release=lambda *_: setattr(app.sm, "current", "home"))
        b.add_widget(btn_cambiar)

        btn_salir = BotonSalir(text="Cerrar", size_hint_y=None, height=dp(46))
        btn_salir.bind(on_release=lambda *_: App.get_running_app().stop())
        b.add_widget(btn_salir)

    def _ir(self, pantalla):
        app = App.get_running_app()
        if app.ruta_curso is None:
            aviso("Falta el curso", "Vuelve y selecciona grado y curso.")
            return
        app.sm.current = pantalla


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: ESTUDIANTES
# ─────────────────────────────────────────────────────────────────────────────
class EstudiantesScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cont = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        self.add_widget(self.cont)

    def on_pre_enter(self, *_):
        self.construir()

    def construir(self):
        app = App.get_running_app()
        self.cont.clear_widgets()
        b = self.cont
        b.add_widget(Encabezado(f"Estudiantes \u00b7 {app.grado}\u00b0{app.curso}"))
        if not _openpyxl_disponible():
            b.add_widget(Label(text="Falta la librería 'openpyxl'.\nInstala: pip install openpyxl"))
            self._boton_volver(b)
            return
        nombres = leer_lista_estudiantes(app.ruta_curso)
        lista_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        lista_box.bind(minimum_height=lista_box.setter("height"))
        if nombres:
            for pos, nombre in enumerate(nombres, start=1):
                lista_box.add_widget(Label(text=f"{codigo_de(pos)}    ·    {nombre}",
                                           size_hint_y=None, height=dp(30)))
        else:
            lista_box.add_widget(Label(text="(Aún no hay estudiantes)",
                                       size_hint_y=None, height=dp(30)))
        scroll = ScrollView()
        scroll.add_widget(lista_box)
        b.add_widget(scroll)
        fila = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.in_nombre = TextInput(hint_text="Nombre del estudiante", multiline=False)
        fila.add_widget(self.in_nombre)
        btn_add = Button(text="Agregar", size_hint_x=0.3)
        btn_add.bind(on_release=self._agregar)
        fila.add_widget(btn_add)
        b.add_widget(fila)
        btn_importar = Button(text="Importar planilla (Excel/CSV)",
                              size_hint_y=None, height=dp(44))
        btn_importar.bind(on_release=self._importar)
        b.add_widget(btn_importar)
        btn_prueba = Button(text="Generar lista de prueba (Jesús, María, José)",
                            size_hint_y=None, height=dp(44))
        btn_prueba.bind(on_release=self._generar_prueba)
        b.add_widget(btn_prueba)
        btn_vaciar = Factory.BotonPeligro(text="Vaciar lista", size_hint_y=None,
                                          height=dp(40))
        btn_vaciar.bind(on_release=self._vaciar)
        b.add_widget(btn_vaciar)
        self._boton_volver(b)

    def _boton_volver(self, b):
        btn = Button(text="← Volver al menú", size_hint_y=None, height=dp(44))
        btn.bind(on_release=lambda *_: setattr(App.get_running_app().sm, "current", "dashboard"))
        b.add_widget(btn)

    def _agregar(self, *_):
        app = App.get_running_app()
        nombre = self.in_nombre.text.strip()
        if not nombre:
            return
        nombres = leer_lista_estudiantes(app.ruta_curso)
        nombres.append(nombre)
        guardar_lista_estudiantes(app.ruta_curso, nombres)
        self.construir()

    def _generar_prueba(self, *_):
        app = App.get_running_app()
        guardar_lista_estudiantes(app.ruta_curso, list(ESTUDIANTES_PRUEBA))
        self.construir()

    def _vaciar(self, *_):
        app = App.get_running_app()
        guardar_lista_estudiantes(app.ruta_curso, [])
        self.construir()

    def _importar(self, *_):
        app = App.get_running_app()
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            ruta = filedialog.askopenfilename(
                title="Elige la planilla (Excel o CSV)",
                filetypes=[("Excel/CSV", "*.xlsx *.xlsm *.csv"), ("Todos", "*.*")])
            root.destroy()
        except Exception as e:
            aviso("Error", f"No se pudo abrir el explorador: {e}")
            return
        if not ruta:
            return
        nombres = importar_planilla(ruta)
        if not nombres:
            aviso("Sin nombres", "No encontré nombres en ese archivo.\n"
                  "Debe tener una columna con los nombres.")
            return
        guardar_lista_estudiantes(app.ruta_curso, nombres)
        self.construir()
        aviso("Listo", f"Se importaron {len(nombres)} estudiantes.")


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: EXÁMENES (Paso 3)
# ─────────────────────────────────────────────────────────────────────────────
class EsamenesScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cont = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        self.add_widget(self.cont)

    def on_pre_enter(self, *_):
        self.construir()

    def construir(self):
        app = App.get_running_app()
        self.cont.clear_widgets()
        b = self.cont
        b.add_widget(Encabezado(f"Ex\u00e1menes \u00b7 {app.grado}\u00b0{app.curso}"))
        examenes = listar_examenes(app.ruta_curso)
        lista_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        lista_box.bind(minimum_height=lista_box.setter("height"))
        if examenes:
            for ruta, nombre, npreg in examenes:
                fila = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(8))
                lbl = Label(
                    text=f"{nombre}\n[size=12sp][color=6E7681]{npreg} preguntas[/color][/size]",
                    markup=True, halign="left", valign="middle")
                lbl.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, i.height)))
                fila.add_widget(lbl)
                btn_dl = Factory.BotonOutline(text="Descargar", size_hint_x=None,
                                              width=dp(120))
                btn_dl.bind(on_release=lambda inst, n=nombre, q=npreg: self._descargar(n, q))
                fila.add_widget(btn_dl)
                btn_x = Factory.BotonPeligro(text="X", size_hint_x=None, width=dp(46))
                btn_x.bind(on_release=lambda inst, r=ruta: self._borrar(r))
                fila.add_widget(btn_x)
                lista_box.add_widget(fila)
        else:
            lista_box.add_widget(Label(text="(Aún no hay exámenes)",
                                       size_hint_y=None, height=dp(30)))
        scroll = ScrollView()
        scroll.add_widget(lista_box)
        b.add_widget(scroll)
        btn_nuevo = Button(text="+ Crear examen nuevo", size_hint_y=None, height=dp(50))
        btn_nuevo.bind(on_release=lambda *_: self._popup_nuevo())
        b.add_widget(btn_nuevo)
        btn_volver = Button(text="← Volver al menú", size_hint_y=None, height=dp(44))
        btn_volver.bind(on_release=lambda *_: setattr(App.get_running_app().sm, "current", "dashboard"))
        b.add_widget(btn_volver)

    def _borrar(self, ruta):
        try:
            ruta.unlink()
        except Exception:
            pass
        self.construir()

    def _descargar(self, nombre, npreg):
        try:
            cantidad = int(npreg)
        except (ValueError, TypeError):
            aviso("No se pudo", "Ese examen no tiene un número de preguntas válido.")
            return
        try:
            dest = generar_pdf_a_descargas(nombre, cantidad)
            aviso("Descargado", f"PDF guardado en:\n{dest}")
        except Exception as e:
            aviso("No se pudo descargar", str(e))

    def _popup_nuevo(self):
        cont = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(10))
        cont.add_widget(Label(text="Nuevo examen", size_hint_y=None, height=dp(28), font_size="16sp"))
        cont.add_widget(Label(text="Nombre:", size_hint_y=None, height=dp(22)))
        in_nombre = TextInput(hint_text="ej. Ingles", multiline=False, size_hint_y=None, height=dp(42))
        cont.add_widget(in_nombre)
        cont.add_widget(Label(text="Número de preguntas:", size_hint_y=None, height=dp(22)))
        in_num = TextInput(hint_text="ej. 10", multiline=False, input_filter="int",
                           size_hint_y=None, height=dp(42))
        cont.add_widget(in_num)
        cont.add_widget(Label(text="Clave (letras seguidas, ej. ABDC):", size_hint_y=None, height=dp(22)))
        in_clave = TextInput(hint_text="ABCD...", multiline=False, size_hint_y=None, height=dp(42))
        cont.add_widget(in_clave)
        fila_chk = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
        chk = CheckBox(size_hint_x=None, width=dp(36), active=True)
        fila_chk.add_widget(chk)
        fila_chk.add_widget(Label(text="Guardar el PDF de la hoja en Descargas"))
        cont.add_widget(fila_chk)
        lbl_msg = Label(text="", size_hint_y=None, height=dp(24), color=(0.78, 0.16, 0.16, 1))
        cont.add_widget(lbl_msg)
        btn_guardar = Factory.BotonAccion(text="Guardar", size_hint_y=None, height=dp(48))
        cont.add_widget(btn_guardar)
        pop = Popup(title="Crear examen", content=cont, size_hint=(0.95, 0.9))

        def _guardar(*_):
            app = App.get_running_app()
            nombre = in_nombre.text.strip()
            if not nombre:
                lbl_msg.text = "Escribe el nombre del examen."
                return
            try:
                cantidad = int(in_num.text)
            except ValueError:
                lbl_msg.text = "El número de preguntas debe ser un número."
                return
            if not (1 <= cantidad <= 50):
                lbl_msg.text = "El número de preguntas debe ir de 1 a 50."
                return
            clave = in_clave.text.strip().upper()
            if len(clave) != cantidad or any(c not in "ABCD" for c in clave):
                lbl_msg.text = f"La clave debe tener {cantidad} letras (solo A, B, C, D)."
                return
            guardar_clave(app.ruta_curso, nombre, cantidad, list(clave))
            mensaje = f"Examen '{nombre}' guardado."
            if chk.active:
                try:
                    dest = generar_pdf_a_descargas(nombre, cantidad)
                    mensaje += f"\nPDF en Descargas:\n{dest}"
                except Exception as e:
                    mensaje += f"\n(No se pudo guardar el PDF: {e})"
            pop.dismiss()
            self.construir()
            aviso("Listo", mensaje)

        btn_guardar.bind(on_release=_guardar)
        pop.open()


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: CALIFICAR (Paso 4)  ·  digitalizar -> leer -> guardar notas
# ─────────────────────────────────────────────────────────────────────────────
class CalificarScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cont = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        self.add_widget(self.cont)
        self.resultados = []
        self.examen = ""

    def on_pre_enter(self, *_):
        self.resultados = []
        self.examen = ""
        self.construir()

    def construir(self):
        app = App.get_running_app()
        self.cont.clear_widgets()
        b = self.cont
        b.add_widget(Encabezado(f"Calificar \u00b7 {app.grado}\u00b0{app.curso}"))

        examenes = listar_examenes(app.ruta_curso)
        if not examenes:
            b.add_widget(Label(text="Primero crea un examen en 'Exámenes'."))
            self._volver(b)
            return

        self._mapa_claves = {nombre: ruta for ruta, nombre, _ in examenes}
        fila = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        fila.add_widget(Label(text="Examen:", size_hint_x=0.3))
        nombres = list(self._mapa_claves.keys())
        self.sp_examen = Spinner(text=nombres[0], values=nombres)
        fila.add_widget(self.sp_examen)
        b.add_widget(fila)

        btn = Factory.BotonAccion(text="Cargar foto(s) y calificar", size_hint_y=None,
                                  height=dp(52))
        btn.bind(on_release=self._calificar)
        b.add_widget(btn)

        btn_cam = Button(text="Tomar foto con la cámara", size_hint_y=None, height=dp(48))
        btn_cam.bind(on_press=lambda *_: _vibrar())
        btn_cam.bind(on_release=self._tomar_foto)
        b.add_widget(btn_cam)

        lista = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        lista.bind(minimum_height=lista.setter("height"))
        if self.resultados:
            lista.add_widget(Label(text="[b]Resultados[/b]", markup=True,
                                   size_hint_y=None, height=dp(26)))
            for r in self.resultados:
                fila_r = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
                codigo = r.get("codigo", "???")
                dudoso = ("?" in codigo) or codigo in ("", "???", "ERROR")
                if codigo == "ERROR":
                    texto = f"[color={ROJO}]{r['archivo']}: error al leer[/color]"
                else:
                    n = nota_local(r["aciertos"], r["total"])
                    col = VERDE if n >= 6.0 else ROJO
                    estado = "APROB\u00d3" if n >= 6.0 else "REPROB\u00d3"
                    texto = (f"[b]{codigo}[/b]   \u00b7   {r['aciertos']}/{r['total']}"
                             f"   \u00b7   nota [color={col}][b]{n:.1f}[/b][/color]"
                             f"   \u00b7   [color={col}]{estado}[/color]")
                if dudoso:
                    texto = f"[color={AMBAR}]{codigo}   \u00b7   revisar c\u00f3digo[/color]"
                fila_r.add_widget(Label(text=texto, markup=True))
                btn_e = Button(text="Corregir código", size_hint_x=None, width=dp(140))
                btn_e.bind(on_release=lambda inst, rr=r: self._editar_codigo(rr))
                fila_r.add_widget(btn_e)
                lista.add_widget(fila_r)
        else:
            lista.add_widget(Label(text="Elige el examen y carga las fotos.",
                                   size_hint_y=None, height=dp(28)))
        scroll = ScrollView()
        scroll.add_widget(lista)
        b.add_widget(scroll)

        self._volver(b)

    def _volver(self, b):
        btn = Button(text="← Volver al menú", size_hint_y=None, height=dp(44))
        btn.bind(on_release=lambda *_: setattr(App.get_running_app().sm, "current", "dashboard"))
        b.add_widget(btn)

    def _elegir_archivos(self):
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            rutas = filedialog.askopenfilenames(
                title="Elige la(s) foto(s) de las hojas",
                filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp"), ("Todos", "*.*")])
            root.destroy()
            return list(rutas)
        except Exception as e:
            aviso("Error", f"No se pudo abrir el explorador: {e}")
            return []

    def _calificar(self, *_):
        app = App.get_running_app()
        archivos = self._elegir_archivos()
        if not archivos:
            return

        import lector_omr as L
        ruta_curso = app.ruta_curso
        clave_json = self._mapa_claves[self.sp_examen.text]

        # 1) Copiar las fotos a examenes_crudos (igual que la consola)
        dir_crudos = ruta_curso / "examenes_crudos"
        dir_crudos.mkdir(parents=True, exist_ok=True)
        for a in archivos:
            try:
                shutil.copy(a, dir_crudos / Path(a).name)
            except Exception:
                pass

        # 2) DIGITALIZAR: alinear crudos -> procesados (usa digitalizador.py)
        L.auto_digitalizar(ruta_curso)

        # 3) Calificar todas las hojas procesadas
        dir_imgs = ruta_curso / "examenes_procesados"
        dir_salida = ruta_curso / "resultados"
        dir_salida.mkdir(parents=True, exist_ok=True)
        imagenes = L._listar_imagenes(dir_imgs)
        if not imagenes:
            aviso("Sin imágenes", "No se generaron imágenes alineadas.\n"
                  "¿Está 'digitalizador.py' en la carpeta?")
            return

        datos = L.cargar_datos_examen(clave_json)
        examen = datos.nombre
        nuevos = []
        for img in imagenes:
            try:
                res = L._procesar_con_salida(img, clave_json, dir_salida)
                aciertos = sum(1 for p, r in res.respuestas.items()
                               if r == datos.clave.get(p))
                nuevos.append({"archivo": img.name, "codigo": res.codigo_estudiante,
                               "aciertos": aciertos, "total": datos.total_preguntas})
            except Exception as e:
                nuevos.append({"archivo": img.name, "codigo": "ERROR",
                               "aciertos": 0, "total": datos.total_preguntas,
                               "_err": str(e)})

        # 4) Guardar notas_<examen>.json (merge por archivo, igual que la consola)
        notas_path = dir_salida / f"notas_{examen}.json"
        registros = {}
        if notas_path.exists():
            try:
                for r in json.loads(notas_path.read_text(encoding="utf-8")):
                    registros[r.get("archivo", "")] = r
            except Exception:
                pass
        for r in nuevos:
            registros[r["archivo"]] = {k: v for k, v in r.items() if not k.startswith("_")}
        notas_path.write_text(
            json.dumps(list(registros.values()), indent=2, ensure_ascii=False),
            encoding="utf-8")

        # 5) Guardar para mostrar y permitir corrección de código
        self.examen = examen
        self.resultados = nuevos
        self.construir()

    def _editar_codigo(self, r):
        cont = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        cont.add_widget(Label(text=f"Hoja: {r['archivo']}", size_hint_y=None, height=dp(24)))
        cont.add_widget(Label(text="Código correcto (3 dígitos):",
                              size_hint_y=None, height=dp(24)))
        actual = "".join(c for c in r.get("codigo", "") if c.isdigit())
        ti = TextInput(text=actual, multiline=False, input_filter="int",
                       size_hint_y=None, height=dp(46))
        cont.add_widget(ti)
        lbl = Label(text="", size_hint_y=None, height=dp(22), color=(0.78, 0.16, 0.16, 1))
        cont.add_widget(lbl)
        btn = Factory.BotonAccion(text="Guardar c\u00f3digo", size_hint_y=None, height=dp(46))
        cont.add_widget(btn)
        pop = Popup(title="Corregir código", content=cont, size_hint=(0.85, 0.55))

        def _ok(*_):
            nuevo = ti.text.strip()
            if not nuevo.isdigit():
                lbl.text = "Escribe solo números."
                return
            nuevo = nuevo.zfill(3)
            r["codigo"] = nuevo
            self._actualizar_notas_codigo(r["archivo"], nuevo)
            pop.dismiss()
            self.construir()

        btn.bind(on_release=_ok)
        pop.open()

    def _actualizar_notas_codigo(self, archivo, nuevo):
        app = App.get_running_app()
        notas_path = app.ruta_curso / "resultados" / f"notas_{self.examen}.json"
        if not notas_path.exists():
            return
        try:
            data = json.loads(notas_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for e in data:
            if e.get("archivo") == archivo:
                e["codigo"] = nuevo
        notas_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    # ── Cámara (solo Android / iOS) ───────────────────────────────────────────
    def _ruta_captura(self):
        """Carpeta donde la cámara guardará la foto. En Android usa la carpeta
        externa de la app (sí es accesible por la app de cámara); en otro caso,
        el directorio de datos del usuario."""
        if platform == "android":
            try:
                from jnius import autoclass  # type: ignore
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                ctx = PythonActivity.mActivity
                ext = ctx.getExternalFilesDir(None)
                if ext is not None:
                    return Path(ext.getAbsolutePath()) / "captura_omr.jpg"
            except Exception:
                pass
        return Path(App.get_running_app().user_data_dir) / "captura_omr.jpg"

    def _tomar_foto(self, *_):
        if platform not in ("android", "ios"):
            aviso("Cámara", "Función solo disponible en dispositivos android o ios.")
            return
        if platform == "android":
            # Android 7+ cierra la app si se pasa una ruta file:// a otra app.
            # Este ajuste desactiva esa muerte por seguridad para que la app de
            # cámara pueda recibir la ruta del archivo (FileUriExposedException).
            try:
                from jnius import autoclass  # type: ignore
                StrictMode = autoclass("android.os.StrictMode")
                StrictMode.disableDeathOnFileUriExposure()
            except Exception:
                pass
        try:
            from plyer import camera  # type: ignore  # solo existe en Android/iOS
        except Exception:
            aviso("Cámara", "No se pudo acceder a la cámara en este dispositivo.")
            return
        destino = self._ruta_captura()
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            camera.take_picture(filename=str(destino), on_complete=self._foto_lista)
        except Exception as e:
            aviso("Cámara", f"No se pudo abrir la cámara: {e}")

    def _foto_lista(self, ruta_foto):
        """Callback de plyer: recibe la ruta de la foto, la procesa en RAM y la borra."""
        p = Path(str(ruta_foto)) if ruta_foto else None
        if not p or not p.exists():
            aviso("Cámara", "No se recibió la foto.")
            return
        import cv2
        import lector_omr as L
        img = cv2.imread(str(p))          # se carga a memoria (RAM)
        try:
            p.unlink()                    # se borra enseguida: no deja basura ni toca la galería
        except Exception:
            pass
        if img is None:
            aviso("Cámara", "La foto no se pudo leer.")
            return
        try:
            clave_json = self._mapa_claves[self.sp_examen.text]
            datos = L.cargar_datos_examen(clave_json)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            marcas = L.detectar_marcas(gray)
            if marcas is None:
                aviso("No se detectó la hoja",
                      "No se vieron las 4 marcas de esquina.\n"
                      "Repite la foto con buena luz y la hoja completa.")
                return
            recta, scale = L.corregir_perspectiva(img, marcas)
            res = L.leer_respuestas(recta, datos.total_preguntas, scale)
            anotada = L.dibujar_anotaciones(recta, res, datos.clave, scale, datos.nombre)
            aciertos = sum(1 for q, r in res.respuestas.items()
                           if r == datos.clave.get(q))
        except Exception as e:
            aviso("Error al procesar", str(e))
            return

        self.examen = datos.nombre
        archivo = f"camara_{res.codigo_estudiante}"
        self._registrar_nota_camara(archivo, res.codigo_estudiante,
                                    aciertos, datos.total_preguntas)
        self.resultados.append({"archivo": archivo, "codigo": res.codigo_estudiante,
                                "aciertos": aciertos, "total": datos.total_preguntas})
        self.construir()
        self._popup_resultado(anotada, res.codigo_estudiante, aciertos,
                              datos.total_preguntas)

    def _registrar_nota_camara(self, archivo, codigo, aciertos, total):
        app = App.get_running_app()
        dir_salida = app.ruta_curso / "resultados"
        dir_salida.mkdir(parents=True, exist_ok=True)
        notas_path = dir_salida / f"notas_{self.examen}.json"
        registros = {}
        if notas_path.exists():
            try:
                for r in json.loads(notas_path.read_text(encoding="utf-8")):
                    registros[r.get("archivo", "")] = r
            except Exception:
                pass
        registros[archivo] = {"archivo": archivo, "codigo": codigo,
                              "aciertos": aciertos, "total": total}
        notas_path.write_text(
            json.dumps(list(registros.values()), indent=2, ensure_ascii=False),
            encoding="utf-8")

    @staticmethod
    def _np_a_textura(img_bgr):
        import cv2
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        rgb = cv2.flip(rgb, 0)  # el origen de la textura de Kivy está abajo
        h, w = rgb.shape[:2]
        tex = Texture.create(size=(w, h), colorfmt="rgb")
        tex.blit_buffer(rgb.tobytes(), colorfmt="rgb", bufferfmt="ubyte")
        return tex

    def _popup_resultado(self, anotada, codigo, aciertos, total):
        cont = FloatLayout()
        img_w = Image(texture=self._np_a_textura(anotada),
                      allow_stretch=True, keep_ratio=True,
                      size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        cont.add_widget(img_w)
        btn_x = Factory.BotonPeligro(text="X", size_hint=(None, None),
                                     size=(dp(42), dp(42)),
                                     pos_hint={"right": 1, "top": 1})
        cont.add_widget(btn_x)
        pop = Popup(title=f"{codigo}  \u00b7  {aciertos}/{total}",
                    content=cont, size_hint=(0.96, 0.92))
        btn_x.bind(on_release=lambda *_: pop.dismiss())
        pop.open()


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: REGISTRO DE NOTAS (Paso 5)  ·  Excel cruzando código -> estudiante
# ─────────────────────────────────────────────────────────────────────────────
class RegistroScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cont = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        self.add_widget(self.cont)
        self.ultimo_excel = None
        self.mensaje = ""

    def on_pre_enter(self, *_):
        self.ultimo_excel = None
        self.mensaje = ""
        self.construir()

    def construir(self):
        app = App.get_running_app()
        self.cont.clear_widgets()
        b = self.cont
        b.add_widget(Encabezado(f"Registro de notas \u00b7 {app.grado}\u00b0{app.curso}"))

        import registro_notas as RN
        examenes = RN._examenes_disponibles(app.ruta_curso)
        if not examenes:
            b.add_widget(Label(text="Aún no hay exámenes calificados.\n"
                                    "Primero califica hojas en 'Calificar'."))
            self._volver(b)
            return

        fila = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        fila.add_widget(Label(text="Examen:", size_hint_x=0.3))
        self.sp_examen = Spinner(text=examenes[0], values=examenes)
        fila.add_widget(self.sp_examen)
        b.add_widget(fila)

        btn = Factory.BotonAccion(text="Generar registro Excel", size_hint_y=None,
                                  height=dp(52))
        btn.bind(on_release=self._generar)
        b.add_widget(btn)

        self.lbl_msg = Label(text=self.mensaje, size_hint_y=None, height=dp(60))
        b.add_widget(self.lbl_msg)

        if self.ultimo_excel:
            btn_abrir = Button(text="Abrir Excel", size_hint_y=None, height=dp(44))
            btn_abrir.bind(on_release=lambda *_: self._abrir(self.ultimo_excel))
            b.add_widget(btn_abrir)

        b.add_widget(Label(text="", size_hint_y=1))
        self._volver(b)

    def _volver(self, b):
        btn = Button(text="← Volver al menú", size_hint_y=None, height=dp(44))
        btn.bind(on_release=lambda *_: setattr(App.get_running_app().sm, "current", "dashboard"))
        b.add_widget(btn)

    def _generar(self, *_):
        app = App.get_running_app()
        import registro_notas as RN
        examen = self.sp_examen.text
        try:
            ruta = RN.generar_registro(app.ruta_curso, examen)
        except Exception as e:
            aviso("Error", f"No se pudo generar el registro:\n{e}")
            return
        if ruta is None:
            aviso("Falta la planilla",
                  "No hay lista de estudiantes para este curso.\n"
                  "Créala en 'Estudiantes' y vuelve a intentar.")
            return
        self.ultimo_excel = str(ruta)
        self.mensaje = f"Registro generado:\n{ruta.name}"
        self.construir()

    def _abrir(self, ruta):
        try:
            os.startfile(ruta)  # Windows
        except Exception as e:
            aviso("No se pudo abrir", f"Abre el archivo manualmente:\n{ruta}\n\n({e})")


# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────
class CalificadorApp(App):
    profesor = ""
    grado = ""
    curso = ""
    ruta_curso = None

    def build(self):
        self.title = "CalificadorApp"
        # En Android la carpeta de instalación es de solo lectura: movemos el
        # "directorio de trabajo" a la carpeta privada de la app (sí escribible),
        # para que 'profesores/' y todos los datos se guarden sin problemas.
        if platform == "android":
            try:
                os.chdir(self.user_data_dir)
            except Exception:
                pass
        _registrar_fuentes()
        Window.clearcolor = FONDO
        if platform != "android":
            Window.size = (400, 720)   # vista tipo celular para probar en PC
        GS.inicializar_sistema()
        self.sm = ScreenManager(transition=SlideTransition(duration=0.18))
        self.sm.add_widget(SetupScreen(name="setup"))
        self.sm.add_widget(HomeScreen(name="home"))
        self.sm.add_widget(DashboardScreen(name="dashboard"))
        self.sm.add_widget(EstudiantesScreen(name="estudiantes"))
        self.sm.add_widget(EsamenesScreen(name="examenes"))
        self.sm.add_widget(CalificarScreen(name="calificar"))
        self.sm.add_widget(RegistroScreen(name="registro"))
        self.sm.current = "home" if _subdirs(BASE) else "setup"
        return self.sm

    def on_start(self):
        _solicitar_permisos_android()

    def ir_a_home(self):
        self.sm.current = "home"


if __name__ == "__main__":
    CalificadorApp().run()