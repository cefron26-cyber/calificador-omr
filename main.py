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
from kivy.clock import Clock
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
        self.no_vibra = True  # los botones de cerrar/salir no vibran
        self.halign = "center"
        self.valign = "middle"
        self.bind(pos=self._redibujar, size=self._redibujar)

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
    on_press: app.tap_pulsar(self)
    canvas.before:
        Color:
            rgba: C_AZUL if self.state == 'normal' else C_AZUL_OSC
        RoundedRectangle:
            pos: (self.x + self.width * 0.03, self.y + self.height * 0.03) if self.state == 'down' else self.pos
            size: (self.width * 0.94, self.height * 0.94) if self.state == 'down' else self.size
            radius: [10,]

<BotonAccion@Button>:
    color: C_DORADO_TXT
    bold: True
    canvas.before:
        Color:
            rgba: C_DORADO if self.state == 'normal' else C_DORADO_OSC
        RoundedRectangle:
            pos: (self.x + self.width * 0.03, self.y + self.height * 0.03) if self.state == 'down' else self.pos
            size: (self.width * 0.94, self.height * 0.94) if self.state == 'down' else self.size
            radius: [10,]

<BotonPeligro@Button>:
    color: C_BLANCO
    canvas.before:
        Color:
            rgba: C_ROJO if self.state == 'normal' else C_ROJO_OSC
        RoundedRectangle:
            pos: (self.x + self.width * 0.03, self.y + self.height * 0.03) if self.state == 'down' else self.pos
            size: (self.width * 0.94, self.height * 0.94) if self.state == 'down' else self.size
            radius: [10,]

<BotonOutline@Button>:
    color: C_DORADO_TXT
    bold: True
    canvas.before:
        Color:
            rgba: (1, 1, 1, 1) if self.state == 'normal' else (0.98, 0.96, 0.88, 1)
        RoundedRectangle:
            pos: (self.x + self.width * 0.03, self.y + self.height * 0.03) if self.state == 'down' else self.pos
            size: (self.width * 0.94, self.height * 0.94) if self.state == 'down' else self.size
            radius: [10,]
        Color:
            rgba: C_DORADO
        Line:
            rounded_rectangle: (self.x + self.width * 0.03 + 1, self.y + self.height * 0.03 + 1, self.width * 0.94 - 2, self.height * 0.94 - 2, 10) if self.state == 'down' else (self.x + 1, self.y + 1, self.width - 2, self.height - 2, 10)
            width: 1.4

<BotonSalir>:
    color: C_GRIS
    bold: False
    canvas.before:
        Color:
            rgba: (1, 1, 1, 1) if self.state == 'normal' else (0.95, 0.96, 0.98, 1)
        RoundedRectangle:
            pos: (self.x + self.width * 0.03, self.y + self.height * 0.03) if self.state == 'down' else self.pos
            size: (self.width * 0.94, self.height * 0.94) if self.state == 'down' else self.size
            radius: [10,]
        Color:
            rgba: C_BORDE
        Line:
            rounded_rectangle: (self.x + self.width * 0.03 + 1, self.y + self.height * 0.03 + 1, self.width * 0.94 - 2, self.height * 0.94 - 2, 10) if self.state == 'down' else (self.x + 1, self.y + 1, self.width - 2, self.height - 2, 10)
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
    raiz = FloatLayout()
    cont = BoxLayout(orientation="vertical",
                     padding=[dp(10), dp(40), dp(10), dp(10)], spacing=dp(8))
    lbl = Label(text=str(mensaje), halign="center", valign="top", size_hint_y=None)
    lbl.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
    lbl.bind(texture_size=lambda i, ts: setattr(i, "height", ts[1]))
    scroll = ScrollView()
    scroll.add_widget(lbl)
    cont.add_widget(scroll)
    raiz.add_widget(cont)
    btn = Factory.BotonPeligro(text="\u2715", size_hint=(None, None),
                               size=(dp(34), dp(34)), pos_hint={"right": 1, "top": 1})
    btn.no_vibra = True
    raiz.add_widget(btn)
    popup = Popup(title=titulo, content=raiz, size_hint=(0.9, 0.6))
    btn.bind(on_release=popup.dismiss)
    popup.open()


def confirmar(titulo, mensaje, on_si):
    """Muestra '¿estás seguro?' con Sí / No. Llama on_si() solo si pulsa Sí."""
    cont = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(12))
    lbl = Label(text=str(mensaje), halign="center", valign="middle")
    lbl.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
    cont.add_widget(lbl)
    fila = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
    btn_no = BotonSalir(text="No")
    btn_si = Factory.BotonPeligro(text="S\u00ed, continuar")
    fila.add_widget(btn_no)
    fila.add_widget(btn_si)
    cont.add_widget(fila)
    popup = Popup(title=titulo, content=cont, size_hint=(0.85, 0.4),
                  auto_dismiss=False)
    btn_no.bind(on_release=popup.dismiss)

    def _si(*_):
        popup.dismiss()
        try:
            on_si()
        except Exception as e:
            aviso("Error", str(e))
    btn_si.bind(on_release=_si)
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
        import openpyx