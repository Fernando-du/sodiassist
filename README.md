SodiAssist - Agente de Postventa (Sodimac)

SodiAssist es un agente inteligente para la atención de postventa de Sodimac. Clasifica intenciones mediante JSON estructurado (Pydantic), consulta el estado de compras mediante herramientas (Tool Use) y responde dudas de políticas con un sistema RAG (ChromaDB).

Proyecto desarrollado para la asignatura Ingeniería de Soluciones con IA (ISY0101) - Duoc UC.

📂 Estructura del Proyecto

data/docs/: Documentos en Markdown (.md) con las políticas oficiales.

data/pedidos.json: Base de datos simulada de pedidos.

main.py: Script principal con la lógica del agente y pruebas.

requirements.txt: Dependencias del proyecto.

README.md: Instrucciones de ejecución.

⚙️ Requisitos Previos

Python 3.9 o superior.

Clave de API de Groq (GROQ_API_KEY).

🚀 Instrucciones de Ejecución
Clonar el repositorio
git clone <URL_DE_TU_REPOSITORIO>
cd <NOMBRE_DEL_REPOSITORIO>

Crear y activar un entorno virtual
python -m venv venv


Windows (PowerShell):

.\venv\Scripts\activate


Linux / macOS:

source venv/bin/activate

Instalar las dependencias
pip install -r requirements.txt

Configurar la clave de API

Windows (PowerShell):

$env:GROQ_API_KEY="tu_api_key_aqui"


Linux / macOS:

export GROQ_API_KEY="tu_api_key_aqui"

Ejecutar el script principal
python main.py

🧪 Pruebas del Sistema

Al ejecutar main.py, el sistema procesará automáticamente 4 consultas de prueba que validan:

Consulta de estado de pedidos (Tool Use).

Consulta de problemas con pedidos y políticas de despacho (Tool Use + RAG).

Búsqueda de políticas de cambios y devoluciones (RAG).

Solicitudes fuera de alcance con derivación a ejecutivo humano.

📦 Dependencias (requirements.txt)
groq
chromadb
pydantic