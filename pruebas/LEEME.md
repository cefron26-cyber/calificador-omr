# Hojas de prueba — media hoja, 20 preguntas

20 hojas ya rellenas con situaciones distintas, para comprobar que la app
califica y avisa lo que debe. Todo lo de esta tabla se comprobó pasando las
fotos por el lector y por el flujo de la app (Calificar → galería → Confirmar).

## Qué hay en esta carpeta

| Archivo | Para qué |
|---|---|
| `hojas_para_imprimir.pdf` | 10 páginas carta = 20 medias hojas ya rellenas. Imprímelas, recórtalas y fotografíalas con el celular. |
| `fotos/` | Las mismas 20 hojas ya "fotografiadas" (sobre una mesa, con perspectiva). Se cargan con **Desde la galería**, sin imprimir nada. Se crean con `python pruebas/generar_pruebas.py` (no están en GitHub). |
| `lista_estudiantes_prueba.xlsx` | Lista del curso de prueba (16 alumnos, códigos 001 a 016). |
| `resultado_esperado/` | Cómo debe verse cada hoja ya calificada (con el panel de nota y alertas). |
| `resultados_esperados.xlsx` | La misma tabla de abajo, en Excel. |
| `generar_pruebas.py`, `verificar_pruebas.py` | Vuelven a crear las hojas y a comprobar los resultados (solo PC). |
| `verificar_hoja_mayor.py` | Comprueba el caso "examen de 25 en hoja de 30" en media hoja y hoja completa: las preguntas 26 a 30 no cuentan y se avisa si están marcadas (solo PC). Deja las hojas marcadas en `hoja_mayor/`. |

> Esta carpeta **no** entra en el APK (está excluida en `buildozer.spec`). No hace falta subirla a GitHub.

## Cómo hacer la prueba

1. En **Inicio**, agrega un curso de prueba (por ejemplo, grado 99, curso A) y entra.
2. **Estudiantes → Importar planilla** → elige `lista_estudiantes_prueba.xlsx` (16 alumnos).
3. **Exámenes → nuevo**: nombre `Prueba`, **20 preguntas**, formato **media hoja**, con esta clave:

   | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 |
   |---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
   | A | C | B | D | B | A | D | C | A | B | C | D | D | C | B | A | B | D | A | C |

4. **Calificar → Desde la galería**: elige **todas las fotos menos la 15**.
   - Resumen esperado: **19 hojas · 15 bien · 3 por revisar · 1 sin leer**.
   - Toca **Revisar y confirmar**. La galería muestra primero la 19 (sin leer), luego 12, 13 y 14 (por revisar) y después las demás por código.
   - Toca **Confirmar y guardar (18)**.
5. Ahora carga **solo la foto 15** (otra hoja del alumno 001). La galería dice
   **"Reemplaza la hoja que ya tenía guardada"**. Al confirmar, el 001 queda con **6.5** (antes 10.0).

## Resultados esperados

Nota = 10 × aciertos / 20, truncada a un decimal, mínimo 1.0. Aprueba con 6.0.
"Alertas" es lo que sale en el panel de abajo de la hoja marcada; "En la app"
es lo que dice la tarjeta de la galería y la fila de la lista.

| N° | Situación | Código | Aciertos | Nota | Alertas en la hoja marcada | En la app |
|---|---|---|---|---|---|---|
| 01 | Todas correctas | 001 | 20/20 | **10.0** | — | Ana María Pérez |
| 02 | 15 correctas y 5 incorrectas | 002 | 15/20 | **7.5** | — | Bruno Díaz Ríos |
| 03 | Justo en el límite | 003 | 12/20 | **6.0** aprueba | — | Carla Núñez Soto |
| 04 | Reprueba por poco | 004 | 11/20 | **5.5** reprueba | — | Daniel Ortiz Vega |
| 05 | Solo 7 correctas | 005 | 7/20 | **3.5** | — | Elena Ruiz Mora |
| 06 | Todas incorrectas | 006 | 0/20 | **1.0** (piso) | — | Felipe Gómez Lara |
| 07 | En blanco la 17 a la 20 | 007 | 16/20 | **8.0** | Sin resp: 17, 18, 19, 20 | Gabriela Peña Cruz |
| 08 | Doble marca en 3 y 9 | 008 | 18/20 | **9.0** | Doble marca: 3, 9 | Héctor Mejía Rojas |
| 09 | Relleno muy claro en 2, 5, 8, 11, 14 | 009 | 20/20 | **10.0** | Marca tenue (contada, verificar): 2, 5, 8, 11, 14 | Isabel Castro León |
| 10 | Equis (X) en 4, 12 y 18 | 010 | 20/20 | **10.0** | — (ver nota ⚠️) | Julián Herrera Paz |
| 11 | Medio relleno en 6 y 15; dos burbujas a medias en 10 y 20 | 011 | 18/20 | **9.0** | REVISAR: preg. 10, 20 - marca debil | Karen Salazar Gil |
| 12 | **No rellenó el código** | ??? | 14/20 | **7.0** | — | ámbar: "No se lee bien el código: corrígelo" |
| 13 | Código con doble marca en el último dígito (0 y 4) | 00? | 16/20 | **8.0** | — | ámbar: "No se lee bien el código: corrígelo" |
| 14 | Código que no está en la lista | 099 | 10/20 | **5.0** | — | ámbar: "No está en la lista del curso: revísalo" |
| 15 | Segunda hoja del alumno 001 | 001 | 13/20 | **6.5** | — | ámbar: "Reemplaza la hoja que ya tenía guardada" |
| 16 | Foto de cabeza (180°) | 012 | 17/20 | **8.5** | — | Luis Fernando Arias |
| 17 | Foto de lado (90°) | 013 | 19/20 | **9.5** | — | Mariana Torres Vélez |
| 18 | Sombra fuerte y foto inclinada | 014 | 15/20 | **7.5** | — | Nicolás Restrepo Cano |
| 19 | Esquina rota: falta una marca negra | — | — | **error** | — | rojo: "No pudimos leerla · No se vieron las 4 marcas negras…" (no se guarda) |
| 20 | Hoja en blanco (solo el código) | 016 | 0/20 | **1.0** | Sin resp: 1 a 20 | Pablo Andrés Duque |

Para probar la corrección de códigos: en la 12 pon **015** y en la 13 pon **004**.
La 13 tiene el mismo código que la hoja 04, así que la app pregunta si la
reemplaza (si ya estaba guardada) o la galería avisa que la reemplazará.

### ⚠️ Hallazgo: las equis cuentan como respuesta

En la hoja 10, una X de lapicero llena alrededor del **50 %** de la burbuja y el lector
cuenta como marcada cualquier burbuja de más del **45 %**. Por eso hoy la X
**se cuenta como respuesta y la app no avisa**. Con una X muy fina el relleno
queda en 46 %, justo en el límite: en la vida real a veces contará y a veces no.
Se puede mejorar el lector para que una X salga como "REVISAR".

## Si imprimes las hojas

- Las hojas 16, 17 y 18 son normales en papel: la situación la creas tú al
  fotografiar (de cabeza, de lado, con sombra e inclinada).
- En la hoja 19 la esquina inferior derecha sale "arrancada" (en blanco).
- El relleno muy claro (hoja 09) depende de la impresora: si imprime más oscuro,
  esas marcas pueden contarse sin la alerta de "Marca tenue".
