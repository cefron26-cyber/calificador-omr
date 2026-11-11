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
from kivy.graphics import (Color, RoundedRectangle, Line, Canvas, Scale, Ellipse, Rectangle,
                            PushMatrix, PopMatrix)
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget
from kivy.utils import platform
from kivy.uix.modalview import ModalView
from kivy.graphics.texture import Texture
from kivy.properties import NumericProperty, ListProperty, BooleanProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.animation import Animation

import os
import json
import shutil
import tempfile
import threading
from pathlib import Path
import gestor_salones as GS
import plataforma as PF
import layout_hoja as LH

BASE = GS.BASE_DIR  # carpeta "profesores"

ARCHIVO_LISTA = "lista_estudiantes.xlsx"
# Fotos que se califican a la vez. OpenCV ya reparte cada foto entre núcleos:
# con más de 3 casi no se gana y se gasta mucha memoria (importa en el celular).
HILOS_CALIFICAR = max(1, min(3, (os.cpu_count() or 2) - 1))


# ─────────────────────────────────────────────────────────────────────────────
# TEMA VISUAL · azul marino institucional + dorado, tarjetas blancas
# (solo apariencia, no lógica)
# ─────────────────────────────────────────────────────────────────────────────
AZUL     = (0.075, 0.161, 0.294, 1)   # #13294B  (azul del escudo)
AZUL_OSC = (0.047, 0.114, 0.220, 1)   # #0C1D38
DORADO   = (0.890, 0.663, 0.071, 1)   # #E3A912  (acento dorado)
FONDO    = (0.957, 0.965, 0.980, 1)   # #F4F6FA  (fondo de la app)
BLANCO   = (1, 1, 1, 1)
TEXTO    = (0.078, 0.125, 0.200, 1)   # #142033
GRIS     = (0.420, 0.451, 0.522, 1)   # #6B7385  (texto secundario)
BORDE    = (0.882, 0.898, 0.925, 1)   # #E1E5EC
TINTE    = (0.918, 0.941, 0.980, 1)   # #EAF0FA  (azul muy suave)
# Colores "con significado" para texto con markup (formato hexadecimal):
VERDE = "2E7D32"   # aprobó
ROJO  = "C62828"   # reprobó / error
AMBAR = "E09B00"   # por revisar
GRIS_HEX = "6B7385"

_DIR = Path(__file__).resolve().parent
_ESCUDO = _DIR / "assets" / "escudo_app.png"


def _registrar_fuentes():
    """Si hay fuentes en assets/fonts, reemplaza la fuente por defecto.
    Detecta el archivo sin importar el nombre exacto (Inter-Regular.ttf,
    Inter_18pt-Regular.ttf, etc.). Si no hay, la app sigue con la letra estándar.
    También registra "Titulos" (la versión gruesa) para los títulos de ventanas."""
    from kivy.resources import resource_find
    base = _DIR / "assets" / "fonts"
    ttfs = list(base.glob("*.ttf")) if base.exists() else []

    def _buscar(*claves):
        for t in ttfs:
            n = t.name.lower()
            if all(k in n for k in claves):
                return t
        return None

    bold = None
    if ttfs:
        regular = _buscar("regular") or ttfs[0]
        bold = _buscar("semibold") or _buscar("bold") or regular
        try:
            LabelBase.register(name="Roboto",
                               fn_regular=str(regular),
                               fn_bold=str(bold))
        except Exception:
            bold = None
    try:
        LabelBase.register(name="Titulos", fn_regular=str(
            bold or resource_find("data/fonts/Roboto-Bold.ttf")))
    except Exception:
        pass


_textura_escudo = None


def _textura_del_escudo():
    """Textura del escudo con mipmaps: se ve nítido y suave aunque se dibuje
    mucho más pequeño que la imagen original."""
    global _textura_escudo
    if _textura_escudo is None and _ESCUDO.exists():
        try:
            from kivy.core.image import Image as CoreImage
            _textura_escudo = CoreImage(str(_ESCUDO), mipmap=True).texture
        except Exception:
            _textura_escudo = None
    return _textura_escudo


def _fondo_tarjeta(w, color=BLANCO, radio=None, sombra=True):
    """Dibuja detrás del widget una tarjeta redondeada con sombra suave."""
    radio = dp(16) if radio is None else radio
    capas = []
    with w.canvas.before:
        if sombra:
            for extra, baja, alfa in ((dp(3), dp(4), 0.025), (dp(1.5), dp(2.5), 0.04),
                                      (dp(0.5), dp(1), 0.06)):
                Color(rgba=(0.05, 0.09, 0.17, alfa))
                capas.append((RoundedRectangle(radius=[radio + extra]), extra, baja))
        w._color_fondo = Color(rgba=color)
        capas.append((RoundedRectangle(radius=[radio]), 0, 0))

    def _sync(*_):
        for rect, extra, baja in capas:
            rect.pos = (w.x - extra, w.y - extra - baja)
            rect.size = (w.width + 2 * extra, w.height + 2 * extra)
    w.bind(pos=_sync, size=_sync)
    _sync()


class Tarjeta(BoxLayout):
    """Caja blanca redondeada con sombra, para agrupar contenido."""

    def __init__(self, color=BLANCO, radio=None, sombra=True, **kw):
        kw.setdefault("orientation", "vertical")
        super().__init__(**kw)
        _fondo_tarjeta(self, color, radio, sombra)


class InsigniaEscudo(Widget):
    """El escudo del colegio sobre un círculo blanco con aro dorado."""

    def __init__(self, tam, **kw):
        super().__init__(size_hint=(None, None), size=(tam, tam), **kw)
        tex = _textura_del_escudo()
        with self.canvas:
            Color(rgba=(0, 0, 0, 0.12))
            self._sombra = Ellipse()
            Color(rgba=BLANCO)
            self._circulo = Ellipse()
            Color(rgba=DORADO)
            self._aro = Line(width=dp(1.3))
            Color(1, 1, 1, 1)
            self._img = Rectangle(texture=tex) if tex is not None else None
        if tex is None:
            self._iniciales = Label(text="LS", bold=True, color=AZUL, font_size=tam * 0.32)
            self.add_widget(self._iniciales)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        x, y = self.pos
        t = self.width
        self._sombra.pos = (x, y - dp(1.5))
        self._sombra.size = (t, t)
        self._circulo.pos = (x, y)
        self._circulo.size = (t, t)
        self._aro.circle = (x + t / 2, y + t / 2, t / 2 - dp(2.5))
        s = t * 0.70
        if self._img is not None:
            self._img.pos = (x + (t - s) / 2, y + (t - s) / 2)
            self._img.size = (s, s)
        else:
            self._iniciales.pos = self.pos
            self._iniciales.size = self.size


def _vibrar(duracion: float = 0.02):
    """Vibración corta SOLO en Android. En PC no hace nada (no rompe la prueba)."""
    try:
        if platform == "android":
            from plyer import vibrator  # type: ignore  # solo existe en Android
            vibrator.vibrate(duracion)
    except Exception:
        pass


def _solicitar_permisos_android():
    """Solo Android 9 o anterior necesita permiso para guardar en Descargas.
    Desde Android 10 no se pide ningún permiso: las fotos y planillas se eligen
    con el selector del sistema y Descargas se usa a través de MediaStore."""
    try:
        if platform != "android":
            return
        from jnius import autoclass  # type: ignore
        if autoclass("android.os.Build$VERSION").SDK_INT <= 28:
            from android.permissions import request_permissions, Permission  # type: ignore
            request_permissions([Permission.WRITE_EXTERNAL_STORAGE])
    except Exception:
        pass


def _ajustar_texto(lb):
    """Hace que la etiqueta respete su ancho/alto (para alinear a la izquierda)."""
    lb.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, i.height)))
    return lb


def _redibujar_al_cambiar(w, funcion):
    """Llama a funcion() cuando el widget se mueve o cambia de tamaño, pero en el
    siguiente cuadro: así right/top/center ya tienen su valor final."""
    disparador = Clock.create_trigger(lambda dt: funcion(), -1)
    w.bind(pos=lambda *_: disparador(), size=lambda *_: disparador())


class Encabezado(BoxLayout):
    """Barra azul marino con el escudo, el título y el subtítulo de cada pantalla."""

    def __init__(self, titulo, subtitulo="Liceo Sahagún", **kw):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=dp(78), padding=[dp(12), dp(12), dp(12), dp(12)],
                         spacing=dp(12), **kw)
        _fondo_tarjeta(self, AZUL, dp(20))

        caja_escudo = AnchorLayout(size_hint=(None, 1), width=dp(54))
        caja_escudo.add_widget(InsigniaEscudo(dp(52)))
        self.add_widget(caja_escudo)

        caja = BoxLayout(orientation="vertical", spacing=dp(1))
        lbl_t = Label(text=titulo, bold=True, color=BLANCO, font_size="19sp",
                      halign="left", valign="bottom", shorten=True,
                      shorten_from="right")
        sub = Label(text=subtitulo, color=(0.95, 0.80, 0.42, 1), font_size="12.5sp",
                    halign="left", valign="top", shorten=True, shorten_from="right")
        caja.add_widget(_ajustar_texto(lbl_t))
        caja.add_widget(_ajustar_texto(sub))
        self.add_widget(caja)

        # Botón de cerrar la app (esquina superior derecha), con confirmación
        cerrar = AnchorLayout(size_hint=(None, 1), width=dp(36), anchor_y="top")
        btn_x = BotonCerrar(size_hint=(None, None), size=(dp(34), dp(34)))
        btn_x.bind(on_release=lambda *_: pedir_salir())
        cerrar.add_widget(btn_x)
        self.add_widget(cerrar)


class Portada(FloatLayout):
    """Encabezado grande de la pantalla de inicio: escudo, colegio y saludo."""

    def __init__(self, saludo, detalle, **kw):
        super().__init__(size_hint_y=None, height=dp(206), **kw)
        _fondo_tarjeta(self, AZUL, dp(24))
        caja = BoxLayout(orientation="vertical", spacing=dp(4),
                         padding=[dp(16), dp(18), dp(16), dp(16)],
                         pos_hint={"x": 0, "y": 0}, size_hint=(1, 1))
        fila_escudo = AnchorLayout(size_hint_y=None, height=dp(84))
        fila_escudo.add_widget(InsigniaEscudo(dp(82)))
        caja.add_widget(fila_escudo)
        caja.add_widget(Widget(size_hint_y=None, height=dp(6)))
        colegio = Label(text="LICEO SAHAGÚN", bold=True, font_size="11.5sp",
                        color=(0.95, 0.80, 0.42, 1), size_hint_y=None, height=dp(16))
        titulo = Label(text=saludo, bold=True, font_size="22sp", color=BLANCO,
                       size_hint_y=None, height=dp(30), shorten=True)
        sub = Label(text=detalle, font_size="13sp", color=(0.78, 0.83, 0.92, 1),
                    size_hint_y=None, height=dp(20), shorten=True)
        for lb in (colegio, titulo, sub):
            lb.halign = "center"
            lb.valign = "middle"
            caja.add_widget(_ajustar_texto(lb))
        self.add_widget(caja)
        btn_x = BotonCerrar(size_hint=(None, None), size=(dp(34), dp(34)),
                            pos_hint={"right": 0.975, "top": 0.95})
        btn_x.bind(on_release=lambda *_: pedir_salir())
        self.add_widget(btn_x)


class BotonMenu(Button):
    """Tarjeta del menú del curso: ícono, título, una línea de ayuda y una flecha."""

    def __init__(self, icono="", titulo="", detalle="", **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(76))
        super().__init__(markup=True, **kw)
        self._icono = icono
        self.text = (f"[b]{titulo}[/b]\n[size=12.5sp][color={GRIS_HEX}]{detalle}"
                     f"[/color][/size]")
        self.halign = "left"
        self.valign = "middle"
        self.color = TEXTO
        self.bold = False
        self.line_height = 1.15
        self.color_fondo = (0, 0, 0, 0)
        self.color_fondo_down = (0, 0, 0, 0)
        _fondo_tarjeta(self, BLANCO, dp(18))
        self.bind(state=lambda *_: setattr(
            self._color_fondo, "rgba", BLANCO if self.state == "normal" else TINTE))
        # El ícono va en su propio grupo: así se redibuja sin borrar el resto
        # de canvas.after (ahí está el cierre de la animación al tocar)
        self._g_icono = Canvas()
        self.canvas.after.add(self._g_icono)
        _redibujar_al_cambiar(self, self._redibujar)

    def _redibujar(self, *_):
        self.padding = [dp(74), 0, dp(40), 0]
        self.text_size = (self.width, self.height)
        self._g_icono.clear()
        d = dp(44)
        cx, cy = self.x + dp(16) + d / 2, self.center_y
        s = dp(22)
        with self._g_icono:
            Color(rgba=TINTE)
            RoundedRectangle(pos=(cx - d / 2, cy - d / 2), size=(d, d), radius=[dp(13)])
            Color(rgba=AZUL)
            self._dibujar_icono(self._icono, cx - s / 2, cy - s / 2, s)
            # Flecha ">" a la derecha
            Color(rgba=(0.70, 0.73, 0.79, 1))
            fx, fy, f = self.right - dp(22), self.center_y, dp(5)
            Line(points=[fx - f, fy + f * 1.4, fx, fy, fx - f, fy - f * 1.4],
                 width=dp(1.3), cap="round", joint="round")

    @staticmethod
    def _dibujar_icono(nombre, x, y, s):
        w = dp(1.3)
        if nombre == "estudiantes":
            Line(circle=(x + s * 0.36, y + s * 0.70, s * 0.17), width=w)
            Line(ellipse=(x + s * 0.06, y - s * 0.10, s * 0.60, s * 0.62, -90, 90), width=w)
            Line(circle=(x + s * 0.74, y + s * 0.64, s * 0.13), width=w)
            Line(ellipse=(x + s * 0.54, y - s * 0.02, s * 0.42, s * 0.46, 0, 90), width=w)
        elif nombre == "examenes":
            Line(rounded_rectangle=(x + s * 0.14, y, s * 0.72, s, s * 0.12), width=w)
            Line(points=[x + s * 0.32, y + s * 0.70, x + s * 0.68, y + s * 0.70], width=w,
                 cap="round")
            Line(points=[x + s * 0.32, y + s * 0.50, x + s * 0.68, y + s * 0.50], width=w,
                 cap="round")
            Line(points=[x + s * 0.32, y + s * 0.30, x + s * 0.54, y + s * 0.30], width=w,
                 cap="round")
        elif nombre == "calificar":
            Line(rounded_rectangle=(x, y + s * 0.08, s, s * 0.74, s * 0.14), width=w)
            Line(points=[x + s * 0.32, y + s * 0.82, x + s * 0.40, y + s * 0.96,
                         x + s * 0.60, y + s * 0.96, x + s * 0.68, y + s * 0.82], width=w,
                 joint="round")
            Line(circle=(x + s * 0.50, y + s * 0.45, s * 0.20), width=w)
        elif nombre == "registro":
            Line(points=[x + s * 0.12, y + s * 0.04, x + s * 0.12, y + s * 0.96], width=w,
                 cap="round")
            Line(points=[x + s * 0.04, y + s * 0.08, x + s * 0.96, y + s * 0.08], width=w,
                 cap="round")
            for i, alto in enumerate((0.40, 0.68, 0.52)):
                bx = x + s * (0.28 + i * 0.24)
                Line(rounded_rectangle=(bx, y + s * 0.16, s * 0.14, s * alto, s * 0.04),
                     width=w)
        elif nombre == "papelera":
            # Tapa con asa, cuerpo que se angosta hacia abajo y dos ranuras
            Line(points=[x + s * 0.08, y + s * 0.80, x + s * 0.92, y + s * 0.80], width=w,
                 cap="round")
            Line(points=[x + s * 0.36, y + s * 0.80, x + s * 0.40, y + s * 0.96,
                         x + s * 0.60, y + s * 0.96, x + s * 0.64, y + s * 0.80], width=w,
                 joint="round")
            Line(points=[x + s * 0.18, y + s * 0.80, x + s * 0.25, y + s * 0.04,
                         x + s * 0.75, y + s * 0.04, x + s * 0.82, y + s * 0.80], width=w,
                 joint="round")
            for fx in (0.41, 0.59):
                Line(points=[x + s * fx, y + s * 0.20, x + s * fx, y + s * 0.62], width=w,
                     cap="round")
        elif nombre == "codigos":
            # Tarjeta con un código de barras
            Line(rounded_rectangle=(x, y + s * 0.12, s, s * 0.76, s * 0.12), width=w)
            for fx, ancho in ((0.20, 1.6), (0.32, 1.0), (0.42, 2.0), (0.56, 1.0),
                              (0.66, 1.6), (0.80, 1.0)):
                Line(points=[x + s * fx, y + s * 0.30, x + s * fx, y + s * 0.70],
                     width=w * ancho * 0.8)
        elif nombre == "respaldo":
            # Caja de archivo: tapa, cuerpo y asa
            Line(rounded_rectangle=(x, y + s * 0.66, s, s * 0.26, s * 0.06), width=w)
            Line(points=[x + s * 0.08, y + s * 0.66, x + s * 0.08, y + s * 0.06,
                         x + s * 0.92, y + s * 0.06, x + s * 0.92, y + s * 0.66], width=w,
                 joint="round")
            Line(points=[x + s * 0.38, y + s * 0.46, x + s * 0.62, y + s * 0.46], width=w,
                 cap="round")
        elif nombre == "agregar":
            Line(circle=(x + s * 0.5, y + s * 0.5, s * 0.46), width=w)
            Line(points=[x + s * 0.5, y + s * 0.28, x + s * 0.5, y + s * 0.72], width=w,
                 cap="round")
            Line(points=[x + s * 0.28, y + s * 0.5, x + s * 0.72, y + s * 0.5], width=w,
                 cap="round")
        elif nombre == "organizar":
            # Tres reguladores (deslizadores) con su perilla
            for fy, fx in ((0.82, 0.30), (0.50, 0.68), (0.18, 0.44)):
                Line(points=[x, y + s * fy, x + s, y + s * fy], width=w, cap="round")
                Line(circle=(x + s * fx, y + s * fy, s * 0.11), width=w)


class BotonHerramienta(Button):
    """Tarjeta con un ícono dibujado (los de BotonMenu) y un texto corto.
    vertical=True: ícono arriba y texto abajo (mosaico); False: en fila."""

    def __init__(self, icono, texto, vertical=True, peligro=False, **kw):
        super().__init__(text=texto, **kw)
        self._icono, self._vertical = icono, vertical
        self._tinta = (0.776, 0.157, 0.157, 1) if peligro else AZUL
        self.color = TEXTO
        self.font_size = "12.5sp" if vertical else "14sp"
        self.bold = True
        self.halign = "center" if vertical else "left"
        self.valign = "bottom" if vertical else "middle"
        self.color_fondo = (0, 0, 0, 0)
        self.color_fondo_down = (0, 0, 0, 0)
        _fondo_tarjeta(self, BLANCO, dp(16))
        self.bind(state=lambda *_: setattr(
            self._color_fondo, "rgba", BLANCO if self.state == "normal" else TINTE))
        self._g = Canvas()
        self.canvas.after.add(self._g)
        _redibujar_al_cambiar(self, self._redibujar)

    def _redibujar(self, *_):
        if self._vertical:
            d, s = dp(40), dp(20)
            cx, cy = self.center_x, self.top - dp(8) - d / 2
            self.padding = [dp(2), dp(6)]
        else:
            d, s = dp(34), dp(17)
            cx, cy = self.x + dp(12) + d / 2, self.center_y
            self.padding = [dp(12) + d + dp(10), 0, dp(8), 0]
        self.text_size = (self.width, self.height)
        self._g.clear()
        with self._g:
            Color(rgba=(0.992, 0.925, 0.925, 1) if self._tinta[0] > 0.5 else TINTE)
            RoundedRectangle(pos=(cx - d / 2, cy - d / 2), size=(d, d), radius=[dp(11)])
            Color(rgba=self._tinta)
            BotonMenu._dibujar_icono(self._icono, cx - s / 2, cy - s / 2, s)


class Pildora(Label):
    """Etiqueta con fondo azul muy suave redondeado (para el curso elegido)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.color = AZUL
        self.font_size = "13.5sp"
        self.halign = "center"
        self.valign = "middle"
        self.markup = True
        with self.canvas.before:
            Color(rgba=TINTE)
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._r.pos = self.pos
        self._r.size = self.size
        self.text_size = (self.width - dp(24), self.height)


class BotonCerrar(Button):
    """Botón redondo con una X, para cerrar la app (va en el encabezado)."""

    def __init__(self, **kw):
        super().__init__(text="", **kw)
        self._icono = Canvas()
        self.canvas.after.add(self._icono)
        _redibujar_al_cambiar(self, self._redibujar)

    def _redibujar(self, *_):
        g = self._icono
        g.clear()
        m = self.width * 0.35
        g.add(Color(rgba=(1, 1, 1, 0.85)))
        g.add(Line(points=[self.x + m, self.y + m, self.right - m, self.top - m],
                   width=dp(1.3), cap="round"))
        g.add(Line(points=[self.x + m, self.top - m, self.right - m, self.y + m],
                   width=dp(1.3), cap="round"))


class BotonIcono(Button):
    """Botón cuadrado pequeño con un ícono dibujado: 'borrar' o 'descargar'."""

    def __init__(self, icono, peligro=False, **kw):
        kw.setdefault("size_hint", (None, None))
        kw.setdefault("size", (dp(44), dp(44)))
        super().__init__(text="", **kw)
        self._icono_nombre = icono
        self._tinta = (0.776, 0.157, 0.157, 1) if peligro else AZUL
        if peligro:
            self.color_fondo = (0.992, 0.925, 0.925, 1)
            self.color_fondo_down = (0.980, 0.851, 0.851, 1)
        else:
            self.color_fondo = TINTE
            self.color_fondo_down = (0.851, 0.890, 0.957, 1)
        self._g = Canvas()
        self.canvas.after.add(self._g)
        _redibujar_al_cambiar(self, self._redibujar)

    def _redibujar(self, *_):
        self._g.clear()
        s = dp(18)
        x, y = self.center_x - s / 2, self.center_y - s / 2
        w = dp(1.4)
        with self._g:
            Color(rgba=self._tinta)
            if self._icono_nombre == "borrar":
                Line(points=[x + s * 0.06, y + s * 0.80, x + s * 0.94, y + s * 0.80],
                     width=w, cap="round")
                Line(points=[x + s * 0.36, y + s * 0.80, x + s * 0.40, y + s * 0.96,
                             x + s * 0.60, y + s * 0.96, x + s * 0.64, y + s * 0.80],
                     width=w, joint="round")
                Line(points=[x + s * 0.18, y + s * 0.80, x + s * 0.26, y,
                             x + s * 0.74, y, x + s * 0.82, y + s * 0.80],
                     width=w, joint="round")
                Line(points=[x + s * 0.42, y + s * 0.20, x + s * 0.42, y + s * 0.62],
                     width=w, cap="round")
                Line(points=[x + s * 0.58, y + s * 0.20, x + s * 0.58, y + s * 0.62],
                     width=w, cap="round")
            elif self._icono_nombre in ("izq", "der"):
                d = -1 if self._icono_nombre == "izq" else 1
                cx = x + s * 0.5
                Line(points=[cx - d * s * 0.2, y + s * 0.92, cx + d * s * 0.2, y + s * 0.5,
                             cx - d * s * 0.2, y + s * 0.08], width=dp(1.8), cap="round",
                     joint="round")
            elif self._icono_nombre == "descargar":
                Line(points=[x + s * 0.5, y + s * 0.98, x + s * 0.5, y + s * 0.30],
                     width=w, cap="round")
                Line(points=[x + s * 0.24, y + s * 0.56, x + s * 0.5, y + s * 0.30,
                             x + s * 0.76, y + s * 0.56], width=w, cap="round",
                     joint="round")
                Line(points=[x + s * 0.06, y + s * 0.30, x + s * 0.06, y,
                             x + s * 0.94, y, x + s * 0.94, y + s * 0.30],
                     width=w, cap="round", joint="round")


class Casilla(ButtonBehavior, BoxLayout):
    """Fila tocable con una casilla de verificación propia y un texto."""
    active = BooleanProperty(False)

    def __init__(self, texto="", active=False, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(44))
        super().__init__(spacing=dp(12), **kw)
        self.active = active
        self._caja = Widget(size_hint=(None, 1), width=dp(24))
        self.add_widget(self._caja)
        self.lbl = _ajustar_texto(Label(text=texto, halign="left", valign="middle",
                                        font_size="14.5sp", markup=True))
        self.add_widget(self.lbl)
        self._g = Canvas()
        self._caja.canvas.add(self._g)
        _redibujar_al_cambiar(self._caja, self._dibujar)
        self.bind(active=self._dibujar)

    def on_release(self):
        self.active = not self.active

    def _dibujar(self, *_):
        c = self._caja
        t = dp(22)
        x, y = c.x, c.center_y - t / 2
        self._g.clear()
        with self._g:
            if self.active:
                Color(rgba=AZUL)
                RoundedRectangle(pos=(x, y), size=(t, t), radius=[dp(6)])
                Color(rgba=BLANCO)
                Line(points=[x + t * 0.26, y + t * 0.52, x + t * 0.44, y + t * 0.32,
                             x + t * 0.76, y + t * 0.70], width=dp(1.6), cap="round",
                     joint="round")
            else:
                Color(rgba=BLANCO)
                RoundedRectangle(pos=(x, y), size=(t, t), radius=[dp(6)])
                Color(rgba=(0.74, 0.77, 0.83, 1))
                Line(rounded_rectangle=(x, y, t, t, dp(6)), width=dp(1.2))


def _boton_volver(texto, destino):
    """Botón discreto (sin relleno) para volver a otra pantalla."""
    btn = Factory.BotonTexto(text=f"←  {texto}", size_hint_y=None, height=dp(44))
    btn.bind(on_release=lambda *_: setattr(App.get_running_app().sm, "current", destino))
    return btn


def _vacio(titulo, detalle="", alto=110):
    """Mensaje amable para cuando una lista todavía no tiene nada."""
    lbl = Label(text=f"[b]{titulo}[/b]" + (f"\n[size=13sp][color={GRIS_HEX}]{detalle}"
                                          f"[/color][/size]" if detalle else ""),
                markup=True, halign="center", valign="middle", size_hint_y=None,
                height=dp(alto), color=TEXTO, font_size="15.5sp", line_height=1.25)
    lbl.bind(width=lambda i, w: setattr(i, "text_size", (w - dp(24), None)))
    return lbl


def pedir_salir():
    """Pide confirmación antes de cerrar la app."""
    confirmar("¿Ya te vas?", "Todo tu trabajo queda guardado.",
              "Salir", lambda: App.get_running_app().stop(), peligro=False)


# ── Respuesta al tocar: TODOS los botones se hunden un poco y vibran ─────────
class _Pulso(Widget):   # Animation solo anima widgets
    valor = NumericProperty(1.0)   # ("s" no sirve: Animation lo usa como "paso")


def _preparar_pulso(w):
    """Agrega al botón una escala (alrededor de su centro) que se puede animar.
    Se agrega la primera vez que se toca: PushMatrix/Scale al inicio de
    canvas.before y PopMatrix al final de canvas.after."""
    p = getattr(w, "_pulso", None)
    if p is None:
        p = _Pulso()
        escala = Scale(1, 1, 1)
        w.canvas.before.insert(0, escala)
        w.canvas.before.insert(0, PushMatrix())
        w.canvas.after.add(PopMatrix())

        def _aplicar(_p, v):
            escala.origin = w.center
            escala.x = escala.y = v
            w.canvas.ask_update()
        p.bind(valor=_aplicar)
        w._pulso = p
    return p


_press_original = ButtonBehavior._do_press
_release_original = ButtonBehavior._do_release


def _do_press_con_pulso(self):
    _press_original(self)
    _vibrar()
    try:
        p = _preparar_pulso(self)
        Animation.cancel_all(p)
        Animation(valor=0.96, d=0.07, t="out_quad").start(p)
    except Exception:
        pass


def _do_release_con_pulso(self, *args):
    _release_original(self, *args)
    p = getattr(self, "_pulso", None)
    if p is not None:
        Animation.cancel_all(p)
        Animation(valor=1.0, d=0.22, t="out_back").start(p)


# Mismo nombre que los originales: Kivy a veces programa el "soltar" para un
# instante después buscándolo por su NOMBRE; con otro nombre, la app se cerraba.
_do_press_con_pulso.__name__ = "_do_press"
_do_release_con_pulso.__name__ = "_do_release"
ButtonBehavior._do_press = _do_press_con_pulso
ButtonBehavior._do_release = _do_release_con_pulso


class CirculoProgreso(Widget):
    """
    Anillo de progreso animado.
      • Arco dorado (grueso): cuánto se ha avanzado; crece suavemente.
      • Arco azul (fino, por dentro): gira mientras se trabaja, para que se
        note actividad aunque una foto tarde en procesarse.
      • En el centro, el porcentaje.
    """
    valor = NumericProperty(0.0)          # 0..1 (se anima con animar_a)
    giro = NumericProperty(0.0)           # ángulo del arco azul
    color_avance = ListProperty(list(DORADO))

    def __init__(self, con_porcentaje=True, **kw):
        self._con_porcentaje = con_porcentaje
        super().__init__(**kw)
        with self.canvas:
            Color(rgba=(0.906, 0.922, 0.949, 1))
            self._pista = Line(width=dp(6))
            self._c_avance = Color(rgba=self.color_avance)
            self._avance = Line(width=dp(6), cap="round")
            Color(rgba=AZUL)
            self._giro = Line(width=dp(2.2), cap="round")
        self.lbl = Label(markup=True, halign="center", valign="middle", color=AZUL)
        self.add_widget(self.lbl)
        self.bind(pos=self._dibujar, size=self._dibujar, valor=self._dibujar,
                  giro=self._dibujar, color_avance=self._dibujar)
        self._reloj = Clock.schedule_interval(self._girar, 1 / 60.0)

    def _girar(self, dt):
        self.giro = (self.giro + 260 * dt) % 360

    def _dibujar(self, *_):
        cx, cy = self.center
        r = min(self.width, self.height) / 2 - dp(8)
        self._pista.circle = (cx, cy, r)
        self._c_avance.rgba = self.color_avance
        if self.valor > 0.001:
            self._avance.circle = (cx, cy, r, 0, 360 * min(self.valor, 1.0))
        else:
            self._avance.points = []
        if self._reloj is not None:
            self._giro.circle = (cx, cy, r - dp(12), self.giro, self.giro + 80)
        else:
            self._giro.points = []
        self.lbl.size = self.size
        self.lbl.pos = self.pos
        self.lbl.text_size = self.size
        pct = int(round(self.valor * 100))
        self.lbl.text = (f"[size=34sp][b]{pct}[/b][/size][size=16sp][b] %[/b][/size]"
                         if self._con_porcentaje else "")

    def animar_a(self, valor):
        Animation.cancel_all(self, "valor")
        Animation(valor=valor, d=0.45, t="out_cubic").start(self)

    def detener(self):
        """Deja de girar el arco azul (el trabajo terminó)."""
        if self._reloj is not None:
            self._reloj.cancel()
            self._reloj = None
        self._dibujar()


class _VentanaSinRastro(ModalView):
    """ModalView que fuerza el repintado al cerrarse: si no, en algunos
    equipos la tarjeta quedaba "pegada" en pantalla hasta el siguiente toque."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(_is_open=self._al_cerrarse)

    @staticmethod
    def _al_cerrarse(_inst, abierto):
        if not abierto:
            Clock.schedule_once(lambda dt: Window.canvas.ask_update(), 0)


def _tarjeta_blanca(**kw):
    tarjeta = BoxLayout(orientation="vertical", **kw)
    with tarjeta.canvas.before:
        Color(rgba=BLANCO)
        fondo = RoundedRectangle(radius=[dp(18)])
    tarjeta.bind(pos=lambda w, *_: setattr(fondo, "pos", w.pos),
                 size=lambda w, *_: setattr(fondo, "size", w.size))
    return tarjeta


class PopupEspera(_VentanaSinRastro):
    """Ventana "Un momento…" con el anillo girando (sin porcentaje)."""

    def __init__(self, mensaje, **kw):
        super().__init__(size_hint=(0.8, None), height=dp(250), auto_dismiss=False,
                         background_color=(0, 0, 0, 0),
                         overlay_color=(0.05, 0.08, 0.15, 0.6), **kw)
        tarjeta = _tarjeta_blanca(padding=[dp(20), dp(18)], spacing=dp(10))
        caja = AnchorLayout(size_hint_y=None, height=dp(130))
        circulo = CirculoProgreso(size_hint=(None, None), size=(dp(120), dp(120)),
                                  con_porcentaje=False)
        caja.add_widget(circulo)
        lbl = Label(text=mensaje, bold=True, color=AZUL, font_size="16sp",
                    halign="center", valign="middle")
        lbl.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, None)))
        tarjeta.add_widget(caja)
        tarjeta.add_widget(lbl)
        self.add_widget(tarjeta)


class PopupProgreso(_VentanaSinRastro):
    """Ventana de "Calificando…" con anillo de progreso, contadores y Cancelar."""

    def __init__(self, titulo, subtitulo, total, al_cancelar, **kw):
        super().__init__(size_hint=(0.9, None), height=dp(440), auto_dismiss=False,
                         background_color=(0, 0, 0, 0),
                         overlay_color=(0.05, 0.08, 0.15, 0.6), **kw)
        self.total = total
        self._al_cancelar = al_cancelar
        self._cuenta = {"ok": 0, "revisar": 0, "error": 0}

        tarjeta = _tarjeta_blanca(padding=[dp(22), dp(20)], spacing=dp(6))

        def etiqueta(texto, alto, **kw):
            lb = Label(text=texto, size_hint_y=None, height=dp(alto), halign="center",
                       valign="middle", shorten=True, shorten_from="center", **kw)
            lb.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, i.height)))
            return lb

        self.lbl_titulo = etiqueta(titulo, 28, bold=True, color=AZUL, font_size="19sp")
        self.lbl_sub = etiqueta(subtitulo, 20, color=GRIS, font_size="13sp")
        caja = AnchorLayout(size_hint_y=None, height=dp(190))
        self.circulo = CirculoProgreso(size_hint=(None, None), size=(dp(176), dp(176)))
        caja.add_widget(self.circulo)
        self.lbl_estado = etiqueta("Preparando…", 24, bold=True, font_size="16sp")
        self.lbl_archivo = etiqueta("", 18, color=GRIS, font_size="12sp")
        self.lbl_cuenta = etiqueta("", 22, markup=True, font_size="13sp")
        self.zona_boton = BoxLayout(size_hint_y=None, height=dp(48))
        self.btn = Factory.BotonOutline(text="Detener")
        self.btn.bind(on_release=self._cancelar)
        self.zona_boton.add_widget(self.btn)

        for w in (self.lbl_titulo, self.lbl_sub, caja, self.lbl_estado,
                  self.lbl_archivo, self.lbl_cuenta, Widget(size_hint_y=None, height=dp(4)),
                  self.zona_boton):
            tarjeta.add_widget(w)
        self.add_widget(tarjeta)
        self._mostrar_cuenta()

    def _mostrar_cuenta(self):
        c = self._cuenta
        self.lbl_cuenta.text = (f"[color={VERDE}]{c['ok']} bien[/color]   ·   "
                                f"[color={AMBAR}]{c['revisar']} por revisar[/color]   ·   "
                                f"[color={ROJO}]{c['error']} sin leer[/color]")

    def _cancelar(self, *_):
        self.btn.disabled = True
        self.btn.text = "Deteniendo…"
        self.lbl_estado.text = "Terminando las hojas en curso…"
        self._al_cancelar()

    def empezar(self, i, nombre):
        """Se empieza a procesar la hoja i (0-based)."""
        if not self.btn.disabled:
            self.lbl_estado.text = f"Calificando hoja {i + 1} de {self.total}"
        self.lbl_archivo.text = nombre

    def avance(self, hechas, estado):
        """Terminó una hoja. estado: 'ok', 'revisar' o 'error'."""
        self._cuenta[estado] += 1
        self._mostrar_cuenta()
        self.circulo.animar_a(hechas / float(self.total))

    def terminar(self, cuenta, cancelado, al_cerrar, nota="", texto_boton="Ver resultados"):
        """Muestra el resumen final y cambia el botón a 'Ver resultados'.
        nota: línea extra (p. ej. hojas reemplazadas)."""
        self._cuenta = cuenta
        self._mostrar_cuenta()
        self.circulo.detener()
        hechas = sum(cuenta.values())
        if cancelado:
            self.lbl_titulo.text = "Calificación detenida"
            self.lbl_estado.text = f"Alcanzamos a calificar {hechas} de {self.total}"
        else:
            self.lbl_titulo.text = "¡Listo!"
            self.circulo.animar_a(1.0)
            self.lbl_estado.text = (f"{hechas} hoja calificada" if hechas == 1
                                    else f"{hechas} hojas calificadas")
        self.lbl_archivo.text = nota or ("Dale un vistazo a las marcadas en ámbar o rojo."
                                         if cuenta["revisar"] or cuenta["error"] else "")
        # Anillo verde si todo salió bien; ámbar si hay algo que revisar
        self.circulo.color_avance = list(
            (0.180, 0.490, 0.196, 1) if not (cuenta["revisar"] or cuenta["error"])
            else (0.976, 0.659, 0.145, 1))
        self.zona_boton.clear_widgets()
        btn = Factory.BotonAccion(text=texto_boton)
        btn.bind(on_release=lambda *_: (self.dismiss(), al_cerrar()))
        self.zona_boton.add_widget(btn)


def _caption(texto):
    """Etiqueta pequeña gris que va encima de un campo."""
    lb = Label(text=texto, color=GRIS, font_size="12.5sp",
               size_hint_y=None, height=dp(20), halign="left", valign="middle")
    lb.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, i.height)))
    return lb


# Tema visual (embebido para no depender de un archivo .kv externo) -------------
_TEMA_KV = """
#:set C_AZUL       (0.075, 0.161, 0.294, 1)
#:set C_AZUL_OSC   (0.047, 0.114, 0.220, 1)
#:set C_DORADO     (0.890, 0.663, 0.071, 1)
#:set C_DORADO_OSC (0.800, 0.588, 0.047, 1)
#:set C_ROJO       (0.776, 0.157, 0.157, 1)
#:set C_ROJO_OSC   (0.620, 0.118, 0.118, 1)
#:set C_TEXTO      (0.078, 0.125, 0.200, 1)
#:set C_GRIS       (0.420, 0.451, 0.522, 1)
#:set C_BORDE      (0.882, 0.898, 0.925, 1)
#:set C_TINTE      (0.918, 0.941, 0.980, 1)
#:set C_TINTE_OSC  (0.851, 0.890, 0.957, 1)
#:set C_BLANCO     (1, 1, 1, 1)
#:set C_DESACT     (0.80, 0.82, 0.86, 1)

<Label>:
    color: C_TEXTO
    font_size: '15sp'

# Todos los botones dibujan su fondo con estas propiedades; cada estilo solo
# cambia los colores (así ningún estilo tapa a otro).
<Button>:
    background_normal: ''
    background_down: ''
    background_disabled_normal: ''
    background_disabled_down: ''
    background_color: 0, 0, 0, 0
    color: C_BLANCO
    disabled_color: (1, 1, 1, 0.75)
    bold: True
    font_size: '15sp'
    color_fondo: C_AZUL
    color_fondo_down: C_AZUL_OSC
    color_borde: (0, 0, 0, 0)
    radio: dp(14)
    canvas.before:
        Color:
            rgba: C_DESACT if self.disabled else ((self.color_fondo or C_AZUL) if self.state == 'normal' else (self.color_fondo_down or C_AZUL_OSC))
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [self.radio or 0,]
        Color:
            rgba: self.color_borde or (0, 0, 0, 0)
        Line:
            rounded_rectangle: (self.x + 0.5, self.y + 0.5, self.width - 1, self.height - 1, self.radio or 0)
            width: dp(0.9)

# Principal: dorado con texto azul marino
<BotonAccion@Button>:
    color: C_AZUL
    color_fondo: C_DORADO
    color_fondo_down: C_DORADO_OSC

<BotonPeligro@Button>:
    color: C_BLANCO
    color_fondo: C_ROJO
    color_fondo_down: C_ROJO_OSC

# Secundario: blanco con borde fino
<BotonOutline@Button>:
    color: C_AZUL
    color_fondo: C_BLANCO
    color_fondo_down: C_TINTE
    color_borde: C_BORDE

# Terciario: azul muy suave
<BotonSuave@Button>:
    color: C_AZUL
    color_fondo: C_TINTE
    color_fondo_down: C_TINTE_OSC

# Solo texto (volver, enlaces)
<BotonTexto@Button>:
    color: C_AZUL
    bold: False
    color_fondo: (0, 0, 0, 0)
    color_fondo_down: C_TINTE

<FilaLista@Button>:
    color: C_TEXTO
    bold: False
    markup: True
    halign: 'left'
    valign: 'middle'
    padding: [dp(16), 0]
    text_size: self.size
    font_size: '15sp'
    color_fondo: C_BLANCO
    color_fondo_down: C_TINTE
    color_borde: C_BORDE
    radio: dp(12)

<BotonCerrar>:
    color_fondo: (1, 1, 1, 0.12)
    color_fondo_down: (1, 1, 1, 0.28)
    radio: self.height / 2.

<Spinner>:
    color: C_TEXTO
    bold: False
    font_size: '15sp'
    halign: 'left'
    valign: 'middle'
    shorten: True
    shorten_from: 'right'
    padding: [dp(14), 0, dp(38), 0]
    text_size: self.size
    color_fondo: C_BLANCO
    color_fondo_down: C_TINTE
    color_borde: C_BORDE
    radio: dp(12)
    canvas.after:
        Color:
            rgba: C_GRIS
        Line:
            points: [self.right - dp(24), self.center_y + dp(2.5), self.right - dp(19), self.center_y - dp(2.5), self.right - dp(14), self.center_y + dp(2.5)]
            width: dp(1.3)
            cap: 'round'
            joint: 'round'

<SpinnerOption>:
    color: C_TEXTO
    bold: False
    halign: 'left'
    valign: 'middle'
    padding: [dp(16), 0]
    text_size: self.size
    height: dp(46)
    color_fondo: C_BLANCO
    color_fondo_down: C_TINTE
    radio: 0
    canvas.after:
        Color:
            rgba: C_BORDE
        Rectangle:
            pos: self.x + dp(12), self.y
            size: self.width - dp(24), dp(1)

<TextInput>:
    background_normal: ''
    background_active: ''
    background_color: C_BLANCO
    foreground_color: C_TEXTO
    cursor_color: C_AZUL
    cursor_width: dp(1.6)
    hint_text_color: (0.62, 0.65, 0.71, 1)
    selection_color: (0.890, 0.663, 0.071, 0.35)
    font_size: '15sp'
    padding: [dp(14), (self.height - self.line_height) / 2. if not self.multiline else dp(12), dp(14), 0]
    canvas.after:
        Color:
            rgba: C_AZUL if self.focus else C_BORDE
        Line:
            rounded_rectangle: (self.x + 0.5, self.y + 0.5, self.width - 1, self.height - 1, dp(12))
            width: dp(1.4) if self.focus else dp(1)

<Popup>:
    background: ''
    background_color: 0, 0, 0, 0
    # El oscurecido de Kivy se dibuja en "canvas", encima del fondo blanco; por eso
    # se apaga y se dibuja aquí, antes de la tarjeta.
    overlay_color: (0, 0, 0, 0)
    title_color: C_TEXTO
    title_size: '18sp'
    title_font: 'Titulos'
    separator_color: C_BORDE
    separator_height: dp(1)
    canvas.before:
        Color:
            rgba: (0.04, 0.07, 0.14, 0.55 * self._anim_alpha)
        Rectangle:
            size: self._window.size if self._window else (0, 0)
        Color:
            rgba: C_BLANCO
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(22),]
"""

Builder.load_string(_TEMA_KV)


def _subdirs(p):
    return sorted(d.name for d in p.iterdir() if d.is_dir()) if p.exists() else []


def aviso(titulo, mensaje):
    _popup_texto(titulo, mensaje, [("Entendido", "normal", None)])


def confirmar(titulo, mensaje, texto_si, al_si, peligro=True):
    """Pregunta antes de algo que no se puede deshacer."""
    _popup_texto(titulo, mensaje, [("No, volver", "outline", None),
                                   (texto_si, "peligro" if peligro else "accion", al_si)])


def aviso_archivo(titulo, mensaje, ref, nombre):
    """Aviso de archivo guardado, con botones para abrirlo o compartirlo."""
    def _abrir():
        err = PF.abrir(ref, nombre)
        if err:
            aviso("No pudimos abrirlo", f"Búscalo en tu carpeta de Descargas.\n\n({err})")

    def _compartir():
        err = PF.compartir(ref, nombre)
        if err:
            aviso("No pudimos compartirlo", err)

    _popup_texto(titulo, mensaje, [("Abrir", "accion", _abrir),
                                   ("Compartir" if PF.ES_ANDROID else "Ver carpeta", "normal", _compartir),
                                   ("Listo", "outline", None)])


def _popup_texto(titulo, mensaje, botones, alto=0.55):
    """Ventana con un texto y una fila de botones [(texto, estilo, acción)].
    estilo: 'accion' (dorado), 'peligro' (rojo), 'outline' o 'normal' (azul)."""
    cont = BoxLayout(orientation="vertical", padding=[dp(8), dp(12), dp(8), dp(4)],
                     spacing=dp(14))
    lbl = Label(text=str(mensaje), halign="center", valign="top", size_hint_y=None,
                color=TEXTO, line_height=1.2)
    lbl.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
    lbl.bind(texture_size=lambda i, ts: setattr(i, "height", ts[1]))
    scroll = ScrollView()
    scroll.add_widget(lbl)
    cont.add_widget(scroll)
    fila = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
    popup = Popup(title=titulo, content=cont, size_hint=(0.92, alto))
    clases = {"accion": Factory.BotonAccion, "peligro": Factory.BotonPeligro,
              "outline": Factory.BotonOutline, "normal": Factory.BotonSuave}
    for texto, estilo, accion in botones:
        btn = clases[estilo](text=texto, font_size="14sp")

        def _pulsar(*_, a=accion):
            popup.dismiss()
            if a is not None:
                a()
        btn.bind(on_release=_pulsar)
        fila.add_widget(btn)
    cont.add_widget(fila)
    popup.open()
    return popup


def en_segundo_plano(mensaje, trabajo, al_terminar):
    """
    Corre trabajo() en otro hilo mostrando una ventana de espera (la interfaz
    no se congela). Al final llama a al_terminar(resultado, error) en el hilo
    de la interfaz; error es None si todo salió bien.
    """
    espera = PopupEspera(mensaje)
    espera.open()

    def _hilo():
        try:
            res, err = trabajo(), None
        except Exception as e:
            res, err = None, e

        def _fin(dt):
            espera.dismiss()
            al_terminar(res, err)
        Clock.schedule_once(_fin, 0)
    threading.Thread(target=_hilo, daemon=True).start()


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


def generar_plantilla_estudiantes(carpeta):
    """Crea un Excel-plantilla para que el profesor llene N° de lista + nombres
    (formato tradicional Apellidos Nombres) y luego lo importe."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    archivo = Path(carpeta) / "plantilla_estudiantes.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Estudiantes"
    azul = PatternFill("solid", start_color="1F3864")
    blanco = Font(bold=True, color="FFFFFF", size=12)
    centro = Alignment(horizontal="center", vertical="center")
    ws.cell(row=1, column=1, value="N\u00b0 Lista")
    ws.cell(row=1, column=2, value="Nombre completo (Apellidos Nombres)")
    for c in (1, 2):
        cell = ws.cell(row=1, column=c)
        cell.fill = azul
        cell.font = blanco
        cell.alignment = centro
    for i in range(1, 41):
        ws.cell(row=i + 1, column=1, value=i).alignment = centro
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 46
    ws.freeze_panes = "A2"

    # Hoja con instrucciones claras
    ins = wb.create_sheet("LÉEME (instrucciones)")
    guia = [
        "CÓMO LLENAR LA PLANILLA DE ESTUDIANTES",
        "",
        "1) Ve a la hoja 'Estudiantes' (pestaña de abajo).",
        "2) Escribe un estudiante por fila en la columna 'Nombre completo'.",
        "3) Usa el formato tradicional: primero APELLIDOS y luego NOMBRES.",
        "      Ejemplo:  Pérez Gómez Juan Carlos",
        "4) El N° de Lista ya viene numerado por orden; puedes agregar más filas.",
        "5) El CÓDIGO de cada alumno (001, 002, 003, ...) lo genera la app sola,",
        "      según el orden de la lista. No tienes que escribirlo.",
        "6) Guarda este archivo (Excel) y vuelve a la app:",
        "      Estudiantes  ->  'Importar lista'  ->  elige este archivo.",
        "7) La app mostrará cada nombre con su código, para que se los des a los alumnos.",
    ]
    for i, linea in enumerate(guia, start=1):
        celda = ins.cell(row=i, column=1, value=linea)
        if i == 1:
            celda.font = Font(bold=True, size=13)
    ins.column_dimensions["A"].width = 80

    wb.save(archivo)
    return archivo


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
            # Las claves viejas no traen formato: todas eran de hoja completa
            formato = LH.obtener(d.get("formato")).clave
            total = d.get("total_preguntas", "?")
            try:
                hoja = LH.preguntas_en_hoja(total, d.get("preguntas_hoja"), formato)
            except (TypeError, ValueError):
                hoja = total
            out.append((f, d.get("examen", f.stem), total, formato, hoja))
        except Exception:
            continue
    return out


def guardar_clave(ruta_curso, nombre, cantidad, clave_letras, formato, preguntas_hoja=0):
    """preguntas_hoja: preguntas que trae la hoja IMPRESA, si son más que las
    del examen (examen de 25 en hoja de 30). Las que sobran no se califican."""
    carpeta = ruta_curso / "examenes_claves"
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = nombre.replace(" ", "_")
    datos = {"examen": nombre, "total_preguntas": cantidad,
             "clave_correctas": clave_letras, "formato": LH.obtener(formato).clave}
    hoja = LH.preguntas_en_hoja(cantidad, preguntas_hoja, formato)
    if hoja > cantidad:
        datos["preguntas_hoja"] = hoja
    archivo = carpeta / f"respuestas_{nombre}.json"
    archivo.write_text(json.dumps(datos, indent=4, ensure_ascii=False), encoding="utf-8")
    return archivo


def cambiar_hoja_examen(ruta_json, formato, preguntas_hoja=0):
    """Cambia la hoja (tamaño y preguntas impresas) de un examen ya creado,
    sin tocar sus respuestas correctas."""
    datos = json.loads(ruta_json.read_text(encoding="utf-8"))
    cantidad = int(datos["total_preguntas"])
    datos["formato"] = LH.obtener(formato).clave
    hoja = LH.preguntas_en_hoja(cantidad, preguntas_hoja, formato)
    if hoja > cantidad:
        datos["preguntas_hoja"] = hoja
    else:
        datos.pop("preguntas_hoja", None)
    ruta_json.write_text(json.dumps(datos, indent=4, ensure_ascii=False), encoding="utf-8")


def tipo_hoja(formato):
    """'media hoja' u 'hoja completa'"""
    return ("media hoja" if LH.obtener(formato).clave == LH.MEDIA_CARTA.clave
            else "hoja completa")


def texto_hoja(npreg, formato, hoja=0):
    """'25 preguntas · media hoja de 30' (o '20 preguntas · media hoja')."""
    texto = f"{npreg} pregunta{'' if npreg == 1 else 's'} · {tipo_hoja(formato)}"
    if isinstance(npreg, int) and isinstance(hoja, int) and hoja > npreg:
        texto += f" de {hoja}"
    return texto


def texto_sobrantes(npreg, hoja):
    """Las preguntas de la hoja que no son del examen: 'la 30 no cuenta',
    'de la 26 a la 30 no cuentan'. '' si no sobra ninguna."""
    if not (isinstance(npreg, int) and isinstance(hoja, int)) or hoja <= npreg:
        return ""
    if hoja == npreg + 1:
        return f"la {hoja} no cuenta"
    return f"de la {npreg + 1} a la {hoja} no cuentan"


def texto_alertas(r):
    """Lo que conviene mirar en una hoja calificada: 'doble marca en 3, 9 ·
    marcó fuera del examen (26, 27)'. '' si no hay nada."""
    a = r.get("alertas") or {}

    def nums(v):
        return ", ".join(str(x) for x in v[:4]) + ("…" if len(v) > 4 else "")
    partes = []
    if a.get("doble"):
        partes.append(f"doble marca en {nums(a['doble'])}")
    if a.get("dudosas"):
        partes.append(f"marca débil en {nums(a['dudosas'])}")
    if a.get("tenues"):
        partes.append(f"marca muy clara en {nums(a['tenues'])}")
    if a.get("marcas_extra"):
        partes.append(f"marcó fuera del examen ({nums(a['marcas_extra'])})")
    return " · ".join(partes)


# La hoja ya impresa que usa el docente (p. ej. la de 30 preguntas que imprime
# la institución). Se recuerda para proponerla en el siguiente examen.
ARCHIVO_HOJA_IMPRESA = "hoja_impresa.json"


def leer_hoja_impresa(ruta_profesor):
    """{'preguntas': 30, 'formato': 'media_carta'} o None si no usa una."""
    try:
        d = json.loads((ruta_profesor / ARCHIVO_HOJA_IMPRESA).read_text(encoding="utf-8"))
        return {"preguntas": int(d["preguntas"]), "formato": LH.obtener(d.get("formato")).clave}
    except Exception:
        return None


def guardar_hoja_impresa(ruta_profesor, preguntas, formato):
    """Recuerda la hoja impresa del docente; con preguntas=0 la olvida."""
    archivo = ruta_profesor / ARCHIVO_HOJA_IMPRESA
    try:
        if preguntas:
            archivo.write_text(json.dumps({"preguntas": int(preguntas),
                                           "formato": LH.obtener(formato).clave}),
                               encoding="utf-8")
        elif archivo.exists():
            archivo.unlink()
    except Exception:
        pass   # es solo una comodidad: si no se puede guardar, no pasa nada


def generar_pdf_a_descargas(nombre, cantidad, formato="carta"):
    """Genera la hoja PDF y la deja en Descargas. Devuelve (texto, referencia,
    nombre_archivo); la referencia sirve para abrirla o compartirla."""
    import generador_pdf as GP  # importación tardía
    nombre_arch = f"{nombre.replace(' ', '_')}_hoja.pdf"
    tmp = Path(tempfile.mkdtemp(prefix="hoja_")) / nombre_arch
    GP.generar_hoja_omr(tmp, cantidad, formato)
    texto, ref = PF.guardar_en_descargas(tmp, nombre_arch)
    shutil.rmtree(tmp.parent, ignore_errors=True)
    return texto, ref, nombre_arch


MESES_FOTOS = 6   # "Liberar espacio": exámenes calificados hace más de esto


def _fotos_de_hoja(r, carpeta_curso):
    """Archivos de una hoja calificada: su imagen marcada y su foto original
    archivada (reducida: <nombre>.jpg; o con su nombre de antes)."""
    rutas = []
    if r.get("imagen"):
        rutas.append(carpeta_curso / "resultados" / r["imagen"])
    archivo = r.get("archivo")
    if archivo:
        arch = carpeta_curso / "examenes_crudos_archivados"
        rutas += [arch / archivo, arch / f"{Path(archivo).stem}.jpg"]
    return [x for x in dict.fromkeys(rutas) if x.is_file()]


def examenes_con_fotos(meses=MESES_FOTOS):
    """
    Todos los exámenes que aún tienen fotos, por curso:
    [{curso, examen, notas_json, hojas, fotos, bytes, ultima, viejo}].
    'viejo': su última hoja se calificó hace más de 'meses' meses.
    Las fotos originales sueltas (de hojas descartadas o reemplazadas, que no
    son de ninguna nota) van en un grupo aparte (examen=None, viejo=True).
    """
    from datetime import datetime, timedelta
    limite = datetime.now() - timedelta(days=meses * 30.5)
    examenes, usadas = [], set()
    for notas_json in BASE.glob("*/*/*/resultados/notas_*.json"):
        carpeta = notas_json.parent.parent
        try:
            datos = json.loads(notas_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        fotos = []
        for r in datos:
            de_hoja = _fotos_de_hoja(r, carpeta)
            usadas.update(de_hoja)
            fotos += de_hoja
        if not fotos:
            continue
        fechas = [r["fecha"] for r in datos if r.get("fecha")]
        try:
            ultima = datetime.fromisoformat(max(fechas)) if fechas else None
        except ValueError:
            ultima = None
        examenes.append({"curso": _nombre_curso(carpeta.parent.name, carpeta.name),
                         "examen": notas_json.stem[len("notas_"):].replace("_", " "),
                         "notas_json": notas_json, "hojas": len(datos), "fotos": fotos,
                         "bytes": sum(f.stat().st_size for f in fotos), "ultima": ultima,
                         "viejo": ultima is not None and ultima < limite})
    sueltas = [f for f in BASE.glob("*/*/*/examenes_crudos_archivados/*")
               if f.is_file() and f not in usadas]
    if sueltas:
        examenes.append({"curso": "", "examen": None, "notas_json": None, "hojas": 0,
                         "fotos": sueltas, "bytes": sum(f.stat().st_size for f in sueltas),
                         "ultima": None, "viejo": True})

    def orden(e):   # por curso (6°A, 6°B, … 11°B) y, dentro, el más viejo primero
        g, _, c = e["curso"].partition("°")
        return (e["examen"] is None, int(g) if g.isdigit() else 0, c,
                e["ultima"] or datetime.min)
    examenes.sort(key=orden)
    return examenes


def borrar_fotos_examenes(viejos):
    """Borra las fotos (originales y hojas marcadas) de esos exámenes. Las
    notas se conservan; cada hoja queda marcada con foto_borrada. Devuelve
    los bytes liberados."""
    liberado = 0
    for e in viejos:
        for f in e["fotos"]:
            try:
                tam = f.stat().st_size
                f.unlink()
                liberado += tam
            except Exception:
                pass
        if e["notas_json"] is not None:
            datos = json.loads(e["notas_json"].read_text(encoding="utf-8"))
            for r in datos:
                if r.pop("imagen", None):
                    r["foto_borrada"] = True
            e["notas_json"].write_text(json.dumps(datos, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    return liberado


def _tamano(n_bytes):
    """1536000 -> '1.5 MB'"""
    if n_bytes >= 1e9:
        return f"{n_bytes / 1e9:.1f} GB"
    if n_bytes >= 1e6:
        return f"{n_bytes / 1e6:.1f} MB"
    return f"{max(n_bytes, 0) / 1e3:.0f} KB"


def generar_codigos_a_descargas(ruta_profesor, docente):
    """PDF de códigos de todos los salones del docente (una página por salón)
    en Descargas. Devuelve (texto, referencia, nombre_archivo, n_salones,
    salones_sin_estudiantes)."""
    import generador_pdf as GP
    import registro_notas as RN

    def orden_grado(g):   # 6, 7, …, 10, 11 (no "10" antes que "6")
        return (0, int(g), g) if g.isdigit() else (1, 0, g)

    salones, vacios = [], []
    for grado in sorted(_subdirs(ruta_profesor), key=orden_grado):
        for curso in _subdirs(ruta_profesor / grado):
            roster = RN.cargar_roster(ruta_profesor / grado / curso)
            if roster:
                salones.append((f"Grado {grado}° {curso}",
                                [(e["codigo"], e["nombre"]) for e in roster]))
            else:
                vacios.append(_nombre_curso(grado, curso))
    if not salones:
        raise ValueError("Ningún curso tiene estudiantes todavía. Agrégalos en "
                         "'Estudiantes' (o importa la planilla) y vuelve a intentarlo.")
    nombre_arch = "codigos_estudiantes.pdf"
    tmp = Path(tempfile.mkdtemp(prefix="codigos_")) / nombre_arch
    try:
        GP.generar_hojas_codigos(tmp, salones, docente)
        texto, ref = PF.guardar_en_descargas(tmp, nombre_arch)
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    return texto, ref, nombre_arch, len(salones), vacios


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: CONFIGURACIÓN INICIAL
# ─────────────────────────────────────────────────────────────────────────────
class SetupScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        root.add_widget(Portada("¡Hola!",
                                "Preparemos tu espacio. Solo toma un minuto."))

        tarjeta = Tarjeta(padding=[dp(16), dp(14)], spacing=dp(8))
        tarjeta.add_widget(_caption("¿Cómo te llamas?"))
        self.in_nombre = TextInput(hint_text="Tu nombre y apellido", multiline=False,
                                   size_hint_y=None, height=dp(50))
        tarjeta.add_widget(self.in_nombre)
        tarjeta.add_widget(Widget(size_hint_y=None, height=dp(4)))
        tarjeta.add_widget(_caption("¿Qué grados tienes? Indica cuántos cursos hay en cada uno"))
        self.filas_box = BoxLayout(orientation="vertical", size_hint_y=None,
                                   spacing=dp(8))
        self.filas_box.bind(minimum_height=self.filas_box.setter("height"))
        scroll = ScrollView()
        scroll.add_widget(self.filas_box)
        tarjeta.add_widget(scroll)

        self.filas = []
        self._agregar_fila()

        btn_add = Factory.BotonSuave(text="+  Agregar otro grado", size_hint_y=None,
                                     height=dp(46))
        btn_add.bind(on_release=lambda *_: self._agregar_fila())
        tarjeta.add_widget(btn_add)
        root.add_widget(tarjeta)

        btn_crear = Factory.BotonAccion(text="Empezar", size_hint_y=None,
                                        height=dp(54))
        btn_crear.bind(on_release=self._crear)
        root.add_widget(btn_crear)
        self.add_widget(root)

    def _agregar_fila(self):
        fila = BoxLayout(size_hint_y=None, height=dp(74), spacing=dp(12))

        col_g = BoxLayout(orientation="vertical", spacing=dp(4))
        col_g.add_widget(_caption("Grado"))
        in_grado = TextInput(hint_text="Ej.: 11", multiline=False, input_filter="int",
                             size_hint_y=None, height=dp(48))
        col_g.add_widget(in_grado)

        col_c = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_x=0.55)
        col_c.add_widget(_caption("Cursos (A, B…)"))
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
            aviso("¿Cómo te llamas?", "Escribe tu nombre para poder continuar.")
            return
        grados_cursos = []
        for in_grado, sp in self.filas:
            g = in_grado.text.strip()
            if g:
                grados_cursos.append((g, int(sp.text)))
        if not grados_cursos:
            aviso("Falta un grado", "Escribe al menos un grado (por ejemplo, 11) "
                  "y cuántos cursos tiene.")
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
        self.contenedor = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        self.add_widget(self.contenedor)

    def on_pre_enter(self, *_):
        self.construir()

    def construir(self):
        self.contenedor.clear_widgets()
        b = self.contenedor

        profesores = _subdirs(BASE)
        primero = profesores[0] if profesores else ""
        nombre = primero.replace("_", " ").split(" ")[0] if primero else ""
        b.add_widget(Portada(f"Hola, {nombre}" if nombre else "¡Hola!",
                             "¿Con qué curso vas a trabajar hoy?"))

        tarjeta = Tarjeta(size_hint_y=None, padding=[dp(16), dp(14)], spacing=dp(8))
        tarjeta.bind(minimum_height=tarjeta.setter("height"))
        self.sp_prof = Spinner(text=primero, values=profesores,
                               size_hint_y=None, height=dp(48))
        self.sp_prof.bind(text=lambda *_: self._refrescar_grados())
        # Solo se pregunta por el docente si en este celular hay más de uno
        if len(profesores) > 1:
            tarjeta.add_widget(_caption("Docente"))
            tarjeta.add_widget(self.sp_prof)

        fila_gc = BoxLayout(size_hint_y=None, height=dp(72), spacing=dp(10))
        col_g = BoxLayout(orientation="vertical", spacing=dp(4))
        col_g.add_widget(_caption("Grado"))
        self.sp_grado = Spinner(text="", values=[], size_hint_y=None, height=dp(48))
        self.sp_grado.bind(text=lambda *_: self._refrescar_cursos())
        col_g.add_widget(self.sp_grado)
        col_c = BoxLayout(orientation="vertical", spacing=dp(4))
        col_c.add_widget(_caption("Curso"))
        self.sp_curso = Spinner(text="", values=[], size_hint_y=None, height=dp(48))
        self.sp_curso.bind(text=lambda *_: self._guardar_seleccion())
        col_c.add_widget(self.sp_curso)
        fila_gc.add_widget(col_g)
        fila_gc.add_widget(col_c)
        tarjeta.add_widget(fila_gc)

        self.lbl_actual = Pildora(text="", size_hint_y=None, height=dp(36))
        tarjeta.add_widget(self.lbl_actual)
        b.add_widget(tarjeta)

        b.add_widget(Widget())  # espacio flexible: empuja el botón principal abajo

        btn_cal = Factory.BotonAccion(text="Entrar al curso", size_hint_y=None,
                                      height=dp(54))
        btn_cal.bind(on_release=lambda *_: self._entrar())
        b.add_widget(btn_cal)

        self._acciones(b)
        self._refrescar_grados()

    def _acciones(self, b):
        """Cursos en una fila; herramientas en mosaicos con ícono."""
        fila = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        for icono, texto, accion in (("agregar", "Agregar grado", self._popup_agregar),
                                     ("organizar", "Organizar", self._popup_editar)):
            btn = BotonHerramienta(icono, texto, vertical=False)
            btn.bind(on_release=lambda *_, a=accion: a())
            fila.add_widget(btn)
        b.add_widget(fila)
        fila = BoxLayout(size_hint_y=None, height=dp(86), spacing=dp(10))
        for icono, texto, accion, peligro in (
                ("codigos", "Códigos", self._hojas_codigos, False),
                ("respaldo", "Respaldo", self._popup_respaldo, False),
                ("papelera", "Liberar espacio", self._liberar_espacio, True)):
            btn = BotonHerramienta(icono, texto, peligro=peligro)
            btn.bind(on_release=lambda *_, a=accion: a())
            fila.add_widget(btn)
        b.add_widget(fila)

    # ── Liberar espacio (fotos de los exámenes que se elijan) ───────────────
    def _liberar_espacio(self):
        en_segundo_plano("Revisando el espacio\u2026", examenes_con_fotos,
                         self._popup_espacio)

    def _popup_espacio(self, examenes, err):
        if err:
            aviso("No pudimos revisar el espacio", str(err))
            return
        if not examenes:
            aviso("Liberar espacio", "No hay fotos de exámenes guardadas: no hay nada "
                  "que liberar.")
            return
        meses = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct",
                 "nov", "dic")
        cont = BoxLayout(orientation="vertical", spacing=dp(8), padding=[dp(6), dp(6)])
        cont.add_widget(_ajustar_texto(Label(
            text=f"Elige los exámenes cuyas fotos quieres borrar. [b]Las notas se "
                 f"conservan[/b]. Ya vienen marcados los de hace más de {MESES_FOTOS} "
                 "meses.", markup=True, color=GRIS, font_size="13sp", halign="left",
            valign="middle", size_hint_y=None, height=dp(54))))

        casillas = []     # (Casilla, examen)
        lista = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        lista.bind(minimum_height=lista.setter("height"))
        curso_actual = object()
        for e in examenes:
            if e["curso"] != curso_actual:
                curso_actual = e["curso"]
                titulo = f"Curso {e['curso']}" if e["curso"] else "Otras fotos"
                lista.add_widget(Label(text=f"[b]{titulo}[/b]", markup=True, color=AZUL,
                                       font_size="14sp", halign="left", valign="bottom",
                                       size_hint_y=None, height=dp(32),
                                       text_size=(None, None)))
                lista.children[0].bind(size=lambda i, *_: setattr(i, "text_size", i.size))
            if e["examen"] is None:
                nombre = "Fotos sueltas"
                detalle = f"De hojas descartadas o reemplazadas  ·  {_tamano(e['bytes'])}"
            else:
                nombre = e["examen"]
                fecha = (f"{meses[e['ultima'].month - 1]} {e['ultima'].year}"
                         if e["ultima"] else "sin fecha")
                detalle = (f"{e['hojas']} hoja{'s' if e['hojas'] != 1 else ''}  ·  "
                           f"{fecha}  ·  {_tamano(e['bytes'])}")
            c = Casilla(texto=f"{nombre}\n[size=12sp][color={GRIS_HEX}]{detalle}"
                              f"[/color][/size]", active=e["viejo"], height=dp(52))
            casillas.append((c, e))
            lista.add_widget(c)
        scroll = ScrollView()
        scroll.add_widget(lista)
        cont.add_widget(scroll)

        atajos = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        for texto, regla in ((f"Más de {MESES_FOTOS} meses", lambda e: e["viejo"]),
                             ("Todos", lambda e: True), ("Ninguno", lambda e: False)):
            btn = Factory.BotonSuave(text=texto, font_size="13sp")
            btn.bind(on_release=lambda *_, r=regla: [setattr(c, "active", r(e))
                                                     for c, e in casillas])
            atajos.add_widget(btn)
        cont.add_widget(atajos)

        fila = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        btn_borrar = Factory.BotonPeligro(font_size="14sp")
        btn_no = Factory.BotonOutline(text="Cancelar", font_size="14sp", size_hint_x=0.6)
        fila.add_widget(btn_borrar)
        fila.add_widget(btn_no)
        cont.add_widget(fila)
        pop = Popup(title="Liberar espacio", content=cont, size_hint=(0.95, 0.9))
        btn_no.bind(on_release=lambda *_: pop.dismiss())

        def elegidos():
            return [e for c, e in casillas if c.active]

        def actualizar(*_):
            peso = sum(e["bytes"] for e in elegidos())
            btn_borrar.text = f"Borrar fotos ({_tamano(peso)})" if peso else "Elige exámenes"
            btn_borrar.disabled = not peso
        for c, _ in casillas:
            c.bind(active=actualizar)
        actualizar()

        def _borrar(*_):
            sel = elegidos()
            n = sum(1 for e in sel if e["examen"] is not None)
            peso = _tamano(sum(e["bytes"] for e in sel))
            que = (f"{n} examen" if n == 1 else f"{n} exámenes") if n else "las fotos sueltas"

            def hacer():
                pop.dismiss()

                def listo(liberado, err2):
                    if err2:
                        aviso("No pudimos liberar el espacio", str(err2))
                        return
                    aviso("¡Listo!", f"Liberaste {_tamano(liberado)}.")
                en_segundo_plano("Liberando espacio\u2026",
                                 lambda: borrar_fotos_examenes(sel), listo)
            confirmar("¿Borrar las fotos?",
                      f"Se borrarán las fotos de {que} ({peso}): la original y la hoja "
                      "marcada.\n\nLas notas se conservan (Excel y estadísticas siguen "
                      "funcionando), pero ya no podrás ver esas hojas en la galería.",
                      "Sí, borrar fotos", hacer)
        btn_borrar.bind(on_release=_borrar)
        pop.open()

    # ── Hojas de códigos (todos los salones) ────────────────────────────────
    def _hojas_codigos(self):
        """PDF con los códigos de TODOS los salones del docente: una hoja carta
        por salón, en letra grande, para pegar en el salón o dictar."""
        prof = self.sp_prof.text
        if not prof:
            aviso("Aún no hay cursos", "Primero agrega tus grados y cursos.")
            return

        def trabajo():
            return generar_codigos_a_descargas(BASE / prof, prof.replace("_", " "))

        def listo(res, err):
            if err:
                aviso("No pudimos crear las hojas", str(err))
                return
            texto, ref, nombre, salones, vacios = res
            msg = (f"Una hoja por salón ({salones} hoja{'s' if salones != 1 else ''}), "
                   f"lista para imprimir.\n\nLa encuentras en:\n{texto}")
            if vacios:
                msg += (f"\n\nSin estudiantes todavía (no salen): {_enumerar(vacios)}.")
            aviso_archivo("Hojas de códigos listas", msg, ref, nombre)
        en_segundo_plano("Preparando las hojas de códigos…", trabajo, listo)

    # ── Copia de seguridad ──────────────────────────────────────────────────
    def _popup_respaldo(self):
        _popup_texto(
            "Copia de seguridad",
            "Guardamos todo (listas, exámenes, notas y fotos) en un solo archivo "
            "en tu carpeta de Descargas.\n\nSúbelo a Drive o envíatelo: si cambias "
            "de celular o reinstalas la app, con ese archivo recuperas todo.",
            [("Crear copia", "accion", self._guardar_respaldo),
             ("Restaurar", "normal", self._elegir_respaldo),
             ("Ahora no", "outline", None)], alto=0.52)

    def _guardar_respaldo(self):
        def trabajo():
            zip_path = PF.crear_respaldo(BASE)
            try:
                return PF.guardar_en_descargas(zip_path, zip_path.name) + (zip_path.name,)
            finally:
                zip_path.unlink()

        def listo(res, err):
            if err:
                aviso("No pudimos crear la copia", str(err))
                return
            texto, ref, nombre = res
            aviso_archivo("Tu copia está lista",
                          f"La encuentras en:\n{texto}\n\nTe recomendamos subirla a Drive "
                          "o enviártela, para tenerla fuera del celular.", ref, nombre)
        en_segundo_plano("Guardando tu copia\u2026", trabajo, listo)

    def _elegir_respaldo(self):
        PF.elegir_archivos(self._respaldo_elegido, tipo="zip", multiple=False,
                           titulo="Elige tu copia de seguridad (.zip)")

    def _respaldo_elegido(self, refs):
        nombre = PF.nombre_de(refs[0])
        if not nombre.lower().endswith(".zip"):
            aviso("Ese archivo no sirve", f"'{nombre}' no es una copia de seguridad "
                  "de la app (debe ser un archivo .zip).")
            return

        def trabajo():
            zip_local = PF.copiar_a_temporal(refs[0])
            try:
                return PF.restaurar_respaldo(zip_local, BASE)
            finally:
                shutil.rmtree(zip_local.parent, ignore_errors=True)

        def listo(anterior, err):
            if err:
                aviso("No pudimos restaurar la copia", str(err))
                return
            App.get_running_app().ruta_curso = None
            self.construir()
            aviso("¡Todo de vuelta!",
                  "Recuperamos tus datos de la copia.\n\n"
                  f"Lo que había antes no se perdió: quedó guardado aparte ({anterior.name}).")

        confirmar("¿Restaurar esta copia?",
                  f"Tus datos actuales se cambiarán por los de '{nombre}'.\n\n"
                  "No te preocupes: lo que hay ahora queda guardado aparte, por si acaso.",
                  "Sí, restaurar", lambda: en_segundo_plano("Restaurando tu copia\u2026",
                                                            trabajo, listo), peligro=False)

    def _entrar(self):
        app = App.get_running_app()
        if app.ruta_curso is None:
            aviso("Elige un curso", "Primero escoge el grado y el curso con el que "
                  "vas a trabajar.")
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
            self.lbl_actual.text = f"Vas a trabajar con [b]{app.grado}°{app.curso}[/b]"
        else:
            app.ruta_curso = None
            self.lbl_actual.text = "Escoge un grado y un curso"

    def _popup_agregar(self):
        cont = BoxLayout(orientation="vertical", spacing=dp(6), padding=[dp(8), dp(10)])
        lbl = Label(text="Si el grado ya existe, le sumamos los cursos nuevos.",
                    size_hint_y=None, height=dp(36), font_size="13sp", color=GRIS,
                    halign="left", valign="middle")
        cont.add_widget(_ajustar_texto(lbl))
        cont.add_widget(_caption("Grado"))
        in_g = TextInput(hint_text="Ej.: 10", multiline=False, input_filter="int",
                         size_hint_y=None, height=dp(48))
        cont.add_widget(in_g)
        cont.add_widget(_caption("¿Cuántos cursos?"))
        sp = Spinner(text="1", values=[str(i) for i in range(1, 11)],
                     size_hint_y=None, height=dp(48))
        cont.add_widget(sp)
        cont.add_widget(Widget())
        btn = Factory.BotonAccion(text="Agregar", size_hint_y=None, height=dp(50))
        cont.add_widget(btn)
        pop = Popup(title="Agregar un grado", content=cont, size_hint=(0.9, 0.62))

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

    def _popup_editar(self):
        prof_dir = BASE / self.sp_prof.text
        grados = _subdirs(prof_dir)
        cont = BoxLayout(orientation="vertical", spacing=dp(8), padding=[dp(6), dp(10)])
        cont.add_widget(_ajustar_texto(Label(
            text="Quita los grados o cursos que ya no uses. Siempre te preguntaremos "
                 "antes de borrar algo.",
            size_hint_y=None, height=dp(40), font_size="13sp", color=GRIS,
            halign="left", valign="middle")))
        inner = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        inner.bind(minimum_height=inner.setter("height"))
        if not grados:
            inner.add_widget(_vacio("Todavía no hay grados"))
        for grado in grados:
            fg = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8),
                           padding=[0, dp(6), 0, 0])
            lg = Label(text=f"[b]Grado {grado}[/b]", markup=True, font_size="16sp",
                       halign="left", valign="middle")
            fg.add_widget(_ajustar_texto(lg))
            bg = Factory.BotonOutline(text="Borrar grado", size_hint_x=None,
                                      width=dp(124), font_size="13.5sp",
                                      color=(0.776, 0.157, 0.157, 1))
            bg.bind(on_release=lambda inst, gr=grado: self._eliminar_grado(gr))
            fg.add_widget(bg)
            inner.add_widget(fg)
            for curso in _subdirs(prof_dir / grado):
                fc = Tarjeta(orientation="horizontal", size_hint_y=None, height=dp(52),
                             padding=[dp(14), dp(4), dp(4), dp(4)], spacing=dp(6),
                             radio=dp(12), sombra=False)
                lc = Label(text=f"Curso {grado}\u00b0{curso}", halign="left",
                           valign="middle")
                fc.add_widget(_ajustar_texto(lc))
                bc = BotonIcono("borrar", peligro=True)
                bc.bind(on_release=lambda inst, gr=grado, cu=curso:
                        self._eliminar_curso(gr, cu))
                fc.add_widget(bc)
                inner.add_widget(fc)
        scroll = ScrollView()
        scroll.add_widget(inner)
        cont.add_widget(scroll)
        btn_cerrar = Factory.BotonSuave(text="Listo", size_hint_y=None, height=dp(48))
        cont.add_widget(btn_cerrar)
        self._pop_editar = Popup(title="Organizar grados y cursos", content=cont,
                                 size_hint=(0.95, 0.85))
        btn_cerrar.bind(on_release=self._pop_editar.dismiss)
        self._pop_editar.open()

    def _eliminar_ruta(self, ruta, listo):
        try:
            shutil.rmtree(ruta)
        except Exception as e:
            aviso("No pudimos borrarlo", str(e))
            return
        try:
            self._pop_editar.dismiss()
        except Exception:
            pass
        App.get_running_app().ruta_curso = None
        self.construir()
        aviso("Hecho", listo)

    def _eliminar_grado(self, grado):
        confirmar(f"¿Borrar el grado {grado}?",
                  f"Se borrarán todos sus cursos, con sus estudiantes, exámenes y "
                  "notas. Esto no se puede deshacer.\n\n"
                  "Si quieres conservar algo, crea antes una copia de seguridad.",
                  "Sí, borrar", lambda: self._eliminar_ruta(
                      BASE / self.sp_prof.text / grado,
                      f"Borramos el grado {grado} y todos sus cursos."))

    def _eliminar_curso(self, grado, curso):
        confirmar(f"¿Borrar {grado}\u00b0{curso}?",
                  "Se borrarán sus estudiantes, exámenes y notas. "
                  "Esto no se puede deshacer.",
                  "Sí, borrar", lambda: self._eliminar_ruta(
                      BASE / self.sp_prof.text / grado / curso,
                      f"Borramos el curso {grado}\u00b0{curso}."))


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: PANEL DEL CURSO (Dashboard)
# ─────────────────────────────────────────────────────────────────────────────
class DashboardScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.contenedor = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        self.add_widget(self.contenedor)

    def on_pre_enter(self, *_):
        self.construir()

    def construir(self):
        app = App.get_running_app()
        b = self.contenedor
        b.clear_widgets()
        b.add_widget(Encabezado(f"Curso {app.grado}°{app.curso}",
                                f"Liceo Sahagún  ·  {app.profesor.replace('_', ' ')}"))
        b.add_widget(_caption("¿Qué quieres hacer?"))

        acciones = (
            ("estudiantes", "Estudiantes", "Tu lista del curso y el código de cada uno",
             "estudiantes"),
            ("examenes", "Exámenes", "Crea un examen y descarga la hoja para imprimir",
             "examenes"),
            ("calificar", "Calificar", "Toma fotos de las hojas y obtén las notas al instante",
             "calificar"),
            ("registro", "Notas", "Planilla de Excel, estadísticas y envío al coordinador",
             "registro"),
        )
        for icono, titulo, detalle, destino in acciones:
            btn = BotonMenu(icono=icono, titulo=titulo, detalle=detalle)
            btn.bind(on_release=lambda inst, d=destino: self._ir(d))
            b.add_widget(btn)

        b.add_widget(Widget())  # espacio flexible
        b.add_widget(_boton_volver("Cambiar de curso", "home"))

    def _ir(self, pantalla):
        app = App.get_running_app()
        if app.ruta_curso is None:
            aviso("Elige un curso", "Vuelve al inicio y escoge el grado y el curso.")
            return
        app.sm.current = pantalla


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: ESTUDIANTES
# ─────────────────────────────────────────────────────────────────────────────
class EstudiantesScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cont = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        self.add_widget(self.cont)

    def on_pre_enter(self, *_):
        self.construir()

    def construir(self):
        app = App.get_running_app()
        self.cont.clear_widgets()
        b = self.cont
        b.add_widget(Encabezado("Estudiantes", f"Curso {app.grado}°{app.curso}"))
        if not _openpyxl_disponible():
            b.add_widget(_vacio("Falta un componente",
                                "Instala la librería 'openpyxl' (pip install openpyxl)."))
            self._boton_volver(b)
            return
        nombres = leer_lista_estudiantes(app.ruta_curso)
        b.add_widget(_caption(f"{len(nombres)} estudiantes  ·  toca un nombre para cambiarlo"
                              if nombres else "Tu lista del curso"))
        lista_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6),
                              padding=[0, 0, 0, dp(4)])
        lista_box.bind(minimum_height=lista_box.setter("height"))
        if nombres:
            for pos, nombre in enumerate(nombres, start=1):
                fila = Factory.FilaLista(
                    text=f"[color={GRIS_HEX}][b]{codigo_de(pos)}[/b][/color]     {nombre}",
                    size_hint_y=None, height=dp(48))
                fila.bind(on_release=lambda inst, p=pos: self._editar(p))
                lista_box.add_widget(fila)
        else:
            lista_box.add_widget(_vacio(
                "Todavía no hay estudiantes",
                "Escríbelos abajo uno por uno, o importa tu lista de Excel. "
                "A cada uno le damos un código según su orden (001, 002…).", alto=150))
        scroll = ScrollView()
        scroll.add_widget(lista_box)
        b.add_widget(scroll)
        fila = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self.in_nombre = TextInput(hint_text="Nombre del estudiante", multiline=False)
        self.in_nombre.bind(on_text_validate=self._agregar)
        fila.add_widget(self.in_nombre)
        btn_add = Button(text="Agregar", size_hint_x=None, width=dp(104))
        btn_add.bind(on_release=self._agregar)
        fila.add_widget(btn_add)
        b.add_widget(fila)
        fila2 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        btn_importar = Factory.BotonOutline(text="Importar lista", font_size="14sp")
        btn_importar.bind(on_release=self._importar)
        fila2.add_widget(btn_importar)
        btn_plantilla = Factory.BotonOutline(text="Plantilla Excel", font_size="14sp")
        btn_plantilla.bind(on_release=self._descargar_plantilla)
        fila2.add_widget(btn_plantilla)
        if nombres:
            btn_vaciar = BotonIcono("borrar", peligro=True, size=(dp(46), dp(46)))
            btn_vaciar.bind(on_release=self._vaciar)
            fila2.add_widget(btn_vaciar)
        b.add_widget(fila2)
        self._boton_volver(b)

    def _boton_volver(self, b):
        b.add_widget(_boton_volver("Volver al curso", "dashboard"))

    def _agregar(self, *_):
        app = App.get_running_app()
        nombre = self.in_nombre.text.strip()
        if not nombre:
            return
        nombres = leer_lista_estudiantes(app.ruta_curso)
        nombres.append(nombre)
        guardar_lista_estudiantes(app.ruta_curso, nombres)
        self.construir()

    def _editar(self, pos):
        """Editar el nombre o eliminar al estudiante de la posición 'pos' (1-based)."""
        app = App.get_running_app()
        nombres = leer_lista_estudiantes(app.ruta_curso)
        if not 1 <= pos <= len(nombres):
            return
        cont = BoxLayout(orientation="vertical", spacing=dp(8), padding=[dp(8), dp(10)])
        cont.add_widget(_caption(f"Nombre  ·  código {codigo_de(pos)}"))
        ti = TextInput(text=nombres[pos - 1], multiline=False, size_hint_y=None, height=dp(48))
        cont.add_widget(ti)
        cont.add_widget(Widget())
        fila = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        btn_borrar = BotonIcono("borrar", peligro=True, size=(dp(48), dp(48)))
        btn_ok = Factory.BotonAccion(text="Guardar cambios")
        fila.add_widget(btn_borrar)
        fila.add_widget(btn_ok)
        cont.add_widget(fila)
        pop = Popup(title="Estudiante", content=cont, size_hint=(0.9, 0.42))

        def _guardar(*_):
            nuevo = ti.text.strip()
            if nuevo:
                nombres[pos - 1] = nuevo
                guardar_lista_estudiantes(app.ruta_curso, nombres)
            pop.dismiss()
            self.construir()

        def _eliminar():
            del nombres[pos - 1]
            guardar_lista_estudiantes(app.ruta_curso, nombres)
            self.construir()

        def _pedir_confirmacion(*_):
            pop.dismiss()
            siguientes = len(nombres) - pos
            extra = (f"\n\nOjo: los {siguientes} que siguen en la lista cambiarán de "
                     f"código (el {codigo_de(pos + 1)} pasa a ser {codigo_de(pos)}, y así). "
                     "Si ya calificaste exámenes, algunas hojas podrían quedar con otro estudiante."
                     if siguientes else "")
            confirmar(f"¿Quitar a {nombres[pos - 1]}?",
                      f"Saldrá de la lista del curso.{extra}",
                      "Sí, quitar", _eliminar)

        btn_ok.bind(on_release=_guardar)
        ti.bind(on_text_validate=_guardar)
        btn_borrar.bind(on_release=_pedir_confirmacion)
        pop.open()

    def _descargar_plantilla(self, *_):
        def trabajo():
            tmp = Path(tempfile.mkdtemp(prefix="plantilla_"))
            try:
                ruta = generar_plantilla_estudiantes(tmp)
                return PF.guardar_en_descargas(ruta, ruta.name) + (ruta.name,)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        def listo(res, err):
            if err:
                aviso("No pudimos crear la plantilla", str(err))
                return
            texto, ref, nombre = res
            aviso_archivo("Tu plantilla está lista",
                          f"La encuentras en:\n{texto}\n\nLlénala en Excel o Google Sheets "
                          "y luego usa 'Importar lista'.", ref, nombre)
        en_segundo_plano("Preparando la plantilla\u2026", trabajo, listo)

    def _vaciar(self, *_):
        app = App.get_running_app()
        n = len(leer_lista_estudiantes(app.ruta_curso))
        if not n:
            return

        def _hacer():
            guardar_lista_estudiantes(app.ruta_curso, [])
            self.construir()
        confirmar("¿Vaciar la lista?", f"Quitaremos a los {n} estudiantes de este curso.",
                  "Sí, vaciar", _hacer)

    def _importar(self, *_):
        PF.elegir_archivos(self._planilla_elegida, tipo="planillas", multiple=False,
                           titulo="Elige tu lista (Excel o CSV)")

    def _planilla_elegida(self, refs):
        app = App.get_running_app()
        nombre = PF.nombre_de(refs[0])
        if Path(nombre).suffix.lower() not in (".xlsx", ".xlsm", ".csv"):
            aviso("Ese archivo no sirve", f"'{nombre}' no es un Excel (.xlsx) ni un CSV.\n\n"
                  "Si tu lista está en Google Sheets, descárgala como .xlsx y vuelve a intentarlo.")
            return
        try:
            nombres = importar_planilla(PF.copiar_a_temporal(refs[0]))
        except Exception as e:
            aviso("No pudimos leer el archivo", str(e))
            return
        if not nombres:
            aviso("No encontramos nombres", "El archivo necesita una columna con los "
                  "nombres de los estudiantes.")
            return

        def _hacer():
            guardar_lista_estudiantes(app.ruta_curso, nombres)
            self.construir()
            aviso("¡Lista importada!", f"Agregamos {len(nombres)} estudiantes al curso.")

        actuales = len(leer_lista_estudiantes(app.ruta_curso))
        if actuales:
            confirmar("¿Cambiar la lista actual?",
                      f"El archivo trae {len(nombres)} estudiantes y reemplazará a los "
                      f"{actuales} que tienes ahora. Los códigos siguen el orden del archivo.",
                      "Sí, cambiarla", _hacer, peligro=False)
        else:
            _hacer()

# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: EXÁMENES (Paso 3)
# ─────────────────────────────────────────────────────────────────────────────
class OpcionesHoja(BoxLayout):
    """
    Con qué hoja se presenta un examen: su tamaño y, si el docente usará una
    hoja YA IMPRESA con más preguntas que el examen (p. ej. la de 30 que
    imprime la institución para un examen de 25), cuántas trae esa hoja.
    Las preguntas que sobran no se califican.
    """

    def __init__(self, formato=None, preguntas_hoja=0, **kw):
        super().__init__(orientation="vertical", size_hint_y=None, spacing=dp(6), **kw)
        self.bind(minimum_height=self.setter("height"))
        self.cantidad = 0        # preguntas del examen (para el texto de ayuda)
        self._formatos = {f.descripcion: f for f in (LH.MEDIA_CARTA, LH.CARTA)}
        inicial = LH.obtener(formato) if formato else LH.MEDIA_CARTA
        self.add_widget(_caption("Tamaño de la hoja"))
        self.sp_formato = Spinner(text=inicial.descripcion, values=list(self._formatos),
                                  size_hint_y=None, height=dp(48))
        self.add_widget(self.sp_formato)
        self.chk = Casilla(texto="Usaré una hoja ya impresa con más preguntas",
                           active=bool(preguntas_hoja))
        self.add_widget(self.chk)
        # Solo se ve con la casilla marcada
        self._extra = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4),
                                height=dp(48 + 4 + 34))
        self.in_hoja = TextInput(text=str(preguntas_hoja) if preguntas_hoja else "",
                                 hint_text="¿Cuántas preguntas trae esa hoja? Ej.: 30",
                                 multiline=False, input_filter="int",
                                 size_hint_y=None, height=dp(48))
        self._extra.add_widget(self.in_hoja)
        self.lbl_info = _ajustar_texto(Label(
            markup=True, font_size="12.5sp", color=GRIS, size_hint_y=None, height=dp(34),
            halign="left", valign="top", line_height=1.1))
        self._extra.add_widget(self.lbl_info)
        self.chk.bind(active=self._refrescar)
        self.in_hoja.bind(text=self._refrescar)
        self.sp_formato.bind(text=self._refrescar)
        self._refrescar()

    @property
    def formato(self):
        return self._formatos[self.sp_formato.text]

    def fijar_cantidad(self, cantidad):
        """Preguntas del examen (0 si aún no se sabe)."""
        self.cantidad = cantidad
        # Si no cabe en media hoja, pasar sola a hoja completa
        if max(cantidad, self._hoja_escrita()) > LH.MEDIA_CARTA.max_preguntas:
            self.sp_formato.text = LH.CARTA.descripcion
        self._refrescar()

    def _hoja_escrita(self):
        try:
            return int(self.in_hoja.text) if self.chk.active else 0
        except ValueError:
            return 0

    def _refrescar(self, *_):
        if self.chk.active and self._extra.parent is None:
            self.add_widget(self._extra)
        elif not self.chk.active and self._extra.parent is not None:
            self.remove_widget(self._extra)
        hoja, n = self._hoja_escrita(), self.cantidad
        sobran = texto_sobrantes(n, hoja) if n else ""
        if sobran and hoja <= self.formato.max_preguntas:
            self.lbl_info.text = (f"Se califica{'n' if n != 1 else ''} de la 1 a la {n}; "
                                  f"[b]{sobran}[/b]. Si alguien las marca, te avisamos.")
        else:
            self.lbl_info.text = ("Las preguntas que sobren en la hoja no se califican: "
                                  "los estudiantes las dejan en blanco.")

    def leer(self, cantidad):
        """(formato, preguntas_hoja, hoja_escrita, error). preguntas_hoja = 0
        si la hoja trae las mismas preguntas del examen; hoja_escrita es lo
        que puso el docente (para recordarlo); error = texto o None."""
        f = self.formato
        corto = f.descripcion.split(" (")[0].lower()
        if not (1 <= cantidad <= f.max_preguntas):
            return f, 0, 0, f"En {corto} caben de 1 a {f.max_preguntas} preguntas."
        if not self.chk.active:
            return f, 0, 0, None
        hoja = self._hoja_escrita()
        if not hoja:
            return f, 0, 0, "Escribe cuántas preguntas trae tu hoja impresa."
        if hoja < cantidad:
            return f, 0, 0, (f"Tu hoja trae {hoja} preguntas y el examen {cantidad}: "
                             "corrige el número o desmarca la casilla.")
        if hoja > f.max_preguntas:
            return f, 0, 0, f"En {corto} caben máximo {f.max_preguntas} preguntas."
        return f, (hoja if hoja > cantidad else 0), hoja, None


class ExamenesScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cont = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        self.add_widget(self.cont)

    def on_pre_enter(self, *_):
        self.construir()

    def construir(self):
        app = App.get_running_app()
        self.cont.clear_widgets()
        b = self.cont
        b.add_widget(Encabezado("Exámenes", f"Curso {app.grado}°{app.curso}"))
        examenes = listar_examenes(app.ruta_curso)
        lista_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8),
                              padding=[0, dp(2), 0, dp(6)])
        lista_box.bind(minimum_height=lista_box.setter("height"))
        if examenes:
            b.add_widget(_caption(f"{len(examenes)} {'exámenes' if len(examenes) != 1 else 'examen'}"
                                  "  ·  toca uno para cambiar su hoja"))
            for ruta, nombre, npreg, formato, hoja in examenes:
                fila = Tarjeta(orientation="horizontal", size_hint_y=None, height=dp(70),
                               padding=[dp(6), dp(8), dp(12), dp(8)], spacing=dp(8))
                # El nombre es un botón: abre las opciones de la hoja del examen
                btn_info = Factory.BotonTexto(
                    text=f"[b]{nombre.replace('_', ' ')}[/b]\n[size=12.5sp][color={GRIS_HEX}]"
                         f"{texto_hoja(npreg, formato, hoja)}[/color][/size]",
                    markup=True, halign="left", valign="middle", line_height=1.15,
                    max_lines=2, color=TEXTO, padding=[dp(10), 0])
                btn_info.bind(on_release=lambda inst, r=ruta: self._popup_hoja(r))
                fila.add_widget(_ajustar_texto(btn_info))
                btn_dl = BotonIcono("descargar")
                btn_dl.bind(on_release=lambda inst, n=nombre, q=hoja, f=formato:
                            self._descargar(n, q, f))
                fila.add_widget(btn_dl)
                btn_x = BotonIcono("borrar", peligro=True)
                btn_x.bind(on_release=lambda inst, r=ruta: self._borrar(r))
                fila.add_widget(btn_x)
                lista_box.add_widget(fila)
        else:
            lista_box.add_widget(_vacio(
                "Todavía no hay exámenes",
                "Crea el primero: le pones nombre, marcas las respuestas correctas "
                "y te damos la hoja lista para imprimir.", alto=160))
        scroll = ScrollView()
        scroll.add_widget(lista_box)
        b.add_widget(scroll)
        btn_nuevo = Factory.BotonAccion(text="+  Nuevo examen", size_hint_y=None,
                                        height=dp(54))
        btn_nuevo.bind(on_release=lambda *_: self._popup_nuevo())
        b.add_widget(btn_nuevo)
        b.add_widget(_boton_volver("Volver al curso", "dashboard"))

    def _borrar(self, ruta):
        try:
            nombre = json.loads(ruta.read_text(encoding="utf-8")).get("examen", ruta.stem)
        except Exception:
            nombre = ruta.stem

        def _hacer():
            try:
                ruta.unlink()
            except Exception:
                pass
            self.construir()
        confirmar("¿Borrar este examen?",
                  f"Se borrará '{nombre.replace('_', ' ')}' con sus respuestas correctas.\n\n"
                  "Las notas que ya calificaste se conservan.", "Sí, borrar", _hacer)

    def _popup_hoja(self, ruta):
        """Cambiar la hoja de un examen ya creado: su tamaño o usar una hoja
        ya impresa con más preguntas. Las respuestas correctas no se tocan."""
        app = App.get_running_app()
        try:
            d = json.loads(ruta.read_text(encoding="utf-8"))
            cantidad = int(d["total_preguntas"])
        except Exception:
            aviso("Algo no cuadra", "No pudimos leer ese examen.")
            return
        nombre = str(d.get("examen", ruta.stem)).replace("_", " ")
        formato = LH.obtener(d.get("formato"))
        hoja = LH.preguntas_en_hoja(cantidad, d.get("preguntas_hoja"), formato)
        # El mismo examen (mismo nombre y número de preguntas) en otros cursos
        otros = []
        prof = BASE / app.profesor
        for g in _subdirs(prof):
            for c in _subdirs(prof / g):
                otro = prof / g / c / "examenes_claves" / ruta.name
                if (g, c) == (app.grado, app.curso) or not otro.exists():
                    continue
                try:
                    if int(json.loads(otro.read_text(encoding="utf-8"))
                           ["total_preguntas"]) == cantidad:
                        otros.append((_nombre_curso(g, c), otro))
                except Exception:
                    pass

        cont = BoxLayout(orientation="vertical", spacing=dp(6), padding=[dp(8), dp(10)])
        cont.add_widget(_ajustar_texto(Label(
            text=f"[b]{nombre}[/b]  ·  {cantidad} pregunta{'' if cantidad == 1 else 's'}\n"
                 f"[size=12.5sp][color={GRIS_HEX}]Sus respuestas correctas y las notas "
                 f"ya guardadas no cambian.[/color][/size]",
            markup=True, size_hint_y=None, height=dp(46), halign="left", valign="middle",
            line_height=1.15)))
        opciones = OpcionesHoja(formato, hoja if hoja > cantidad else 0)
        opciones.fijar_cantidad(cantidad)
        cont.add_widget(opciones)
        chk_otros = None
        if otros:
            chk_otros = Casilla(texto="Cambiarla también en "
                                + _enumerar([n for n, _ in otros]), active=True)
            cont.add_widget(chk_otros)
        lbl_msg = _ajustar_texto(Label(text="", size_hint_y=None, height=dp(34),
                                       font_size="13sp", color=(0.776, 0.157, 0.157, 1),
                                       halign="center", valign="middle"))
        cont.add_widget(lbl_msg)
        cont.add_widget(Widget())
        btn = Factory.BotonAccion(text="Guardar", size_hint_y=None, height=dp(50))
        cont.add_widget(btn)
        pop = Popup(title="Hoja de este examen", content=cont, size_hint=(0.92, 0.84))

        def _guardar(*_):
            f, nueva, escrita, error = opciones.leer(cantidad)
            if error:
                lbl_msg.text = error
                return
            rutas = [ruta] + ([r for _, r in otros]
                              if chk_otros is not None and chk_otros.active else [])
            try:
                for r in rutas:
                    cambiar_hoja_examen(r, f.clave, nueva)
            except Exception as e:
                lbl_msg.text = f"No pudimos guardarlo: {e}"
                return
            if escrita:
                guardar_hoja_impresa(prof, escrita, f.clave)
            pop.dismiss()
            self.construir()
            sobran = texto_sobrantes(cantidad, nueva)
            aviso("Hoja actualizada",
                  f"'{nombre}' ahora usa: {texto_hoja(cantidad, f.clave, nueva)}."
                  + (f"\n\nAl calificar, {sobran}: si un estudiante las marca, "
                     "te avisamos." if sobran else ""))

        btn.bind(on_release=_guardar)
        pop.open()

    def _descargar(self, nombre, npreg, formato):
        try:
            cantidad = int(npreg)
        except (ValueError, TypeError):
            aviso("Algo no cuadra", "Ese examen no tiene un número de preguntas válido.")
            return

        def listo(res, err):
            if err:
                aviso("No pudimos crear la hoja", str(err))
                return
            texto, ref, arch = res
            aviso_archivo("Tu hoja está lista", f"La encuentras en:\n{texto}", ref, arch)
        en_segundo_plano("Preparando la hoja\u2026",
                         lambda: generar_pdf_a_descargas(nombre, cantidad, formato), listo)

    def _popup_nuevo(self):
        cont = BoxLayout(orientation="vertical", spacing=dp(6), padding=[dp(8), dp(10)])
        cont.add_widget(_caption("¿Cómo se llama?"))
        in_nombre = TextInput(hint_text="Ej.: Inglés primer parcial", multiline=False,
                              size_hint_y=None, height=dp(48))
        cont.add_widget(in_nombre)
        cont.add_widget(_caption("¿Cuántas preguntas tiene?"))
        in_num = TextInput(hint_text="Ej.: 20", multiline=False, input_filter="int",
                           size_hint_y=None, height=dp(48))
        cont.add_widget(in_num)
        # Si el docente ya usa una hoja impresa (p. ej. la de 30 de la
        # institución), se propone de una vez
        impresa = leer_hoja_impresa(BASE / App.get_running_app().profesor)
        opciones = (OpcionesHoja(impresa["formato"], impresa["preguntas"]) if impresa
                    else OpcionesHoja())
        cont.add_widget(opciones)

        def _al_escribir_cantidad(_inst, texto):
            try:
                opciones.fijar_cantidad(int(texto))
            except ValueError:
                opciones.fijar_cantidad(0)
        in_num.bind(text=_al_escribir_cantidad)
        lbl_msg = _ajustar_texto(Label(text="", size_hint_y=None, height=dp(34),
                                       font_size="13sp", color=(0.776, 0.157, 0.157, 1),
                                       halign="center", valign="middle"))
        cont.add_widget(lbl_msg)
        cont.add_widget(Widget())
        btn_generar = Factory.BotonAccion(text="Siguiente: marcar respuestas",
                                          size_hint_y=None, height=dp(50))
        cont.add_widget(btn_generar)
        pop = Popup(title="Nuevo examen", content=cont, size_hint=(0.92, 0.9))

        def _generar(*_):
            app = App.get_running_app()
            nombre = in_nombre.text.strip()
            if not nombre:
                lbl_msg.text = "Ponle un nombre al examen."
                return
            try:
                cantidad = int(in_num.text)
            except ValueError:
                lbl_msg.text = "Escribe cuántas preguntas tiene."
                return
            formato, hoja, escrita, error = opciones.leer(cantidad)
            if error:
                lbl_msg.text = error
                return

            def _ir():
                pop.dismiss()
                app.sm.get_screen("claves").preparar(nombre, cantidad, formato.clave,
                                                     hoja, escrita)
                app.sm.current = "claves"

            existente = (app.ruta_curso / "examenes_claves"
                         / f"respuestas_{nombre.replace(' ', '_')}.json")
            if existente.exists():
                confirmar("Ese nombre ya existe",
                          f"Ya tienes un examen llamado '{nombre}'.\n\n"
                          "Si sigues, cambiarás sus respuestas correctas por las nuevas.",
                          "Seguir", _ir, peligro=False)
            else:
                _ir()

        btn_generar.bind(on_release=_generar)
        pop.open()


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: RESPUESTAS CORRECTAS  ·  botones A/B/C/D por pregunta
# ─────────────────────────────────────────────────────────────────────────────
def _nombre_curso(grado, curso):
    return f"{grado}°{curso}"


def _enumerar(cosas):
    """['a', 'b', 'c'] -> 'a, b y c'"""
    cosas = list(cosas)
    if len(cosas) <= 1:
        return "".join(cosas)
    return ", ".join(cosas[:-1]) + " y " + cosas[-1]


class OpcionLetra(Button):
    """Botón de una letra (A, B, C o D); azul cuando está elegido."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.radio = dp(10)
        self.marcar(False)

    def marcar(self, elegido):
        if elegido:
            self.color = BLANCO
            self.color_fondo = AZUL
            self.color_fondo_down = AZUL_OSC
            self.color_borde = (0, 0, 0, 0)
        else:
            self.color = AZUL
            self.color_fondo = BLANCO
            self.color_fondo_down = TINTE
            self.color_borde = BORDE


class ClavesScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cont = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        self.add_widget(self.cont)
        self.nombre = ""
        self.cantidad = 0
        self.formato = LH.MEDIA_CARTA.clave
        self.preguntas_hoja = 0     # > cantidad si se usa una hoja impresa más grande
        self.hoja_escrita = 0       # lo que el docente dijo que trae su hoja impresa
        self.respuestas = []
        self.botones = []
        self.destinos = set()       # otros cursos donde también se crea: {(grado, curso)}

    def preparar(self, nombre, cantidad, formato, preguntas_hoja=0, hoja_escrita=0):
        self.nombre = nombre
        self.cantidad = int(cantidad)
        self.formato = formato
        self.preguntas_hoja = preguntas_hoja
        self.hoja_escrita = hoja_escrita
        # Por defecto, también en los demás cursos del mismo grado
        app = App.get_running_app()
        self.destinos = {(g, c) for g, c in self._otros_cursos() if g == app.grado}

    def on_pre_enter(self, *_):
        self.construir()

    # ── Otros cursos del docente ────────────────────────────────────────────
    def _otros_cursos(self):
        """[(grado, curso)] de todos los cursos del docente, menos el actual."""
        app = App.get_running_app()
        prof = BASE / app.profesor
        return [(g, c) for g in _subdirs(prof) for c in _subdirs(prof / g)
                if (g, c) != (app.grado, app.curso)]

    def construir(self):
        app = App.get_running_app()
        self.cont.clear_widgets()
        b = self.cont
        b.add_widget(Encabezado("Respuestas correctas", self.nombre.replace("_", " ")))
        b.add_widget(_caption(texto_hoja(self.cantidad, self.formato, self.preguntas_hoja)
                              + "  ·  toca la letra correcta"))

        n = self.cantidad
        self.respuestas = [None] * (n + 1)   # 1-indexado
        self.botones = [None] * (n + 1)
        lista = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None,
                          padding=[0, 0, 0, dp(6)])
        lista.bind(minimum_height=lista.setter("height"))
        for q in range(1, n + 1):
            fila = Tarjeta(orientation="horizontal", size_hint_y=None, height=dp(58),
                           padding=[dp(10), dp(8)], spacing=dp(8), radio=dp(14),
                           sombra=False)
            etq = Label(text=str(q), size_hint_x=None, width=dp(34), bold=True,
                        color=GRIS, halign="center", valign="middle")
            fila.add_widget(_ajustar_texto(etq))
            grupo = []
            for letra in ("A", "B", "C", "D"):
                btn = OpcionLetra(text=letra)
                btn.bind(on_release=lambda inst, q=q, l=letra: self._elegir(q, l))
                grupo.append(btn)
                fila.add_widget(btn)
            self.botones[q] = grupo
            lista.add_widget(fila)

        scroll = ScrollView(bar_width=dp(3))
        scroll.add_widget(lista)
        b.add_widget(scroll)

        self.lbl_cuenta = Label(size_hint_y=None, height=dp(22), font_size="13.5sp",
                                bold=True, color=AZUL, markup=True)
        b.add_widget(self.lbl_cuenta)
        self._contar()

        opciones = Tarjeta(size_hint_y=None, padding=[dp(14), dp(4)], spacing=0,
                           radio=dp(14), sombra=False)
        opciones.bind(minimum_height=opciones.setter("height"))
        if self._otros_cursos():
            fila_otros = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
            self.chk_otros = Casilla(active=bool(self.destinos), height=dp(48))
            self.chk_otros.bind(active=self._al_marcar_otros)
            fila_otros.add_widget(self.chk_otros)
            btn_elegir = Factory.BotonTexto(text="Elegir", size_hint_x=None, width=dp(70),
                                            font_size="14sp", bold=True)
            btn_elegir.bind(on_release=lambda *_: self._elegir_cursos())
            fila_otros.add_widget(btn_elegir)
            opciones.add_widget(fila_otros)
            self._texto_otros()
        else:
            self.chk_otros = None
        # Con una hoja ya impresa no hace falta descargarla otra vez
        self.chk_pdf = Casilla(texto="Descargar también la hoja para imprimir",
                               active=not self.hoja_escrita, height=dp(48))
        opciones.add_widget(self.chk_pdf)
        b.add_widget(opciones)

        fila_btn = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(10))
        btn_cancel = Factory.BotonOutline(text="Cancelar", size_hint_x=0.4)
        btn_cancel.bind(on_release=lambda *_: setattr(
            App.get_running_app().sm, "current", "examenes"))
        btn_guardar = Factory.BotonAccion(text="Guardar examen")
        btn_guardar.bind(on_release=self._guardar)
        fila_btn.add_widget(btn_cancel)
        fila_btn.add_widget(btn_guardar)
        b.add_widget(fila_btn)

    def _elegir(self, q, letra):
        self.respuestas[q] = letra
        for btn in self.botones[q]:
            btn.marcar(btn.text == letra)
        self._contar()

    # ── "Crear también en otros cursos" ─────────────────────────────────────
    def _texto_otros(self):
        app = App.get_running_app()
        if self.destinos:
            nombres = [_nombre_curso(g, c) for g, c in sorted(self.destinos)]
            texto = "Crear también en " + _enumerar(nombres)
        elif any(g == app.grado for g, _ in self._otros_cursos()):
            texto = f"Crear también en los otros cursos de {app.grado}°"
        else:
            texto = "Crear también en otros cursos"
        self.chk_otros.lbl.text = texto

    def _al_marcar_otros(self, _chk, activo):
        app = App.get_running_app()
        if activo and not self.destinos:
            mismos = {(g, c) for g, c in self._otros_cursos() if g == app.grado}
            if mismos:
                self.destinos = mismos
            else:
                self._elegir_cursos()
        elif not activo:
            self.destinos = set()
        self._texto_otros()

    def _elegir_cursos(self):
        """Ventana con una casilla por cada curso del docente."""
        app = App.get_running_app()
        cont = BoxLayout(orientation="vertical", spacing=dp(8), padding=[dp(8), dp(10)])
        cont.add_widget(_ajustar_texto(Label(
            text="Guardaremos el mismo examen, con las mismas respuestas, en los cursos "
                 "que marques. Así no tienes que repetirlo.",
            size_hint_y=None, height=dp(56), font_size="13sp", color=GRIS,
            halign="left", valign="middle")))
        inner = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        inner.bind(minimum_height=inner.setter("height"))
        casillas = {}
        grado_previo = None
        for g, c in self._otros_cursos():
            if g != grado_previo:
                inner.add_widget(_caption(f"Grado {g}"))
                grado_previo = g
            chk = Casilla(texto=f"Curso {_nombre_curso(g, c)}",
                          active=(g, c) in self.destinos)
            casillas[(g, c)] = chk
            inner.add_widget(chk)
        scroll = ScrollView()
        scroll.add_widget(inner)
        cont.add_widget(scroll)
        fila = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        btn_mismo = Factory.BotonOutline(text=f"Solo {app.grado}°", size_hint_x=0.45)
        btn_ok = Factory.BotonAccion(text="Listo")
        fila.add_widget(btn_mismo)
        fila.add_widget(btn_ok)
        cont.add_widget(fila)
        pop = Popup(title="¿En qué otros cursos?", content=cont, size_hint=(0.92, 0.78))

        def _solo_mismo_grado(*_):
            for (g, _c), chk in casillas.items():
                chk.active = g == app.grado

        def _aceptar(*_):
            self.destinos = {k for k, chk in casillas.items() if chk.active}
            pop.dismiss()
            if self.chk_otros is not None:
                self.chk_otros.active = bool(self.destinos)
                self._texto_otros()

        btn_mismo.bind(on_release=_solo_mismo_grado)
        btn_ok.bind(on_release=_aceptar)
        pop.open()

    # ── Guardar ─────────────────────────────────────────────────────────────
    def _faltan(self):
        return [q for q in range(1, self.cantidad + 1) if self.respuestas[q] is None]

    def _contar(self):
        faltan = len(self._faltan())
        hechas = self.cantidad - faltan
        self.lbl_cuenta.text = (f"Llevas {hechas} de {self.cantidad}" if faltan
                                else f"[color={VERDE}]¡Todas las respuestas listas![/color]")

    def _guardar(self, *_):
        app = App.get_running_app()
        faltan = self._faltan()
        if faltan:
            lista = ", ".join(str(q) for q in faltan[:10]) + ("…" if len(faltan) > 10 else "")
            aviso("Te faltan algunas", f"Marca la respuesta correcta de la pregunta"
                  f"{'s' if len(faltan) > 1 else ''}:\n\n{lista}")
            return
        destinos = sorted(self.destinos) if self.chk_otros is not None else []
        nombre_arch = f"respuestas_{self.nombre.replace(' ', '_')}.json"
        ya_existe = [_nombre_curso(g, c) for g, c in destinos
                     if (BASE / app.profesor / g / c / "examenes_claves" / nombre_arch).exists()]
        if ya_existe:
            confirmar("Ese examen ya está en otros cursos",
                      f"'{self.nombre}' ya existe en {_enumerar(ya_existe)}.\n\n"
                      "Si sigues, sus respuestas correctas se cambiarán por estas.",
                      "Seguir", lambda: self._guardar_en(destinos), peligro=False)
        else:
            self._guardar_en(destinos)

    def _guardar_en(self, destinos):
        app = App.get_running_app()
        clave = [self.respuestas[q] for q in range(1, self.cantidad + 1)]
        guardar_clave(app.ruta_curso, self.nombre, self.cantidad, clave, self.formato,
                      self.preguntas_hoja)
        # Se recuerda (o se olvida) la hoja impresa para el próximo examen
        guardar_hoja_impresa(BASE / app.profesor, self.hoja_escrita, self.formato)
        errores = []
        for g, c in destinos:
            try:
                guardar_clave(BASE / app.profesor / g / c, self.nombre, self.cantidad,
                              clave, self.formato, self.preguntas_hoja)
            except Exception as e:
                errores.append(f"{_nombre_curso(g, c)} ({e})")
        cursos = [_nombre_curso(app.grado, app.curso)] + [
            _nombre_curso(g, c) for g, c in destinos]
        mensaje = (f"'{self.nombre}' quedó guardado en {_enumerar(cursos)}."
                   if len(cursos) > 1 else
                   f"'{self.nombre}' quedó guardado con sus {self.cantidad} respuestas.")
        sobran = texto_sobrantes(self.cantidad, self.preguntas_hoja)
        if sobran:
            mensaje += (f"\n\nSe presenta en tu hoja de {self.preguntas_hoja} preguntas: "
                        f"{sobran} (los estudiantes las dejan en blanco).")
        if errores:
            mensaje += "\n\nNo pudimos guardarlo en: " + ", ".join(errores)
        app.sm.current = "examenes"
        if self.chk_pdf.active:
            nombre, formato = self.nombre, self.formato
            cantidad = max(self.cantidad, self.preguntas_hoja)   # las de la hoja impresa

            def listo(res, err):
                if err:
                    aviso("¡Examen guardado!", f"{mensaje}\n\n(La hoja no se pudo crear: {err})")
                    return
                texto, ref, arch = res
                aviso_archivo("¡Examen guardado!",
                              f"{mensaje}\n\nLa hoja para imprimir está en:\n{texto}", ref, arch)
            en_segundo_plano("Preparando la hoja…",
                             lambda: generar_pdf_a_descargas(nombre, cantidad, formato), listo)
        else:
            aviso("¡Examen guardado!", mensaje)


# ─────────────────────────────────────────────────────────────────────────────
# GALERÍA DE HOJAS  ·  revisar deslizando, antes o después de guardar
# ─────────────────────────────────────────────────────────────────────────────
class GaleriaHojas(_VentanaSinRastro):
    """
    Hojas calificadas a pantalla completa: se pasa de una a otra deslizando
    (o con las flechas). Dos modos:
      • 'revisar': hojas recién calificadas y AÚN sin guardar. Se puede
        corregir el código o descartar cada una; nada se guarda hasta tocar
        Confirmar.
      • 'historial': las hojas ya guardadas (botón Ver). Corregir y eliminar
        se aplican al momento.
    Solo se tienen en memoria las imágenes de la hoja actual y sus vecinas
    (con 40 hojas en el celular, cargarlas todas se comería la memoria).
    """

    def __init__(self, pantalla, hojas, modo="revisar", inicio=0, **kw):
        super().__init__(size_hint=(1, 1), auto_dismiss=False,
                         background_color=(0, 0, 0, 0),
                         overlay_color=(0.05, 0.08, 0.15, 0.97), **kw)
        self.pantalla = pantalla
        self.hojas = list(hojas)
        self.modo = modo
        self.descartadas = set()      # índices (solo modo 'revisar')
        self._lista = pantalla._lista_codigos()
        self._carpeta = pantalla._ruta_notas().parent

        raiz = BoxLayout(orientation="vertical", padding=[dp(10), dp(10), dp(10), dp(12)],
                         spacing=dp(8))
        # Arriba: título, contador y cerrar
        arriba = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self.lbl_titulo = Label(markup=True, halign="left", valign="middle",
                                color=BLANCO, font_size="17sp")
        self.lbl_titulo.bind(size=lambda i, *_: setattr(i, "text_size", i.size))
        arriba.add_widget(self.lbl_titulo)
        btn_x = BotonCerrar(size_hint=(None, None), size=(dp(44), dp(44)))
        btn_x.bind(on_release=lambda *_: self._cerrar())
        arriba.add_widget(btn_x)
        raiz.add_widget(arriba)

        # Datos de la hoja actual
        self.tarjeta = _tarjeta_blanca(size_hint_y=None, height=dp(62),
                                       padding=[dp(14), dp(6)])
        self.lbl_info = Label(markup=True, halign="left", valign="middle", color=TEXTO,
                              font_size="15sp", line_height=1.15, max_lines=3)
        self.lbl_info.bind(size=lambda i, *_: setattr(i, "text_size", i.size))
        self.tarjeta.add_widget(self.lbl_info)
        raiz.add_widget(self.tarjeta)

        # La hoja (deslizable) con flechas a los lados
        from kivy.uix.carousel import Carousel
        zona = FloatLayout()
        self.carrusel = Carousel(loop=False, size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                                 ignore_perpendicular_swipes=True, anim_move_duration=0.25)
        self.carrusel.bind(index=lambda *_: self._al_cambiar())
        zona.add_widget(self.carrusel)
        self.btn_izq = BotonIcono("izq", size=(dp(44), dp(44)),
                                  pos_hint={"x": 0, "center_y": 0.5})
        self.btn_izq.bind(on_release=lambda *_: self.carrusel.load_previous())
        self.btn_der = BotonIcono("der", size=(dp(44), dp(44)),
                                  pos_hint={"right": 1, "center_y": 0.5})
        self.btn_der.bind(on_release=lambda *_: self.carrusel.load_next())
        zona.add_widget(self.btn_izq)
        zona.add_widget(self.btn_der)
        raiz.add_widget(zona)

        # Acciones sobre la hoja actual
        fila = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        if modo == "revisar":
            self.btn_quitar = Factory.BotonOutline(text="Descartar", font_size="14sp")
        else:
            self.btn_quitar = BotonIcono("borrar", peligro=True, size=(dp(48), dp(48)))
        self.btn_quitar.bind(on_release=lambda *_: self._quitar())
        fila.add_widget(self.btn_quitar)
        self.btn_codigo = Factory.BotonSuave(text="Corregir código", font_size="14sp")
        self.btn_codigo.bind(on_release=lambda *_: self._corregir())
        fila.add_widget(self.btn_codigo)
        if modo == "historial":
            btn_listo = Factory.BotonOutline(text="Listo", font_size="14sp", size_hint_x=0.6)
            btn_listo.bind(on_release=lambda *_: self.dismiss())
            fila.add_widget(btn_listo)
        raiz.add_widget(fila)

        if modo == "revisar":
            self.btn_confirmar = Factory.BotonAccion(size_hint_y=None, height=dp(54),
                                                     font_size="16sp")
            self.btn_confirmar.bind(on_release=lambda *_: self._confirmar())
            raiz.add_widget(self.btn_confirmar)

        self.add_widget(raiz)
        self._armar(inicio)
        self.bind(on_open=lambda *_: Window.bind(on_keyboard=self._tecla),
                  on_dismiss=lambda *_: Window.unbind(on_keyboard=self._tecla))

    # ── Diapositivas ─────────────────────────────────────────────────────────
    def _armar(self, inicio=0):
        self.carrusel.clear_widgets()
        for r in self.hojas:
            if r.get("imagen"):
                img = Image(fit_mode="contain")
            else:
                # Sin imagen (no se pudo leer, o se borró para liberar espacio)
                texto = ("La foto de esta hoja se borró para liberar espacio.\n"
                         "La nota se conserva." if r.get("foto_borrada") else
                         r.get("error") or "No pudimos leer esta hoja.")
                img = Label(text=texto,
                            color=BLANCO, font_size="16sp", halign="center",
                            valign="middle", padding=[dp(48), 0])
                img.bind(size=lambda i, *_: setattr(i, "text_size", i.size))
            img.hoja = r
            self.carrusel.add_widget(img)
        if self.hojas:
            self.carrusel.index = max(0, min(inicio, len(self.hojas) - 1))
        self._al_cambiar()

    def _al_cambiar(self):
        """Carga la imagen de la hoja actual y sus vecinas; suelta las demás."""
        i = self.carrusel.index or 0
        for j, img in enumerate(self.carrusel.slides):
            if not isinstance(img, Image):
                continue
            if abs(j - i) <= 1:
                if img.texture is None:
                    img.texture = self._textura(img.hoja)
            elif img.texture is not None:
                img.texture = None
            # Descartada: se ve atenuada
            img.opacity = 0 if img.texture is None else (0.3 if j in self.descartadas else 1)
        self._actualizar()

    def _textura(self, r):
        if not r.get("imagen"):
            return None
        import lector_omr as L
        img = L.leer_imagen(self._carpeta / r["imagen"])
        return None if img is None else CalificarScreen._np_a_textura(img)

    # ── Estado y textos ──────────────────────────────────────────────────────
    def _estado(self, i):
        r = self.hojas[i]
        if self.modo == "historial":
            import registro_notas as RN
            repetidos = RN.detectar_conflictos(self.pantalla._leer_notas())
            return self.pantalla._estado_hoja(r, repetidos, self._lista)
        if i in self.descartadas:
            return "descartada"
        estado = self.pantalla._estado_hoja(r, set(), self._lista)
        if estado != "ok":
            return estado
        cod = str(r.get("codigo"))
        # Dos fotos del mismo alumno en esta tanda: se guarda la última
        if any(j > i and j not in self.descartadas and str(o.get("codigo")) == cod
               for j, o in enumerate(self.hojas)):
            return "tapada"
        if any(str(g.get("codigo")) == cod for g in self.pantalla._leer_notas()):
            return "reemplaza"
        return "ok"

    def _texto(self, r, estado):
        codigo = str(r.get("codigo", "???"))
        gris = f"[size=13sp][color={GRIS_HEX}]"
        if estado == "error":
            return (f"[color={ROJO}][b]No pudimos leerla[/b][/color]\n{gris}"
                    f"No se guardará. Abajo dice por qué.[/color][/size]")
        avisos = {
            "ilegible": "No se lee bien el código: corrígelo",
            "repetido": "Código repetido: revisa cuál es el correcto",
            "fuera": "No está en la lista del curso: revísalo",
            "tapada": "Hay otra foto de este alumno más adelante: se guardará esa",
            "descartada": "Descartada: no se guardará",
        }
        if estado in avisos:
            col = GRIS_HEX if estado == "descartada" else AMBAR
            return (f"[color={col}][b]Código {codigo}[/b][/color]\n{gris}"
                    f"{avisos[estado]}[/color][/size]")
        n = nota_local(r["aciertos"], r["total"])
        col = VERDE if n >= 6.0 else ROJO
        nombre = self._lista.get(codigo, "")
        extra = (f"\n{gris}[color={AMBAR}]Reemplaza la hoja que ya tenía guardada"
                 f"[/color][/color][/size]" if estado == "reemplaza" else
                 f"\n{gris}{r['aciertos']} de {r['total']} correctas[/color][/size]")
        # Dobles marcas, marcas débiles o fuera del examen: conviene mirar la hoja
        alertas = texto_alertas(r)
        if alertas:
            extra += f"\n[size=12.5sp][color={AMBAR}]Mira la hoja: {alertas}[/color][/size]"
        return (f"[b]Código {codigo}[/b]   [color={col}][b]{n:.1f}[/b][/color]   "
                f"{gris}{nombre}[/color][/size]{extra}")

    def _actualizar(self):
        total = len(self.hojas)
        i = self.carrusel.index or 0
        if not total:
            self.lbl_titulo.text = "[b]Sin hojas[/b]"
            self.lbl_info.text = ""
            return
        r = self.hojas[i]
        titulo = "Revisa las hojas" if self.modo == "revisar" else "Hojas calificadas"
        self.lbl_titulo.text = f"[b]{titulo}[/b]   [size=14sp]{i + 1} de {total}[/size]"
        estado = self._estado(i)
        self.lbl_info.text = self._texto(r, estado)
        self.tarjeta.height = dp(84 if self.lbl_info.text.count("\n") >= 2 else 62)
        self.btn_izq.opacity, self.btn_izq.disabled = (0, True) if i == 0 else (1, False)
        ultima = i >= total - 1
        self.btn_der.opacity, self.btn_der.disabled = (0, True) if ultima else (1, False)
        self.btn_codigo.disabled = estado in ("error", "descartada")
        if self.modo == "revisar":
            self.btn_quitar.text = "Recuperar" if i in self.descartadas else "Descartar"
            quedan = len(self._conservadas())
            self.btn_confirmar.text = (f"Confirmar y guardar ({quedan})" if quedan
                                       else "Confirmar (no se guarda ninguna)")

    def _conservadas(self):
        """Las hojas que se guardarían (no descartadas y con lectura)."""
        return [r for j, r in enumerate(self.hojas)
                if j not in self.descartadas and r.get("codigo") != "ERROR"]

    # ── Acciones ─────────────────────────────────────────────────────────────
    def _actual(self):
        return self.hojas[self.carrusel.index or 0] if self.hojas else None

    def _quitar(self):
        r = self._actual()
        if r is None:
            return
        if self.modo == "revisar":
            i = self.carrusel.index or 0
            self.descartadas.symmetric_difference_update({i})
            self._al_cambiar()
            return
        self.pantalla._eliminar_hoja(r, listo=self._recargar)

    def _corregir(self):
        r = self._actual()
        if r is None:
            return
        if self.modo == "revisar":
            def _guardar(nuevo):
                r["codigo"] = nuevo
                r["codigo_corregido"] = True
                self._actualizar()
            self.pantalla._pedir_codigo(r, _guardar)
        else:
            self.pantalla._editar_codigo(r, listo=self._recargar)

    def _recargar(self):
        """Modo historial: tras corregir o eliminar, vuelve a leer las hojas
        (en orden) y se queda en la misma hoja, o en la siguiente."""
        actual = self._actual()
        i = self.carrusel.index or 0
        self.hojas = self.pantalla._hojas_ordenadas()
        if not self.hojas:
            self.dismiss()
            return
        archivos = [h.get("archivo") for h in self.hojas]
        if actual is not None and actual.get("archivo") in archivos:
            i = archivos.index(actual.get("archivo"))
        self._armar(i)

    def _confirmar(self):
        conservadas = self._conservadas()
        descartadas = [r for j, r in enumerate(self.hojas) if j in self.descartadas]
        for r in descartadas:
            self.pantalla._borrar_imagen(r)
        self.dismiss()
        errores = [r for j, r in enumerate(self.hojas)
                   if j not in self.descartadas and r.get("codigo") == "ERROR"]
        self.pantalla._confirmar_tanda(conservadas, errores)

    def _cerrar(self):
        if self.modo != "revisar":
            self.dismiss()
            return
        n = len(self._conservadas())
        if not n:
            self._descartar_todo()
            return
        confirmar("¿Salir sin guardar?",
                  f"Las {n} hojas calificadas no se guardarán." if n > 1 else
                  "La hoja calificada no se guardará.",
                  "Sí, salir sin guardar", self._descartar_todo)

    def _descartar_todo(self):
        for r in self.hojas:
            self.pantalla._borrar_imagen(r)
        self.dismiss()

    def _tecla(self, _window, tecla, *_):
        """Atrás/Esc cierra (en 'revisar', preguntando); flechas cambian de hoja."""
        if not Window.children or Window.children[0] is not self:
            return False   # hay otra ventana encima (p. ej. corregir código)
        if tecla == 27:
            self._cerrar()
            return True
        if tecla == 276:
            self.carrusel.load_previous()
            return True
        if tecla == 275:
            self.carrusel.load_next()
            return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: CALIFICAR (Paso 4)  ·  digitalizar -> leer -> guardar notas
# ─────────────────────────────────────────────────────────────────────────────
class CalificarScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cont = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        self.add_widget(self.cont)
        self.examen = ""
        self.errores = []     # hojas que no se pudieron leer en esta sesión (no se guardan)

    def on_pre_enter(self, *_):
        self.errores = []
        self.construir()

    def _lista_codigos(self):
        """{código: nombre} de la lista del curso ({} si aún no hay lista)."""
        import registro_notas as RN
        try:
            roster = RN.cargar_roster(App.get_running_app().ruta_curso)
        except Exception:
            roster = []
        return {e["codigo"]: e["nombre"] for e in roster}

    @staticmethod
    def _estado_hoja(r, repetidos, lista):
        """'error', 'ilegible', 'repetido', 'fuera' (no está en la lista) u 'ok'."""
        codigo = str(r.get("codigo", "???"))
        if codigo == "ERROR":
            return "error"
        if not codigo.isdigit():
            return "ilegible"
        if codigo in repetidos:
            return "repetido"
        if lista and codigo not in lista:
            return "fuera"
        return "ok"

    def _hojas_ordenadas(self, guardados=None, repetidos=None, lista=None):
        """Lo que se muestra, en orden: las ilegibles de esta sesión (no se
        guardan) y luego el historial del examen ordenado por código."""
        import registro_notas as RN
        guardados = self._leer_notas() if guardados is None else guardados
        repetidos = RN.detectar_conflictos(guardados) if repetidos is None else repetidos
        lista = self._lista_codigos() if lista is None else lista
        return self.errores + self._ordenar(guardados, repetidos, lista)

    def _ordenar(self, notas, repetidos, lista):
        """Por código (001, 002…); las que hay que revisar, arriba."""
        def clave(r):
            cod = str(r.get("codigo", ""))
            return (self._estado_hoja(r, repetidos, lista) == "ok",
                    int(cod) if cod.isdigit() else -1, r.get("fecha", ""))
        return sorted(notas, key=clave)

    def construir(self):
        app = App.get_running_app()
        self.cont.clear_widgets()
        b = self.cont
        b.add_widget(Encabezado("Calificar", f"Curso {app.grado}°{app.curso}"))

        examenes = listar_examenes(app.ruta_curso)
        if not examenes:
            b.add_widget(_vacio("Primero necesitas un examen",
                                "Créalo en 'Exámenes' con sus respuestas correctas y "
                                "vuelve aquí para calificar.", alto=150))
            b.add_widget(Widget())
            self._volver(b)
            return

        self._mapa_claves = {nombre: ruta for ruta, nombre, *_ in examenes}
        nombres = list(self._mapa_claves.keys())
        if self.examen not in nombres:
            self.examen, self.errores = nombres[0], []
        b.add_widget(_caption("Examen"))
        # En la lista se ven con espacios ("Primer parcial"); por dentro, con "_"
        self._por_texto = {n.replace("_", " "): n for n in nombres}
        self.sp_examen = Spinner(text=self.examen.replace("_", " "),
                                 values=list(self._por_texto),
                                 size_hint_y=None, height=dp(48))
        self.sp_examen.bind(text=self._cambiar_examen)
        b.add_widget(self.sp_examen)
        # Con qué hoja se califica (para no fotografiar la hoja equivocada)
        npreg, formato, hoja = next((n, f, h) for _, nom, n, f, h in examenes
                                    if nom == self.examen)
        sobran = texto_sobrantes(npreg, hoja)
        b.add_widget(_caption(texto_hoja(npreg, formato, hoja)
                              + (f"  ({sobran})" if sobran else "")))

        fila_btn = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(10))
        btn_cam = Factory.BotonAccion(text="Usar la cámara")
        btn_cam.bind(on_release=self._tomar_foto)
        fila_btn.add_widget(btn_cam)
        btn = Button(text="Desde la galería")
        btn.bind(on_release=self._calificar)
        fila_btn.add_widget(btn)
        b.add_widget(fila_btn)

        lista = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6),
                          padding=[0, 0, 0, dp(6)])
        lista.bind(minimum_height=lista.setter("height"))
        import registro_notas as RN
        guardados = self._leer_notas()
        if guardados or self.errores:
            # Códigos usados por hojas distintas en TODO el examen
            repetidos = RN.detectar_conflictos(guardados)
            codigos = self._lista_codigos()
            hojas = len(guardados)
            b.add_widget(_caption(f"{hojas} hoja{'s' if hojas != 1 else ''} calificada"
                                  f"{'s' if hojas != 1 else ''}  ·  ordenadas por código"))
            for r in self._hojas_ordenadas(guardados, repetidos, codigos):
                lista.add_widget(self._fila_resultado(r, repetidos, codigos))
        else:
            lista.add_widget(_vacio("Aún no has calificado hojas de este examen",
                                    "Toma una foto de cada hoja (o elígelas de la galería) "
                                    "y aquí verás las notas.", alto=140))
        scroll = ScrollView()
        scroll.add_widget(lista)
        b.add_widget(scroll)

        self._volver(b)

    def _fila_resultado(self, r, repetidos, lista):
        codigo = str(r.get("codigo", "???"))
        estado = self._estado_hoja(r, repetidos, lista)
        if estado == "error":
            motivo = str(r.get("error") or r.get("archivo") or "")
            if len(motivo) > 42:
                motivo = motivo[:40].rstrip() + "…"
            texto = (f"[color={ROJO}][b]No pudimos leerla[/b][/color]\n[size=12.5sp]"
                     f"[color={GRIS_HEX}]{motivo}[/color][/size]")
        elif estado == "ilegible":
            texto = (f"[color={AMBAR}][b]Código {codigo}[/b][/color]\n[size=12.5sp]"
                     f"[color={GRIS_HEX}]No se lee bien: tócala para corregirlo[/color][/size]")
        elif estado == "repetido":
            texto = (f"[color={AMBAR}][b]Código {codigo}[/b][/color]\n[size=12.5sp]"
                     f"[color={GRIS_HEX}]Está repetido: revisa cuál es el correcto"
                     f"[/color][/size]")
        elif estado == "fuera":
            texto = (f"[color={AMBAR}][b]Código {codigo}[/b][/color]\n[size=12.5sp]"
                     f"[color={GRIS_HEX}]No está en la lista del curso: revísalo"
                     f"[/color][/size]")
        else:
            n = nota_local(r["aciertos"], r["total"])
            col = VERDE if n >= 6.0 else ROJO
            nombre = f"{lista[codigo]}  ·  " if codigo in lista else ""
            # Doble marca, marca débil o fuera del examen: conviene mirar la hoja
            ojo = (f"   [size=12sp][color={AMBAR}]mira la hoja[/color][/size]"
                   if texto_alertas(r) else "")
            texto = (f"[b]Código {codigo}[/b]   [color={col}][b]{n:.1f}[/b][/color]{ojo}\n"
                     f"[size=12.5sp][color={GRIS_HEX}]{nombre}{r['aciertos']} de "
                     f"{r['total']} correctas[/color][/size]")
        fila = Tarjeta(orientation="horizontal", size_hint_y=None, height=dp(64),
                       padding=[dp(16), dp(8), dp(10), dp(8)], spacing=dp(8),
                       radio=dp(14), sombra=False)
        lbl = Label(text=texto, markup=True, halign="left", valign="middle", font_size="15sp",
                    max_lines=2, line_height=1.15)
        lbl.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, i.height)))
        fila.add_widget(lbl)
        btn = Factory.BotonSuave(text="Ver", size_hint=(None, None), size=(dp(64), dp(44)),
                                 font_size="14sp")
        btn.bind(on_release=lambda inst, rr=r: self._ver_hoja(rr))
        fila.add_widget(btn)
        return fila

    def _cambiar_examen(self, _sp, texto):
        nombre = self._por_texto.get(texto, texto)
        if nombre != self.examen:
            self.examen, self.errores = nombre, []
            self.construir()

    def _volver(self, b):
        b.add_widget(_boton_volver("Volver al curso", "dashboard"))

    def _calificar(self, *_):
        PF.elegir_archivos(lambda refs: self._iniciar_calificacion(refs, mover=False),
                           tipo="imagenes", multiple=True,
                           titulo="Elige las fotos de las hojas")

    def _ver_hoja(self, r):
        """Abre la galería de hojas ya guardadas en esta hoja (se desliza
        para ver las demás; corregir y eliminar se aplican al momento)."""
        hojas = self._hojas_ordenadas()
        i = next((k for k, h in enumerate(hojas) if h is r or
                  (h.get("archivo") == r.get("archivo") and r.get("codigo") != "ERROR")), 0)
        GaleriaHojas(self, hojas, modo="historial", inicio=i).open()

    def _eliminar_hoja(self, r, listo=None):
        """Quita una hoja (preguntando). listo(): se llama después."""
        if r.get("codigo") == "ERROR":
            self.errores = [e for e in self.errores if e is not r]
            self.construir()
            if listo:
                listo()
            return

        def _hacer():
            datos = [e for e in self._leer_notas() if e.get("archivo") != r.get("archivo")]
            self._escribir_notas(datos)
            self._borrar_imagen(r)
            self.construir()
            if listo:
                listo()
        confirmar("¿Quitar esta hoja?",
                  f"Código {r.get('codigo')}  ·  {r['aciertos']} de {r['total']} correctas.\n\n"
                  "Su nota ya no saldrá en la planilla. Úsalo si la foto estaba repetida "
                  "o era de otro examen.", "Sí, quitar", _hacer)

    def _iniciar_calificacion(self, archivos, mover=False, al_terminar=None):
        """
        Califica las fotos EN SEGUNDO PLANO, con una ventana de progreso.

        La interfaz no se congela (en Android así no aparece "La app no
        responde"): varios hilos (HILOS_CALIFICAR) procesan las fotos a la vez
        y avisan a la pantalla después de cada una. Cancelar detiene el trabajo
        al terminar las hojas en curso; las hojas ya calificadas se guardan.

        mover=True mueve la foto en vez de copiarla (fotos de la cámara).
        al_terminar(registros): se llama al final en lugar de mostrar el resumen.
        """
        import lector_omr as L
        if not archivos:
            return
        app = App.get_running_app()
        ruta_curso = app.ruta_curso
        clave_json = self._mapa_claves[self.examen]
        try:
            datos = L.cargar_datos_examen(clave_json)
        except Exception as e:
            aviso("Hay un problema con este examen",
                  f"No pudimos leer sus respuestas correctas:\n{e}")
            return

        cancelar = threading.Event()
        pop = PopupProgreso(
            "Calificando hojas" if len(archivos) > 1 else "Calificando la hoja",
            f"{datos.nombre.replace('_', ' ')}  ·  {app.grado}°{app.curso}",
            len(archivos), cancelar.set)
        pop.open()

        dir_crudos = ruta_curso / "examenes_crudos"
        dir_crudos.mkdir(parents=True, exist_ok=True)

        def estado_de(r):
            if r["codigo"] == "ERROR":
                return "error"
            return "ok" if str(r["codigo"]).isdigit() else "revisar"

        candado = threading.Lock()
        hechas = [0]

        def una(i, a):
            if cancelar.is_set():
                return None
            try:
                nombre = PF.nombre_de(a)
            except Exception:
                nombre = "foto"
            Clock.schedule_once(lambda dt, i=i, n=nombre: pop.empezar(i, n))
            # Copiar con nombre único (dos 'IMG_0001.jpg' ya no se pisan)
            # y calificar SOLO esa foto
            destino = dir_crudos / L.nombre_unico(nombre)
            try:
                PF.copiar(a, destino, mover=mover)
                r = L.calificar_foto(destino, clave_json, ruta_curso, datos)
            except Exception as e:
                r = {"archivo": nombre, "codigo": "ERROR", "aciertos": 0,
                     "total": datos.total_preguntas, "error": str(e)}
            with candado:
                hechas[0] += 1
                k = hechas[0]
            Clock.schedule_once(lambda dt, k=k, e=estado_de(r): pop.avance(k, e))
            return r

        def trabajo():
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(HILOS_CALIFICAR) as hilos:
                # map conserva el orden en que se eligieron las fotos
                nuevos = [r for r in hilos.map(una, range(len(archivos)), archivos)
                          if r is not None]
            Clock.schedule_once(lambda dt: self._fin_calificacion(
                nuevos, datos, pop, cancelar.is_set(), al_terminar))

        threading.Thread(target=trabajo, daemon=True).start()

    def _fin_calificacion(self, nuevos, datos, pop, cancelado, al_terminar):
        """De vuelta en la interfaz: resumen y luego la galería para revisar.
        NADA se guarda todavía: las notas se guardan al tocar Confirmar."""
        if datos.nombre != self.examen:
            self.errores = []
        self.examen = datos.nombre
        if al_terminar is not None:
            pop.dismiss()
            al_terminar(nuevos)
            return
        lista = self._lista_codigos()
        cuenta = {"ok": 0, "revisar": 0, "error": 0}
        for r in nuevos:
            estado = self._estado_hoja(r, set(), lista)
            cuenta[estado if estado in ("ok", "error") else "revisar"] += 1
        if not nuevos:
            pop.terminar(cuenta, cancelado, al_cerrar=lambda: None)
            return
        pop.terminar(cuenta, cancelado, al_cerrar=lambda: self._revisar(nuevos),
                     nota="Revísalas y toca Confirmar para guardar las notas.",
                     texto_boton="Revisar y confirmar")

    def _revisar(self, nuevos):
        """Galería de la tanda recién calificada, en el mismo orden de la lista."""
        lista = self._lista_codigos()
        errores = [r for r in nuevos if r["codigo"] == "ERROR"]
        leidas = [r for r in nuevos if r["codigo"] != "ERROR"]
        # sorted es estable: entre fotos del mismo alumno se mantiene el orden
        # en que se eligieron (se guarda la última)
        GaleriaHojas(self, errores + self._ordenar(leidas, set(), lista)).open()

    def _confirmar_tanda(self, conservadas, errores):
        """Confirmar en la galería: ahora sí se guardan las notas."""
        self._guardar_registros(conservadas)
        # Las hojas ilegibles no son notas: se muestran solo en esta sesión
        self.errores = errores + self.errores
        self.construir()

    def _ruta_notas(self):
        app = App.get_running_app()
        dir_salida = app.ruta_curso / "resultados"
        dir_salida.mkdir(parents=True, exist_ok=True)
        return dir_salida / f"notas_{self.examen}.json"

    def _leer_notas(self):
        notas_path = self._ruta_notas()
        if not notas_path.exists():
            return []
        try:
            return json.loads(notas_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _guardar_registros(self, nuevos):
        """Agrega/actualiza registros en notas_<examen>.json (clave: archivo).
        Las hojas con ERROR no se guardan: no son una nota (se ven en pantalla).

        Si llega otra hoja del mismo alumno, se queda la última: la anterior
        y su imagen marcada se quitan. Solo con códigos legibles que estén en
        la lista del curso (o cualquiera legible si aún no hay lista); un
        código dudoso no pisa a nadie y queda 'por revisar'.
        Devuelve cuántas hojas anteriores se reemplazaron."""
        lista = self._lista_codigos()
        registros = {r.get("archivo", ""): r for r in self._leer_notas()}
        reemplazadas = 0
        for r in nuevos:
            cod = str(r.get("codigo", ""))
            if cod.isdigit() and (not lista or cod in lista):
                for archivo, viejo in list(registros.items()):
                    if archivo != r["archivo"] and str(viejo.get("codigo", "")) == cod:
                        del registros[archivo]
                        self._borrar_imagen(viejo)
                        reemplazadas += 1
            registros[r["archivo"]] = r
        self._escribir_notas(list(registros.values()))
        return reemplazadas

    def _escribir_notas(self, datos):
        """Guarda las notas del examen. Se escriben primero en un archivo
        temporal y luego se cambia de un golpe: si la app se cierra a media
        escritura (batería, llamada), las notas anteriores no se dañan."""
        ruta = self._ruta_notas()
        temporal = ruta.with_name(ruta.name + ".tmp")
        temporal.write_text(json.dumps(datos, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        os.replace(temporal, ruta)

    def _borrar_imagen(self, r):
        """Borra la imagen marcada de una hoja (si tiene)."""
        if r.get("imagen"):
            try:
                (self._ruta_notas().parent / r["imagen"]).unlink()
            except Exception:
                pass

    def _pedir_codigo(self, r, al_guardar):
        """Cuadro para escribir el código; al_guardar(nuevo) con 3 dígitos."""
        cont = BoxLayout(orientation="vertical", spacing=dp(8), padding=[dp(8), dp(10)])
        cont.add_widget(_ajustar_texto(Label(
            text="Escribe el código que el estudiante debía marcar (3 números).",
            size_hint_y=None, height=dp(40), font_size="13sp", color=GRIS,
            halign="left", valign="middle")))
        actual = "".join(c for c in r.get("codigo", "") if c.isdigit())
        ti = TextInput(text=actual, multiline=False, input_filter="int",
                       hint_text="Ej.: 007", size_hint_y=None, height=dp(48))
        cont.add_widget(ti)
        lbl = Label(text="", size_hint_y=None, height=dp(22), font_size="13sp",
                    color=(0.776, 0.157, 0.157, 1))
        cont.add_widget(lbl)
        cont.add_widget(Widget())
        btn = Factory.BotonAccion(text="Guardar", size_hint_y=None, height=dp(50))
        cont.add_widget(btn)
        pop = Popup(title="Corregir código", content=cont, size_hint=(0.88, 0.5))

        def _ok(*_):
            nuevo = ti.text.strip()
            if not nuevo.isdigit():
                lbl.text = "Solo números, por favor."
                return
            pop.dismiss()
            al_guardar(nuevo.zfill(3))

        btn.bind(on_release=_ok)
        ti.bind(on_text_validate=_ok)
        pop.open()

    def _editar_codigo(self, r, listo=None):
        """Corrige el código de una hoja ya guardada. listo(): se llama después."""
        def _guardar(nuevo):
            otras = [e for e in self._leer_notas()
                     if e.get("archivo") != r["archivo"] and str(e.get("codigo")) == nuevo]

            def _aplicar(quitar=()):
                r["codigo"] = nuevo
                self._actualizar_notas_codigo(r["archivo"], nuevo, quitar)
                self.construir()
                if listo:
                    listo()
            if not otras:
                _aplicar()
                return
            # Ya hay una hoja con ese código: se queda esta (la que corriges)
            confirmar(f"Ya hay una hoja con el código {nuevo}",
                      "Si sigues, esta hoja queda como la de ese alumno y la otra se "
                      "quita (su nota ya no saldrá en la planilla).",
                      "Sí, reemplazar", lambda: _aplicar(otras))
        self._pedir_codigo(r, _guardar)

    def _actualizar_notas_codigo(self, archivo, nuevo, quitar=()):
        """Cambia el código de una hoja; 'quitar': hojas que esta reemplaza."""
        fuera = {e.get("archivo") for e in quitar}
        data = [e for e in self._leer_notas() if e.get("archivo") not in fuera]
        for e in data:
            if e.get("archivo") == archivo:
                e["codigo"] = nuevo
                e["codigo_corregido"] = True
        for e in quitar:
            self._borrar_imagen(e)
        self._escribir_notas(data)

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
        if platform == "android":
            self._pedir_permiso_camara()
            return
        if platform == "ios":
            try:
                from plyer import camera  # type: ignore
            except Exception:
                aviso("Cámara", "No pudimos usar la cámara de este dispositivo.")
                return
            destino = self._ruta_captura()
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            try:
                camera.take_picture(filename=str(destino), on_complete=self._foto_lista)
            except Exception as e:
                aviso("Cámara", f"No pudimos abrir la cámara: {e}")
            return
        aviso("Cámara", "La cámara solo funciona en el celular. Aquí puedes usar "
              "'Desde la galería' para elegir las fotos.")

    def _pedir_permiso_camara(self):
        """Pide el permiso de cámara (solo la primera vez) y luego la abre."""
        try:
            from android.permissions import (request_permissions, check_permission,  # type: ignore
                                             Permission)
        except Exception:
            self._abrir_camara_c4k()
            return
        if check_permission(Permission.CAMERA):
            self._abrir_camara_c4k()
            return

        def _respuesta(_permisos, concedidos):
            if concedidos and all(concedidos):
                Clock.schedule_once(lambda dt: self._abrir_camara_c4k(), 0.2)
            else:
                Clock.schedule_once(lambda dt: aviso(
                    "Cámara", "Para tomar fotos necesitamos permiso de cámara.\n\n"
                    "Puedes darlo en Ajustes del teléfono > Aplicaciones > "
                    "CalificadorApp > Permisos."), 0)
        request_permissions([Permission.CAMERA], _respuesta)

    def _abrir_camara_c4k(self):
        """Cámara integrada con camera4kivy (CameraX): vista previa en vivo
        dentro de la app + botón de captura."""
        try:
            from camera4kivy import Preview  # type: ignore
        except Exception as e:
            aviso("Cámara", "No pudimos iniciar la cámara: %s\n\n"
                  "Mientras tanto, puedes usar 'Desde la galería'." % e)
            return
        try:
            cont = FloatLayout()
            self._preview = Preview(aspect_ratio="4:3",
                                    size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
            cont.add_widget(self._preview)

            btn_cap = Factory.BotonAccion(text="Tomar foto", size_hint=(None, None),
                                          size=(dp(180), dp(60)),
                                          pos_hint={"center_x": 0.5, "y": 0.03})
            btn_cap.bind(on_release=lambda *_: self._preview.capture_photo(location="private"))
            cont.add_widget(btn_cap)

            btn_x = BotonCerrar(size_hint=(None, None), size=(dp(52), dp(52)),
                                pos_hint={"right": 0.97, "top": 0.97})
            btn_x.color_fondo = (0, 0, 0, 0.45)
            btn_x.color_fondo_down = (0, 0, 0, 0.65)
            cont.add_widget(btn_x)

            self._popup_cam = Popup(title="Encuadra la hoja completa", content=cont,
                                    size_hint=(1, 1), auto_dismiss=False)
            btn_x.bind(on_release=lambda *_: self._popup_cam.dismiss())
            self._popup_cam.bind(
                on_open=lambda *_: self._preview.connect_camera(
                    camera_id="back", filepath_callback=self._foto_c4k,
                    enable_video=False),
                on_pre_dismiss=lambda *_: self._desconectar_c4k())
            self._popup_cam.open()
        except Exception as e:
            import traceback
            aviso("Cámara", "No pudimos iniciar la cámara: %s\n\n%s"
                  % (e, traceback.format_exc()))

    def _desconectar_c4k(self):
        try:
            self._preview.disconnect_camera()
        except Exception:
            pass

    def _foto_c4k(self, path):
        """camera4kivy llama esto cuando la foto quedó guardada (otro hilo)."""
        Clock.schedule_once(lambda dt: self._tras_captura_c4k(path), 0)

    def _tras_captura_c4k(self, path):
        p = Path(str(path)) if path else None
        if p is None or not p.exists():
            return  # puede ser un mensaje de aviso, no una ruta real
        try:
            self._popup_cam.dismiss()
        except Exception:
            pass
        # Espera a que se cierre la cámara antes de abrir la ventana de progreso
        Clock.schedule_once(lambda dt: self._foto_lista(str(p)), 0.3)

    def _foto_lista(self, ruta_foto):
        """La cámara terminó: se califica la foto con la misma ventana de
        progreso que las fotos cargadas, y luego se muestra la hoja marcada."""
        p = Path(str(ruta_foto)) if ruta_foto else None
        if not p or not p.exists():
            aviso("Cámara", "No nos llegó la foto. Inténtalo de nuevo.")
            return
        # Se mueve a la carpeta del curso (no queda en la galería)
        self._iniciar_calificacion([str(p)], mover=True,
                                   al_terminar=self._mostrar_foto_calificada)

    def _mostrar_foto_calificada(self, registros):
        r = registros[0] if registros else None
        if r is None or r["codigo"] == "ERROR":
            aviso("No pudimos calificarla", (r or {}).get("error") or
                  "No logramos leer la hoja. Prueba con más luz y la hoja completa en la foto.")
            return
        self._revisar(registros)

    @staticmethod
    def _np_a_textura(img_bgr):
        import cv2
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        rgb = cv2.flip(rgb, 0)  # el origen de la textura de Kivy está abajo
        h, w = rgb.shape[:2]
        tex = Texture.create(size=(w, h), colorfmt="rgb")
        tex.blit_buffer(rgb.tobytes(), colorfmt="rgb", bufferfmt="ubyte")
        return tex


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: REGISTRO DE NOTAS (Paso 5)  ·  Excel cruzando código -> estudiante
# ─────────────────────────────────────────────────────────────────────────────
class RegistroScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cont = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        self.add_widget(self.cont)
        self.ultimo_excel = None
        self.mensaje = ""
        self.examen = ""          # examen elegido (se conserva al redibujar)

    def on_pre_enter(self, *_):
        self.ultimo_excel = None
        self.mensaje = ""
        self.construir()

    def _examen_elegido(self):
        return self._por_texto.get(self.sp_examen.text, self.sp_examen.text)

    def _al_elegir_examen(self, *_):
        """Otro examen: la planilla recién creada ya no corresponde."""
        if self._examen_elegido() != self.examen:
            self.examen = self._examen_elegido()
            if self.ultimo_excel:
                self.ultimo_excel, self.mensaje = None, ""
                self.construir()

    def construir(self):
        app = App.get_running_app()
        self.cont.clear_widgets()
        b = self.cont
        b.add_widget(Encabezado("Notas", f"Curso {app.grado}\u00b0{app.curso}"))

        import registro_notas as RN
        examenes = RN.examenes_disponibles(app.ruta_curso)
        if not examenes:
            b.add_widget(_vacio("Todavía no hay notas",
                                "Cuando califiques hojas en 'Calificar', aquí podrás "
                                "armar la planilla de Excel.", alto=150))
            b.add_widget(Widget())
            self._volver(b)
            return

        tarjeta = Tarjeta(size_hint_y=None, padding=[dp(16), dp(14)], spacing=dp(10))
        tarjeta.bind(minimum_height=tarjeta.setter("height"))
        tarjeta.add_widget(_caption("Examen"))
        # En la lista se ven con espacios; por dentro, con "_"
        self._por_texto = {e.replace("_", " "): e for e in examenes}
        if self.examen not in examenes:
            self.examen = examenes[0]
        self.sp_examen = Spinner(text=self.examen.replace("_", " "),
                                 values=list(self._por_texto),
                                 size_hint_y=None, height=dp(48))
        self.sp_examen.bind(text=self._al_elegir_examen)
        tarjeta.add_widget(self.sp_examen)
        btn = Factory.BotonAccion(text="Crear planilla de notas", size_hint_y=None,
                                  height=dp(52))
        btn.bind(on_release=self._generar)
        tarjeta.add_widget(btn)

        if self.ultimo_excel:
            ref, nombre = self.ultimo_excel
            self.lbl_msg = _ajustar_texto(Label(
                text=self.mensaje, markup=True, size_hint_y=None, height=dp(52),
                font_size="13sp", color=GRIS, halign="center", valign="middle"))
            tarjeta.add_widget(self.lbl_msg)
            fila_b = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
            btn_abrir = Factory.BotonSuave(text="Abrir")
            btn_abrir.bind(on_release=lambda *_: self._abrir(ref, nombre))
            fila_b.add_widget(btn_abrir)
            btn_comp = Factory.BotonSuave(text="Compartir" if PF.ES_ANDROID else "Ver carpeta")
            btn_comp.bind(on_release=lambda *_: self._compartir(ref, nombre))
            fila_b.add_widget(btn_comp)
            tarjeta.add_widget(fila_b)
        b.add_widget(tarjeta)

        b.add_widget(Widget(size_hint_y=None, height=dp(4)))
        b.add_widget(_caption("Más opciones"))
        btn_rep = BotonMenu(icono="registro", titulo="Estadísticas del examen",
                            detalle="Promedio, aprobados y las preguntas más difíciles")
        btn_rep.bind(on_release=self._reporte_docente)
        b.add_widget(btn_rep)

        btn_sem = BotonMenu(icono="examenes", titulo="Enviar al coordinador",
                            detalle="Sube las notas del semestre de forma segura")
        btn_sem.bind(on_release=lambda *_: setattr(
            App.get_running_app().sm, "current", "semestrales"))
        b.add_widget(btn_sem)

        b.add_widget(Widget())
        self._volver(b)

    def _volver(self, b):
        b.add_widget(_boton_volver("Volver al curso", "dashboard"))

    def _reporte_docente(self, *_):
        ruta_curso = App.get_running_app().ruta_curso
        examen = self._examen_elegido()

        def trabajo():
            import reportes
            ruta = reportes.generar_reporte_docente(ruta_curso, examen)
            return PF.guardar_en_descargas(ruta, ruta.name) + (ruta.name,)

        def listo(res, err):
            if err:
                aviso("No pudimos crear las estadísticas", str(err))
                return
            texto, ref, nombre = res
            aviso_archivo("Tus estadísticas están listas",
                          "Promedio, aprobados, análisis por pregunta y gráficas.\n\n"
                          f"Las encuentras en:\n{texto}", ref, nombre)
        en_segundo_plano("Calculando estadísticas\u2026", trabajo, listo)

    def _generar(self, *_):
        app = App.get_running_app()
        import registro_notas as RN
        examen = self._examen_elegido()
        try:
            ruta = RN.generar_registro(app.ruta_curso, examen)
        except Exception as e:
            aviso("No pudimos crear la planilla", str(e))
            return
        if ruta is None:
            aviso("Falta la lista del curso",
                  "Para armar la planilla necesitamos los nombres de los estudiantes.\n\n"
                  "Agrégalos en 'Estudiantes' y vuelve a intentarlo.")
            return
        # Copia en Descargas para encontrarlo, abrirlo o compartirlo fuera de la app
        try:
            texto, ref = PF.guardar_en_descargas(ruta, ruta.name)
        except Exception:
            texto, ref = str(ruta), str(ruta)
        self.ultimo_excel = (ref, ruta.name)
        self.mensaje = f"[b][color={VERDE}]¡Planilla lista![/color][/b]  Está en:\n{texto}"
        self.construir()

    def _abrir(self, ref, nombre):
        err = PF.abrir(ref, nombre)
        if err:
            aviso("No pudimos abrirla",
                  f"Búscala en tu carpeta de Descargas ({nombre}).\n\n"
                  "Necesitas una app de hojas de cálculo, como Excel, Google Sheets o WPS.\n\n"
                  f"({err})")

    def _compartir(self, ref, nombre):
        err = PF.compartir(ref, nombre)
        if err:
            aviso("No pudimos compartirlo", err)


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA: SUBIR SEMESTRALES  ·  genera el .json.enc y lo sube al coordinador
# ─────────────────────────────────────────────────────────────────────────────
# Catálogo de áreas (debe coincidir con el del coordinador; acentos/mayúsculas
# no importan allá, pero un área nueva haría que su sincronización aborte).
AREAS = ("Inglés", "Matemáticas", "Español", "Ciencias")


def _ruta_config_subida():
    return Path(App.get_running_app().user_data_dir) / "config_subida.json"


def _leer_area_guardada():
    """Devuelve la última área elegida (o la primera del catálogo)."""
    try:
        d = json.loads(_ruta_config_subida().read_text(encoding="utf-8"))
        a = d.get("area", "")
        return a if a in AREAS else AREAS[0]
    except Exception:
        return AREAS[0]


def _guardar_area(area):
    try:
        _ruta_config_subida().write_text(
            json.dumps({"area": area}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


class SemestralesScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cont = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        self.add_widget(self.cont)

    def on_pre_enter(self, *_):
        self.construir()

    def construir(self):
        import datetime
        import registro_notas as RN
        app = App.get_running_app()
        self.cont.clear_widgets()
        b = self.cont
        b.add_widget(Encabezado("Enviar al coordinador", f"Curso {app.grado}\u00b0{app.curso}"))

        examenes = RN.examenes_disponibles(app.ruta_curso)
        if not examenes:
            b.add_widget(_vacio("Todavía no hay notas para enviar",
                                "Primero califica las hojas en 'Calificar'.", alto=140))
            b.add_widget(Widget())
            self._volver(b)
            return

        aviso_lbl = _ajustar_texto(Label(
            text="Enviamos las notas del semestre protegidas, para que solo "
                 "coordinación pueda abrirlas.",
            size_hint_y=None, height=dp(44), font_size="13.5sp", color=GRIS,
            halign="left", valign="middle"))
        b.add_widget(aviso_lbl)

        tarjeta = Tarjeta(size_hint_y=None, padding=[dp(16), dp(14)], spacing=dp(6))
        tarjeta.bind(minimum_height=tarjeta.setter("height"))
        tarjeta.add_widget(_caption("Examen"))
        self.sp_examen = Spinner(text=examenes[0], values=examenes,
                                 size_hint_y=None, height=dp(48))
        tarjeta.add_widget(self.sp_examen)

        # Período semestral (formato AAAA-S)
        hoy = datetime.date.today()
        anios = [str(a) for a in range(hoy.year - 1, hoy.year + 2)]
        fila_per = BoxLayout(size_hint_y=None, height=dp(74), spacing=dp(10))
        col_a = BoxLayout(orientation="vertical", spacing=dp(4))
        col_a.add_widget(_caption("Año"))
        self.sp_anio = Spinner(text=str(hoy.year), values=anios,
                               size_hint_y=None, height=dp(48))
        col_a.add_widget(self.sp_anio)
        col_s = BoxLayout(orientation="vertical", spacing=dp(4))
        col_s.add_widget(_caption("Semestre"))
        self.sp_semestre = Spinner(text=("1" if hoy.month <= 6 else "2"),
                                   values=("1", "2"), size_hint_y=None, height=dp(48))
        col_s.add_widget(self.sp_semestre)
        fila_per.add_widget(col_a)
        fila_per.add_widget(col_s)
        tarjeta.add_widget(fila_per)

        # Área (se recuerda la última elegida)
        tarjeta.add_widget(_caption("Área"))
        self.sp_area = Spinner(text=_leer_area_guardada(), values=AREAS,
                               size_hint_y=None, height=dp(48))
        tarjeta.add_widget(self.sp_area)
        b.add_widget(tarjeta)

        b.add_widget(Widget())
        btn_coord = Factory.BotonAccion(text="Enviar notas",
                                        size_hint_y=None, height=dp(54))
        btn_coord.bind(on_release=self._enviar_coordinador)
        b.add_widget(btn_coord)
        self._volver(b)

    def _enviar_coordinador(self, *_):
        app = App.get_running_app()
        examen = self.sp_examen.text
        periodo = f"{self.sp_anio.text}-{self.sp_semestre.text}"
        area = self.sp_area.text
        ruta_curso = app.ruta_curso

        def _hacer():
            _guardar_area(area)

            def trabajo():
                import reportes
                import subida
                # 1) Generar el .json.enc cifrado  2) subirlo
                ruta = reportes.generar_json_salon(ruta_curso, examen, periodo)
                ok, msg = subida.subir_a_drive(str(ruta), area, periodo)
                return ruta, ok, msg

            def listo(res, err):
                if err:
                    aviso("No pudimos preparar el envío", str(err))
                    return
                ruta, ok, msg = res
                if ok:
                    aviso("¡Notas enviadas!", "Coordinación ya tiene tus notas.\n\n"
                          f"{ruta.name}")
                else:
                    aviso("No pudimos enviarlas",
                          f"Preparamos el archivo, pero no se pudo subir:\n{msg}\n\n"
                          "Revisa tu conexión a internet e inténtalo de nuevo.\n\n"
                          f"Archivo: {ruta.name}")
            en_segundo_plano("Enviando tus notas\u2026", trabajo, listo)

        confirmar("¿Enviamos estas notas?",
                  f"'{examen}'  ·  curso {app.grado}\u00b0{app.curso}\n"
                  f"Área: {area}  ·  Semestre {periodo}",
                  "Sí, enviar", _hacer, peligro=False)

    def _volver(self, b):
        b.add_widget(_boton_volver("Volver a notas", "registro"))


# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────
class CalificadorApp(App):
    profesor = ""
    grado = ""
    curso = ""
    ruta_curso = None

    def build(self):
        self.title = "Calificador · Liceo Sahagún"
        # En Android la carpeta de instalación es de solo lectura: movemos el
        # "directorio de trabajo" a la carpeta privada de la app (sí escribible),
        # para que 'profesores/' y todos los datos se guarden sin problemas.
        # En PC, los datos van siempre junto a la app (antes dependían de la
        # carpeta desde donde se abría, y parecía que se "perdían").
        try:
            os.chdir(self.user_data_dir if platform == "android" else _DIR)
        except Exception:
            pass
        _registrar_fuentes()
        Window.clearcolor = FONDO
        # Al escribir, la pantalla sube para que el campo quede sobre el teclado
        Window.softinput_mode = "below_target"
        if platform != "android":
            Window.size = (400, 720)   # vista tipo celular para probar en PC
        GS.inicializar_sistema()
        self.sm = ScreenManager(transition=SlideTransition(duration=0.18))
        self.sm.add_widget(SetupScreen(name="setup"))
        self.sm.add_widget(HomeScreen(name="home"))
        self.sm.add_widget(DashboardScreen(name="dashboard"))
        self.sm.add_widget(EstudiantesScreen(name="estudiantes"))
        self.sm.add_widget(ExamenesScreen(name="examenes"))
        self.sm.add_widget(ClavesScreen(name="claves"))
        self.sm.add_widget(CalificarScreen(name="calificar"))
        self.sm.add_widget(RegistroScreen(name="registro"))
        self.sm.add_widget(SemestralesScreen(name="semestrales"))
        self.sm.current = "home" if _subdirs(BASE) else "setup"
        Window.bind(on_keyboard=self._tecla)
        return self.sm

    # Pantalla a la que lleva "Atrás" desde cada una
    _ATRAS = {"estudiantes": "dashboard", "examenes": "dashboard",
              "calificar": "dashboard", "registro": "dashboard", "dashboard": "home",
              "claves": "examenes", "semestrales": "registro"}

    def _tecla(self, _window, tecla, *_):
        """Botón "Atrás" de Android (y Esc en PC): vuelve a la pantalla anterior
        en lugar de cerrar la app. En el inicio pregunta antes de cerrarla."""
        if tecla != 27:
            return False
        if any(isinstance(w, ModalView) for w in Window.children):
            return True   # hay una ventana abierta (p. ej. calificando): no salir
        destino = self._ATRAS.get(self.sm.current)
        if destino:
            self.sm.current = destino
        else:
            pedir_salir()   # en el inicio: preguntar antes de cerrar
        return True

    def on_start(self):
        _solicitar_permisos_android()

    def ir_a_home(self):
        self.sm.current = "home"


if __name__ == "__main__":
    CalificadorApp().run()