[app]

# Nombre que se ve en el teléfono
title = CalificadorApp

# Identificadores internos (sin espacios ni mayúsculas raras)
package.name = calificador
package.domain = org.liceosahagun

# Carpeta del código (el . = la misma carpeta donde está este archivo)
source.dir = .

# Tipos de archivo que se empaquetan dentro del APK
source.include_exts = py,png,jpg,jpeg,kv,atlas,ttf,json

# Versión de la app
version = 0.1

# Librerías que necesita la app
requirements = python3,kivy,opencv,numpy,pillow,openpyxl,et_xmlfile,plyer,pyjnius,camera4kivy,gestures4kivy

# La app se ve en vertical
orientation = portrait
fullscreen = 0

# Permisos de Android
android.permissions = CAMERA,VIBRATE,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

# Arquitectura (cubre los celulares modernos)
android.archs = arm64-v8a

# camera4kivy/CameraX exige API 33
android.api = 33

# Activa el proveedor de cámara CameraX (necesita la carpeta camerax_provider/ en el repo)
p4a.hook = camerax_provider/gradle_options.py

android.allow_backup = 1

# --- Opcionales: descomenta si quieres usar el logo como ícono/splash ---
# icon.filename = %(source.dir)s/logo.png
# presplash.filename = %(source.dir)s/logo.png


[buildozer]

# Nivel de detalle de los mensajes (2 = bastante detalle)
log_level = 2
warn_on_root = 1
