from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from playwright.async_api import TimeoutError as PLTimeout
import pandas as pd
import asyncio
import logging
import re
from typing import Dict, List
from time import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PAGE_URLS = [
f"https://www.trucadao.com.br/venda/implementos?subcategoria=rodoviario&page={i}"
for i in range(1, 40)
]

ARQUIVO_PKL_DADOS = "Implementos.pkl"
ARQUIVO_EXCEL_DADOS = "Implementos.xlsx"
ARQUIVO_CHECKPOINT = "checkpoint_trucadao.pkl" 
ARQUIVO_LINKS_CACHE = "links_trucadao.pkl"

TIMEOUT = 30000
MAX_BOTOES_POR_PAGINA = 9999 # processa todos os "Ver anúncio" da página
ANCHOR_DETALHE = "div.produtoVendedor" 

def formatar_preco(preco_raw: str) -> str:
    try:
        preco_limpo = (
        preco_raw.replace("R$", "")
        .replace("\xa0", "")
        .replace(" ", "")
        .replace(".", "")
        .replace(",", ".")
        .strip()
        )
        preco_float = float(preco_limpo)
        return f"R$ {preco_float:,.2f}".replace(".", "X").replace(",", ".").replace("X", ",")
    except Exception:
        return "Não informado"
    
async def tentar_extrair_dados_tecnicos(pagina) -> Dict[str, str]:
    campos = {
        "Tipo": "Não informado",
        "Marca": "Não informado",
        "Modelo": "Não informado",
        "Ano": "Não informado",
        "Combustível": "Não informado",
        "Placa": "Não informado",
        "Cor": "Não informado",
        "Quilometragem": "Não informado",
        "Situação": "Não informado",
    }

    try:
        await pagina.wait_for_selector("div.MuiGrid-container.css-3uuuu9", timeout=5000)
        linhas = pagina.locator("div.MuiGrid-container.css-3uuuu9 > div.MuiGrid-item")
        total = await linhas.count()
        logger.info(f"Encontradas {total} linhas de dados técnicos.")

        for i in range(total):
            bloco = linhas.nth(i)
            chave = ""
            valor = ""

            if await bloco.locator("label").count() > 0:
                chave = (await bloco.locator("label").inner_text()).strip().lower()

            p_tags = bloco.locator("p")
            p_count = await p_tags.count()
            if p_count > 0:
                valor = (await p_tags.first.inner_text()).strip()
            else:
                valor = ""

            if chave and valor:
                if "tipo" in chave:
                    campos["Tipo"] = valor
                elif "marca" in chave:
                    campos["Marca"] = valor
                elif "modelo" in chave:
                    campos["Modelo"] = valor
                elif "ano" in chave:
                    campos["Ano"] = valor
                elif "combust" in chave:
                    campos["Combustível"] = valor
                elif "placa" in chave:
                    campos["Placa"] = valor
                elif "cor" in chave:
                    campos["Cor"] = valor
                elif "km" in chave:
                    campos["Quilometragem"] = valor
                elif "situação" in chave or "situacao" in chave:
                    campos["Situação"] = valor
    except Exception as e:
        logger.error(f"Erro ao extrair dados técnicos: {e}", exc_info=True)

    return campos

async def tentar_extrair_preco(pagina) -> str:
    try:
        selector = "div.produtoVendedor h2"
        await pagina.wait_for_selector(selector, timeout=TIMEOUT)
        preco_raw = await pagina.locator(selector).inner_text()
        logger.info(f"Preço localizado: {preco_raw}")
    except Exception as e:
        logger.warning(f"Erro ao localizar o preço: {e}")
        return "Não informado"
    return formatar_preco(preco_raw)

async def tentar_extrair_revenda(pagina) -> str:
    try:
        selector = "div.produtoVendedor span p"
        await pagina.wait_for_selector(selector, timeout=TIMEOUT)
        texto = await pagina.locator(selector).inner_text()
        revenda_text = texto.strip().title()
        logger.info(f"Localização da revenda: {revenda_text}")
        return revenda_text
    except Exception as e:
        logger.warning(f"Erro ao extrair localização: {e}")
    return "Não informado"

async def extrair_da_listagem(pagina) -> List[Dict]:
    dados_coletados: List[Dict] = []

    # força carregar mais itens (lazy load)
    for _ in range(12):
        await pagina.evaluate("window.scrollBy(0, 1200)")
        await asyncio.sleep(0.15)

    # cards de implementos
    CARD_SELECTOR = "div.productCard.columns"
    INFO_SELECTOR = "div.infoProduct.columns"

    # se preferir, pode restringir aos que estão dentro do container principal:
    # CARD_SELECTOR = "div.produtoCard div.productCard.columns"

    await pagina.wait_for_selector(CARD_SELECTOR, timeout=TIMEOUT)
    cards = pagina.locator(CARD_SELECTOR)
    total = await cards.count()
    logger.info(f"{total} cards encontrados na listagem.")

    for i in range(total):
        card = cards.nth(i)

        # Título (h4)
        titulo = "Não informado"
        try:
            loc_titulo = card.locator(f"{INFO_SELECTOR} h4")
            if await loc_titulo.count() == 0:
                loc_titulo = card.locator("h4")  # fallback
            if await loc_titulo.count() > 0:
                titulo = (await loc_titulo.first.inner_text()).strip()
        except Exception:
            pass

        # Preço (p.price)
        preco_raw = ""
        try:
            loc_preco = card.locator(f"{INFO_SELECTOR} p.price")
            if await loc_preco.count() == 0:
                loc_preco = card.locator("p.price")  # fallback
            if await loc_preco.count() > 0:
                preco_raw = (await loc_preco.first.inner_text()).strip()
        except Exception:
            pass

        preco = formatar_preco(preco_raw)
        
        # Imagem (alt + src) dentro do card
        alt_img, src_img = "", ""
        try:
            img_loc = card.locator("div.product-img-container.columns img")
            if await img_loc.count() > 0:
                el = img_loc.first
                alt_img = (await el.get_attribute("alt")) or ""
                src_img = (await el.get_attribute("src")) or ""
        except Exception:
            pass

        # (Opcional) Link se existir no card — não clica, só guarda
        url = ""
        try:
            a = card.locator('a[href]')
            if await a.count() > 0:
                href = await a.first.get_attribute("href")
                if href:
                    url = "https://www.trucadao.com.br" + href if href.startswith("/") else href
        except Exception:
            pass

        dados_coletados.append({
            "Título": titulo,
            "Preço_raw": preco_raw,
            "Preço": preco,
            "Imagem_alt": alt_img,
            "Imagem_src": src_img, 
            "URL": url,
        })

    return dados_coletados

async def processar_todas_as_paginas() -> List[Dict]:
    dados_total: List[Dict] = []
    inicio = time()

    async with async_playwright() as p:
        navegador = await p.chromium.launch(headless=False)
        pagina = await navegador.new_page()
        try:
            for idx, url in enumerate(PAGE_URLS, start=1):
                logger.info(f"===== Página {idx}/{len(PAGE_URLS)} =====")
                await pagina.goto(url, timeout=80000)
                await pagina.wait_for_load_state("domcontentloaded")

                dados = await extrair_da_listagem(pagina)
                dados_total.extend(dados)

                # checkpoint a cada página processada
                try:
                    pd.DataFrame(dados_total).to_pickle(ARQUIVO_CHECKPOINT)
                    logger.info(f"Checkpoint salvo ({len(dados_total)} regs)")
                except Exception as e:
                    logger.warning(f"Falha ao salvar checkpoint: {e}")
        finally:
            await navegador.close()

        logger.info(f"Concluído em {time() - inicio:.1f}s com {len(dados_total)} registros")
        return dados_total

async def salvar_dados(dados: List[Dict]):
    if not dados:
        logger.warning("Nenhum dado para salvar.")
        return

    df = pd.DataFrame(dados)
    try:
        df.to_pickle(ARQUIVO_PKL_DADOS)
        logger.info(f"PKL salvo: {ARQUIVO_PKL_DADOS}")
    except Exception as e:
        logger.error(f"Erro ao salvar PKL: {e}")

    try:
        df.to_excel(ARQUIVO_EXCEL_DADOS, index=False)
        logger.info(f"Excel salvo: {ARQUIVO_EXCEL_DADOS}")
    except Exception as e:
        logger.error(f"Erro ao salvar Excel: {e}")

async def main():
    dados = await processar_todas_as_paginas()
    await salvar_dados(dados)

if __name__ == "__main__":
    asyncio.run(main())