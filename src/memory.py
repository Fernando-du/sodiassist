import os
import glob
from datetime import datetime
from typing import List, Dict, Any
import chromadb
from langgraph.checkpoint.memory import MemorySaver


class LongTermMemory:
    """
    Gestiona la memoria persistente en disco mediante ChromaDB:
    1. Conocimiento organizacional (Políticas de Sodimac en Markdown).
    2. Memoria episódica/semántica de interacciones previas por cliente.
    """

    def __init__(self, db_path: str = "data/chroma_db", docs_dir: str = "data/docs"):
        self.db_path = db_path
        self.docs_dir = docs_dir
        os.makedirs(self.db_path, exist_ok=True)
        
        self.client = chromadb.PersistentClient(path=self.db_path)
        self.policies_collection = self.client.get_or_create_collection(name="politicas_sodimac")
        self.client_memory_collection = self.client.get_or_create_collection(name="historial_clientes")
        
        self._ingest_policies()

    def _chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start += chunk_size - overlap
        return chunks

    def _ingest_policies(self):
        """Indexa las políticas .md si la colección está vacía o requiere actualización."""
        existing = self.policies_collection.get()
        if existing and existing.get("ids"):
            self.policies_collection.delete(ids=existing["ids"])

        files = glob.glob(os.path.join(self.docs_dir, "*.md"))
        for doc_idx, file_path in enumerate(files):
            file_name = os.path.basename(file_path)
            category = file_name.replace("politica_", "").replace(".md", "").upper()

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            chunks = self._chunk_text(content)
            for chunk_idx, chunk in enumerate(chunks):
                chunk_id = f"{category}_{doc_idx}_{chunk_idx}"
                self.policies_collection.add(
                    ids=[chunk_id],
                    documents=[chunk],
                    metadatas=[{
                        "documento": file_name,
                        "categoria": category,
                        "fragmento_id": chunk_id
                    }]
                )

    def buscar_politicas(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Recuperación semántica (RAG) sobre las políticas oficiales."""
        results = self.policies_collection.query(query_texts=[query], n_results=top_k)
        fragmentos = []
        if results and results.get("documents"):
            for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                fragmentos.append({"texto": doc, "metadatos": meta})
        return fragmentos

    def guardar_interaccion_cliente(self, cliente_id: str, resumen: str, tipo_caso: str):
        """Almacena un registro semántico en la memoria de largo plazo del cliente."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mem_id = f"{cliente_id}_{int(datetime.now().timestamp())}"
        documento = f"[{timestamp}] Cliente {cliente_id} ({tipo_caso}): {resumen}"
        
        self.client_memory_collection.add(
            ids=[mem_id],
            documents=[documento],
            metadatas=[{
                "cliente_id": str(cliente_id),
                "tipo_caso": tipo_caso,
                "fecha": timestamp
            }]
        )

    def recuperar_historial_cliente(self, cliente_id: str, consulta_actual: str, top_k: int = 3) -> List[str]:
        """Recupera recuerdos relevantes de sesiones anteriores del mismo cliente."""
        count = self.client_memory_collection.count()
        if count == 0:
            return []
        
        try:
            results = self.client_memory_collection.query(
                query_texts=[consulta_actual],
                n_results=min(top_k, count),
                where={"cliente_id": str(cliente_id)}
            )
            if results and results.get("documents") and results["documents"][0]:
                return results["documents"][0]
        except Exception:
            return []
        return []


def get_short_term_memory() -> MemorySaver:
    """Retorna el checkpointer en memoria para mantener el estado conversacional por sesión."""
    return MemorySaver()