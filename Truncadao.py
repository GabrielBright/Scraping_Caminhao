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

async def tentar_extrair_dados_tecnicos(pagina, config: Config) -> Dict[str, str]:
    campos = {
        "Marca": "Não informado",
        "Modelo": "Não informado",
        "Ano": "Não informado",
        "Combustível": "Não informado",
        "Quilometragem": "Não informado",
        "Tipo": "Cavalo Mecânico",
        "Situação": "Não informado"
    }

    try:
        # Lista de campos que vamos procurar
        labels_procurados = {
            "Marca": "Marca",
            "Modelo": "Modelo",
            "Ano": "Ano",
            "Combustível": "Combustivel",  
            "Quilometragem": "Km",
            "Situação": "Situação"
        }

        # Seleciona todos os pares label + valor
        blocos = pagina.locator("div.MuiGrid-item")
        total_blocos = await blocos.count()

        for i in range(total_blocos):
            bloco = blocos.nth(i)
            try:
                await bloco.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                
                label = await bloco.locator("label").inner_text()
                valor = await bloco.locator("p").inner_text()

                for campo, label_site in labels_procurados.items():
                    if label.strip().lower() == label_site.lower():
                        campos[campo] = valor.strip()
            except Exception:
                continue

    except Exception as e:
        logger.error(f"Erro ao extrair dados técnicos dinâmicos: {e}", exc_info=True)
        for campo in campos:
            if campos[campo] == "Não informado":
                campos[campo] = "Erro"

    return campos

async def tentar_extrair_preco(pagina, config: Config) -> str:
    try:
        selector = "div.produtoVendedor h2"  
        await pagina.wait_for_selector(selector, timeout=config.TIMEOUT_PADRAO)
        preco_raw = await pagina.locator(selector).inner_text()
        logger.info(f" Preço localizado: {preco_raw}")
    except Exception as e:
        logger.warning(f"Erro ao localizar o preço: {e}")
        return "Não informado"

    # Limpeza e formatação
    try:
        preco_limpo = preco_raw.replace("R$", "").replace("\xa0", "").replace(" ", "").replace(".", "").replace(",", ".").strip()
        preco_float = float(preco_limpo)
        preco_formatado = f"R$ {preco_float:,.2f}".replace(".", "X").replace(",", ".").replace("X", ",")
        return preco_formatado
    except Exception as e:
        logger.error(f"Erro ao formatar preço: {e}")
        return "Não informado"

async def tentar_extrair_revenda(pagina, config: Config) -> str:
    try:
        selector = "div.produtoVendedor span p"  
        await pagina.wait_for_selector(selector, timeout=30000)
        texto = await pagina.locator(selector).inner_text()
        revenda_text = texto.strip().title()
        logger.info(f" Localização da revenda: {revenda_text}")
        return revenda_text
    except Exception as e:
        logger.warning(f"Erro ao extrair localização: {e}")
        return "Não informado"

async def extracaoDadosTrucadao(pagina, config: Config) -> List[Dict]:
    dados_coletados = []
    try:
        botoes = pagina.locator('button.button', has_text="Ver anúncio")
        await pagina.wait_for_selector('button.button', timeout=config.TIMEOUT_PADRAO)
        total_botoes = await botoes.count()
        logger.info(f"{total_botoes} botões 'Ver anúncio' encontrados na página.")

        for i in range(min(config.MAX_BOTOES_POR_PAGINA, total_botoes)):
            logger.info(f"  Processando anúncio {i + 1}/{total_botoes}")
            botao = botoes.nth(i)

            try:
                await botao.scroll_into_view_if_needed()
                await botao.wait_for(state="attached", timeout=35000)
                await botao.hover()
                await asyncio.sleep(0.5)
                await botao.click(timeout=config.TIMEOUT_PADRAO)
                logger.info(f" Clicou no anúncio {i + 1}")
            except Exception as e:
                logger.warning(f" Falha ao clicar no botão {i + 1}: {e}")
                continue

            try:
                await pagina.wait_for_load_state("networkidle", timeout=30000)
                await asyncio.sleep(2.0)
            except PlaywrightTimeoutError:
                logger.warning(f" Timeout ao carregar anúncio {i + 1}, pulando para o próximo.")
                await pagina.go_back(timeout=config.TIMEOUT_PADRAO)
                await pagina.wait_for_selector('button.button', timeout=config.TIMEOUT_PADRAO)
                continue

            preco = await tentar_extrair_preco(pagina, config)
            logger.info(f" Preço extraído: {preco}")

            dados_tecnicos = await tentar_extrair_dados_tecnicos(pagina, config)
            logger.info(f" Dados técnicos extraídos.")

            revenda = await tentar_extrair_revenda(pagina, config)
            logger.info(f" Localização da revenda: {revenda}")

            url_anuncio = pagina.url
            dados_coletados.append({
                "Preço": preco,
                **dados_tecnicos,
                "Localização": revenda,
                "URL": url_anuncio
            })

            logger.info(" Voltando para listagem de anúncios...")
            try:
                await pagina.go_back(timeout=config.TIMEOUT_PADRAO)
                await pagina.wait_for_selector('button.button', timeout=config.TIMEOUT_PADRAO)
                await asyncio.sleep(1.0)
                logger.info("↩ Retornou com sucesso para a listagem")
            except Exception as e:
                logger.error(f" Erro ao retornar para a listagem: {e}")
                break

    except Exception as e:
        logger.error(f" Erro geral durante extração: {e}")
    return dados_coletados

async def coletar_dados_trucadao(pagina, config: Config) -> List[Dict]:
    todos_dados = []
    pagina_atual = 1

    while pagina_atual <= config.MAX_PAGINAS:
        logger.info(f" Página {pagina_atual} de {config.MAX_PAGINAS}")
        dados = await extracaoDadosTrucadao(pagina, config)
        todos_dados.extend(dados)

        try:
            proximo_botao = pagina.locator("button[aria-label='Go to next page']")
            await proximo_botao.scroll_into_view_if_needed()
            await proximo_botao.wait_for(state="visible", timeout=15000)

            if await proximo_botao.is_enabled():
                await asyncio.sleep(0.5)
                await proximo_botao.click()
                logger.info(" Clique realizado, aguardando próxima página...")
                await pagina.wait_for_selector('button.button', timeout=60000)
                pagina_atual += 1
                logger.info(f" Avançou para a página {pagina_atual}")
            else:
                logger.info(" Botão de próxima página desabilitado.")
                break
        except Exception as e:
            logger.warning(f" Falha ao mudar de página: {e}")
            break

    return todos_dados

async def iniciar_scraping():
    async with async_playwright() as p:
        try:
            navegador = await p.chromium.launch(headless=False, slow_mo=100)
            pagina = await navegador.new_page()
            config = Config()

            logger.info(f" Acessando {config.URL_BASE}")
            await pagina.goto(config.URL_BASE, timeout=80000)
            await pagina.wait_for_load_state("networkidle")

            dados = await coletar_dados_trucadao(pagina, config)

            if dados:
                df = pd.DataFrame(dados)
                df.to_excel(config.OUTPUT_FILE, index=False)
                logger.info(f" {len(dados)} registros salvos em {config.OUTPUT_FILE}")
            else:
                logger.warning(" Nenhum dado foi extraído.")
        except Exception as e:
            logger.critical(f" Erro crítico durante execução: {e}")
        finally:
            await navegador.close()

if __name__ == "__main__":
    asyncio.run(iniciar_scraping())