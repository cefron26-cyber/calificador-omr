# Calificador OMR — Liceo Sahagún

Aplicación (hecha en **Kivy**, Python) que califica exámenes de opción múltiple a
partir de **fotos** de las hojas de respuestas. Lee el código del estudiante y las
respuestas marcadas, calcula la nota y arma el registro en Excel. Funciona en PC y
se empaqueta como **app de Android** con Buildozer.

---

## Qué hace

1. **Configuración inicial (una sola vez):** nombre del profesor, sus grados y
   cuántos cursos tiene cada uno (los cursos se nombran A, B, C…).
2. **Estudiantes:** lista por curso con código automático según la posición
   (001, 002…). Permite agregar, **editar o eliminar** (toca al estudiante),
   descargar una **plantilla** para llenar e **importar la planilla** (Excel/CSV).
3. **Exámenes:** crea el examen y, en la pantalla **Respuestas correctas**, toca la
   letra correcta de cada pregunta (botones A/B/C/D). Con **Crear también en…**
   el mismo examen se guarda de una vez en los otros cursos del grado (o en los
   que elijas con **Elegir**), sin volver a marcar las respuestas. Luego genera el
   **PDF** de la hoja:
   - **Media hoja** (2 iguales por página, para recortar): hasta 40 preguntas.
   - **Hoja completa** (1 por página): hasta 50 preguntas.
   - **Hoja ya impresa con más preguntas:** si solo puedes imprimir un tipo de
     hoja (por ejemplo la de 30) y el examen tiene menos (25), marca **Usaré una
     hoja ya impresa con más preguntas** y escribe cuántas trae. Ver
     [Examen con menos preguntas que la hoja](#examen-con-menos-preguntas-que-la-hoja).
   - Toca un examen de la lista para **cambiar su hoja** después (tamaño o
     preguntas impresas) sin volver a marcar las respuestas.
4. **Calificar:** carga una o varias fotos → las **escanea** (recorta el fondo,
   endereza y quita sombras, al estilo CamScanner) → las **lee y califica**
   (varias a la vez) → se abre una **galería** para revisarlas deslizando:
   corrige el código o descarta las que no sirvan. **Las notas se guardan al
   tocar Confirmar**; si sales sin confirmar, no se guarda nada.
   - Si una hoja tiene dobles marcas, marcas débiles o marcas fuera del examen,
     la lista dice **mira la hoja** y la galería explica qué revisar.
   - Si la foto es de una hoja de **otro tamaño** (hoja completa en un examen de
     media hoja, o al revés), no se inventa una nota: la app lo dice.
   - Si llega otra hoja de un alumno que ya tenía una, **se queda la última**
     (solo con códigos legibles que estén en la lista del curso).
   - El **historial** del examen sale ordenado por código, con las hojas por
     revisar arriba. **Ver** abre la misma galería para recorrerlas, corregir
     códigos o eliminarlas.
5. **Notas:** genera el **Excel** cruzando código → estudiante, con
   nota, promedio y "No presentó" para los ausentes. Se guarda en **Descargas**
   y se puede abrir o **compartir** (WhatsApp, Drive, correo).
   - **Estadísticas del examen:** Excel aparte con promedio, mediana, aprobados,
     análisis por pregunta y gráficas.
   - **Enviar al coordinador:** genera un archivo cifrado con las notas y lo envía
     al coordinador (Google Drive, vía Apps Script). Se configura en `subida.py`.
6. **Inicio:** agregar, **editar o eliminar** grados y cursos, y **copia de
   seguridad** (guarda todo en un `.zip` en Descargas y lo restaura en otro
   celular o tras reinstalar la app).
   - **Códigos** (mosaico con código de barras): un PDF (en Descargas) con **una hoja carta vertical
     por salón** (6 salones = 6 hojas): código en letra grande y nombre de cada
     estudiante, para pegar en el salón o dictar los códigos. La letra se ajusta
     para que todo el salón quepa en su hoja; los cursos sin estudiantes no salen.
   - **Liberar espacio** (papelera): lista los exámenes con fotos, agrupados por
     curso, con cuánto ocupa cada uno; vienen marcados los de hace más de 6 meses
     (atajos: Más de 6 meses / Todos / Ninguno). Borra solo las **fotos** (la
     original y la hoja marcada): **las notas se conservan** y el Excel y las
     estadísticas siguen funcionando. Las fotos originales se guardan reducidas
     (~0.15 MB) en cuanto se califican.
7. **Cámara integrada** (Android): vista previa en vivo dentro de la app con
   botón Tomar foto; la foto se califica al instante.

---

## Requisitos (PC)

- **Python 3.11, 3.12 o 3.13** (recomendado el de **Anaconda**). No usar 3.14.
- Librerías:
  ```
  pip install kivy opencv-python numpy openpyxl
  ```

---

## Archivos del proyecto

| Archivo | Para qué |
|---|---|
| `main.py` | La aplicación (interfaz y pantallas). |
| `layout_hoja.py` | **Geometría única** de las hojas (marcas, burbujas, encabezado) para cada formato. La usan el generador y el lector. |
| `generador_pdf.py` | Dibuja el PDF de la hoja (Python puro, funciona en Android). |
| `digitalizador.py` | "Escáner": encuentra la hoja en la foto, la endereza y quita sombras. |
| `lector_omr.py` | Motor OMR: marcas de esquina, orientación, lectura de burbujas, nota. |
| `registro_notas.py` | Arma el Excel cruzando código → estudiante. |
| `reportes.py` | Reporte del docente (estadísticas y gráficas) y archivo del salón para el coordinador. |
| `cripto.py` | Cifrado ligero del archivo que va al coordinador. |
| `subida.py` | Envío al coordinador (Apps Script). **Pega aquí tu URL y token.** |
| `gestor_salones.py` | Crea las carpetas Profesor/Grado/Curso. |
| `plataforma.py` | Lo que cambia entre PC y Android: elegir archivos, Descargas, abrir/compartir, copia de seguridad. |
| `assets/` | Fuentes de la app, `escudo_app.png` (encabezado) y `logo_pdf.png` (logo reducido para el PDF). |
| `camerax_provider/` | Conecta la cámara (CameraX) con camera4kivy al compilar el APK. |
| `logo.png` | Logo original en alta resolución (no se empaqueta en el APK). |
| `buildozer.spec`, `.github/workflows/build.yml` | Compilación del APK de Android en GitHub (pestaña Actions). |

---

## Cómo ejecutarla (PC)

1. Abre una terminal (en Windows, **Anaconda Prompt**) en la carpeta del proyecto.
2. Ejecuta:
   ```
   python main.py
   ```
3. La primera vez pide la configuración inicial; luego abre directo en el menú.

Para probar solo el escáner con fotos reales:
```
python digitalizador.py foto1.jpg foto2.jpg
```
Guarda `foto1_escaneada.jpg` junto a cada foto.

---

## Cómo se usa (flujo típico)

1. **Estudiantes** → importa o crea la lista del curso (cada alumno recibe un código).
2. **Exámenes** → crea el examen con su clave y descarga el PDF para imprimir.
3. Si es media hoja, recorta por la línea punteada. Cada alumno rellena **su
   código** y sus respuestas.
4. Toma una foto de cada hoja (en cualquier orientación; se corrige sola).
5. **Calificar** → elige el examen → carga las fotos → revisa los resultados
   (corrige el código si alguno salió dudoso).
6. **Registro de notas** → genera y abre el Excel del curso.

> **Importante:** el código que el alumno rellena en la hoja debe coincidir con su
> código en la lista. Si no coincide, o si dos hojas distintas traen el mismo
> código, esa hoja aparece en la pestaña **"Por revisar"** del Excel con el motivo.
> Usa **Corregir código** para arreglarlo.

---

## La hoja de respuestas

- **4 cuadrados negros en las esquinas:** el lector los busca para enderezar la
  hoja y ubicar cada burbuja con precisión.
- **Cuadrado pequeño debajo del de arriba a la izquierda:** marca de orientación.
  Le dice al lector cuál es la esquina superior izquierda, así la foto se puede
  tomar girada o de cabeza. No debe taparse ni rellenarse.

---

## Examen con menos preguntas que la hoja

Pensado para cuando la institución imprime **un solo tipo de hoja** (por ejemplo,
la de 30 preguntas) y el examen tiene menos (por ejemplo, 25):

1. En **Exámenes → Nuevo examen** escribe las preguntas reales (25), marca
   **Usaré una hoja ya impresa con más preguntas** y escribe las de la hoja (30).
   La app lo recuerda: en el siguiente examen ya viene marcado.
   Para un examen que ya existe, tócalo en la lista y cambia su hoja.
2. Solo marcas las 25 respuestas correctas. Los estudiantes dejan en blanco
   de la 26 a la 30.
3. Al calificar, la nota sale sobre 25. Las preguntas 26 a 30 aparecen tapadas
   en gris (**NO CUENTAN**) en la hoja marcada.
4. Si un estudiante **marcó alguna de las que sobran** (por ejemplo, se corrió
   una fila), la nota no cambia pero la app avisa: *"marcó fuera del examen
   (26, 27)"*, para que mires esa hoja.

La planilla de Excel y las estadísticas usan solo las 25 preguntas del examen.
Funciona igual en media hoja y en hoja completa, y con cualquier cantidad
(20 en hoja de 40, 45 en hoja de 50…).

---

## Dónde quedan los datos

Todo se guarda dentro de la carpeta `profesores/` (en PC, junto a `main.py`;
en Android, en la carpeta privada de la app; por eso conviene la copia de
seguridad):

```
profesores/<Profesor>/<Grado>/<Curso>/
    estudiantes/                 → lista_estudiantes.xlsx
    examenes_claves/             → respuestas_<examen>.json (clave + formato de hoja
                                   + preguntas de la hoja impresa, si son más)
    examenes_crudos/             → fotos recién cargadas (de paso)
    examenes_crudos_archivados/  → fotos originales ya calificadas (reducidas, ~0.15 MB c/u)
    resultados/                  → imágenes marcadas + notas_<examen>.json
                                   + coordinador_<grado><curso>_<periodo>.json.enc
    resultados_excel/            → registro_<examen>.xlsx, reporte_<curso>_<examen>.xlsx
```

Los PDF de las hojas, los registros Excel y las copias de seguridad se guardan
en la carpeta **Descargas**.

---

## Escala de notas

Lineal de **0 a 10**: `nota = 10 × (aciertos / total)`, truncada a un decimal
(sin redondear hacia arriba) y con **piso de 1.0** (ninguna nota baja de 1).
Aprueba con **6.0**.
