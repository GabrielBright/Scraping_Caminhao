from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import pandas as pd
import asyncio
import logging
import re
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Config:
    URL_BASE = 'https://www.trucadao.com.br/venda/caminhoes-usados?tipo=cavalo-mecanico&page=1'
    MAX_PAGINAS = 10
    MAX_BOTOES_POR_PAGINA = 20
    MAX_RETRIES = 3
    TIMEOUT_PADRAO = 60000
    OUTPUT_FILE = 'dados_trucadao_completos.xlsx'

async def extrair_informacoes_tecnicas(texto: str) -> Dict[str, str]:
    campos = {
        "Tipo": "Não informado",
        "Marca": "Não informado",
        "Modelo": "Não informado",
        "Ano": "Não informado",
        "Situação": "Não informado",
        "Quilometragem": "Não informado",
        "Combustível": "Não informado",
        "Cor": "Não informado"
    }

    linhas = [l.strip() for l in texto.split('\n') if l.strip()]
    i = 0
    while i < len(linhas):
        linha = linhas[i].lower()
        for campo in campos.keys():
            if campo.lower() in linha:
                if i + 1 < len(linhas):
                    campos[campo] = linhas[i + 1].strip()
                break
        i += 1

    return campos

async def tentar_extrair_preco(pagina, config: Config) -> str:
    # Tenta primeiro com seletor direto
    preco_selectors = [
        "h5.price",
        "h5.MuiTypography-root.MuiTypography-h5.price",  # alternativa exata do HTML
        "h5:has-text('R$')"  # fallback textual
    ]

    for selector in preco_selectors:
        try:
            logger.info(f"🔍 Tentando localizar preço com seletor: {selector}")
            await pagina.wait_for_selector(selector, timeout=config.TIMEOUT_PADRAO)
            preco_raw = await pagina.locator(selector).inner_text()
            if preco_raw:
                logger.info(f"💰 Preço encontrado via seletor: {preco_raw}")
                break
        except Exception:
            continue
    else:
        # Fallback via JavaScript DOM direto
        logger.warning("⚠️ Nenhum seletor funcionou, tentando via JavaScript direto")
        preco_raw = await pagina.evaluate("""
            () => {
                const el = document.querySelector('h5.price');
                return el ? el.innerText : null;
            }
        """)
        if not preco_raw:
            logger.error("❌ Preço não encontrado nem com fallback")
            return "Não informado"
        logger.info(f"✅ Preço via evaluate: {preco_raw}")

    # Limpeza e formatação
    try:
        preco_limpo = preco_raw.replace("R$", "").replace("\xa0", "").replace(" ", "").replace(".", "").replace(",", ".").strip()
        if preco_limpo.replace('.', '').isdigit():
            preco_formatado = f"R$ {float(preco_limpo):,.2f}".replace(".", "X").replace(",", ".").replace("X", ",")
            logger.info(f"💰 Preço extraído: {preco_formatado}")
            return preco_formatado
        else:
            logger.warning(f"⚠️ Preço não numérico após limpeza: {preco_limpo}")
    except Exception as e:
        logger.error(f"❌ Erro ao formatar preço: {e}")

    return "Não informado"

async def tentar_extrair_dados_tecnicos(pagina, config: Config) -> Dict[str, str]:
    try:
        info_selector = "div[role='tabpanel']:has(div:has-text('Marca'))"
        await pagina.wait_for_selector(info_selector, timeout=config.TIMEOUT_PADRAO)
        informacoes = await pagina.locator(info_selector).inner_text()
        return await extrair_informacoes_tecnicas(informacoes)
    except Exception as e:
        logger.error(f"Erro nos dados técnicos: {e}")
        return {k: "Erro" for k in ["Tipo", "Marca", "Modelo", "Ano", "Situação", "Quilometragem", "Combustível", "Cor"]}

async def tentar_extrair_revenda(pagina, config: Config) -> str:
    try:
        selector = "span.city"
        el = pagina.locator(selector)

        await el.scroll_into_view_if_needed()
        await el.wait_for(state="visible", timeout=15000)  # timeout menor evita travar o script

        raw_text = await el.inner_text()
        revenda_text = raw_text.replace("Cidade:", "").strip().title()

        logger.info(f"🏪 Localização da revenda: {revenda_text}")
        return revenda_text
    except Exception as e:
        logger.warning(f"Erro na revenda: {e}")
        return "Não informado"

async def extracaoDadosTrucadao(pagina, config: Config) -> List[Dict]:
    dados_coletados = []
    try:
        botoes = pagina.locator('button.button', has_text="Ver anúncio")
        await pagina.wait_for_selector('button.button', timeout=config.TIMEOUT_PADRAO)
        total_botoes = await botoes.count()
        logger.info(f"{total_botoes} botões 'Ver anúncio' encontrados na página.")

        for i in range(min(config.MAX_BOTOES_POR_PAGINA, total_botoes)):
            logger.info(f"➡️  Processando anúncio {i + 1}/{total_botoes}")
            botao = botoes.nth(i)

            try:
                await botao.scroll_into_view_if_needed()
                await botao.wait_for(state="attached", timeout=5000)
                await botao.hover()
                await asyncio.sleep(0.5)
                await botao.click(timeout=config.TIMEOUT_PADRAO)
                logger.info(f"✅ Clicou no anúncio {i + 1}")
            except Exception as e:
                logger.warning(f"❌ Falha ao clicar no botão {i + 1}: {e}")
                continue

            await pagina.wait_for_load_state("networkidle")
            await asyncio.sleep(2.0)

            preco = await tentar_extrair_preco(pagina, config)
            logger.info(f"💰 Preço extraído: {preco}")

            dados_tecnicos = await tentar_extrair_dados_tecnicos(pagina, config)
            logger.info(f"📄 Dados técnicos extraídos.")

            revenda = await tentar_extrair_revenda(pagina, config)
            logger.info(f"🏢 Localização da revenda: {revenda}")

            url_anuncio = pagina.url
            dados_coletados.append({
                "Preço": preco,
                **dados_tecnicos,
                "Localização": revenda,
                "URL": url_anuncio
            })

            logger.info("🔙 Voltando para listagem de anúncios...")
            try:
                await pagina.go_back(timeout=config.TIMEOUT_PADRAO)
                await pagina.wait_for_selector('button.button', timeout=config.TIMEOUT_PADRAO)
                await asyncio.sleep(1.0)
                logger.info("↩️ Retornou com sucesso para a listagem")
            except Exception as e:
                logger.error(f"❌ Erro ao retornar para a listagem: {e}")
                break

    except Exception as e:
        logger.error(f"❌ Erro geral durante extração: {e}")
    return dados_coletados

async def coletar_dados_trucadao(pagina, config: Config) -> List[Dict]:
    todos_dados = []
    pagina_atual = 1

    while pagina_atual <= config.MAX_PAGINAS:
        logger.info(f"📄 Página {pagina_atual} de {config.MAX_PAGINAS}")
        dados = await extracaoDadosTrucadao(pagina, config)
        todos_dados.extend(dados)

        try:
            proximo_botao = pagina.locator("ul.MuiPagination-ul li:has(a[aria-label='Go to next page']) a")
            await proximo_botao.wait_for(state="visible", timeout=10000)
            if await proximo_botao.is_enabled():
                await proximo_botao.click()
                await pagina.wait_for_load_state("networkidle")
                pagina_atual += 1
            else:
                logger.info("⛔ Botão de próxima página indisponível.")
                break
        except Exception as e:
            logger.warning(f"⚠️ Falha ao mudar de página: {e}")
            break

    return todos_dados

async def iniciar_scraping():
    async with async_playwright() as p:
        try:
            navegador = await p.chromium.launch(headless=True, slow_mo=100)
            pagina = await navegador.new_page()
            config = Config()

            logger.info(f"🌐 Acessando {config.URL_BASE}")
            await pagina.goto(config.URL_BASE, timeout=60000)
            await pagina.wait_for_load_state("networkidle")

            dados = await coletar_dados_trucadao(pagina, config)

            if dados:
                df = pd.DataFrame(dados)
                df.to_excel(config.OUTPUT_FILE, index=False)
                logger.info(f"✅ {len(dados)} registros salvos em {config.OUTPUT_FILE}")
            else:
                logger.warning("⚠️ Nenhum dado foi extraído.")
        except Exception as e:
            logger.critical(f"💥 Erro crítico durante execução: {e}")
        finally:
            await navegador.close()

if __name__ == "__main__":
    asyncio.run(iniciar_scraping())