#!/usr/bin/env python3
"""
pipeline_hotmart.py — Extrae transcripciones de un curso en Hotmart
y construye un knowledge base listo para entrenar un agente en GPT Maker.

Uso:
  python3 pipeline_hotmart.py \
    --url "https://hotmart.com/es/club/TU-CURSO/products/XXXXXXX" \
    --output-dir ./mi_curso \
    --whisper-model medium \
    --wait-vtt 90

Requiere: playwright, openai-whisper, ffmpeg, requests
  pip3 install playwright openai-whisper requests
  playwright install chromium
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import requests
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("❌ Playwright no instalado. Corre: pip3 install playwright && playwright install chromium")
    sys.exit(1)

# ─── CLI ─────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Extrae transcripciones de un curso Hotmart")
    p.add_argument("--url",           required=True,  help="URL del curso en Hotmart")
    p.add_argument("--output-dir",    required=True,  help="Carpeta de salida")
    p.add_argument("--whisper-model", default="medium", help="Modelo Whisper (tiny/base/small/medium/large)")
    p.add_argument("--whisper-lang",  default="es",   help="Idioma para Whisper (default: es)")
    p.add_argument("--wait-vtt",      type=int, default=90, help="Segundos esperando VTT por clase")
    p.add_argument("--wait-between",  type=int, default=3,  help="Segundos entre clases")
    p.add_argument("--max-retries",   type=int, default=2,  help="Reintentos por clase")
    return p.parse_args()

# ─── Utils ───────────────────────────────────────────────────────────────────

def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2))

def is_vtt_url(url):
    u = url.lower()
    return any(x in u for x in [".vtt", "subtitle", "caption", "transcript", "textstream"])

def find_whisper():
    candidates = [
        os.path.expanduser("~/Library/Python/3.9/bin/whisper"),
        os.path.expanduser("~/Library/Python/3.10/bin/whisper"),
        os.path.expanduser("~/Library/Python/3.11/bin/whisper"),
        "whisper",
    ]
    for c in candidates:
        if Path(c).exists() or c == "whisper":
            try:
                subprocess.run([c, "--help"], capture_output=True, timeout=5)
                return c
            except Exception:
                continue
    return None

# ─── FASE 1: Mapeo ───────────────────────────────────────────────────────────

async def mapear_curso(page, curso_url):
    print("\n" + "="*55)
    print("FASE 1 — MAPEO DEL CURSO")
    print("="*55)

    for _ in range(5):
        collapsed = await page.query_selector_all('button[aria-controls^="sectionId"][aria-expanded="false"]')
        if not collapsed:
            break
        for btn in collapsed:
            try:
                await btn.click()
                await asyncio.sleep(0.4)
            except Exception:
                pass
        await asyncio.sleep(1)

    modulos = []
    module_buttons = await page.query_selector_all('button[aria-controls^="sectionId"]')
    print(f"  → {len(module_buttons)} módulos encontrados")

    for btn in module_buttons:
        nombre_modulo = re.sub(r'\s+', ' ', (await btn.inner_text()).strip())
        panel_id = await btn.get_attribute("aria-controls")
        clases = []

        try:
            panel = await page.query_selector(f'#{panel_id}')
            if panel:
                links = await panel.query_selector_all("a[href]")
                for i, link in enumerate(links):
                    href = await link.get_attribute("href")
                    texto = re.sub(r'\s+', ' ', (await link.inner_text()).strip())
                    if href and texto:
                        if href.startswith("/"):
                            href = "https://hotmart.com" + href
                        clases.append({
                            "id": f"{panel_id}_c{i}",
                            "nombre": texto,
                            "url": href,
                            "vtt_descargado": False
                        })
        except Exception as e:
            print(f"  ⚠️  Error módulo '{nombre_modulo}': {e}")

        modulos.append({"id": panel_id, "nombre": nombre_modulo, "clases": clases})

    total = sum(len(m["clases"]) for m in modulos)
    curso_nombre = await page.title()

    data = {
        "curso": curso_nombre,
        "url_base": curso_url,
        "total_clases": total,
        "modulos": modulos
    }
    print(f"✅ {len(modulos)} módulos · {total} clases")
    for m in modulos:
        print(f"   • {m['nombre']}: {len(m['clases'])} clases")
    return data

# ─── FASE 2: Descarga VTT ────────────────────────────────────────────────────

async def intercept_vtt(context, page, url, wait_secs):
    segments = {}

    async def on_response(response):
        if not is_vtt_url(response.url):
            return
        try:
            body = await response.body()
            if not body or len(body) < 10:
                return
            m = re.search(r'textstream[^=]*=\d+-(\d+)', response.url)
            seq = int(m.group(1)) if m else len(segments)
            if seq not in segments:
                segments[seq] = body
        except Exception:
            pass

    context.on("response", on_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass

    await asyncio.sleep(10)

    play_clicked = False
    for frame in [page] + list(page.frames):
        if play_clicked:
            break
        for sel in ['.vjs-big-play-button', 'button[aria-label*="Play" i]',
                    '[data-test="play-button"]', '.play-button', 'button[title*="Play" i]']:
            try:
                el = await frame.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    play_clicked = True
                    await asyncio.sleep(2)
                    break
            except Exception:
                pass

    last_count = 0
    stable_count = 0
    for _ in range(wait_secs * 2):
        await asyncio.sleep(0.5)
        if len(segments) > last_count:
            last_count = len(segments)
            stable_count = 0
        elif len(segments) > 0:
            stable_count += 1
            if stable_count >= 20:
                break

    context.remove_listener("response", on_response)

    if not segments:
        return None

    vtt_lines = ["WEBVTT\n\n"]
    for seq in sorted(segments.keys()):
        chunk = segments[seq].decode("utf-8", errors="replace")
        chunk = re.sub(r'^WEBVTT[^\n]*\n+', '', chunk).strip()
        if chunk:
            vtt_lines.append(chunk + "\n\n")

    return "".join(vtt_lines).encode("utf-8")


async def get_video_url(page):
    try:
        src = await page.evaluate("""
            () => {
                const v = document.querySelector('video');
                if (v && v.src && v.src.startsWith('http')) return v.src;
                const s = document.querySelector('video source');
                if (s) return s.src;
                return null;
            }
        """)
        if src and src.startswith("http"):
            return src
    except Exception:
        pass
    try:
        html = await page.content()
        for pat in [r'"(https?://[^"]+\.m3u8[^"]*)"', r'"(https?://[^"]+\.mp4[^"]*)"']:
            m = re.search(pat, html)
            if m:
                return m.group(1)
    except Exception:
        pass
    await asyncio.sleep(5)
    try:
        src = await page.evaluate("() => { const v = document.querySelector('video'); return v ? v.currentSrc || v.src : null; }")
        if src and src.startswith("http"):
            return src
    except Exception:
        pass
    return None


def transcribir_whisper(audio_path, vtt_dir, whisper_cmd, model, lang):
    print(f"    🎙️  Whisper {model}...")
    try:
        subprocess.run(
            [whisper_cmd, str(audio_path),
             "--model", model,
             "--language", lang,
             "--output_format", "vtt",
             "--output_dir", str(vtt_dir),
             "--verbose", "False"],
            capture_output=True, text=True, timeout=3600
        )
        out = vtt_dir / (audio_path.stem + ".vtt")
        if out.exists():
            return out.read_bytes()
    except Exception as e:
        print(f"    💥 Whisper: {e}")
    return None


def descargar_video(video_url, cookies, destino):
    try:
        if ".m3u8" in video_url:
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies[:15]])
            subprocess.run(
                ["ffmpeg", "-y",
                 "-headers", f"Cookie: {cookie_str}\r\nReferer: https://hotmart.com/\r\n",
                 "-i", video_url,
                 "-vn", "-acodec", "copy", "-t", "7200", str(destino)],
                capture_output=True, timeout=3600
            )
        else:
            sess = requests.Session()
            sess.cookies.update({c["name"]: c["value"] for c in cookies})
            resp = sess.get(video_url, headers={"Referer": "https://hotmart.com/"}, stream=True, timeout=60)
            if not resp.ok:
                return False
            with open(destino, "wb") as f:
                for chunk in resp.iter_content(65536):
                    f.write(chunk)
        return Path(destino).exists() and Path(destino).stat().st_size > 10000
    except Exception as e:
        print(f"    ⚠️  Descarga: {e}")
        return False


async def descargar_clase(context, page, clase, vtt_dir, audio_dir, cookies_getter,
                          wait_secs, max_retries, whisper_cmd, whisper_model, whisper_lang):
    clase_id = clase["id"]
    safe_id = re.sub(r"[^\w\-]", "_", clase_id)
    vtt_out = vtt_dir / f"clase-{safe_id}.vtt"

    if vtt_out.exists():
        print(f"  ✓  Ya existe: {clase['nombre'][:55]}")
        return True

    print(f"\n  📽  {clase['nombre'][:65]}")

    for intento in range(1, max_retries + 1):
        vtt_data = await intercept_vtt(context, page, clase["url"], wait_secs)
        if vtt_data:
            vtt_out.write_bytes(vtt_data)
            print(f"    ✅ VTT red ({len(vtt_data)} bytes)")
            return True

        cookies = await cookies_getter()
        try:
            track = await page.query_selector("track[src]")
            if track:
                src = await track.get_attribute("src")
                if src:
                    src = "https:" + src if src.startswith("//") else src
                    sess = requests.Session()
                    sess.cookies.update({c["name"]: c["value"] for c in cookies})
                    resp = sess.get(src, timeout=30)
                    if resp.ok and len(resp.content) > 50:
                        vtt_out.write_bytes(resp.content)
                        print(f"    ✅ VTT DOM ({len(resp.content)} bytes)")
                        return True
        except Exception:
            pass

        if not whisper_cmd:
            print(f"    ❌ Sin VTT y Whisper no disponible (intento {intento})")
            await asyncio.sleep(3)
            continue

        print("    🎙️  Sin subtítulos → Whisper fallback...")
        video_url = await get_video_url(page)
        if not video_url:
            print(f"    ❌ No encontré video (intento {intento})")
            await asyncio.sleep(3)
            continue

        audio_dir.mkdir(exist_ok=True)
        audio_path = audio_dir / f"{safe_id}.mp4"
        ok = descargar_video(video_url, cookies, audio_path)
        if not ok:
            try: audio_path.unlink()
            except: pass
            await asyncio.sleep(3)
            continue

        vtt_data = transcribir_whisper(audio_path, vtt_dir, whisper_cmd, whisper_model, whisper_lang)
        try: audio_path.unlink()
        except: pass

        if vtt_data:
            vtt_out.write_bytes(vtt_data)
            return True

    return False

# ─── FASE 3: Parsear VTT ─────────────────────────────────────────────────────

def parsear_vtt(contenido):
    lineas = contenido.splitlines()
    texto, prev = [], None
    for linea in lineas:
        linea = linea.strip()
        if not linea or linea.startswith("WEBVTT") or linea.startswith("NOTE"):
            continue
        if re.match(r'^\d+$', linea):
            continue
        if re.match(r'\d{2}:\d{2}[\d:.,\s>]+\d{2}:\d{2}', linea):
            continue
        linea = re.sub(r'<[^>]+>', '', linea).strip()
        if linea and linea != prev:
            texto.append(linea)
            prev = linea
    return " ".join(texto)

# ─── FASE 4: Knowledge Base ───────────────────────────────────────────────────

def construir_kb(data, transcripciones, output_dir):
    kb_json = output_dir / "knowledge_base.json"
    kb_text = output_dir / "knowledge_base.txt"

    bloques = []
    txt = [f"# BASE DE CONOCIMIENTO — {data['curso']}\n\n"]

    for modulo in data["modulos"]:
        txt.append(f"## MÓDULO: {modulo['nombre']}\n\n")
        for clase in modulo["clases"]:
            t = transcripciones.get(clase["id"])
            if not t or not t.get("texto"):
                continue
            bloque_txt = t["texto"].strip()
            bloques.append({
                "id": clase["id"],
                "modulo": modulo["nombre"],
                "clase": clase["nombre"],
                "url": clase.get("url", ""),
                "contenido": bloque_txt,
                "palabras": len(bloque_txt.split()),
                "fuente": t.get("fuente", "vtt")
            })
            txt.append(f"### {clase['nombre']}\n{bloque_txt}\n\n---\n\n")

    total_palabras = sum(b["palabras"] for b in bloques)
    kb_json.write_text(json.dumps({
        "curso": data["curso"],
        "total_clases": data["total_clases"],
        "clases_transcritas": len(bloques),
        "total_palabras": total_palabras,
        "bloques": bloques
    }, ensure_ascii=False, indent=2))
    kb_text.write_text("".join(txt), encoding="utf-8")

    print(f"\n{'='*55}")
    print(f"🎯 KNOWLEDGE BASE LISTA")
    print(f"   📚 Clases transcritas: {len(bloques)}/{data['total_clases']}")
    print(f"   📝 Palabras totales:   {total_palabras:,}")
    print(f"   📄 {kb_json}")
    print(f"   📄 {kb_text}")
    print(f"{'='*55}")

    return kb_json

# ─── MAIN ─────────────────────────────────────────────────────────────────────

async def main():
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    vtt_dir   = output_dir / "clases_vtt"
    audio_dir = output_dir / "audios_temp"
    clases_json = output_dir / "clases.json"
    session_file = output_dir / "session_cookies.json"

    vtt_dir.mkdir(exist_ok=True)

    whisper_cmd = find_whisper()
    if not whisper_cmd:
        print("⚠️  Whisper no encontrado — se omitirá el fallback por audio")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=50, channel="chrome")
        context = await browser.new_context()
        page    = await context.new_page()

        await page.goto(args.url, wait_until="domcontentloaded")
        print("🔐 Inicia sesión en Hotmart en la ventana de Chrome que se abrió.")
        print("   Navega hasta ver el contenido del curso, luego escribe 'listo' aquí:")
        while True:
            val = input().strip().lower()
            if val == "listo":
                url_act = page.url
                if any(x in url_act for x in ["club", "product", "members", "hotmart"]):
                    break
                print(f"   ⚠️  URL actual: {url_act}")
                print("   Navega al curso y escribe 'listo' de nuevo:")

        # Fase 1
        if clases_json.exists():
            print("\n⚡ clases.json ya existe, saltando mapeo...")
            data = json.loads(clases_json.read_text())
        else:
            data = await mapear_curso(page, args.url)
            save_json(clases_json, data)

        # Fase 2
        print("\n" + "="*55)
        print("FASE 2 — DESCARGA DE TRANSCRIPCIONES")
        print("="*55)

        total = sum(len(m["clases"]) for m in data["modulos"])
        descargados, fallidos = 0, []

        async def get_cookies():
            return await context.cookies()

        for modulo in data["modulos"]:
            print(f"\n📁 {modulo['nombre']}")
            for clase in modulo["clases"]:
                safe_id = re.sub(r"[^\w\-]", "_", clase["id"])
                if clase.get("vtt_descargado") or (vtt_dir / f"clase-{safe_id}.vtt").exists():
                    print(f"  ✓  {clase['nombre'][:55]}")
                    clase["vtt_descargado"] = True
                    descargados += 1
                    continue

                ok = await descargar_clase(
                    context, page, clase, vtt_dir, audio_dir, get_cookies,
                    args.wait_vtt, args.max_retries,
                    whisper_cmd, args.whisper_model, args.whisper_lang
                )
                if ok:
                    clase["vtt_descargado"] = True
                    descargados += 1
                else:
                    fallidos.append(clase["nombre"])

                save_json(clases_json, data)
                await asyncio.sleep(args.wait_between)

        print(f"\n📊 {descargados}/{total} procesadas | {len(fallidos)} fallidas")

        cookies = await context.cookies()
        save_json(session_file, cookies)
        await browser.close()

    # Fase 3
    print("\n" + "="*55)
    print("FASE 3 — PARSEO DE VTTs")
    print("="*55)

    transcripciones = {}
    for modulo in data["modulos"]:
        for clase in modulo["clases"]:
            safe_id = re.sub(r"[^\w\-]", "_", clase["id"])
            vtt_path = vtt_dir / f"clase-{safe_id}.vtt"
            if not vtt_path.exists():
                continue
            try:
                contenido = vtt_path.read_text(encoding="utf-8", errors="replace")
                texto = parsear_vtt(contenido)
                if texto:
                    transcripciones[clase["id"]] = {
                        "modulo": modulo["nombre"],
                        "clase": clase["nombre"],
                        "texto": texto,
                        "palabras": len(texto.split()),
                        "fuente": "vtt"
                    }
                    print(f"  ✅ {clase['nombre'][:55]} ({len(texto.split())} palabras)")
            except Exception as e:
                print(f"  ⚠️  {clase['nombre'][:40]}: {e}")

    # Fase 4
    print("\n" + "="*55)
    print("FASE 4 — CONSTRUYENDO KNOWLEDGE BASE")
    print("="*55)

    kb_path = construir_kb(data, transcripciones, output_dir)
    print(f"\n✅ Pipeline completo.")
    print(f"   Knowledge base: {kb_path}")
    return str(kb_path)


if __name__ == "__main__":
    asyncio.run(main())
