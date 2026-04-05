#!/bin/bash
# run_completo.sh — Pipeline completo: Hotmart → Knowledge Base → GPT Maker
#
# Uso:
#   bash run_completo.sh \
#     "https://hotmart.com/es/club/tu-curso/products/XXXXXX" \
#     "Nombre del Bot" \
#     "Nombre del Curso" \
#     "Nombre Instructor/a" \
#     "TU_GPTMAKER_APIKEY" \
#     "TU_GPTMAKER_WORKSPACE_ID"
#
# O con variables de entorno:
#   export GPTMAKER_API_KEY="..."
#   export GPTMAKER_WORKSPACE_ID="..."
#   bash run_completo.sh "URL" "Bot" "Curso" "Instructora"

set -e

# ─── Args ────────────────────────────────────────────────────────────────────
URL_CURSO="${1:?❌ Falta argumento 1: URL del curso}"
NOMBRE_AGENTE="${2:?❌ Falta argumento 2: Nombre del bot}"
NOMBRE_CURSO="${3:?❌ Falta argumento 3: Nombre del curso}"
INSTRUCTORA="${4:?❌ Falta argumento 4: Nombre del instructor/a}"
GPTMAKER_API_KEY="${5:-${GPTMAKER_API_KEY:?❌ Falta API Key de GPT Maker (arg 5 o variable GPTMAKER_API_KEY)}}"
GPTMAKER_WORKSPACE_ID="${6:-${GPTMAKER_WORKSPACE_ID:-}}"

# ─── Rutas ───────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$(pwd)/$(echo "$NOMBRE_CURSO" | tr ' ' '_' | tr '[:upper:]' '[:lower:]')"
KB_PATH="$OUTPUT_DIR/knowledge_base.json"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        Hotmart → GPT Maker — Pipeline Completo      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Curso:   $NOMBRE_CURSO"
echo "  Bot:     $NOMBRE_AGENTE"
echo "  Salida:  $OUTPUT_DIR"
echo ""

# ─── Fase 1-4: Pipeline Hotmart ──────────────────────────────────────────────
echo "━━━ FASE 1-4: Extracción del curso ━━━━━━━━━━━━━━━━━━━"
python3 "$SCRIPT_DIR/pipeline_hotmart.py" \
  --url "$URL_CURSO" \
  --output-dir "$OUTPUT_DIR"

if [ ! -f "$KB_PATH" ]; then
  echo "❌ No se generó knowledge_base.json. Verifica el pipeline."
  exit 1
fi

echo ""
echo "━━━ FASE 5: Creando agente en GPT Maker ━━━━━━━━━━━━━━"

# Args opcionales
WORKSPACE_ARG=""
if [ -n "$GPTMAKER_WORKSPACE_ID" ]; then
  WORKSPACE_ARG="--workspace $GPTMAKER_WORKSPACE_ID"
fi

python3 "$SCRIPT_DIR/crear_agente.py" \
  --kb "$KB_PATH" \
  --nombre-agente "$NOMBRE_AGENTE" \
  --nombre-curso "$NOMBRE_CURSO" \
  --instructora "$INSTRUCTORA" \
  --apikey "$GPTMAKER_API_KEY" \
  $WORKSPACE_ARG

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║                  ✅ TODO LISTO                      ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Paso final (manual):                               ║"
echo "║  → Ve a app.gptmaker.ai                             ║"
echo "║  → Busca el agente: $NOMBRE_AGENTE"
echo "║  → Canales → conecta WhatsApp o el canal deseado   ║"
echo "╚══════════════════════════════════════════════════════╝"
