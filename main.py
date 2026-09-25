import os
import json
import glob
import time
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from groq import Groq, GroqError
import chromadb

# Asigna la API Key desde la variable de entorno o usa la clave indicada por defecto
API_KEY_REAL = "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"

# Instancia el cliente directamente con la cadena
client = Groq(api_key=API_KEY_REAL)

# Modelo activo de Groq compatible con Structured Outputs (JSON)
MODEL_NAME = "openai/gpt-oss-20b"

# =====================================================================
# 1. ESQUEMA DE SALIDA DEL CLASIFICADOR JSON
# =====================================================================
class DatosExtraidos(BaseModel):
    id_pedido: Optional[str] = Field(default=None, description="ID del pedido de 4 dígitos si está presente")
    producto: Optional[str] = Field(default=None, description="Producto mencionado")
    incidencia: Optional[str] = Field(default=None, description="Problema reportado (ej: dañado, atrasado)")

class ClasificacionConsulta(BaseModel):
    intencion: str = Field(
        description="Categoría principal: CAMBIO, DEVOLUCION, GARANTIA, DESPACHO, ESTADO_PEDIDO, NO_RESOLUBLE"
    )
    confianza: float = Field(description="Nivel de confianza de 0.0 a 1.0")
    datos_extraidos: DatosExtraidos
    informacion_faltante: List[str] = Field(default=[], description="Datos necesarios que no están en la consulta")
    requiere_aclaracion: bool = Field(default=False, description="True si la consulta es muy ambigua")

# =====================================================================
# 2. HERRAMIENTA LECTORA DE PEDIDOS (JSON / SOLO LECTURA)
# =====================================================================
class PedidosTool:
    def __init__(self, json_path: str = "data/pedidos.json"):
        self.json_path = json_path
        self._data = self._load_data()

    def _load_data(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.json_path):
            with open(self.json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def consultar_pedido(self, id_pedido: str) -> Dict[str, Any]:
        """Busca un pedido simulado por su identificador único."""
        for p in self._data:
            if str(p.get("id_pedido")) == str(id_pedido):
                return {"encontrado": True, "pedido": p}
        return {
            "encontrado": False,
            "pedido": None,
            "mensaje": f"No se encontró ningún pedido con el identificador {id_pedido}."
        }

# =====================================================================
# 3. PIPELINE RAG CON CHROMADB (EMBEDDINGS INTEGRADOS)
# =====================================================================
class RAGPipeline:
    def __init__(self, docs_dir: str = "data/docs"):
        self.docs_dir = docs_dir
        self.chroma_client = chromadb.Client()
        self.collection = self.chroma_client.get_or_create_collection(name="sodiassist_rag")
        self._ingest_documents()

    def _chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start += chunk_size - overlap
        return chunks

    def _ingest_documents(self):
        existing_ids = self.collection.get().get("ids", [])
        if existing_ids:
            self.collection.delete(ids=existing_ids)

        files = glob.glob(os.path.join(self.docs_dir, "*.md"))
        doc_id = 0
        
        for file_path in files:
            file_name = os.path.basename(file_path)
            category = file_name.replace("politica_", "").replace(".md", "").upper()
            
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            chunks = self._chunk_text(content, chunk_size=500, overlap=100)
            
            for idx, chunk in enumerate(chunks):
                chunk_id = f"{category}_{doc_id}_{idx}"
                metadata = {
                    "documento": file_name,
                    "categoria": category,
                    "tipo_informacion": "politica_postventa",
                    "fragmento_id": chunk_id
                }
                self.collection.add(
                    ids=[chunk_id],
                    documents=[chunk],
                    metadatas=[metadata]
                )
            doc_id += 1

    def buscar_contexto(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k
        )
        fragmentos = []
        if results and results.get("documents"):
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            for doc, meta in zip(docs, metas):
                fragmentos.append({
                    "texto": doc,
                    "metadatos": meta
                })
        return fragmentos

# =====================================================================
# 4. AGENTE ORQUESTADOR DE SODIASSIST
# =====================================================================
class SodiAssistAgent:
    def __init__(self):
        self.pedidos_tool = PedidosTool()
        self.rag_pipeline = RAGPipeline()

    def clasificar_intencion(self, consulta: str) -> ClasificacionConsulta:
        """Clasifica la intención del usuario retornando un JSON estructurado."""
        prompt_clasificador = f"""
Analiza la consulta de postventa de Sodimac y clasifícala estrictamente según el esquema JSON indicado.

Categorías permitidas para "intencion": CAMBIO, DEVOLUCION, GARANTIA, DESPACHO, ESTADO_PEDIDO, NO_RESOLUBLE.

FORMATO DE SALIDA REQUERIDO (JSON STRICTO CON TODOS LOS CAMPOS):
{{
  "intencion": "ESTADO_PEDIDO",
  "confianza": 0.95,
  "datos_extraidos": {{
    "id_pedido": "1002",
    "producto": null,
    "incidencia": null
  }},
  "informacion_faltante": [],
  "requiere_aclaracion": false
}}

Consulta del usuario: "{consulta}"
"""
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "system", 
                        "content": "Eres un clasificador de consultas de postventa. Responde ÚNICAMENTE un objeto JSON completo que contenga exactamente los campos: intencion, confianza, datos_extraidos (con id_pedido, producto, incidencia), informacion_faltante y requiere_aclaracion."
                    },
                    {"role": "user", "content": prompt_clasificador}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            raw_json = response.choices[0].message.content
            return ClasificacionConsulta.model_validate_json(raw_json)
        except Exception as e:
            print(f"Error clasificando la intención: {e}")
            raise e

    def ejecutar_flujo(self, consulta: str) -> str:
        # Paso 1: Clasificación
        clasificacion = self.clasificar_intencion(consulta)
        intencion = clasificacion.intencion
        datos = clasificacion.datos_extraidos

        if clasificacion.confianza < 0.70 or intencion == "NO_RESOLUBLE":
            return (
                "Disculpa, no dispongo de la información suficiente en nuestras políticas oficiales o la consulta se encuentra fuera de mi alcance. "
                "Voy a derivar tu requerimiento a un ejecutivo de atención humana."
            )

        contexto_rag_str = ""
        contexto_pedido_str = ""

        # Paso 2: Evaluación de fuentes necesarias
        requiere_rag = intencion in ["CAMBIO", "DEVOLUCION", "GARANTIA", "DESPACHO"]
        requiere_tool = intencion in ["ESTADO_PEDIDO"] or (datos.id_pedido is not None)

        if requiere_rag:
            fragmentos = self.rag_pipeline.buscar_contexto(consulta, top_k=3)
            if fragmentos:
                textos = [f"[{f['metadatos']['documento']} | {f['metadatos']['fragmento_id']}]: {f['texto']}" for f in fragmentos]
                contexto_rag_str = "\n".join(textos)

        if requiere_tool:
            if datos.id_pedido:
                res_pedido = self.pedidos_tool.consultar_pedido(datos.id_pedido)
                if res_pedido["encontrado"]:
                    contexto_pedido_str = json.dumps(res_pedido["pedido"], ensure_ascii=False, indent=2)
                else:
                    contexto_pedido_str = f"Resultado de búsqueda: {res_pedido['mensaje']}"
            else:
                return "Para poder consultar el estado o detalle de tu pedido, por favor indícame el número de identificador de tu compra (ID de pedido)."

        # Paso 3: Generación de respuesta final
        prompt_generador = f"""
[ROL Y OBJETIVO]
Eres SodiAssist, el asistente oficial de atención al cliente de Sodimac. Tu objetivo es entregar una respuesta clara, empática y precisa basada EXCLUSIVAMENTE en el contexto proporcionado.

[CONTEXTO DE POLÍTICAS RECUPERADO (RAG)]
{contexto_rag_str if contexto_rag_str else "No se requiere o no está disponible."}

[DATOS DEL PEDIDO CONSULTADO (HERRAMIENTA)]
{contexto_pedido_str if contexto_pedido_str else "No se requiere o no está disponible."}

[INSTRUCCIONES DE SEGURIDAD]
1. Responde únicamente con la información confirmada en los contextos superiores.
2. Si la información disponible es insuficiente, declara que no dispones de ella y solicita datos o deriva a soporte humano.
3. NO inventes plazos, montos ni coberturas.
4. Al final de tu respuesta, SIEMPRE debes incluir la sección "Fuentes consultadas:" citando los documentos y fragmento_id utilizados (o indicando que se consultó el sistema de pedidos).

[CONSULTA DEL USUARIO]
"{consulta}"
"""
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": "Eres SodiAssist, el asistente oficial de atención al cliente de Sodimac."},
                    {"role": "user", "content": prompt_generador}
                ],
                temperature=0.2
            )
            return response.choices[0].message.content
        except GroqError as e:
            return f"Error al generar respuesta: {e}"

# =====================================================================
# 5. DEMO / PUNTO DE ENTRADA CLI
# =====================================================================
if __name__ == "__main__":
    print("=== Inicializando Agente SodiAssist ===")
    agent = SodiAssistAgent()
    print("=== Sistema listo ===\n")

    consultas_prueba = [
        "¿Dónde está mi pedido 1002?",
        "Mi pedido 1002 está atrasado, ¿qué puedo hacer?",
        "Compré un producto hace 15 días y quiero devolverlo, ¿se puede?",
        "¿Me pueden dar el teléfono personal del gerente de la tienda?"
    ]

    for q in consultas_prueba:
        print(f"👤 USUARIO: {q}")
        respuesta = agent.ejecutar_flujo(q)
        print(f"🤖 SODIASSIST:\n{respuesta}")
        print("-" * 60)