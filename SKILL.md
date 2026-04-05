---
name: hotmart-to-gptmaker
description: Pipeline completo que convierte cualquier curso de Hotmart en un agente de soporte entrenado en GPT Maker. Dado la URL del curso, descarga automáticamente las transcripciones de todas las clases (VTT o Whisper como fallback), construye un knowledge base y crea + entrena el agente en GPT Maker vía API. Usar cuando el usuario pida "crea el bot de soporte para el curso de X", "automatiza el soporte de mi curso de Hotmart", "quiero un asistente entrenado con mi curso", o tenga una URL de curso de Hotmart lista.
---

# Hotmart → GPT Maker

Pipeline de 5 fases que va de la URL del curso a un agente de soporte listo en GPT Maker.

## Requisitos

```bash
# Python 3.9+
pip3 install playwright openai-whisper requests python-dotenv
# Asegúrate de tener Google Chrome instalado (no Chromium)
# Descarga: https://www.google.com/chrome

# ffmpeg (para descarga de audio en Whisper fallback)
brew install ffmpeg   # macOS
# apt install ffmpeg  # Linux
```

## Uso rápido

```bash
bash scripts/run_completo.sh \
  "https://hotmart.com/es/club/tu-curso/products/XXXXXX" \
  "Nombre del Bot" \
  "Nombre del Curso" \
  "Nombre Instructor/a" \
  "TU_GPTMAKER_APIKEY" \
  "TU_GPTMAKER_WORKSPACE_ID"
```

O con variables de entorno:

```bash
export GPTMAKER_API_KEY="tu_api_key"
export GPTMAKER_WORKSPACE_ID="tu_workspace_id"

bash scripts/run_completo.sh \
  "https://hotmart.com/es/club/tu-curso/products/XXXXXX" \
  "Lumi" \
  "Jabones con Luisa" \
  "Luisa"
```

## Las 5 Fases

**Fase 1 — Mapeo:** Playwright abre Chrome, el usuario inicia sesión en Hotmart, la skill expande todos los módulos y extrae el listado completo de clases con sus URLs.

**Fase 2 — Intercepción de subtítulos HLS:** Hotmart sirve los subtítulos como segmentos HLS textstream (ej: `textstream_spa=1000-29`, `30`, `31`...) con tokens dinámicos de sesión. Por cada clase: Playwright abre la clase, da play al video e intercepta todos los segmentos de la red. Los ordena por número y los ensambla en un único VTT completo. Si una clase no tiene subtítulos, descarga el audio y lo transcribe con Whisper (fallback).

**Fase 3 — Parseo:** Limpia y normaliza todos los VTTs a texto plano eliminando timestamps, numeración y etiquetas.

**Fase 4 — Knowledge Base:** Genera `knowledge_base.json` y `knowledge_base.txt` con el contenido completo estructurado por módulo y clase, con URLs de referencia.

**Fase 5 — Creación y entrenamiento del agente:** Llama a la API de GPT Maker para crear el agente con su system prompt personalizado, sube el entrenamiento con todo el contenido del curso y lo activa.

## Paso manual del usuario

Cuando Chrome se abre, el usuario inicia sesión en Hotmart normalmente y escribe `listo` en el terminal. Es el único paso que requiere intervención humana.

## Paso manual al finalizar

Ir a `app.gptmaker.ai` → buscar el agente → **Canales** → conectar WhatsApp o el canal deseado.

## Scripts individuales

Si se quiere correr por partes:

```bash
# Solo el pipeline de Hotmart
python3 scripts/pipeline_hotmart.py \
  --url "URL_DEL_CURSO" \
  --output-dir ./mi_curso \
  --whisper-model medium

# Solo crear el agente (si ya tienes knowledge_base.json)
python3 scripts/crear_agente.py \
  --kb ./mi_curso/knowledge_base.json \
  --nombre-agente "Lumi" \
  --nombre-curso "Mi Curso" \
  --instructora "Luisa" \
  --apikey "TU_APIKEY"
```

## Errores comunes

| Error | Solución |
|-------|----------|
| `playwright not found` | `pip3 install playwright` (requiere Google Chrome instalado) |
| `whisper not found` | `pip3 install openai-whisper` (opcional, solo para fallback) |
| `401 GPT Maker` | API Key expirada — regenerar en GPT Maker |
| `knowledge_base.json not found` | Correr primero `pipeline_hotmart.py` |
| VTTs vacíos | Aumentar `--wait-vtt 120` para dar más tiempo al player |
