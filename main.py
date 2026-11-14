import os
from src.agent import SodiAssistGraphAgent


def imprimir_turno(usuario: str, resultado: dict):
    print(f"\n👤 USUARIO: {usuario}")
    print(f"🧭 {resultado['plan']}")
    print(f"🤖 SODIASSIST:\n{resultado['respuesta']}")
    print("-" * 75)


def ejecutar_suite_pruebas(agent: SodiAssistGraphAgent):
    print("\n" + "=" * 75)
    print("ESCENARIO 1: MEMORIA CORTO PLAZO + PLANIFICACIÓN PRIORITARIA + ESCRITURA")
    print("=" * 75)
    # Turno 1: Consulta pedido 1002 (Lavadora atrasada)
    r1 = agent.conversar(
        "Hola, mi pedido 1002 no ha llegado todavía, ¿qué pasó y qué opciones tengo?",
        thread_id="sesion_escenario_1",
        cliente_id="CLI-01"
    )
    imprimir_turno("Hola, mi pedido 1002 no ha llegado todavía, ¿qué pasó y qué opciones tengo?", r1)

    # Turno 2: Sin repetir el ID 1002 (prueba memoria de corto plazo), solicita acción de escritura
    r2 = agent.conversar(
        "Por favor reprográmalo de forma prioritaria y créame un ticket de seguimiento.",
        thread_id="sesion_escenario_1",
        cliente_id="CLI-01"
    )
    imprimir_turno("Por favor reprográmalo de forma prioritaria y créame un ticket de seguimiento.", r2)

    print("\n" + "=" * 75)
    print("ESCENARIO 2: RAZONAMIENTO Y DECISIÓN ADAPTATIVA ANTE PLAZOS")
    print("=" * 75)
    # Pedido 1001 entregado el 2026-09-15 -> al 2026-09-30 van 15 días (fuera de devolución 10d, dentro de cambio 30d)
    r3 = agent.conversar(
        "Compré el taladro del pedido 1001 y quiero devolverlo para que me devuelvan el dinero.",
        thread_id="sesion_escenario_2",
        cliente_id="CLI-02"
    )
    imprimir_turno("Compré el taladro del pedido 1001 y quiero devolverlo para que me devuelvan el dinero.", r3)

    print("\n" + "=" * 75)
    print("ESCENARIO 3: RECUPERACIÓN DE MEMORIA DE LARGO PLAZO (NUEVA SESIÓN)")
    print("=" * 75)
    # Nueva sesión (thread_id distinto) para CLI-01: debe recordar el ticket creado en Escenario 1
    r4 = agent.conversar(
        "Hola, soy el cliente CLI-01. ¿Tienes registro de alguna gestión o ticket que haya abierto antes?",
        thread_id="sesion_escenario_3_nueva",
        cliente_id="CLI-01"
    )
    imprimir_turno("Hola, soy el cliente CLI-01. ¿Tienes registro de alguna gestión o ticket que haya abierto antes?", r4)


def modo_interactivo(agent: SodiAssistGraphAgent):
    print("\n💬 MODO INTERACTIVO ACTIVADO (escribe 'salir' para terminar)")
    cliente_id = input("Ingresa ID de cliente (ej. CLI-01): ").strip() or "CLI-01"
    thread_id = f"chat_vivo_{cliente_id}"

    while True:
        user_input = input("\n👤 Tú: ").strip()
        if user_input.lower() in ["salir", "exit", "quit"]:
            print("Cerrando SodiAssist. ¡Hasta luego!")
            break
        if not user_input:
            continue
        res = agent.conversar(user_input, thread_id=thread_id, cliente_id=cliente_id)
        imprimir_turno(user_input, res)


if __name__ == "__main__":
    print("=== Inicializando SodiAssist v2.0 (LangGraph + Groq + ChromaDB Persistente) ===")
    agente = SodiAssistGraphAgent()
    print("=== Agente listo ===")

    opcion = input("\nSelecciona modo:\n[1] Ejecutar Suite de Pruebas Automáticas (IE7)\n[2] Chat Interactivo en Vivo\nOpción: ").strip()
    if opcion == "2":
        modo_interactivo(agente)
    else:
        ejecutar_suite_pruebas(agente)