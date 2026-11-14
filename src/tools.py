import os
import json
from datetime import datetime
from typing import Optional
from langchain_core.tools import tool
from src.memory import LongTermMemory

PEDIDOS_PATH = "data/pedidos.json"
TICKETS_PATH = "data/tickets.json"

# Instancia compartida de memoria de largo plazo
ltm = LongTermMemory()


def _leer_json(path: str) -> list:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _escribir_json(path: str, data: list):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =====================================================================
# 1. HERRAMIENTAS DE CONSULTA
# =====================================================================
@tool
def consultar_pedido(id_pedido: str) -> str:
    """
    [CONSULTA] Busca los detalles, estado actual, producto, fecha de entrega e incidencias de un pedido en pedidos.json.
    """
    pedidos = _leer_json(PEDIDOS_PATH)
    for p in pedidos:
        if str(p.get("id_pedido")) == str(id_pedido):
            return json.dumps({"encontrado": True, "pedido": p}, ensure_ascii=False)
    return json.dumps({
        "encontrado": False,
        "mensaje": f"No existe ningún pedido registrado con el ID {id_pedido}."
    }, ensure_ascii=False)


@tool
def consultar_politicas(tema_consulta: str) -> str:
    """
    [CONSULTA RAG] Busca en las políticas oficiales de Sodimac sobre cambios, devoluciones, garantías o despachos.
    """
    fragmentos = ltm.buscar_politicas(tema_consulta, top_k=3)
    if not fragmentos:
        return "No se encontraron políticas relevantes."
    salida = []
    for f in fragmentos:
        meta = f["metadatos"]
        salida.append(f"[{meta['documento']} | {meta['fragmento_id']}]: {f['texto']}")
    return "\n".join(salida)


@tool
def consultar_memoria_cliente(cliente_id: str, contexto_actual: str) -> str:
    """
    [CONSULTA MEMORIA LARGO PLAZO] Recupera interacciones o tickets previos de un cliente en sesiones anteriores.
    """
    recuerdos = ltm.recuperar_historial_cliente(cliente_id, contexto_actual)
    if not recuerdos:
        return f"No hay registros históricos previos para el cliente {cliente_id}."
    return "Historial previo encontrado:\n" + "\n".join(f"- {r}" for r in recuerdos)


# =====================================================================
# 2. HERRAMIENTA DE RAZONAMIENTO / CÁLCULO DE REGLAS DE NEGOCIO
# =====================================================================
@tool
def evaluar_elegibilidad_plazos(
    fecha_entrega: str,
    tipo_solicitud: str,
    fecha_referencia: str = "2026-09-30"
) -> str:
    """
    [RAZONAMIENTO] Calcula los días corridos transcurridos desde la fecha_entrega hasta fecha_referencia (YYYY-MM-DD)
    y determina si el pedido cumple los plazos legales de Sodimac:
    - DEVOLUCION: máximo 10 días corridos.
    - CAMBIO: máximo 30 días corridos.
    - GARANTIA: máximo 180 días corridos (6 meses).
    """
    try:
        f_entrega = datetime.strptime(fecha_entrega, "%Y-%m-%d")
        f_actual = datetime.strptime(fecha_referencia, "%Y-%m-%d")
        dias_transcurridos = (f_actual - f_entrega).days
    except ValueError:
        return "Error en el formato de fecha. Debe ser YYYY-MM-DD."

    if dias_transcurridos < 0:
        return json.dumps({
            "elegible": False,
            "motivo": "El pedido aún no ha sido entregado (fecha de entrega futura o pendiente)."
        }, ensure_ascii=False)

    limites = {"DEVOLUCION": 10, "CAMBIO": 30, "GARANTIA": 180}
    tipo = tipo_solicitud.upper().strip()
    limite = limites.get(tipo)

    if not limite:
        return f"Tipo de solicitud '{tipo_solicitud}' no válido. Use DEVOLUCION, CAMBIO o GARANTIA."

    elegible = dias_transcurridos <= limite
    alternativa = None
    if not elegible and tipo == "DEVOLUCION" and dias_transcurridos <= 30:
        alternativa = "No califica para devolución de dinero (>10 días), pero SÍ califica para CAMBIO de producto (<=30 días)."

    return json.dumps({
        "tipo_evaluado": tipo,
        "dias_transcurridos": dias_transcurridos,
        "plazo_maximo_dias": limite,
        "elegible": elegible,
        "alternativa_sugerida": alternativa
    }, ensure_ascii=False)


# =====================================================================
# 3. HERRAMIENTAS DE ESCRITURA (MUTACIÓN DE DATOS)
# =====================================================================
@tool
def gestionar_despacho_atrasado(id_pedido: str, accion: str) -> str:
    """
    [ESCRITURA] Modifica el estado de un pedido atrasado en pedidos.json.
    - accion: 'REPROGRAMAR' (agenda despacho prioritario en 24h) o 'CANCELAR' (cancela pedido y activa reembolso).
    """
    pedidos = _leer_json(PEDIDOS_PATH)
    accion_norm = accion.upper().strip()
    
    if accion_norm not in ["REPROGRAMAR", "CANCELAR"]:
        return "Acción inválida. Debe ser 'REPROGRAMAR' o 'CANCELAR'."

    for p in pedidos:
        if str(p.get("id_pedido")) == str(id_pedido):
            if p.get("estado_pedido") != "atrasado":
                return f"El pedido {id_pedido} tiene estado '{p.get('estado_pedido')}', no está 'atrasado'."
            
            if accion_norm == "REPROGRAMAR":
                p["estado_pedido"] = "reprogramado_prioritario"
                p["incidencia"] = "reprogramacion_24h_confirmada"
                p["fecha_entrega"] = "2026-10-01"
            else:
                p["estado_pedido"] = "cancelado_con_reembolso"
                p["incidencia"] = "cancelado_por_retraso"

            _escribir_json(PEDIDOS_PATH, pedidos)
            return json.dumps({
                "exito": True,
                "id_pedido": id_pedido,
                "nuevo_estado": p["estado_pedido"],
                "detalle": p
            }, ensure_ascii=False)

    return f"No se encontró el pedido {id_pedido} para actualizar."


@tool
def generar_ticket_postventa(
    cliente_id: str,
    id_pedido: str,
    tipo_gestion: str,
    prioridad: str,
    descripcion: str
) -> str:
    """
    [ESCRITURA] Registra un ticket formal en tickets.json y guarda el caso en la memoria de largo plazo.
    - prioridad: 'ALTA' (ej. línea blanca, pedidos atrasados críticos), 'MEDIA' (cambios/devoluciones), 'BAJA' (consultas).
    """
    tickets = _leer_json(TICKETS_PATH)
    ticket_id = f"TCK-{100 + len(tickets) + 1}"
    fecha_creacion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    nuevo_ticket = {
        "ticket_id": ticket_id,
        "fecha": fecha_creacion,
        "cliente_id": str(cliente_id),
        "id_pedido": str(id_pedido),
        "tipo_gestion": tipo_gestion.upper(),
        "prioridad": prioridad.upper(),
        "estado": "ABIERTO",
        "descripcion": descripcion
    }
    tickets.append(nuevo_ticket)
    _escribir_json(TICKETS_PATH, tickets)

    # Persistir también en memoria semántica de largo plazo
    ltm.guardar_interaccion_cliente(
        cliente_id=cliente_id,
        resumen=f"Ticket {ticket_id} (Prioridad {prioridad}) para pedido {id_pedido}: {descripcion}",
        tipo_caso=tipo_gestion.upper()
    )

    return json.dumps({
        "exito": True,
        "ticket_generado": nuevo_ticket
    }, ensure_ascii=False)


ALL_TOOLS = [
    consultar_pedido,
    consultar_politicas,
    consultar_memoria_cliente,
    evaluar_elegibilidad_plazos,
    gestionar_despacho_atrasado,
    generar_ticket_postventa
]