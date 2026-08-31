# Genera un OCDS de muestra (jsonl) para probar sin descargar los 100MB reales.
import json, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = []
def rel(ocid, titulo, entidad, region, ref, adj, cant, prov, fecha, status="complete"):
    return {"ocid":ocid,"date":fecha,"buyer":{"name":entidad},
            "parties":[{"address":{"region":region}}],
            "tender":{"title":titulo,"status":status,"value":{"amount":ref},
                      "items":[{"quantity":cant,"description":titulo}]},
            "awards":[{"suppliers":[{"name":prov}],"value":{"amount":adj}}]}

# Relevantes
rows.append(rel("ocds-dgv273-2026-001","Adquisicion de pantallas interactivas para aulas","Municipalidad de Cayma","Arequipa",480000,462000,20,"BTOUCH SAC","2026-05-10"))
rows.append(rel("ocds-dgv273-2026-002","Compra de pizarras digitales interactivas","UNSA","Arequipa",300000,289000,15,"IMPORT TECH EIRL","2026-06-01"))
rows.append(rel("ocds-dgv273-2026-003","Servicio de senalizacion digital y totem informativo","Gobierno Regional de Moquegua","Moquegua",150000,148000,6,"DIGITAL PERU SAC","2026-04-22"))
rows.append(rel("ocds-dgv273-2026-004","Monitor interactivo 86 pulgadas educativo","Colegio La Salle","Arequipa",95000,93000,5,"BTOUCH SAC","2026-03-15"))
# DUPLICADO intencional del 001 (mismo ocid, debe colapsar a 1)
rows.append(rel("ocds-dgv273-2026-001","Adquisicion de pantallas interactivas para aulas","Municipalidad de Cayma","Arequipa",480000,462000,20,"BTOUCH SAC","2026-05-10"))
# Falso positivo que DEBE excluirse (protector de pantalla)
rows.append(rel("ocds-dgv273-2026-005","Compra de protector de pantalla para laptops","Municipalidad de Lima","Lima",2000,1900,100,"UTILES SAC","2026-02-01"))
# No relevante (no tiene keyword)
rows.append(rel("ocds-dgv273-2026-006","Adquisicion de utiles de oficina","Municipalidad de Tacna","Tacna",5000,4800,50,"OFI SAC","2026-01-20"))

with open(os.path.join(BASE,"data","muestra.jsonl"),"w",encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False)+"\n")
print("muestra.jsonl generada con", len(rows), "lineas (incluye 1 duplicado, 1 excluible, 1 no relevante)")
