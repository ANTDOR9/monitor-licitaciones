"""
Fichas técnicas estructuradas: BTOUCH y marcas competidoras.

Los campos son los mismos que extrae `extractor.py` de las especificaciones de
una licitación, para que la comparación sea campo contra campo y no prosa
contra prosa.

Regla central de honestidad: **`None` significa "la ficha no lo declara", y no
se rellena nunca**. Una marca cuya ficha no declara brillo no "cumple" ni
"incumple" el brillo exigido: no se sabe. Esa distinción es la que decide si
una comparación sirve o es decorativa, porque un modelo con 15 campos sin dato
y cero incumplimientos parece ganador y en realidad está sin medir.

`fuente` dice de dónde salió cada ficha, con el detalle que la hace auditable:
una hoja de datos del fabricante y el catálogo de un revendedor no valen igual
y el informe tiene que poder distinguirlos.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields


@dataclass
class Ficha:
    marca: str
    modelo: str
    fuente: str
    #: "fabricante" | "revendedor" | "catalogo_marca"
    calidad_fuente: str = "fabricante"
    linea: str | None = None                  # HUB (con OPS) / Clásica (sin OPS)

    # --- panel ---
    tamano_pulgadas: float | None = None
    resolucion: str | None = None
    brillo_cdm2: float | None = None
    contraste: str | None = None
    angulo_vision: str | None = None
    #: Respuesta del PANEL (gris a gris).
    tiempo_respuesta_ms: float | None = None
    #: Respuesta del TÁCTIL, que es un orden de magnitud menor. Los
    #: requerimientos piden "tiempo de respuesta ≤ X ms" sin aclarar cuál de
    #: los dos, y la diferencia decide el veredicto: BTOUCH tiene 8 ms de panel
    #: y ≤ 2 ms de táctil, así que un requisito de 6 ms lo descarta o lo
    #: aprueba según cómo se lea la misma frase.
    tiempo_respuesta_tactil_ms: float | None = None
    tecnologia_panel: str | None = None
    vida_util_horas: float | None = None

    # --- táctil ---
    puntos_tactiles: int | None = None
    #: Los paneles con Android certificado reportan menos puntos en Android que
    #: en Windows. Guardar los dos evita comparar contra el número conveniente.
    puntos_tactiles_android: int | None = None
    tecnologia_tactil: str | None = None
    dureza_vidrio: str | None = None

    # --- cómputo embebido ---
    sistema_operativo: str | None = None
    certificacion_edla: bool | None = None
    cpu: str | None = None
    ram_gb: float | None = None
    almacenamiento_gb: float | None = None

    # --- OPS ---
    ops_disponible: bool | None = None
    ops_procesador: str | None = None

    # --- audio ---
    #: Potencia TOTAL del sistema (parlantes + subwoofer). Es el criterio que
    #: Brighter ya validó: contar solo los parlantes principales subestima lo
    #: que el equipo entrega y hace fallar requisitos que sí se cumplen.
    audio_w_total: float | None = None
    audio_detalle: str | None = None

    # --- comercial ---
    garantia_meses: float | None = None

    notas: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def declarados(self) -> int:
        tecnicos = [f.name for f in fields(self)
                    if f.name not in ("marca", "modelo", "fuente", "calidad_fuente",
                                      "linea", "notas", "audio_detalle")]
        return sum(getattr(self, n) is not None for n in tecnicos)


# --------------------------------------------------------------------------- #
# BTOUCH — fichas del fabricante
# --------------------------------------------------------------------------- #

_BT_COMUN = dict(
    fuente="Ficha técnica del fabricante BTOUCH",
    calidad_fuente="fabricante",
    resolucion="3840 × 2160 (4K UHD)",
    brillo_cdm2=410,
    angulo_vision="178° / 178°",
    tiempo_respuesta_ms=8,                  # panel, gris a gris
    tiempo_respuesta_tactil_ms=2,           # ≤ 2 ms declarado en ficha
    tecnologia_panel="TFT LCD",
    vida_util_horas=50_000,
    puntos_tactiles=50,                     # Windows
    puntos_tactiles_android=16,             # EDLA FW
    tecnologia_tactil="Infrarrojo",
    dureza_vidrio="7H (escala de lápiz, ASTM D3363)",
    sistema_operativo="Android 15",
    certificacion_edla=True,
    cpu="Octa-Core ARM Cortex-A76 ×4 + Cortex-A55 ×4",
    ram_gb=16,
    almacenamiento_gb=256,
    audio_w_total=60,                       # 20 W × 2 + subwoofer 20 W
    audio_detalle="20 W × 2 + subwoofer 20 W (total 60 W)",
)

BTOUCH: list[Ficha] = [
    Ficha(marca="BTOUCH", modelo="BT-65LKT HUB", linea="HUB (con OPS)",
          tamano_pulgadas=65, contraste="4000:1 (AUO)", garantia_meses=36,
          ops_disponible=True, ops_procesador="Intel Core i7-1250U (12.ª gen.)",
          **_BT_COMUN),
    Ficha(marca="BTOUCH", modelo="BT-75LKT HUB", linea="HUB (con OPS)",
          tamano_pulgadas=75, contraste="1200:1 (BOE)", garantia_meses=48,
          ops_disponible=True, ops_procesador="Intel Core i7-1255U",
          notas=["La ficha de 75\" declara detección de palma y respuesta táctil < 6 ms."],
          **_BT_COMUN),
    Ficha(marca="BTOUCH", modelo="BT-86LKT HUB", linea="HUB (con OPS)",
          tamano_pulgadas=86, contraste="4000:1 (AUO)", garantia_meses=36,
          ops_disponible=True, ops_procesador="Intel Core i7-1250U (12.ª gen.)",
          **_BT_COMUN),
    Ficha(marca="BTOUCH", modelo="BT-86LKT CLÁSICO", linea="Clásica (sin OPS)",
          tamano_pulgadas=86, contraste="4000:1 (AUO)", garantia_meses=36,
          ops_disponible=False, ops_procesador=None,
          notas=["Sin ranura OPS, sin cámara integrada y sin arreglo de micrófonos."],
          **{k: v for k, v in _BT_COMUN.items() if k != "audio_w_total"}
          , audio_w_total=60),
    Ficha(marca="BTOUCH", modelo="BT-98LKT HUB", linea="HUB (con OPS)",
          tamano_pulgadas=98, contraste="1200:1 (BOE)", garantia_meses=48,
          ops_disponible=True, ops_procesador="Intel Core i7-1250U (12.ª gen.)",
          notas=["Precisión táctil ±1 mm (±0,5 mm en 65\" y 86\")."],
          **_BT_COMUN),
    Ficha(marca="BTOUCH", modelo="BT-98LKT CLÁSICO", linea="Clásica (sin OPS)",
          tamano_pulgadas=98, contraste="1200:1 (BOE)", garantia_meses=36,
          ops_disponible=False, ops_procesador=None,
          notas=["Sin ranura OPS, sin cámara integrada y sin arreglo de micrófonos."],
          **_BT_COMUN),
]


# --------------------------------------------------------------------------- #
# Competencia
# --------------------------------------------------------------------------- #

_TB_COMUN = dict(
    marca="TRIUMPH BOARD",
    fuente="Hoja de datos oficial del fabricante (BLACK Series)",
    calidad_fuente="fabricante",
    resolucion="3840 × 2160 (UHD)",
    brillo_cdm2=400,
    angulo_vision="178° / 178°",
    tiempo_respuesta_ms=8,
    tiempo_respuesta_tactil_ms=10,          # "< 10 ms (típ.)" en la hoja de datos
    vida_util_horas=50_000,
    puntos_tactiles=40,                     # Windows
    puntos_tactiles_android=20,
    tecnologia_tactil="Infrarrojo (transmisión IR)",
    dureza_vidrio="Mohs 7",
    cpu="ARM Cortex-A55 ×4",
    ram_gb=8,
    almacenamiento_gb=64,
    ops_disponible=True,
    audio_w_total=32,                       # 2 × 16 W, sin subwoofer declarado
    audio_detalle="2 × 16 W (2.0), sin subwoofer declarado",
    # La ficha no declara garantía ni certificación EDLA: quedan en None.
)

COMPETENCIA: list[Ficha] = [
    Ficha(modelo='TB 65" IFP BLACK', tamano_pulgadas=65, contraste="1200:1 (5000:1 dinámico)",
          tecnologia_panel="ADS", sistema_operativo="Android 11", **_TB_COMUN),
    Ficha(modelo='TB 75" IFP BLACK', tamano_pulgadas=75, contraste="1200:1 (5000:1 dinámico)",
          tecnologia_panel="ADS", sistema_operativo="Android 13", **_TB_COMUN),
    Ficha(modelo='TB 86" IFP BLACK', tamano_pulgadas=86, contraste="4000:1 (5000:1 dinámico)",
          tecnologia_panel="VA", sistema_operativo="Android 11",
          notas=["El sitio del fabricante indica Android 13; la ficha dice 11."],
          **_TB_COMUN),

    Ficha(marca="CTOUCH", modelo='CTOUCH Riva 75" 4K', tamano_pulgadas=75,
          fuente="Catálogo del comercializador",
          calidad_fuente="revendedor",
          resolucion="3840 × 2160 (4K UHD)",
          tecnologia_panel="LCD con retroiluminación LED",
          tecnologia_tactil="TrueBeam Touch",
          puntos_tactiles=32, puntos_tactiles_android=20,
          audio_w_total=80, audio_detalle="JBL de hasta 80 W",
          notas=["El catálogo no declara brillo, contraste, ángulo, SO, CPU, RAM "
                 "ni almacenamiento: no es comparable en esos campos."]),

    Ficha(marca="EDUBOARD", modelo='EDUBOARD (línea 65"–86")',
          fuente="Catálogo del titular de la marca",
          calidad_fuente="catalogo_marca",
          resolucion="4K UHD",
          puntos_tactiles=40, puntos_tactiles_android=20,
          sistema_operativo="Android 13+ / 14 según modelo",
          dureza_vidrio="Mohs 7",
          audio_w_total=40,
          audio_detalle="2 × 20 W; los modelos superiores suman subwoofer 20 W (60 W)",
          notas=["EDUBOARD rebranding de paneles ViewSonic ViewBoard (EDU55–EDU86); "
                 "no es un fabricante peruano.",
                 "El catálogo no declara tamaño por modelo ni la mayoría de los "
                 "parámetros del panel."]),
]

TODAS: list[Ficha] = BTOUCH + COMPETENCIA


def por_tamano(pulgadas: float | None, tolerancia: float = 0.5) -> list[Ficha]:
    """
    Fichas del tamaño pedido.

    Si el requerimiento no dice tamaño, devuelve todas: suponer uno sería
    inventar el dato que decide qué modelo se compara.
    """
    if pulgadas is None:
        return list(TODAS)
    iguales = [f for f in TODAS
               if f.tamano_pulgadas is not None
               and abs(f.tamano_pulgadas - pulgadas) <= tolerancia]
    # Las fichas sin tamaño declarado (EDUBOARD) entran siempre: no se las puede
    # descartar por un dato que no tienen.
    return iguales + [f for f in TODAS if f.tamano_pulgadas is None]


def marcas() -> list[str]:
    return sorted({f.marca for f in TODAS})


if __name__ == "__main__":
    print(f"{'marca':<15}{'modelo':<26}{'tam':>5}{'campos':>8}  fuente")
    print("-" * 92)
    for f in TODAS:
        tam = f"{f.tamano_pulgadas:.0f}\"" if f.tamano_pulgadas else "—"
        print(f"{f.marca:<15}{f.modelo:<26}{tam:>5}{f.declarados():>8}  "
              f"{f.fuente[:38]} ({f.calidad_fuente})")
    print("-" * 92)
    print(f"{len(TODAS)} fichas · {len(marcas())} marcas: {', '.join(marcas())}")
    print("\n'campos' = parámetros técnicos declarados de 22. Las fichas con pocos")
    print("campos no son peores productos: son productos sin información pública,")
    print("y eso limita lo que cualquier comparación puede afirmar sobre ellas.")
