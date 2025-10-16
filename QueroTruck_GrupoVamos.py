from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import pandas as pd
import re

def extracaoDadosQueroTrck(pagina, xpath, site):
    dados_extraidos = []
    itens = pagina.locator(xpath)

    for i in range(1, itens.count() + 1):
        try:
            xpath_item = f"({xpath})[{i}]"
            informacoes = pagina.locator(f'xpath={xpath_item}').inner_text()
            print(f'Informações {i}: {informacoes}')  
            dados = separar_informacoes_querotruck(informacoes)
            dados_extraidos.append(dados)
        except Exception as e:
            print(f"Erro ao extrair informações do item {i}: {e}")

    return dados_extraidos

def extracaoDadosGrupoVamos(pagina, xpath_card, site=None):
    dados_extraidos = []
    cards = pagina.locator(xpath_card)

    total = cards.count()
    print(f"Total de cards encontrados: {total}")

    for i in range(total):
        try:
            card = cards.nth(i)

            try:
                modelo = card.locator("h2").inner_text(timeout=2000)
            except:
                modelo = "Não informado"

            try:
                marca = card.locator("p.ejs-paragraph.cor-black.s4.fw500.upc.mbauto").inner_text(timeout=2000)
            except:
                marca = "Não informado"

            info_divs = card.locator('div.flex.flex-items-center')

            local = km = ano = "Não informado"

            for j in range(info_divs.count()):
                div = info_divs.nth(j)
                try:
                    img = div.locator("img")
                    if img.count() > 0:
                        alt = img.get_attribute("alt")  # ← isso vai conter: ico-location.svg, ico-km.svg, ico-data.svg
                        texto = div.locator("p").inner_text().strip()

                        if alt == "ico-location.svg":
                            local = texto
                        elif alt == "ico-km.svg":
                            km = texto
                        elif alt == "ico-data.svg":
                            ano = texto
                except:
                    continue

            try:
                preco_raw = card.locator("strong.cor-black.s10.fw600.mtauto").inner_text(timeout=2000)
                preco = preco_raw.replace("\xa0", " ").strip()
            except:
                preco = "Não informado"

            dados = {
                "Modelo": modelo.strip(),
                "Marca": marca.strip(),
                "Localização": local,
                "Quilometragem": km,
                "Ano": ano,
                "Preço": preco.strip(),
                "Anunciante": "Grupo Vamos"
            }
            dados_extraidos.append(dados)

        except Exception as e:
            print(f"Erro ao extrair card {i}: {e}")
            dados_extraidos.append({
                "Modelo": "Erro",
                "Marca": "Erro",
                "Localização": "Erro",
                "Quilometragem": "Erro",
                "Ano": "Erro",
                "Preço": "Erro",
                "Anunciante": "Erro"
            })

    return dados_extraidos

def separar_informacoes_querotruck(informacoes):
    dados = {
        "Marca": "Não informado",
        "Modelo": "Não informado",
        "Preço": "Não informado",
        "Quilometragem": "Não informado",
        "Ano": "Não informado",
        "Anunciante": "Não informado",
        "Localização": "Não informado"
    }

    try:
        linhas = [linha.strip() for linha in informacoes.split('\n') if linha.strip()]

        if len(linhas) >= 2:
            # Primeira linha: Marca e Modelo
            marca_modelo = linhas[0].split(" ", 1)
            dados["Marca"] = marca_modelo[0]
            dados["Modelo"] = marca_modelo[1] if len(marca_modelo) > 1 else "Não informado"

            # Segunda linha: Preço
            dados["Preço"] = linhas[1] if "R$" in linhas[1] else "Não informado"

        for i, linha in enumerate(linhas):
            if "ODÔMETRO" in linha.upper() and i + 1 < len(linhas):
                km = re.search(r"([\d\.]+)", linhas[i + 1])
                dados["Quilometragem"] = km.group(1).replace('.', '') + " km" if km else "Não informado"

            elif "ANO" in linha.upper() and i + 1 < len(linhas):
                ano = re.search(r"\d{4}(?:/\d{4})?", linhas[i + 1])
                dados["Ano"] = ano.group(0) if ano else "Não informado"

            elif "ANUNCIANTE" in linha.upper() and i + 1 < len(linhas):
                dados["Anunciante"] = linhas[i + 1].strip()

            # Tenta encontrar uma linha com formato "Cidade - UF"
            for linha in reversed(linhas):
                if re.search(r"[A-Za-zÀ-ÿ\s]+[-–]\s?[A-Z]{2}$", linha):
                    dados["Localização"] = linha.strip()
                    break
            # Caso não encontre, tenta capturar a última linha que seja uma cidade isolada (sem "- UF")
            if dados["Localização"] == "Não informado":
                for linha in reversed(linhas):
                    if re.match(r"^[A-Za-zÀ-ÿ\s]+$", linha) and len(linha.split()) <= 4:
                        dados["Localização"] = linha.strip()
                        break

    except Exception as e:
        print(f"Erro ao separar informações do QueroTruck: {e}")
        dados = {
            "Marca": "Erro",
            "Modelo": "Erro",
            "Preço": "Erro",
            "Quilometragem": "Erro",
            "Ano": "Erro",
            "Anunciante": "Erro",
            "Localização": "Erro"
        }

    return dados

def separar_informacoes_grupovamos(informacoes):
    dados = {
        "Modelo": "Não informado",
        "Marca": "Não informado",
        "Localização": "Não informado",
        "Quilometragem": "Não informado",
        "Ano": "Não informado",
        "Preço": "Não informado",
        "Anunciante": "Não informado"
    }

    try:
        linhas = [linha.strip() for linha in informacoes.split('\n') if linha.strip()]

        # Garantir que todas as 6 linhas estão presentes e válidas
        if len(linhas) == 6:
            modelo, marca, local, km, ano, preco = linhas

            if any(campo.lower() in ["não informado", ""] for campo in linhas):
                return dados  # ignora entrada inválida

            dados.update({
                "Modelo": modelo,
                "Marca": marca,
                "Localização": local,
                "Quilometragem": km,
                "Ano": ano,
                "Preço": preco,
                "Anunciante": "Não informado"
            })
    except Exception as e:
        print(f"Erro ao separar informações do Grupo Vamos: {e}")
        dados = {
            "Modelo": "Erro",
            "Marca": "Erro",
            "Localização": "Erro",
            "Quilometragem": "Erro",
            "Ano": "Erro",
            "Preço": "Erro",
            "Anunciante": "Erro"
        }

    return dados

def coletar_dados(url, xpath, seletor_proxima_pagina, func_extracao, site):
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()
        pagina.goto(url, timeout=320000)
        pagina.wait_for_load_state('load', timeout=320000)

        todos_os_dados = []

        while True:
            print("Coletando dados da página...")
            if site == "grupovamos":
                pagina.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(3)

            pagina.wait_for_selector(xpath, timeout=320000)
            dados_atual = func_extracao(pagina, xpath, site)
            todos_os_dados.extend(dados_atual)
            time.sleep(5)

            try:
                # Timeout diferente para cada site (mais seguro para a Vamos)
                timeout_proxima_pagina = 10000 if site == "querotruck" else 30000
                pagina.wait_for_selector(seletor_proxima_pagina, timeout=timeout_proxima_pagina)
                proxima_pagina = pagina.locator(seletor_proxima_pagina)

                if proxima_pagina.count() > 0 and proxima_pagina.is_visible():
                    desativado = proxima_pagina.get_attribute("disabled")
                    classe_botao = proxima_pagina.get_attribute("class")

                    if not desativado and (classe_botao is None or "p-disabled" not in classe_botao):
                        
                        if site == "querotruck":
                            print("Indo para a próxima página (QueroTruck)...")
                            proxima_pagina.scroll_into_view_if_needed()
                            proxima_pagina.click()

                            # Espera robusta após o clique → espera os cards recarregarem
                            pagina.wait_for_selector(xpath, timeout=30000)
                            time.sleep(2)
                        else:  # grupo vamos
                            print("Indo para a próxima página (GrupoVamos)...")
                            proxima_pagina.click()
                            pagina.wait_for_load_state('load', timeout=320000)
                            time.sleep(2)
                        
                    else:
                        print("Última página alcançada (botão desativado).")
                        break
                else:
                    print("Última página alcançada.")
                    break
            except Exception as e:
                print(f"Erro ao verificar/acionar botão de próxima página: {e}")
                break

        return todos_os_dados

url_seminovos = "https://vamos.com.br/seminovos/cavalo-mecanico"
xpath_seminovos = "//app-offer-card"
seletor_proxima_pagina_seminovos = 'xpath=//*[@id="paginador"]/pagination-template/nav/ul/li[13]/a'

# Grupo Vamos
dados_seminovos = coletar_dados(
    url_seminovos,
    xpath_seminovos,
    seletor_proxima_pagina_seminovos,
    func_extracao=extracaoDadosGrupoVamos,
    site="grupovamos"
)

df_seminovos = pd.DataFrame(dados_seminovos)

with pd.ExcelWriter('dados_Truck&Vamos.xlsx') as writer:
    df_seminovos.to_excel(writer, sheet_name='GrupoVamos', index=False)

print("Dados exportados para 'dados_Truck&Vamos.xlsx' com abas separadas")
