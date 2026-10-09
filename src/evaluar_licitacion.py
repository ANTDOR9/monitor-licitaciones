"""
Motor de evaluación: ¿qué marcas podían cumplir esta licitación?

Cierra el circuito del proyecto. El extractor saca de las bases lo que la
entidad EXIGIÓ; acá eso se compara, campo por campo, contra las fichas de
BTOUCH y de la competencia. De ahí salen las dos cosas que el estudio necesita
y que ningún documento publicado da directamente:

  1. Si BTOUCH podía presentarse a ese proceso, y con qué modelo.
  2. Qué marcas quedaban fuera por las especificaciones pedidas — que es la
     evidencia del argumento de que un requerimiento está escrito a la medida
     de una marca.

La marca efectivamente adjudicada no se publica (ver sección 11 de
PROJECT_CONTEXT.md): ni el acta de buena pro ni el cuadro de evaluación la
nombran. Esta inferencia es lo que queda, y por eso importa que sea honesta.

## Tres trampas que este motor evita a propósito

**Comparar lo que no se puede comparar.** Si la ficha no declara un parámetro,
el veredicto es SIN DATO, nunca "cumple". Una ficha de catálogo con 7 campos
declarados acumularía cero incumplimientos y parecería la mejor del grupo.

**Castigar a la marca mejor documentada.** BTOUCH declara 21 parámetros y un
catálogo de revendedor declara 7. Si se cuentan incumplimientos en bruto, el
que publica más información pierde. Por eso cada ficha se puntúa solo sobre
los campos COMPARABLES —los que están en el requerimiento y en la ficha— y se
informa cuántos son. Con pocos campos comparables no se emite ranking.

**Forzar el color.** Las reglas comerciales de Brighter (prompt_brighter.md)
distinguen brechas gestionables de especificaciones técnicas duras. Una
licencia de Office o una garantía negociable no son un NO CUMPLE; unas
dimensiones físicas o una certificación de laboratorio no se marcan en verde
sin evidencia. Cada campo lleva su categoría y el motor la respeta en las dos
direcciones.

Uso:
    python src/evaluar_licitacion.py --json resultado.json --expediente 7
    python src/evaluar_licitacion.py --json resultado.json --todos
    python src/evaluar_licitacion.py --demo
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fichas import Ficha, TODAS, por_tamano                      # noqa: E402

CUMPLE, OBSERVADO, NO_CUMPLE, SIN_DATO, MANUAL = (
    "CUMPLE", "OBSERVADO", "NO CUMPLE", "SIN DATO", "REVISIÓN MANUAL")

#: Para el informe: verde / amarillo / rojo / gris, como pide la leyenda de
#: colores de las comparativas de Brighter.
COLOR = {CUMPLE: "verde", OBSERVADO: "amarillo", NO_CUMPLE: "rojo",
         SIN_DATO: "gris", MANUAL: "amarillo"}


@dataclass
class Criterio:
    etiqueta: str
    tipo: str
    #: "A" = brecha gestionable por vía comercial/documental (nunca rojo
    #: automático). "B" = especificación técnica dura (no se fuerza a verde).
    categoria: str
    campo_ficha: str | None = None
    #: Rango plausible del valor EXIGIDO. Fuera de él, el dato se trata como
    #: mal extraído en vez de compararlo.
    plausible: tuple[float, float] | None = None
    nota: str = ""


#: Qué campo del requerimiento se compara contra qué campo de la ficha, cómo, y
#: en qué categoría cae según las reglas de Brighter.
CRITERIOS: dict[str, Criterio] = {
    "tamano_pulgadas":    Criterio("Tamaño del panel", "igual_num", "B",
                                   plausible=(32, 120)),
    "resolucion":         Criterio("Resolución", "resolucion", "B"),
    "brillo_cdm2":        Criterio("Brillo", "minimo", "B", plausible=(150, 1500)),
    "contraste":          Criterio("Contraste", "ratio_minimo", "B"),
    "angulo_vision":      Criterio("Ángulo de visión", "grados_minimo", "B"),
    "tiempo_respuesta_ms": Criterio("Tiempo de respuesta", "respuesta", "B",
                                     plausible=(1, 60),
                                     nota="Las bases no aclaran si piden respuesta "
                                          "de panel o de táctil, y la diferencia "
                                          "invierte el veredicto."),
    "tecnologia_panel":   Criterio("Tecnología del panel", "manual", "B",
                                   nota="El requerimiento suele admitir varias "
                                        "tecnologías en una sola frase; se revisa a mano."),
    "puntos_tactiles":    Criterio("Puntos táctiles", "minimo", "B", plausible=(2, 100)),
    "sistema_operativo":  Criterio("Sistema operativo", "android_minimo", "B"),
    "certificacion_edla": Criterio("Certificación Google EDLA", "booleano", "B"),
    "cpu":                Criterio("CPU del sistema", "manual", "B",
                                   nota="Texto libre en el requerimiento; se revisa a mano."),
    "ram_gb":             Criterio("Memoria RAM", "minimo", "B", plausible=(1, 128)),
    "almacenamiento_gb":  Criterio("Almacenamiento", "minimo", "B", plausible=(8, 4096)),
    "ops_requerido":      Criterio("Ranura / módulo OPS", "booleano", "B",
                                   campo_ficha="ops_disponible"),
    "ops_procesador":     Criterio("Procesador del OPS", "gen_intel", "B"),
    "altavoces_w":        Criterio("Audio (potencia total)", "audio", "B",
                                   campo_ficha="audio_w_total",
                                   nota="Se cuenta la potencia TOTAL del sistema "
                                        "(parlantes + subwoofer), criterio ya "
                                        "validado con Brighter."),
    "vida_util_horas":    Criterio("Vida útil", "minimo", "B",
                                   plausible=(10_000, 200_000)),
    "garantia_meses":     Criterio("Garantía", "minimo", "A",
                                   plausible=(6, 120),
                                   nota="BTOUCH maneja la garantía de forma "
                                        "negociable; una brecha acá es gestionable, "
                                        "no un incumplimiento."),
}

#: Requisitos que aparecen como texto libre y que las reglas de Brighter marcan
#: explícitamente para no resolver de forma automática. El extractor no los
#: captura como campo, así que el motor los recuerda al pie del informe en
#: lugar de dar un veredicto que no puede sostener.
PENDIENTES_MANUALES = [
    ("Dureza del vidrio (7H vs. Mohs 7)",
     "7H es escala de lápiz (ASTM D3363) y Mohs 7 es escala mineral; no hay "
     "conversión oficial. Queda en amarillo hasta tener equivalencia "
     "certificada o ensayo directo."),
    ("Rechazo de palma / reconocimiento de gestos",
     "El táctil infrarrojo no distingue por hardware entre dedo, lápiz y palma. "
     "El rechazo de palma depende de un filtro por software y la ficha no lo "
     "acredita. Pedir confirmación escrita del fabricante."),
    ("Ofimática (MS Office) en el OPS",
     "No viene instalado por defecto. Si el proceso lo exige, Brighter cotiza "
     "licencias legales: gestionable, nunca rojo automático."),
    ("Software educativo / interactivo",
     "No está en la ficha de hardware, pero Brighter ofrece Brighter LMS, "
     "MozaBook, Wordwall, Google for Education y Microsoft Education en "
     "paquetes Clásico / Silver Dual / Gold / Platinum."),
    ("Cables, soportes y accesorios genéricos",
     "Si es componente genérico de mercado (UTP CAT 6A, soporte VESA, rack), "
     "Brighter lo agrega localmente. Revisar antes su catálogo de complementos "
     "(pedestales VESA hasta 1000×600 mm, tótems, paneles LED)."),
    ("Carta de garantía del fabricante",
     "Trámite documental, no riesgo de producto: CUMPLE gestionable."),
]


# --------------------------------------------------------------------------- #
# Parseo de valores
# --------------------------------------------------------------------------- #

def _num(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if not v:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(v).replace(" ", ""))
    return float(m.group(1).replace(",", ".")) if m else None


def _ratio(v) -> float | None:
    """'4000:1' -> 4000. Toma el primero, que es el contraste estático."""
    if not v:
        return None
    m = re.search(r"(\d[\d\s.,]*)\s*:\s*1", str(v))
    return float(re.sub(r"[^\d]", "", m.group(1))) if m else _num(v)


def _grados(v) -> float | None:
    if not v:
        return None
    nums = [float(x) for x in re.findall(r"(\d{2,3})\s*°", str(v))]
    return min(nums) if nums else _num(v)


def _android(v) -> float | None:
    if not v:
        return None
    m = re.search(r"android\s*(\d{1,2})", str(v), re.I)
    return float(m.group(1)) if m else None


def _pixeles(v) -> int | None:
    """'3840 x 2160 (4K UHD)' -> 8294400 px, para comparar sin depender del texto."""
    if not v:
        return None
    m = re.search(r"(\d{3,5})\s*[x×]\s*(\d{3,5})", str(v))
    if m:
        return int(m.group(1)) * int(m.group(2))
    if re.search(r"\b4k\b|uhd", str(v), re.I):
        return 3840 * 2160
    if re.search(r"\bfull\s*hd\b|1080p", str(v), re.I):
        return 1920 * 1080
    return None


def _audio_total(v) -> float | None:
    """
    Potencia total del sistema de audio.

    Los requerimientos escriben '2 x 15W', '15W x 2', '2 × 20 W + 20 W sub'.
    Se multiplica la cantidad por la potencia y se suman los sumandos, que es
    el criterio de potencia TOTAL que Brighter ya validó.
    """
    if isinstance(v, (int, float)):
        return float(v)
    if not v:
        return None
    texto = str(v).lower().replace("×", "x").replace(",", ".")

    # Si el texto ya declara un total, ése manda: sumar además los sumandos
    # contaría dos veces lo mismo ("2 x 20 W + subwoofer 20 W, total 60 W").
    m = re.search(r"total[^\d]{0,14}(\d+(?:\.\d+)?)\s*w", texto)
    if m:
        return float(m.group(1))

    total = 0.0
    visto = False

    def sumar_producto(m: re.Match) -> str:
        nonlocal total, visto
        total += float(m.group(1)) * float(m.group(2))
        visto = True
        return " + "          # se consume, para no volver a contarlo abajo

    for patron in (r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*w",
                   r"(\d+(?:\.\d+)?)\s*w\s*x\s*(\d+(?:\.\d+)?)"):
        texto = re.sub(patron, sumar_producto, texto)

    # Lo que queda son sumandos sueltos: "+ subwoofer 20 w".
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*w", texto):
        total += float(m.group(1))
        visto = True
    return total if visto else None


def _gen_intel(v) -> float | None:
    """
    Generación de un procesador Intel Core.

    'Intel Core i7 13th Generación en adelante' -> 13
    'Intel Core i7-1250U (12.ª gen.)'           -> 12

    La numeración cambió de convención: los de 4 cifras que empiezan en 1
    codifican la generación en los dos primeros dígitos (1250U = 12.ª), y los
    anteriores en el primero (8550U = 8.ª).
    """
    if not v:
        return None
    t = str(v).lower()
    # "13th gen", "12.ª gen.", "10ma generación": el ordinal entre el número y
    # la palabra cambia de forma en cada documento, así que se admite cualquier
    # sufijo corto de letras.
    for patron in (r"(\d{1,2})\s*(?:th|st|nd|rd)\s*gen",
                   r"(\d{1,2})\s*[a-zª.°]{0,4}\s*gener",
                   r"gener\w*\s*(\d{1,2})"):
        m = re.search(patron, t)
        if m:
            return float(m.group(1))
    m = re.search(r"i[3579][\s\-]*(\d{4,5})", t)
    if m:
        n = m.group(1)
        return float(n[:2]) if n.startswith("1") and len(n) == 4 else float(n[0])
    return None


# --------------------------------------------------------------------------- #
# Comparación
# --------------------------------------------------------------------------- #

@dataclass
class Veredicto:
    campo: str
    etiqueta: str
    exigido: str
    ofrecido: str
    resultado: str
    categoria: str
    nota: str = ""

    @property
    def color(self) -> str:
        return COLOR[self.resultado]


def _respuesta(exigido, panel, tactil) -> tuple[str, str]:
    """
    Tiempo de respuesta, que en las bases es una sola cifra ambigua.

    Un requisito de "≤ 6 ms" descarta a BTOUCH si se lee como respuesta del
    panel (8 ms) y lo aprueba con holgura si se lee como respuesta del táctil
    (≤ 2 ms). Marcar rojo sin saber cuál pidieron sería inventar el criterio
    que decide, así que cuando una lectura cumple y la otra no, queda en
    amarillo con el motivo escrito.
    """
    e = _num(exigido)
    if e is None:
        return MANUAL, "no se pudo interpretar el valor exigido"
    p, t = _num(panel), _num(tactil)
    if p is None and t is None:
        return SIN_DATO, ""
    cumple_panel = p is not None and p <= e
    cumple_tactil = t is not None and t <= e
    if cumple_panel:
        return CUMPLE, f"panel {p:g} ms"
    if cumple_tactil:
        panel_txt = f"{p:g} ms" if p is not None else "no declarada"
        return OBSERVADO, (f"cumple como respuesta táctil ({t:g} ms) pero no como "
                           f"respuesta de panel ({panel_txt}). Depende de cuál pidieron.")
    partes = [f"panel {p:g} ms" if p is not None else None,
              f"táctil {t:g} ms" if t is not None else None]
    return NO_CUMPLE, "ninguna lectura baja de " + f"{e:g} ms (" \
        + ", ".join(x for x in partes if x) + ")"


def _comparar(crit: Criterio, exigido, ofrecido) -> tuple[str, str]:
    """Devuelve (resultado, nota)."""
    tipo = crit.tipo

    if tipo == "manual":
        return MANUAL, crit.nota

    if tipo == "booleano":
        if exigido is False:
            return CUMPLE, "no exigido por las bases"
        if ofrecido is True:
            return CUMPLE, ""
        if ofrecido is False:
            return NO_CUMPLE, ""
        return SIN_DATO, ""

    conv = {"minimo": _num, "maximo": _num, "igual_num": _num,
            "ratio_minimo": _ratio, "grados_minimo": _grados,
            "android_minimo": _android, "resolucion": _pixeles,
            "audio": _audio_total, "gen_intel": _gen_intel}[tipo]
    e, o = conv(exigido), conv(ofrecido)
    if e is None:
        return MANUAL, "no se pudo interpretar el valor exigido"
    if o is None:
        return SIN_DATO, ""

    if tipo == "maximo":
        ok = o <= e
    elif tipo == "igual_num":
        ok = abs(o - e) < 0.5
    else:
        ok = o >= e
    return (CUMPLE if ok else NO_CUMPLE), ""


def evaluar(requerimiento: dict, ficha: Ficha) -> list[Veredicto]:
    """Compara un requerimiento contra una ficha, campo por campo."""
    salida: list[Veredicto] = []

    for campo, crit in CRITERIOS.items():
        exigido = requerimiento.get(campo)
        if exigido is None:
            continue                                   # no lo pidieron

        # Dato exigido fuera de rango plausible: casi seguro mal extraído.
        if crit.plausible and not isinstance(exigido, bool):
            n = _num(exigido)
            if n is not None and not (crit.plausible[0] <= n <= crit.plausible[1]):
                salida.append(Veredicto(
                    campo, crit.etiqueta, str(exigido), "—", MANUAL, crit.categoria,
                    f"valor exigido fuera del rango plausible "
                    f"{crit.plausible[0]:g}–{crit.plausible[1]:g}: revisar la extracción"))
                continue

        nombre_ficha = crit.campo_ficha or campo
        ofrecido = getattr(ficha, nombre_ficha, None)

        if crit.tipo == "respuesta":
            # Necesita las dos lecturas de la ficha, no una.
            resultado, nota = _respuesta(exigido, ficha.tiempo_respuesta_ms,
                                         ficha.tiempo_respuesta_tactil_ms)
            ofrecido = (f"panel {ficha.tiempo_respuesta_ms or '—'} ms / "
                        f"táctil {ficha.tiempo_respuesta_tactil_ms or '—'} ms")
        else:
            resultado, nota = _comparar(crit, exigido, ofrecido)

        # Regla de Brighter: una brecha de categoría A no va a rojo.
        if resultado == NO_CUMPLE and crit.categoria == "A":
            resultado = OBSERVADO
            nota = (crit.nota or "brecha gestionable por vía comercial").strip()
        elif resultado == SIN_DATO:
            # Sin dato en la ficha no hay nada que matizar: la nota del
            # criterio explica cómo se interpreta una comparación, y pegarla
            # acá hacía que EDUBOARD mostrara la advertencia sobre panel vs
            # táctil justo donde no declara ninguno de los dos.
            nota = nota or ("la ficha no lo declara, pero es gestionable"
                            if crit.categoria == "A" else "")
        elif not nota:
            nota = crit.nota

        salida.append(Veredicto(campo, crit.etiqueta, str(exigido),
                                "—" if ofrecido is None else str(ofrecido),
                                resultado, crit.categoria, nota))
    return salida


@dataclass
class Resumen:
    ficha: Ficha
    veredictos: list[Veredicto]

    @property
    def cuenta(self) -> dict[str, int]:
        c = {CUMPLE: 0, OBSERVADO: 0, NO_CUMPLE: 0, SIN_DATO: 0, MANUAL: 0}
        for v in self.veredictos:
            c[v.resultado] += 1
        return c

    @property
    def comparables(self) -> int:
        """Campos donde hubo dato en los dos lados. Lo demás no se midió."""
        return self.cuenta[CUMPLE] + self.cuenta[NO_CUMPLE] + self.cuenta[OBSERVADO]

    @property
    def medido(self) -> float:
        """Fracción de lo exigido que esta ficha permite verificar."""
        return self.comparables / len(self.veredictos) if self.veredictos else 0.0

    #: Umbral para emitir dictamen. Es relativo y no absoluto por una razón
    #: concreta: en la primera corrida de este motor EDUBOARD salió primero en
    #: "podían cumplir" con 4 campos verdes y 12 sin dato. Cuatro aciertos sobre
    #: dieciséis exigencias no es un buen producto, es un catálogo que no
    #: publica nada. Un mínimo absoluto bajo premia exactamente a la ficha menos
    #: informativa.
    MINIMO_MEDIDO = 0.60
    MINIMO_CAMPOS = 5

    @property
    def concluyente(self) -> bool:
        return self.comparables >= self.MINIMO_CAMPOS and self.medido >= self.MINIMO_MEDIDO

    @property
    def dictamen(self) -> str:
        c = self.cuenta
        if not self.concluyente:
            return (f"SIN MEDIR — la ficha solo permite verificar "
                    f"{self.comparables} de {len(self.veredictos)} exigencias "
                    f"({self.medido:.0%})")
        if c[NO_CUMPLE] == 0 and c[OBSERVADO] == 0:
            return "PODÍA CUMPLIR"
        if c[NO_CUMPLE] == 0:
            return "PODÍA CUMPLIR CON OBSERVACIONES"
        return f"QUEDABA FUERA ({c[NO_CUMPLE]} incumplimiento/s)"

    @property
    def bloqueantes(self) -> list[Veredicto]:
        return [v for v in self.veredictos if v.resultado == NO_CUMPLE]


def evaluar_todas(requerimiento: dict, fichas: list[Ficha] | None = None) -> list[Resumen]:
    cands = fichas if fichas is not None else por_tamano(requerimiento.get("tamano_pulgadas"))
    return [Resumen(f, evaluar(requerimiento, f)) for f in cands]


# --------------------------------------------------------------------------- #
# Informe
# --------------------------------------------------------------------------- #

def imprimir(requerimiento: dict, resumenes: list[Resumen], etiqueta: str = "") -> None:
    pedidos = {k: v for k, v in requerimiento.items() if v is not None and k in CRITERIOS}
    print("=" * 78)
    print(f"EVALUACIÓN{' · ' + etiqueta if etiqueta else ''}")
    print("=" * 78)
    print(f"Parámetros exigidos y extraídos: {len(pedidos)} de {len(CRITERIOS)}\n")
    for k, v in pedidos.items():
        print(f"   {CRITERIOS[k].etiqueta:<26} {str(v)[:46]}")

    # Las no concluyentes van al final: no compiten con las que sí se midieron.
    # Cobertura de tamaño. Es el dato que más veces explica el resultado y se
    # perdía entre los veredictos: en un proceso de 98" ningún competidor tiene
    # ficha de ese tamaño, así que "podían cumplir: ninguna" dice mucho menos
    # que "BTOUCH era el único que llegaba a ese tamaño".
    pedido = requerimiento.get("tamano_pulgadas")
    if pedido:
        rivales = {r.ficha.marca for r in resumenes
                   if r.ficha.marca != "BTOUCH" and r.ficha.tamano_pulgadas is not None}
        print(f"\nFichas de {pedido:.0f}\" disponibles: "
              + ", ".join(sorted({r.ficha.marca for r in resumenes
                                  if r.ficha.tamano_pulgadas is not None})))
        if not rivales:
            print(f"   Ninguna marca competidora tiene ficha de {pedido:.0f}\". "
                  f"En ese tamaño BTOUCH no tiene rival documentado,")
            print("   y lo único que puede dejarlo fuera es una cláusula del propio TDR.")

    for r in sorted(resumenes, key=lambda r: (not r.concluyente,
                                              r.cuenta[NO_CUMPLE], -r.comparables)):
        c = r.cuenta
        print("\n" + "-" * 78)
        print(f"{r.ficha.marca} · {r.ficha.modelo}")
        print(f"  {r.dictamen}")
        print(f"  verde {c[CUMPLE]} · amarillo {c[OBSERVADO] + c[MANUAL]} · "
              f"rojo {c[NO_CUMPLE]} · sin dato {c[SIN_DATO]}   "
              f"(comparables: {r.comparables})")
        for v in r.veredictos:
            if v.resultado == CUMPLE:
                continue
            print(f"    [{v.resultado:<16}] {v.etiqueta:<26} "
                  f"exige {v.exigido[:28]:<28} ofrece {v.ofrecido[:24]}")
            if v.nota:
                print(f"       {v.nota[:94]}")

    # ------------------------------------------------------------------ cierre
    utiles = [r for r in resumenes if r.concluyente]
    sin_medir = [r for r in resumenes if not r.concluyente]
    # Inicializadas antes de la bifurcación: sin esto, un expediente donde
    # ninguna ficha es concluyente llegaba al bloque de motivos con `fuera`
    # sin definir y cortaba el informe a mitad.
    podian: list[Resumen] = []
    fuera: list[Resumen] = []
    print("\n" + "=" * 78)
    if not utiles:
        print("NO SE PUEDE CONCLUIR NADA.")
        print("Ninguna ficha permite verificar al menos el "
              f"{Resumen.MINIMO_MEDIDO:.0%} de lo exigido.")
        print("Faltan datos de ficha, o la extracción del requerimiento quedó pobre.")
    else:
        podian = [r for r in utiles if not r.bloqueantes]
        fuera = [r for r in utiles if r.bloqueantes]
        print(f"Podían cumplir : {', '.join(f'{r.ficha.marca} {r.ficha.modelo}' for r in podian) or 'ninguna'}")
        print(f"Quedaban fuera : {', '.join(f'{r.ficha.marca} {r.ficha.modelo}' for r in fuera) or 'ninguna'}")
    if sin_medir:
        print(f"Sin medir      : "
              + ", ".join(f"{r.ficha.marca} ({r.medido:.0%})" for r in sin_medir))
        print("                 fichas que no publican lo suficiente. No entran al")
        print("                 ranking: 'cero incumplimientos' sobre tres campos")
        print("                 verificados no es cumplir, es no haberse medido.")
        if fuera:
            motivos: dict[str, int] = {}
            for r in fuera:
                for v in r.bloqueantes:
                    motivos[v.etiqueta] = motivos.get(v.etiqueta, 0) + 1
            print("\nParámetros que más dejan fuera:")
            for etq, n in sorted(motivos.items(), key=lambda kv: -kv[1]):
                print(f"   {etq:<28} descarta a {n} modelo(s)")

    print("\nRevisar a mano (las reglas de Brighter piden no resolverlos solos):")
    for titulo, detalle in PENDIENTES_MANUALES:
        print(f"   · {titulo}")
        print(f"     {detalle[:92]}")
    print("=" * 78)


def agregado(expedientes: list[dict]) -> None:
    """
    La tabla que el estudio necesita: sobre N requerimientos reales, con qué
    frecuencia cada marca podía presentarse y qué parámetros la dejan fuera.

    Un parámetro que descarta a BTOUCH en muchos procesos es un hallazgo
    comercial. Un parámetro que descarta a toda la competencia menos a una
    marca es el otro hallazgo: el indicio de un requerimiento escrito a medida.
    """
    from collections import Counter, defaultdict

    estado: dict[str, Counter] = defaultdict(Counter)
    motivos: dict[str, Counter] = defaultdict(Counter)
    evaluados = 0

    for d in expedientes:
        specs = d.get("specs") or {}
        resumenes = evaluar_todas(specs)
        if not any(r.concluyente for r in resumenes):
            continue
        evaluados += 1
        for r in resumenes:
            clave = f"{r.ficha.marca} {r.ficha.modelo}"
            if not r.concluyente:
                estado[clave]["sin medir"] += 1
                continue
            estado[clave]["podía" if not r.bloqueantes else "fuera"] += 1
            for v in r.bloqueantes:
                motivos[clave][v.etiqueta] += 1

    print("=" * 78)
    print(f"AGREGADO SOBRE {evaluados} REQUERIMIENTO(S) EVALUABLE(S)")
    print("=" * 78)
    if not evaluados:
        print("Ninguno tenía suficientes campos extraídos para evaluar.")
        print("El cuello de botella está en la extracción, no en la comparación.")
        return

    print(f"\n{'modelo':<30}{'podía':>8}{'fuera':>8}{'sin medir':>11}")
    print("-" * 57)
    for clave, c in sorted(estado.items(), key=lambda kv: -kv[1]["podía"]):
        print(f"{clave:<30}{c['podía']:>8}{c['fuera']:>8}{c['sin medir']:>11}")

    print("\nQué deja fuera a cada modelo:")
    for clave, c in sorted(motivos.items()):
        if not c:
            continue
        print(f"  {clave}")
        for etq, n in c.most_common():
            print(f"     {etq:<28} en {n} de {evaluados} proceso(s)")

    print("\n" + "=" * 78)
    print("Leer esta tabla con cuidado: 'fuera' solo cuenta lo que se pudo")
    print("verificar. Una marca con muchos 'sin medir' no es competitiva ni")
    print("incompetitiva — es desconocida, y eso también es un dato del mercado.")
    print("=" * 78)


DEMO = {
    "tamano_pulgadas": 86.0,
    "resolucion": "3840 x 2160 (4K UHD)",
    "brillo_cdm2": 400.0,
    "contraste": "4000:1",
    "angulo_vision": "178°",
    "tiempo_respuesta_ms": 8.0,
    "puntos_tactiles": 40,
    "sistema_operativo": "Android 13",
    "certificacion_edla": True,
    "ram_gb": 8.0,
    "almacenamiento_gb": 64.0,
    "ops_requerido": True,
    "ops_procesador": "Intel Core i7 13th Generación en adelante",
    "altavoces_w": "2 x 15W",
    "vida_util_horas": 50000.0,
    "garantia_meses": 36.0,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="salida del extractor (lista de expedientes)")
    ap.add_argument("--expediente", help="cuál evaluar")
    ap.add_argument("--todos", action="store_true",
                    help="evaluar todos los que tengan specs utilizables")
    ap.add_argument("--resumen", action="store_true",
                    help="tabla agregada sobre todos los expedientes")
    ap.add_argument("--demo", action="store_true",
                    help="correr con un requerimiento de ejemplo")
    args = ap.parse_args()

    if args.demo or not args.json:
        imprimir(DEMO, evaluar_todas(DEMO), "requerimiento de ejemplo (86\")")
        if not args.demo:
            print("\n(Sin --json se corre el ejemplo. Pasá la salida del extractor "
                  "para evaluar expedientes reales.)")
        return 0

    datos = json.loads(Path(args.json).read_text(encoding="utf-8"))
    conspecs = [d for d in datos if d.get("specs")]
    if not conspecs:
        print("Ese JSON no tiene ningún expediente con specs.", file=sys.stderr)
        return 1

    if args.resumen:
        agregado(conspecs)
        return 0

    if args.expediente:
        elegidos = [d for d in conspecs if str(d.get("expediente")) == str(args.expediente)]
        if not elegidos:
            print(f"No encontré el expediente {args.expediente}. "
                  f"Hay: {', '.join(str(d['expediente']) for d in conspecs)}", file=sys.stderr)
            return 1
    elif args.todos:
        elegidos = conspecs
    else:
        elegidos = [max(conspecs, key=lambda d: d.get("specs_cobertura", 0))]
        print(f"Sin --expediente: evalúo el de mayor cobertura "
              f"({elegidos[0]['expediente']}, {elegidos[0]['specs_cobertura']:.0%}).\n")

    for d in elegidos:
        etiqueta = f"expediente {d['expediente']}"
        if d.get("nomenclatura"):
            etiqueta += f" · {d['nomenclatura']}"
        imprimir(d["specs"], evaluar_todas(d["specs"]), etiqueta)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
