import os
import time
from typing import Annotated, TypedDict, List
from pydantic import BaseModel, Field

from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from src.tools import ALL_TOOLS
from src.memory import get_short_term_memory


# =====================================================================
# 1. DEFINICIÓN DEL ESTADO DEL GRAFO Y ESQUEMA DE PLANIFICACIÓN
# =====================================================================
class PlanEjecucion(BaseModel):
    prioridad: str = Field(description="Prioridad del caso: ALTA, MEDIA o BAJA")
    objetivo: str = Field(description="Objetivo principal del usuario en esta interacción")
    pasos_planificados: List[str] = Field(description="Secuencia ordenada de acciones/herramientas a ejecutar")
    criterio_adaptacion: str = Field(description="Qué hacer si una condición o plazo no se cumple")


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    cliente_id: str
    plan_actual: str


# =====================================================================
# 2. CONSTRUCCIÓN DEL GRAFO DE AGENTE (LANGGRAPH)
# =====================================================================
class SodiAssistGraphAgent:
    def __init__(self, model_name: str = "openai/gpt-oss-20b", min_intervalo_segundos: int = 15):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("Falta la variable de entorno GROQ_API_KEY.")

        # Control automático de tasa (Rate Limit) entre turnos
        self.min_intervalo_segundos = min_intervalo_segundos
        self._ultima_llamada = 0.0

        # LLM base para razonamiento y Tool Calling (con reintentos automáticos ante Rate Limit)
        self.llm = ChatGroq(
            model=model_name,
            api_key=api_key,
            temperature=0.1,
            max_retries=4,
            request_timeout=30
        )
        self.llm_with_tools = self.llm.bind_tools(ALL_TOOLS)
        self.planner_llm = self.llm.with_structured_output(PlanEjecucion)

        self.checkpointer = get_short_term_memory()
        self.graph = self._build_graph()

    def _esperar_cuota_tpm(self):
        """Asegura una pausa automática entre llamadas para no exceder el límite TPM de Groq."""
        if self._ultima_llamada > 0:
            transcurrido = time.time() - self._ultima_llamada
            restante = self.min_intervalo_segundos - transcurrido
            if restante > 0:
                print(f"\n⏳ Control automático de cuota Groq: esperando {restante:.1f}s...")
                time.sleep(restante)
        self._ultima_llamada = time.time()

    def _nodo_planificador(self, state: AgentState) -> dict:
        """
        IE5: Planifica la secuencia de tareas y asigna prioridad antes de ejecutar acciones.
        """
        ultimo_mensaje = state["messages"][-1].content
        cliente_id = state.get("cliente_id", "ANONIMO")

        prompt_plan = f"""
Eres el módulo de planificación estratégica de SodiAssist (postventa Sodimac).
Analiza la consulta del cliente '{cliente_id}' y diseña un plan de ejecución secuencial.

Reglas de priorización:
- ALTA: Pedidos atrasados, fallas graves o productos de 'linea_blanca'.
- MEDIA: Solicitudes de cambio, devolución o garantía dentro de plazo.
- BAJA: Consultas informativas sobre políticas sin incidencias activas.

Consulta del usuario: "{ultimo_mensaje}"
"""
        try:
            plan: PlanEjecucion = self.planner_llm.invoke([HumanMessage(content=prompt_plan)])
            plan_texto = (
                f"[PLAN DE EJECUCIÓN | PRIORIDAD: {plan.prioridad}]\n"
                f"- Objetivo: {plan.objetivo}\n"
                f"- Pasos: {' -> '.join(plan.pasos_planificados)}\n"
                f"- Plan B (Adaptación): {plan.criterio_adaptacion}"
            )
        except Exception:
            plan_texto = "[PLAN DE EJECUCIÓN | PRIORIDAD: MEDIA] Consultar contexto, validar políticas y responder."

        return {"plan_actual": plan_texto}

    def _nodo_agente(self, state: AgentState) -> dict:
        """
        Nodo principal de razonamiento que decide qué herramientas llamar según el plan y el historial.
        """
        cliente_id = state.get("cliente_id", "ANONIMO")
        plan_actual = state.get("plan_actual", "")

        system_prompt = f"""
Eres SodiAssist, el agente autónomo oficial de postventa de Sodimac.
Estás atendiendo al cliente con ID: '{cliente_id}'.
Fecha actual de operación del sistema: 2026-09-30.

{plan_actual}

INSTRUCCIONES OPERATIVAS Y DE AUTONOMÍA:
1. Usa SIEMPRE tus herramientas antes de afirmar datos sobre pedidos o políticas.
2. Si el usuario menciona un cliente o inicia conversación, puedes consultar `consultar_memoria_cliente` para verificar casos previos.
3. Si el usuario pide CAMBIO, DEVOLUCION o GARANTIA de un pedido entregado:
   - Primero consulta el pedido (`consultar_pedido`) para obtener su `fecha_entrega`.
   - Luego usa `evaluar_elegibilidad_plazos` con la `fecha_entrega` y fecha de referencia `2026-09-30`.
   - Si no cumple el plazo de devolución (10 días), pero sí el de cambio (30 días), adáptate y ofrécele proactivamente el cambio de producto.
4. Si un pedido está 'atrasado', consulta las políticas de despacho y ofrece explícitamente REPROGRAMAR (prioritario 24h) o CANCELAR con reembolso; si el usuario confirma una opción, ejecuta `gestionar_despacho_atrasado` y luego `generar_ticket_postventa`.
5. Al finalizar cada respuesta, incluye siempre una breve sección 'Fuentes y herramientas ejecutadas:' detallando qué consultaste o modificaste.
6. Si la consulta está fuera del dominio de Sodimac (ej. datos personales de gerentes o temas ajenos), recházala cortésmente y deriva a un ejecutivo humano sin inventar información.
"""
        mensajes = [SystemMessage(content=system_prompt)] + state["messages"]
        respuesta = self.llm_with_tools.invoke(mensajes)
        return {"messages": [respuesta]}

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("planificador", self._nodo_planificador)
        workflow.add_node("agente", self._nodo_agente)
        workflow.add_node("herramientas", ToolNode(ALL_TOOLS))

        workflow.add_edge(START, "planificador")
        workflow.add_edge("planificador", "agente")
        workflow.add_conditional_edges(
            "agente",
            tools_condition,
            {
                "tools": "herramientas",
                END: END
            }
        )
        workflow.add_edge("herramientas", "agente")

        return workflow.compile(checkpointer=self.checkpointer)

    def conversar(self, mensaje: str, thread_id: str = "sesion_1", cliente_id: str = "CLI-01") -> dict:
        """
        Ejecuta un turno de conversación manteniendo la memoria de corto plazo en `thread_id`
        y regulando automáticamente el tiempo entre peticiones.
        """
        self._esperar_cuota_tpm()
        config = {"configurable": {"thread_id": thread_id}}
        resultado = self.graph.invoke(
            {
                "messages": [HumanMessage(content=mensaje)],
                "cliente_id": cliente_id
            },
            config=config
        )
        self._ultima_llamada = time.time()
        return {
            "plan": resultado.get("plan_actual", ""),
            "respuesta": resultado["messages"][-1].content
        }