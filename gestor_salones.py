import os
import json
from pathlib import Path

# =============================================================================
# CONFIGURACIÓN DE RUTAS BASE
# =============================================================================
# Carpeta raíz que almacenará toda la información jerárquica
BASE_DIR = Path("profesores")

def inicializar_sistema():
    """Garantiza la existencia de la carpeta raíz de profesores."""
    if not BASE_DIR.exists():
        BASE_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# FUNCIONES DE GESTIÓN DE DIRECTORIOS (CREACIÓN)
# =============================================================================

def crear_profesor(nombre_completo: str) -> Path:
    """Crea la carpeta para un nuevo profesor."""
    # Reemplazamos espacios por guiones bajos para evitar problemas en consola
    nombre_carpeta = nombre_completo.strip().replace(" ", "_")
    ruta_profesor = BASE_DIR / nombre_carpeta
    ruta_profesor.mkdir(parents=True, exist_ok=True)
    return ruta_profesor

def crear_grado(ruta_profesor: Path, grado: str) -> Path:
    """Crea la carpeta de un grado (ej. '11') dentro de un profesor."""
    ruta_grado = ruta_profesor / grado.strip()
    ruta_grado.mkdir(parents=True, exist_ok=True)
    return ruta_grado

def crear_curso(ruta_grado: Path, curso: str) -> Path:
    """
    Crea la carpeta de un curso (ej. 'A') dentro de un grado.
    Además, crea subcarpetas estándar para organizar exámenes y listas.
    """
    ruta_curso = ruta_grado / curso.strip().upper()
    ruta_curso.mkdir(parents=True, exist_ok=True)
    
    # Subcarpetas dentro de cada curso (nombres consistentes con el resto del flujo OMR)
    (ruta_curso / "estudiantes").mkdir(exist_ok=True)           # Listas de alumnos (Excel/CSV)
    (ruta_curso / "examenes_claves").mkdir(exist_ok=True)       # Claves JSON      (generador_pdf.py)
    (ruta_curso / "hojas_pdf").mkdir(exist_ok=True)             # PDFs a imprimir  (generador_pdf.py)
    (ruta_curso / "examenes_crudos").mkdir(exist_ok=True)       # Fotos sin alinear(entrada digitalizador.py)
    (ruta_curso / "examenes_procesados").mkdir(exist_ok=True)   # Fotos alineadas  (digitalizador.py -> lector_omr.py)
    (ruta_curso / "resultados").mkdir(exist_ok=True)            # Calificados      (lector_omr.py)
    (ruta_curso / "resultados_excel").mkdir(exist_ok=True)      # Registro de notas(registro_notas.py)
    
    return ruta_curso

# =============================================================================
# FUNCIONES INTERACTIVAS DE SELECCIÓN (EL FLUJO QUE BUSCAS)
# =============================================================================

def listar_directorios(ruta: Path) -> list[str]:
    """Devuelve los nombres de las carpetas dentro de una ruta dada."""
    if not ruta.exists():
        return []
    return sorted([d.name for d in ruta.iterdir() if d.is_dir()])

def menu_seleccion_paso_a_paso() -> tuple[Path, str, str, str, str]:
    """
    Flujo interactivo por consola para seleccionar:
    Profesor -> Grado -> Salón -> Examen
    """
    print("\n" + "="*50)
    print("      ASISTENTE DE SELECCIÓN DE SALÓN Y EXAMEN")
    print("="*50)

    # 1. SELECCIONAR O CREAR PROFESOR
    profesores = listar_directorios(BASE_DIR)
    
    print("\n[ Paso 1: Seleccione su perfil de Profesor ]")
    if profesores:
        for idx, prof in enumerate(profesores, 1):
            print(f"  {idx}. {prof.replace('_', ' ')}")
        print(f"  {len(profesores) + 1}. [Registrar Nuevo Profesor]")
        
        opcion = int(input("\n👉 Seleccione una opción: ").strip())
        if opcion == len(profesores) + 1:
            nombre = input("Escriba su Nombre Completo: ")
            ruta_prof = crear_profesor(nombre)
        else:
            ruta_prof = BASE_DIR / profesores[opcion - 1]
    else:
        print("No hay profesores registrados.")
        nombre = input("Escriba su Nombre Completo para registrarse: ")
        ruta_prof = crear_profesor(nombre)

    nombre_profesor = ruta_prof.name.replace("_", " ")

    # 2. SELECCIONAR O CREAR GRADO
    grados = listar_directorios(ruta_prof)
    print(f"\n[ Paso 2: Grados asociados a {nombre_profesor} ]")
    
    if grados:
        for idx, grd in enumerate(grados, 1):
            print(f"  {idx}. Grado {grd}")
        print(f"  {len(grados) + 1}. [Registrar Nuevo Grado]")
        
        opcion = int(input("\n👉 Seleccione el Grado: ").strip())
        if opcion == len(grados) + 1:
            grado_sel = input("Ingrese el número del Grado (Ej: 11): ").strip()
            ruta_grd = crear_grado(ruta_prof, grado_sel)
        else:
            grado_sel = grados[opcion - 1]
            ruta_grd = ruta_prof / grado_sel
    else:
        print("No tienes grados registrados.")
        grado_sel = input("Ingrese el número de su Grado (Ej: 11): ").strip()
        ruta_grd = crear_grado(ruta_prof, grado_sel)

    # 3. SELECCIONAR O CREAR CURSO / SALÓN
    cursos = listar_directorios(ruta_grd)
    print(f"\n[ Paso 3: Salones/Cursos de Grado {grado_sel} ]")
    
    if cursos:
        for idx, cur in enumerate(cursos, 1):
            print(f"  {idx}. Curso {cur}")
        print(f"  {len(cursos) + 1}. [Registrar Nuevo Curso/Salón]")
        
        opcion = int(input("\n👉 Seleccione el Curso: ").strip())
        if opcion == len(cursos) + 1:
            curso_sel = input("Ingrese la letra del Curso/Salón (Ej: A): ").strip().upper()
            ruta_cur = crear_curso(ruta_grd, curso_sel)
        else:
            curso_sel = cursos[opcion - 1]
            ruta_cur = ruta_grd / curso_sel
    else:
        print("No hay cursos registrados en este grado.")
        curso_sel = input("Ingrese la letra del Curso/Salón (Ej: A): ").strip().upper()
        ruta_cur = crear_curso(ruta_grd, curso_sel)

    # 4. SELECCIONAR O CREAR EXAMEN
    # Los exámenes correspondientes a este salón vivirán en 'examenes_claves'
    ruta_claves = ruta_cur / "examenes_claves"
    examenes = sorted([f.stem for f in ruta_claves.glob("*.json")])
    
    print(f"\n[ Paso 4: ¿Qué examen de la lista de {grado_sel}°{curso_sel} va a calificar? ]")
    
    if examenes:
        for idx, exm in enumerate(examenes, 1):
            print(f"  {idx}. {exm}")
        print(f"  {len(examenes) + 1}. [Registrar Nueva Clave de Examen]")
        
        opcion = int(input("\n👉 Seleccione el examen: ").strip())
        if opcion == len(examenes) + 1:
            examen_sel = input("Nombre del examen (Ej: simulacro_ingles): ").strip().lower().replace(" ", "_")
            crear_plantilla_examen_vacio(ruta_claves / f"respuestas_{examen_sel}.json", examen_sel)
        else:
            examen_sel = examenes[opcion - 1]
    else:
        print("No existen claves de exámenes registradas para este salón.")
        examen_sel = input("Ingrese el nombre del nuevo examen (Ej: simulacro_ingles): ").strip().lower().replace(" ", "_")
        crear_plantilla_examen_vacio(ruta_claves / f"respuestas_{examen_sel}.json", examen_sel)

    print("\n" + "="*50)
    print("🎯 CONFIGURACIÓN ESTABLECIDA CON ÉXITO")
    print("="*50)
    print(f"👤 Profesor:  {nombre_profesor}")
    print(f"🏫 Curso:     {grado_sel}° {curso_sel}")
    print(f"📝 Examen:    {examen_sel}")
    print(f"📁 Ruta de trabajo del curso: {ruta_cur}")
    print("="*50 + "\n")
    
    return ruta_cur, nombre_profesor, grado_sel, curso_sel, examen_sel

def crear_plantilla_examen_vacio(ruta_archivo: Path, nombre_examen: str):
    """Crea una plantilla JSON inicial para el examen seleccionado."""
    plantilla = {
        "examen": nombre_examen,
        "total_preguntas": 15,
        "clave_correctas": ["A"] * 15  # Lista por defecto modificable
    }
    with open(ruta_archivo, 'w', encoding='utf-8') as f:
        json.dump(plantilla, f, indent=4, ensure_ascii=False)
    print(f"✔️ Archivo de clave inicial creado en: {ruta_archivo.name}")

# =============================================================================
# EJECUCIÓN PRINCIPAL (PRUEBA LOCAL)
# =============================================================================
if __name__ == "__main__":
    inicializar_sistema()
    
    # Iniciamos el asistente interactivo
    ruta_trabajo, prof, grado, curso, examen = menu_seleccion_paso_a_paso()
    
    # Aquí puedes ver cómo las carpetas se crearon físicamente en tu explorador
    print("Las carpetas de trabajo ya están listas en tu disco duro.")