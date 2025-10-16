import os, sys, re, asyncio, logging, unicodedata
from time import time
from typing import Dict, List, Any, Optional
import pandas as pd
from tqdm import tqdm
from playwright.async_api import async_playwright, TimeoutError as PLTimeout

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("trucadao-por-links")

ARQUIVO_EXCEL_LINKS   = "Links_Truncadao.xlsx"      
ARQUIVO_PKL_DADOS     = "trucadao.pkl"
ARQUIVO_EXCEL_DADOS   = "trucadao.xlsx"
ARQUIVO_CHECKPOINT    = "checkpoint_trucadao.pkl"

TIMEOUT = 30000
RETRIES = 3
MAX_CONCURRENT = 12
HEADLESS = True

DETAIL_SELECTOR = "div.produtoVendedor"

PAINEL_TEC_CSS = 'div[role="tabpanel"][id$="-P-1"]'
GRID_ITEMS_CSS = f'{PAINEL_TEC_CSS} > div > div'   


SELETORES_DIRETOS: Dict[str, List[str]] = {
    "Marca": [
        '#mui-p-86844-P-1 > div > div:nth-child(2) > p.MuiTypography-root.MuiTypography-body1.css-9l3uo3',
        '//*[@id="mui-p-86844-P-1"]/div/div[2]/p[2]',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(2) p.MuiTypography-body1:last-of-type',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(2) p:nth-of-type(2)',
    ],
    "Modelo": [
        '#mui-p-86844-P-1 > div > div:nth-child(3) > p.MuiTypography-root.MuiTypography-body1.css-9l3uo3',
        '//*[@id="mui-p-86844-P-1"]/div/div[3]/p[2]',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(3) p.MuiTypography-body1:last-of-type',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(3) p:nth-of-type(2)',
    ],
    "Ano": [
        '#mui-p-86844-P-1 > div > div:nth-child(4) > p.MuiTypography-root.MuiTypography-body1.css-9l3uo3',
        '//*[@id="mui-p-86844-P-1"]/div/div[4]/p[2]',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(4) p.MuiTypography-body1:last-of-type',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(4) p:nth-of-type(2)',
    ],
    "Km": [
        '#mui-p-86844-P-1 > div > div:nth-child(6) > p.MuiTypography-root.MuiTypography-body1.css-9l3uo3',
        '//*[@id="mui-p-86844-P-1"]/div/div[6]/p[2]',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(6) p.MuiTypography-body1:last-of-type',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(6) p:nth-of-type(2)',
    ],
    "Combustível": [
        '#mui-p-86844-P-1 > div > div:nth-child(7) > p.MuiTypography-root.MuiTypography-body1.css-9l3uo3',
        '//*[@id="mui-p-86844-P-1"]/div/div[7]/p[2]',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(7) p.MuiTypography-body1:last-of-type',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(7) p:nth-of-type(2)',
    ],
    "Cor": [
        '#mui-p-86844-P-1 > div > div:nth-child(8) > p.MuiTypography-root.MuiTypography-body1.css-9l3uo3',
        '//*[@id="mui-p-86844-P-1"]/div/div[8]/p[2]',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(8) p.MuiTypography-body1:last-of-type',
        f'{PAINEL_TEC_CSS} > div > div:nth-child(8) p:nth-of-type(2)',
    ],
}

# Título, preço, localização (mantive como antes)
SELECTORES_CABECALHO = {
    "Título": [
        "div.produtoVendedor h1", "article h1", "//h1"
    ],
    "Preço": [
        "div.produtoVendedor h2",
        "//div[contains(@class,'produtoVendedor')]//h2",
        "//h2[contains(.,'R$') or contains(., 'R\u0024')]",
    ],
    "Localização": [
        "div.produtoVendedor span p",
        "//div[contains(@class,'produtoVendedor')]//span//p"
    ],
}

def _norm(txt: str) -> str:
    if not txt: return ""
    x = unicodedata.normalize("NFKD", txt)
    x = "".join(c for c in x if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", x).strip().lower()

def formatar_preco(preco_raw: str) -> str:
    try:
        preco_limpo = (preco_raw or "").replace("R$", "").replace("\xa0", "").replace(" ", "")
        preco_limpo = preco_limpo.replace(".", "").replace(",", ".").strip()
        v = float(preco_limpo)
        return f"R$ {v:,.2f}".replace(".", "X").replace(",", ".").replace("X", ",")
    except Exception:
        return (preco_raw or "").strip() or "Não informado"

def split_cidade_uf(txt: str):
    if not txt: return "", ""
    ped = [p.strip() for p in txt.split("-")]
    if len(ped) >= 2 and len(ped[-1]) in (2, 3):  # UF
        return "-".join(ped[:-1]).strip(), ped[-1].strip()
    return txt.strip(), ""

async def extrair_primeiro_texto(page, seletores: List[str], default="Não informado") -> str:
    for sel in seletores:
        try:
            loc = page.locator(f"xpath={sel}" if sel.strip().startswith("//") else sel).first
            if await loc.count() > 0:
                txt = await loc.text_content(timeout=TIMEOUT)
                if txt and txt.strip():
                    return txt.strip()
        except Exception:
            continue
    return default

async def carregar_links(arquivo: str) -> List[str]:
    if not os.path.exists(arquivo):
        logger.error(f"Arquivo {arquivo} não encontrado.")
        return []
    df = await asyncio.to_thread(pd.read_excel, arquivo)
    # coluna 'link' (case-insensitive)
    cols = {c.lower(): c for c in df.columns}
    if "link" not in cols:
        logger.error("Coluna 'link' não encontrada.")
        return []
    col = cols["link"]
    links = df[col].dropna().astype(str).str.strip().unique().tolist()
    logger.info(f"{len(links)} links únicos carregados de {arquivo}.")
    return links

ROTULOS_MAP = {
    "marca": "Marca",
    "modelo": "Modelo",
    "ano": "Ano",
    "km": "Km",
    "quilometragem": "Km",
    "combust": "Combustível",
    "cor": "Cor",
}

async def extrair_grid_por_rotulo(page) -> Dict[str, str]:
    dados = {v: "Não informado" for v in set(ROTULOS_MAP.values())}
    try:
        await page.wait_for_selector(GRID_ITEMS_CSS, timeout=5000)
        linhas = page.locator(GRID_ITEMS_CSS)
        total = await linhas.count()
        for i in range(total):
            row = linhas.nth(i)
            try:
                p_all = row.locator("p")
                if await p_all.count() < 2:
                    continue
                rotulo = await p_all.nth(0).inner_text()
                valor  = await p_all.nth(1).inner_text()
                r = _norm(rotulo)
                for key, destino in ROTULOS_MAP.items():
                    if key in r:
                        dados[destino] = (valor or "").strip()
                        break
            except Exception:
                continue
    except Exception:
        pass
    return dados

async def extrair_por_seletores(page) -> Dict[str, str]:
    out = {k: "Não informado" for k in SELETORES_DIRETOS.keys()}
    for campo, sels in SELETORES_DIRETOS.items():
        out[campo] = await extrair_primeiro_texto(page, sels)
    return out

async def extrair_detalhe(context, link: str, sem: asyncio.Semaphore) -> Optional[Dict[str, Any]]:
    async with sem:
        page = await context.new_page()
        try:
            for tentativa in range(1, RETRIES + 1):
                try:
                    resp = await page.goto(link, timeout=TIMEOUT, wait_until="domcontentloaded")
                    if not resp or resp.status >= 400:
                        raise RuntimeError(f"HTTP {resp.status if resp else 'N/A'}")

                    # garante o detalhe e tenta rolar até o painel técnico
                    await page.wait_for_selector(DETAIL_SELECTOR, timeout=TIMEOUT)
                    await page.evaluate("window.scrollBy(0, 800)")
                    await asyncio.sleep(0.2)

                    # Cabeçalho
                    titulo = await extrair_primeiro_texto(page, SELECTORES_CABECALHO["Título"])
                    preco_raw = await extrair_primeiro_texto(page, SELECTORES_CABECALHO["Preço"])
                    loc_raw   = await extrair_primeiro_texto(page, SELECTORES_CABECALHO["Localização"])
                    cidade, uf = split_cidade_uf(loc_raw)

                    # Técnicos: tenta 1) diretos; se falhar algo, 2) por rótulo
                    tecnicos = await extrair_por_seletores(page)
                    faltando = [k for k, v in tecnicos.items() if not v or v == "Não informado"]
                    if faltando:
                        tecnicos2 = await extrair_grid_por_rotulo(page)
                        for k in tecnicos:
                            if tecnicos[k] == "Não informado" and tecnicos2.get(k) and tecnicos2[k] != "Não informado":
                                tecnicos[k] = tecnicos2[k]

                    dados = {
                        "Link": link,
                        "Título": titulo,
                        "Preço_raw": preco_raw,
                        "Preço": formatar_preco(preco_raw),
                        "Localização": loc_raw,
                        "Cidade": cidade,
                        "UF": uf,
                        **tecnicos,
                    }
                    return dados

                except Exception as e:
                    logger.warning(f"Tentativa {tentativa}/{RETRIES} falhou para {link}: {e}")
                    await asyncio.sleep(0.7)
            return None
        finally:
            await page.close()

async def processar_links(links: List[str]) -> List[Dict[str, Any]]:
    inicio = time()
    coletados: List[Dict[str, Any]] = []
    ja = set()

    if os.path.exists(ARQUIVO_CHECKPOINT):
        try:
            prev = pd.read_pickle(ARQUIVO_CHECKPOINT)
            if isinstance(prev, pd.DataFrame):
                prev = prev.to_dict("records")
            coletados.extend(prev or [])
            ja = {d.get("Link") for d in coletados if d.get("Link")}
            links = [lk for lk in links if lk not in ja]
            logger.info(f"Checkpoint: {len(coletados)} prontos, {len(links)} restantes.")
        except Exception as e:
            logger.error(f"Erro ao carregar checkpoint: {e}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context()
        sem = asyncio.Semaphore(MAX_CONCURRENT)

        for i in range(0, len(links), MAX_CONCURRENT):
            lote = links[i:i+MAX_CONCURRENT]
            tarefas = [extrair_detalhe(context, lk, sem) for lk in lote]
            for coro in tqdm(asyncio.as_completed(tarefas), total=len(tarefas), desc=f"Lote {i//MAX_CONCURRENT+1}"):
                try:
                    res = await coro
                    if res:
                        coletados.append(res)
                        if len(coletados) % 200 == 0:
                            pd.DataFrame(coletados).to_pickle(ARQUIVO_CHECKPOINT)
                            logger.info(f"{len(coletados)} regs salvos no checkpoint.")
                except Exception as e:
                    logger.error(f"Erro em tarefa: {e}")
            await asyncio.sleep(0.25)

        await context.close()
        await browser.close()

    logger.info(f"Finalizado em {time()-inicio:.1f}s com {len(coletados)} registros.")
    return coletados

async def salvar(dados: List[Dict[str, Any]]):
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
        if os.path.exists(ARQUIVO_EXCEL_DADOS):
            df_exist = await asyncio.to_thread(pd.read_excel, ARQUIVO_EXCEL_DADOS, engine="openpyxl")
            df_final = pd.concat([df_exist, df], ignore_index=True)
        else:
            df_final = df
        await asyncio.to_thread(df_final.to_excel, ARQUIVO_EXCEL_DADOS, index=False, engine="openpyxl")
        logger.info(f"Excel salvo: {ARQUIVO_EXCEL_DADOS}")
    except Exception as e:
        logger.error(f"Erro ao salvar Excel: {e}")

async def main():
    links = await carregar_links(ARQUIVO_EXCEL_LINKS)
    if not links:
        return
    dados = await processar_links(links)
    await salvar(dados)

if __name__ == "__main__":
    asyncio.run(main())