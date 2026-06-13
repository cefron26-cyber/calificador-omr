# Calificador OMR 

Aplicación de escritorio (hecha en **Kivy**, Python) que califica exámenes de opción
múltiple a partir de **fotos** de las hojas de respuestas. Lee el código del
estudiante y las respuestas marcadas, calcula la nota y arma el registro en Excel.
Es la base de la futura **app de Android**.

---

## Qué hace

Reproduce, con botones, todo lo que antes se hacía por consola:

1. **Configuración inicial (una sola vez):** nombre del profesor, sus grados y
   cuántos cursos tiene cada uno (los cursos se nombran A, B, C…).
2. **Estudiantes:** lista por curso con código automático (001, 002…). Permite
   agregar a mano, **importar una planilla** (Excel/CSV) o generar una lista de prueba.
3. **Exámenes:** crea la **clave** de respuestas y, opcional, el **PDF** de la hoja.
4. **Calificar:** carga una o varias fotos → las **digitaliza** (alinea) →
   las **lee y califica** → guarda la imagen marcada y las notas.
5. **Registro de notas:** genera el **Excel** cruzando código → estudiante,
   con nota, promedio y "No presentó" para los ausentes.
6. **Corregir código:** si una hoja queda con el código dudoso, se corrige a mano
   antes de generar el registro.

---

## Requisitos

- **Python 3.11, 3.12 o 3.13** (recomendado el de **Anaconda**). No usar 3.14.
- Librerías:
  ```
  pip install kivy opencv-python numpy openpyxl reportlab
  ```
  (`reportlab` solo hace falta para generar el PDF de la hoja.)

---

## Archivos del proyecto

La app necesita estos archivos **en la misma carpeta**:

| Archivo | Para qué |
|---|---|
| `main.py` | La aplicación (interfaz y pantallas). |
| `gestor_salones.py` | Crea las carpetas Profesor/Grado/Curso. |
| `lector_omr.py` | Motor OMR: lee marcas, alinea, lee burbujas, calcula nota. |
| `digitalizador.py` | Alinea las fotos crudas antes de leerlas. |
| `generador_pdf.py` | Genera el PDF de la hoja de respuestas. |
| `registro_notas.py` | Arma el Excel cruzando código → estudiante. |
| `logo.png` *(opcional)* | Escudo que aparece en el PDF. |

---

## Cómo ejecutarla

1. Abre una terminal (en Windows, **Anaconda Prompt**) en la carpeta del proyecto.
2. Ejecuta:
   ```
   python main.py
   ```
   En Windows, para asegurar el Python correcto:
   ```
   C:\Users\USUARIO\anaconda3\python.exe main.py
   ```
3. La primera vez pide la configuración inicial; luego abre directo en el menú.

---

## Cómo se usa (flujo típico)

1. **Estudiantes** → importa o crea la lista del curso (cada alumno recibe un código).
2. **Exámenes** → crea el examen con su clave (y genera el PDF para imprimir).
3. Reparte las hojas; cada alumno rellena **su código** y sus respuestas.
4. Toma una foto de cada hoja.
5. **Calificar** → elige el examen → carga las fotos → revisa los resultados
   (corrige el código si alguno salió dudoso).
6. **Registro de notas** → genera y abre el Excel del curso.

> **Importante:** el código que el alumno rellena en la hoja debe coincidir con su
> código en la lista. Si no coincide, esa hoja aparece en la pestaña **"Por revisar"**
> del Excel y el alumno figura como "No presentó". Usa **Corregir código** para
> arreglarlo.

---

## Dónde quedan los datos

Todo se guarda dentro de la carpeta `profesores/`:

```
profesores/<Profesor>/<Grado>/<Curso>/
    estudiantes/           → lista_estudiantes.xlsx
    examenes_claves/       → respuestas_<examen>.json (las claves)
    hojas_pdf/             → <examen>_hoja.pdf
    examenes_crudos/       → fotos tal como salen del celular
    examenes_procesados/   → fotos ya alineadas (digitalizadas)
    resultados/            → imágenes marcadas + notas_<examen>.json
    resultados_excel/      → registro_<examen>.xlsx
```

---

## Escala de notas

Lineal de **0 a 10**: `nota = 10 × (aciertos / total)`, truncada a un decimal
(sin redondear hacia arriba) y con **piso de 1.0** (ninguna nota baja de 1).
Aprueba con **6.0**.

---

## Próximos pasos

- Tomar la foto con la **cámara** y mostrarla en pantalla (etapa Android).
- Empaquetar como **APK** de Android con Buildozer.
- Exportar/compartir resultados (p. ej. a Drive).
