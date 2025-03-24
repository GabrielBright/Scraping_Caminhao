from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import pandas as pd
import asyncio

async def extrair_informacoes_tecnicas(informacoes_tcn):
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

    for i in range(len(linhas) - 1):
        if "Tipo" in linhas[i]:
            dados["Tipo"] = linhas[i + 1]
        elif "Marca" in linhas[i]:
            dados["Marca"] = linhas[i + 1]
        elif "Modelo" in linhas[i]:
            dados["Modelo"] = linhas[i + 1]
        elif "Ano" in linhas[i]:
            dados["Ano"] = linhas[i + 1]
        elif "Situação" in linhas[i]:
            dados["Situação"] = linhas[i + 1]
        elif "Quilometragem" in linhas[i] or "Km" in linhas[i]:
            dados["Quilometragem"] = linhas[i + 1]
        elif "Combustível" in linhas[i]:
            dados["Combustível"] = linhas[i + 1]
        elif "Cor" in linhas[i]:
            dados["Cor"] = linhas[i + 1]

    return dados

async def extracaoDadosTrucadao(pagina, max_retries=3):
    links = []
    try:
        botoes = pagina.locator('xpath=//*[@id="__next"]/div[3]/div/div[2]//button')
        await pagina.wait_for_selector('xpath=//*[@id="__next"]/div[3]/div/div[2]//button', timeout=30000)
        total_botoes = await botoes.count()
        print(f"Encontrados {total_botoes} botões na página.")
        
        for i in range(total_botoes):
            print(f"Clicando no botão {i + 1} de {total_botoes}...")
            botao_atual = botoes.nth(i)

            if not await botao_atual.is_enabled() or not await botao_atual.is_visible():
                print(f"Botão {i + 1} não está disponível. Pulando.")
                continue

            for attempt in range(max_retries):
                try:
                    await botao_atual.scroll_into_view_if_needed()
                    await botao_atual.click(timeout=30000)
                    await pagina.wait_for_load_state('networkidle', timeout=30000)

                    preco_selector = '//*[@id="__next"]/div[2]/div/div[1]/div/div/h5[2]'
                    await pagina.wait_for_selector(preco_selector, timeout=60000)
                    preco = await pagina.locator(preco_selector).inner_text()
                    break  # Sai do loop de retentativas se sucesso
                except PlaywrightTimeoutError as e:
                    print(f"Tentativa {attempt + 1}/{max_retries} falhou ao extrair Preço: {e}")
                    if attempt == max_retries - 1:
                        preco = "Não informado"
                    await asyncio.sleep(2)  # Pequena pausa antes de retentativa

            dados_tecnicos = {
                "Tipo": "Erro", "Marca": "Erro", "Modelo": "Erro", "Ano": "Erro",
                "Situação": "Erro", "Quilometragem": "Erro", "Combustível": "Erro", "Cor": "Erro"
            }

            try:
                info_selector = '.MuiGrid-root.MuiGrid-container.css-3uuuu9'
                await pagina.wait_for_selector(info_selector, timeout=30000)
                informacoes_tcn = await pagina.locator(info_selector).inner_text()
                dados_tecnicos = await extrair_informacoes_tecnicas(informacoes_tcn)
            except Exception as e:
                print(f"Erro ao extrair Informações Técnicas: {e}")

            try:
                revenda_selector = '//*[@id="__next"]/div[2]/div/div[2]/div[2]/div[1]/span/p'
                await pagina.wait_for_selector(revenda_selector, timeout=30000)
                informacoes_rv = await pagina.locator(revenda_selector).inner_text()
            except Exception as e:
                print(f"Erro ao extrair Informações Revenda: {e}")
                informacoes_rv = "Não informado"

            links.append({
                "Preço": preco,
                **dados_tecnicos,
                "Localização": informacoes_rv
            })

            await pagina.go_back()
            await pagina.wait_for_load_state('networkidle', timeout=30000)

    except Exception as e:
        print(f"Erro geral ao extrair dados: {e}")

    return links

async def coletar_dados_trucadao(pagina):
    todos_links = []
    pagina_atual = 1
    max_paginas = 10

    while pagina_atual <= max_paginas:
        print(f"Coletando dados da página {pagina_atual} do Trucadão...")
        links_atuais = await extracaoDadosTrucadao(pagina)
        todos_links.extend(links_atuais)

        try:
            botao_xpath = '//*[@id="__next"]/div[3]/div/nav/ul/li[9]/a'
            await pagina.wait_for_selector(botao_xpath, timeout=15000)
            proxima_pagina = pagina.locator(botao_xpath)

            if await proxima_pagina.is_visible() and await proxima_pagina.is_enabled():
                print(f"Indo para a página {pagina_atual + 1}...")
                await proxima_pagina.click()
                await pagina.wait_for_load_state('networkidle', timeout=30000)
                pagina_atual += 1
            else:
                print("Botão da próxima página não está clicável. Encerrando.")
                break
        except Exception as e:
            print(f"Erro ao avançar para a próxima página: {e}")
            break

    return todos_links

async def iniciar_scraping():
    async with async_playwright() as p:
        navegador = await p.chromium.launch(headless=True)  # headless para menos consumo de recursos
        pagina = await navegador.new_page()
        url = 'https://www.trucadao.com.br/venda/caminhoes-usados?tipo=cavalo-mecanico&page=1'
        try:
            await pagina.goto(url, timeout=120000)
            await pagina.wait_for_load_state('load', timeout=120000)

            todos_os_dados = await coletar_dados_trucadao(pagina)

            df = pd.DataFrame(todos_os_dados)
            df.to_excel('dados_trucadao_completos.xlsx', index=False)
            print("Dados salvos em 'dados_trucadao_completos.xlsx'.")
        except Exception as e:
            print(f"Erro crítico no scraping: {e}")
        finally:
            await navegador.close()

if __name__ == "__main__":
    asyncio.run(iniciar_scraping())