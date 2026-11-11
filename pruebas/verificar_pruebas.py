#!/usr/bin/env python3
"""
verificar_pruebas.py — Califica las 20 fotos de prueba con el lector de la app
y escribe lo que la app debe mostrar en cada una:
  • resultado_esperado/NN_*.jpg   la hoja marcada, igual que en la app
  • resultados_esperados.xlsx     nota, alertas y mensajes por hoja

Antes: python pruebas/generar_pruebas.py      Luego: python pruebas/verificar_pruebas.py
"""
from __future__ import annotations

import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI))
import lector_omr as L              # noqa: E402
import generar_pruebas as GP        # noqa: E402

CODIGOS_LISTA = {f"{i:03d}" for i in range(1, len(GP.NOMBRES) + 1)}


def diseno(c):
    """Lo que se buscó con la hoja: aciertos y alertas según cómo se rellenó."""
    aciertos, blanco, doble, dudosas, tenues = 0, [], [], [], []
    for q, v in c["resp"].items():
        if v is None:
            blanco.append(q)
        elif isinstance(v, str):
            aciertos += v == GP.CLAVE[q - 1]
        elif v[0] == "doble":
            doble.append(q)
        elif v[0] == "dos_medios":
            dudosas.append(q)
        elif v[0] in ("tenue", "medio", "x"):
            # Una X de lapicero llena ~50 % de la burbuja y hoy el lector la
            # cuenta como respuesta, sin avisar (el mínimo es 45 %)
            aciertos += v[1] == GP.CLAVE[q - 1]
            if v[0] == "tenue":
                tenues.append(q)
    cod = c["codigo"]
    codigo = cod if isinstance(cod, str) else ("???" if cod is None else cod[1] + "?")
    return dict(codigo=codigo, aciertos=aciertos, blanco=sorted(blanco), doble=sorted(doble),
                dudosas=sorted(dudosas), tenues=sorted(tenues), error=c["esquina_rota"])


def leer(ruta):
    clave = {i + 1: x for i, x in enumerate(GP.CLAVE)}
    try:
        img = L.cargar_imagen(ruta)
        recta, scale, r = L.leer_foto(img, GP.N_PREG, "media_carta")
    except ValueError as e:
        return dict(error=str(e)), None
    aciertos = sum(1 for p, x in r.respuestas.items() if x is not None and x == clave.get(p))
    anotada = L.dibujar_anotaciones(recta, r, clave, scale, "Prueba", "media_carta")
    return dict(codigo=r.codigo_estudiante, aciertos=aciertos, blanco=sorted(r.en_blanco),
                doble=sorted(r.doble_marca), dudosas=sorted(r.dudosas),
                tenues=sorted(r.tenues), error=False), anotada


def lista_nums(v):
    return ", ".join(str(x) for x in v)


def mensaje_app(n, res):
    """Qué muestra la app en la galería / en la lista para esta hoja."""
    if res.get("error"):
        return "No pudimos leerla: " + res["error"] + " (no se guarda)"
    cod = str(res["codigo"])
    if not cod.isdigit():
        return f"Código {cod}: No se lee bien el código: corrígelo"
    if cod not in CODIGOS_LISTA:
        return f"Código {cod}: No está en la lista del curso: revísalo"
    if n == 15:
        return ("Código 001: Reemplaza la hoja que ya tenía guardada "
                "(si la hoja 01 ya se confirmó antes)")
    return f"Código {cod}  ·  {GP.NOMBRES[int(cod) - 1]}"


def alertas(res):
    if res.get("error"):
        return ""
    partes = []
    if res["blanco"]:
        partes.append("Sin resp: " + lista_nums(res["blanco"]))
    if res["doble"]:
        partes.append("Doble marca: " + lista_nums(res["doble"]))
    if res["dudosas"]:
        partes.append(f"REVISAR: preg. {lista_nums(res['dudosas'])} - marca debil, verificar")
    if res["tenues"]:
        partes.append("Marca tenue (contada, verificar): " + lista_nums(res["tenues"]))
    return "  |  ".join(partes) or "Ninguna"


def main():
    salida = AQUI / "resultado_esperado"
    salida.mkdir(exist_ok=True)
    filas, diferencias = [], []
    for c in GP.CASOS:
        foto = AQUI / "fotos" / f"{GP.nombre_archivo(c)}.jpg"
        res, anotada = leer(foto)
        esp = diseno(c)
        if anotada is not None:
            L.guardar_imagen(salida / f"{GP.nombre_archivo(c)}_calificada.jpg", anotada)
        comparar = ("codigo", "aciertos", "blanco", "doble", "dudosas", "tenues")
        if esp["error"] != bool(res.get("error")) or (
                not esp["error"] and any(esp[k] != res[k] for k in comparar)):
            diferencias.append((c["n"], esp, res))
        nota = None if res.get("error") else L._calcular_nota(res["aciertos"], GP.N_PREG)
        filas.append(dict(
            n=c["n"], archivo=foto.name, situacion=c["titulo"],
            codigo="—" if res.get("error") else res["codigo"],
            aciertos="—" if res.get("error") else f"{res['aciertos']} de {GP.N_PREG}",
            nota="—" if nota is None else f"{nota:.1f}",
            estado=("ERROR" if nota is None else "APROBADO" if nota >= L.NOTA_APROBACION
                    else "REPROBADO"),
            alertas=alertas(res), app=mensaje_app(c["n"], res)))
        print(f"{c['n']:02d}  {filas[-1]['codigo']:>4}  {filas[-1]['aciertos']:>9}  "
              f"{filas[-1]['nota']:>4}  {filas[-1]['alertas']}")
    escribir_excel(filas, AQUI / "resultados_esperados.xlsx")
    if diferencias:
        print("\nDIFERENCIAS ENTRE LO DISEÑADO Y LO LEÍDO:")
        for n, esp, res in diferencias:
            print(f"  hoja {n:02d}\n    diseño: {esp}\n    leído:  {res}")
    else:
        print("\nLas 20 hojas se leen exactamente como se diseñaron.")
    return filas, diferencias


def escribir_excel(filas, ruta):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Resultados esperados"
    ws.append(["Clave del examen (20 preguntas, media hoja):  " + "  ".join(
        f"{i}-{x}" for i, x in enumerate(GP.CLAVE, start=1))])
    ws.merge_cells("A1:I1")
    ws["A1"].font = Font(bold=True)
    enc = ["N°", "Foto", "Situación", "Código leído", "Aciertos", "Nota", "Estado",
           "Alertas en la hoja marcada", "Lo que muestra la app"]
    ws.append(enc)
    azul = PatternFill("solid", start_color="13294B")
    for col in range(1, len(enc) + 1):
        cel = ws.cell(row=2, column=col)
        cel.font, cel.fill = Font(bold=True, color="FFFFFF"), azul
    colores = {"APROBADO": "E2F0D9", "REPROBADO": "FBE4E4", "ERROR": "FFF2CC"}
    for f in filas:
        ws.append([f["n"], f["archivo"], f["situacion"], f["codigo"], f["aciertos"], f["nota"],
                   f["estado"], f["alertas"], f["app"]])
        ws.cell(row=ws.max_row, column=7).fill = PatternFill("solid", start_color=colores[f["estado"]])
    for col, ancho in zip("ABCDEFGHI", (5, 46, 44, 12, 10, 7, 12, 52, 62)):
        ws.column_dimensions[col].width = ancho
    for fila in ws.iter_rows(min_row=3):
        for cel in fila:
            cel.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A3"
    wb.save(ruta)


if __name__ == "__main__":
    main()
