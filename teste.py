from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import pandas as pd
import asyncio
import logging
from typing import Dict, List

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Config:
    URL_BASE = 'https://www.trucadao.com.br/venda/caminhoes-usados?tipo=cavalo-mecanico&page=1'
    MAX_PAGINAS = 10
    MAX_RETRIES = 3
    TIMEOUT_PADRAO = 15000  # 
    OUTPUT_FILE = 'dados_trucadao_completos.xlsx'

async def extrair_informacoes_tecnicas(informacoes_tcn: str) -> Dict[str, str]:
    try:
        linhas = [linha.strip() for linha in informacoes_tcn.split("\n") if linha.strip()]
        dados = {
            "Tipo": "Não informado",
            "Marca": "Não informado",
            "Modelo": "Não informado",
            "Ano": "Não informado",
            "Situação": "Não informado",
            "Quilometragem": "Não informado",
            "Combustível": "Não informado",
            "Cor": "Não informado"
        }
        
        mapeamento = {
            "Tipo": "Tipo",
            "Marca": "Marca",
            "Modelo": "Modelo",
            "Ano": "Ano",
            "Situação": "Situação",
            "Quilometragem": ["Quilometragem", "Km"],
            "Combustível": "Combustível",
            "Cor": "Cor"
        }
        
        for i, linha in enumerate(linhas[:-1]):
            for chave, valor in mapeamento.items():
                matchers = valor if isinstance(valor, list) else [valor]
                if any(matcher in linha for matcher in matchers) and i + 1 < len(linhas):
                    dados[chave] = linhas[i + 1]
        
        return dados
    except Exception as e:
        logger.error(f"Erro ao processar informações técnicas: {e}")
        return {k: "Erro" for k in dados.keys()}

async def tentar_extrair_preco(botao_atual, pagina, config: Config) -> str:
    preco_selector = '//*[@id="__next"]/div[2]/div/div[1]/div/div/h5[2]' 
    for attempt in range(config.MAX_RETRIES):
        try:
            logger.debug("Iniciando clique no botão")
            await botao_atual.scroll_into_view_if_needed()
            await botao_atual.click(timeout=config.TIMEOUT_PADRAO)
            logger.debug("Aguardando selector de preço")
            await pagina.wait_for_selector(preco_selector, timeout=config.TIMEOUT_PADRAO)
            preco = await pagina.locator(preco_selector).inner_text()
            if not any(char.isdigit() for char in preco):
                return "Preço inválido"
            return preco
        except PlaywrightTimeoutError as e:
            logger.warning(f"Tentativa {attempt + 1}/{config.MAX_RETRIES} falhou: {e}")
            if attempt == config.MAX_RETRIES - 1:
                logger.error("Preço não encontrado após todas as retentativas")
                return "Não informado"
            await asyncio.sleep(10)  # Aumentado para 10 segundos
    return "Não informado"

async def tentar_extrair_dados_tecnicos(pagina, config: Config) -> Dict[str, str]:
    try:
        info_selector = '.MuiGrid-root.MuiGrid-container.css-3uuuu9'
        logger.debug("Aguardando selector de informações técnicas")
        await pagina.wait_for_selector(info_selector, timeout=config.TIMEOUT_PADRAO)
        informacoes_tcn = await pagina.locator(info_selector).inner_text()
        return await extrair_informacoes_tecnicas(informacoes_tcn)
    except Exception as e:
        logger.error(f"Erro nos dados técnicos: {e}")
        return {k: "Erro" for k in ["Tipo", "Marca", "Modelo", "Ano", 
                                  "Situação", "Quilometragem", "Combustível", "Cor"]}

async def tentar_extrair_revenda(pagina, config: Config) -> str:
    try:
        revenda_selector = '//*[@id="__next"]/div[2]/div/div[2]/div[2]/div[1]/span/p'
        logger.debug("Aguardando selector de revenda")
        await pagina.wait_for_selector(revenda_selector, timeout=config.TIMEOUT_PADRAO)
        return await pagina.locator(revenda_selector).inner_text()
    except Exception as e:
        logger.error(f"Erro na revenda: {e}")
        return "Não informado"

async def extracaoDadosTrucadao(pagina, config: Config = Config()) -> List[Dict]:
    links = []
    try:
        botoes = pagina.locator('xpath=//*[@id="__next"]/div[3]/div/div[2]//button')
        await pagina.wait_for_selector('xpath=//*[@id="__next"]/div[3]/div/div[2]//button', 
                                     timeout=config.TIMEOUT_PADRAO)
        total_botoes = await botoes.count()
        logger.info(f"Encontrados {total_botoes} botões na página.")
        
        for i in range(total_botoes):
            logger.info(f"Processando botão {i + 1}/{total_botoes}")
            botao_atual = botoes.nth(i)
            
            if not await botao_atual.is_enabled() or not await botao_atual.is_visible():
                logger.warning(f"Botão {i + 1} não disponível")
                continue
                
            preco = await tentar_extrair_preco(botao_atual, pagina, config)
            dados_tecnicos = await tentar_extrair_dados_tecnicos(pagina, config)
            informacoes_rv = await tentar_extrair_revenda(pagina, config)
            
            links.append({
                "Preço": preco,
                **dados_tecnicos,
                "Localização": informacoes_rv
            })
            
            logger.debug("Voltando para página anterior")
            await pagina.go_back(timeout=config.TIMEOUT_PADRAO)
            await pagina.wait_for_selector('xpath=//*[@id="__next"]/div[3]/div/div[2]//button', 
                                         timeout=config.TIMEOUT_PADRAO)
            
    except Exception as e:
        logger.error(f"Erro geral na extração: {e}")
    
    return links

async def coletar_dados_trucadao(pagina, config: Config = Config()) -> List[Dict]:
    todos_links = []
    pagina_atual = 1

    while pagina_atual <= config.MAX_PAGINAS:
        logger.info(f"Coletando dados da página {pagina_atual}/{config.MAX_PAGINAS}")
        links_atuais = await extracaoDadosTrucadao(pagina, config)
        todos_links.extend(links_atuais)

        try:
            botao_xpath = '//*[@id="__next"]/div[3]/div/nav/ul/li[9]/a'
            await pagina.wait_for_selector(botao_xpath, timeout=15000)
            proxima_pagina = pagina.locator(botao_xpath)

            if await proxima_pagina.is_visible() and await proxima_pagina.is_enabled():
                logger.info(f"Indo para a página {pagina_atual + 1}")
                await proxima_pagina.click()
                await pagina.wait_for_selector('xpath=//*[@id="__next"]/div[3]/div/div[2]//button', 
                                             timeout=config.TIMEOUT_PADRAO)
                pagina_atual += 1
            else:
                logger.info("Botão da próxima página não está clicável. Encerrando.")
                break
        except Exception as e:
            logger.error(f"Erro ao avançar para a próxima página: {e}")
            break

    return todos_links

async def iniciar_scraping():
    async with async_playwright() as p:
        try:
            navegador = await p.chromium.launch(headless=True)
            pagina = await navegador.new_page()
            config = Config()
            
            logger.info(f"Acessando {config.URL_BASE}")
            await pagina.goto(config.URL_BASE, timeout=120000)
            await pagina.wait_for_selector('xpath=//*[@id="__next"]/div[3]/div/div[2]//button', 
                                         timeout=config.TIMEOUT_PADRAO)
            
            todos_os_dados = await coletar_dados_trucadao(pagina, config)
            
            if todos_os_dados:
                df = pd.DataFrame(todos_os_dados)
                df.to_excel(config.OUTPUT_FILE, index=False)
                logger.info(f"Dados salvos em {config.OUTPUT_FILE} com {len(todos_os_dados)} registros")
            else:
                logger.warning("Nenhum dado coletado")
                
        except Exception as e:
            logger.error(f"Erro crítico no scraping: {e}")
        finally:
            await navegador.close()

if __name__ == "__main__":
    asyncio.run(iniciar_scraping())