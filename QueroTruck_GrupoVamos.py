from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import pandas as pd
import re

def extracaoDados(pagina, xpath, site):
    dados_extraidos = []
    itens = pagina.locator(xpath)

    for i in range(1, itens.count() + 1):
        try:
            xpath_item = f"({xpath})[{i}]"
            informacoes = pagina.locator(f'xpath={xpath_item}').inner_text()
            print(f'Informações {i}: {informacoes}')
            
            if site == "querotruck":
                dados = separar_informacoes_querotruck(informacoes)
            elif site == "grupovamos":
                dados = separar_informacoes_grupovamos(informacoes)
            
            dados_extraidos.append(dados)
        except Exception as e:
            print(f"Erro ao extrair informações do item {i}: {e}")

    return dados_extraidos

def separar_informacoes_querotruck(informacoes):
    dados = {}

    try:
        informacoes_lista = [info.strip() for info in informacoes.split('\n') if info.strip()]
        
        if len(informacoes_lista) >= 4:

            marca_modelo = informacoes_lista[0].split(" ", 1) 
            if len(marca_modelo) >= 2:
                dados["Marca"] = marca_modelo[0]  
                dados["Modelo"] = marca_modelo[1] 
            else:
                dados["Marca"] = marca_modelo[0]  
                dados["Modelo"] = "Não informado" 

            dados["Preço"] = informacoes_lista[1]

            odometro = re.search(r"Odômetro\s*(\d[\d\.]*)", informacoes)
            dados["Quilometragem"] = odometro.group(1) if odometro else "Não informado"
            
            ano = re.search(r"Ano\s*(\d{4})", informacoes)
            dados["Ano"] = ano.group(1) if ano else "Não informado"
            
            anunciante = re.search(r"Anunciante\s*(.*)", informacoes)
            dados["Anunciante"] = anunciante.group(1) if anunciante else "Não informado"
            
            localizacao = re.search(r"([A-Za-zá-úA-Ú\s]+-\s?[A-Za-zá-úA-Ú\s]+)", informacoes)
            dados["Localização"] = localizacao.group(1) if localizacao else "Não informado"
              
        else:
            dados["Marca"] = "Não informado"
            dados["Modelo"] = "Não informado"
            dados["Preço"] = "Não informado"
            dados["Quilometragem"] = "Não informado"
            dados["Ano"] = "Não informado"
            dados["Anunciante"] = "Não informado"
            dados["Localização"] = "Não informado"
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
    dados = {}

    try:
        informacoes_lista = [info.strip() for info in informacoes.split('\n') if info.strip()]

        if len(informacoes_lista) >= 6:
            dados["Modelo"] = informacoes_lista[0]
            dados["Marca"] = informacoes_lista[1]
            dados["Localização"] = informacoes_lista[2]
            dados["Quilometragem"] = informacoes_lista[3] if len(informacoes_lista) > 3 else "Não informado" 
            dados["Ano"] = informacoes_lista[4] if len(informacoes_lista) > 4 else "Não informado"  
            dados["Preço"] = informacoes_lista[5] if len(informacoes_lista) > 5 else "Não informado"
        else:
            dados["Modelo"] = "Não informado"
            dados["Marca"] = "Não informado"
            dados["Localização"] = "Não informado"
            dados["Quilometragem"] = "Não informado"
            dados["Ano"] = "Não informado"
            dados["Preço"] = "Não informado"
    except Exception as e:
        print(f"Erro ao separar informações do Grupo Vamos: {e}")
        dados = {
            "Marca": "Erro",
            "Modelo": "Erro",
            "Preço": "Erro",
            "Quilometragem": "Erro",
            "Ano": "Erro",
            "Localização": "Erro",
        }

    return dados

def coletar_dados(url, xpath, seletor_proxima_pagina, site):
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()
        pagina.goto(url, timeout=120000)
        pagina.wait_for_load_state('load', timeout=120000)

        todos_os_dados = []

        while True:
            print("Coletando dados da página...")
            pagina.wait_for_selector(xpath, timeout=120000)
            dados_atual = extracaoDados(pagina, xpath, site)
            todos_os_dados.extend(dados_atual)
            time.sleep(5)

            try:
                pagina.wait_for_selector(seletor_proxima_pagina, timeout=120000)
                proxima_pagina = pagina.locator(seletor_proxima_pagina)

                if proxima_pagina.count() > 0 and proxima_pagina.is_visible():
                    desativado = proxima_pagina.get_attribute("disabled")
                    classe_botao = proxima_pagina.get_attribute("class")

                    if not desativado and (classe_botao is None or "p-disabled" not in classe_botao):
                        print("Indo para a próxima página...")
                        proxima_pagina.click()
                        pagina.wait_for_load_state('networkidle')
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

url_caminhoes = "https://querotruck.com.br/anuncios/pesquisa-veiculos?categoria=CAVALO%2520MEC%25C3%2582NICO&sortType=asc&sortField=OrderedAt&pageSize=40&pageIndex=1"
xpath_caminhoes = "//app-truck-card/a/a"
seletor_proxima_pagina_caminhoes = '//button[contains(@class, "p-paginator-next")]'

url_seminovos = "https://vamos.com.br/seminovos/cavalo-mecanico"
xpath_seminovos = "//app-offer-card/div/a"
seletor_proxima_pagina_seminovos = 'xpath=//*[@id="paginador"]/pagination-template/nav/ul/li[13]/a'

dados_caminhoes = coletar_dados(url_caminhoes, xpath_caminhoes, seletor_proxima_pagina_caminhoes, site="querotruck")
dados_seminovos = coletar_dados(url_seminovos, xpath_seminovos, seletor_proxima_pagina_seminovos, site="grupovamos")

df_caminhoes = pd.DataFrame(dados_caminhoes)
df_seminovos = pd.DataFrame(dados_seminovos)

with pd.ExcelWriter('dados_Truck&Vamos.xlsx') as writer:
    df_caminhoes.to_excel(writer, sheet_name='QueroTruck', index=False)
    df_seminovos.to_excel(writer, sheet_name='GrupoVamos', index=False)

print("Dados exportados para 'dados_Truck&Vamos.xlsx' com abas separadas")
