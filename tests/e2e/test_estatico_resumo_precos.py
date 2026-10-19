"""Frases de resumo dos gráficos de preços, frete, custo por nutriente, relação de troca e Brasil x
mercado internacional no site montado pelo build_site.sh (src/estatico/resumo_precos.py), no
navegador.

- Sem JavaScript (o que os buscadores e quem lê sem script recebem), o HTML do build é igual ao
  que o script desenha na visão padrão: mesmo innerHTML das frases e mesmos aria-labels.
- Com JavaScript, as frases acompanham o grupo, o período, o produto do benchmark e a moeda do
  custo por nutriente, e para cada combinação são as mesmas que o Python escreveria (as duas
  versões das regras não podem divergir).

Roda com Playwright e Chromium sobre o site montado numa pasta temporária. As bibliotecas do CDN
vêm de cópias locais, porque os testes não acessam a rede:

    RADAR_E2E_LIBS=/caminho/com/chart.umd.min.js/e/anime.umd.min.js python -m pytest tests/e2e

Sem o Playwright ou sem RADAR_E2E_LIBS, o teste é pulado (como no CI).
"""

import functools
import http.server
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
LIBS = os.environ.get("RADAR_E2E_LIBS")
if not LIBS:
    pytest.skip("defina RADAR_E2E_LIBS com chart.umd.min.js e anime.umd.min.js", allow_module_level=True)

from src.estatico import resumo_precos as R  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
CHROMIUM = os.environ.get("RADAR_E2E_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
GRUPOS = ["TOTAL", "N", "P", "K", "NPK"]
PARTES_BM = ["bm", "spread", "brl"]
# frase (innerHTML) e canvas (aria-label) de cada gráfico
FRASES = ["resumo-precos", "resumo-frete", "resumo-nutrientes", "resumo-troca"] + [f"resumo-{x}" for x in PARTES_BM]
CANVAS = ["grafico-precos", "grafico-frete", "grafico-nutrientes", "grafico-troca"] + [f"grafico-{x}" for x in PARTES_BM]
CAPTURA = """([frases, canvas]) => ({
  html: Object.fromEntries(frases.map((id) => [id, document.getElementById(id).innerHTML])),
  texto: Object.fromEntries(frases.map((id) => [id, document.getElementById(id).textContent])),
  rotulos: Object.fromEntries(canvas.map((id) => [id, document.getElementById(id).getAttribute("aria-label")])),
})"""
FILTRAR = "([g, de, ate]) => { estado.grupo = g; estado.de = de; estado.ate = ate; estado.anoRotas = null; atualizar(); }"
PRODUTO_BM = "(k) => { estado.bm = k; desenharBenchmark(indicesEntre(estado.de, estado.ate)); return estado.bm; }"
MOEDA = "(m) => { estado.nutrMoeda = m; desenharNutrientes(indicesEntre(estado.de, estado.ate)); }"


class _Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    saida = tmp_path_factory.mktemp("estatico-resumo-precos") / "site"
    r = subprocess.run(["bash", str(RAIZ / "build_site.sh"), str(saida)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Silencioso, directory=str(saida)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/", json.loads((saida / "dashboard.json").read_text(encoding="utf-8"))
    srv.shutdown()


@pytest.fixture(scope="module")
def navegador():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROMIUM if Path(CHROMIUM).exists() else None)
        yield b
        b.close()


def _cdn(rota):
    for nome, arquivo in (("chart.js", "chart.umd.min.js"), ("animejs", "anime.umd.min.js")):
        if nome in rota.request.url:
            return rota.fulfill(path=str(Path(LIBS) / arquivo), content_type="application/javascript", headers={"Access-Control-Allow-Origin": "*"})
    return rota.abort()


def _abrir(navegador, url, largura=1440, js=True, tema="light"):
    ctx = navegador.new_context(viewport={"width": largura, "height": 900}, java_script_enabled=js, reduced_motion="reduce", color_scheme=tema)
    pg = ctx.new_page()
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" and "404" not in m.text else None)
    pg.route("https://cdn.jsdelivr.net/**", _cdn)
    pg.route("https://challenges.cloudflare.com/**", lambda rota: rota.abort())
    pg.goto(url)
    if js:
        pg.wait_for_function("!!(window.radarDados && window.Chart)", timeout=30_000)
        pg.wait_for_timeout(400)
    return ctx, pg, erros


def _indices(dados, de, ate):
    p = dados["mensal"]["periodos"]
    return list(range(p.index(de), p.index(ate) + 1))


def _esperado(dados, g, de, ate, bm=None, moeda="usd"):
    """Frases (texto) e aria-labels que o Python escreveria para esse filtro."""
    indices = _indices(dados, de, ate)
    texto = {"resumo-precos": R.frase_precos(dados, g, ate), "resumo-frete": R.frase_frete(dados, g, ate),
             "resumo-nutrientes": R.frase_nutrientes(dados, g, ate, moeda), "resumo-troca": R.frase_troca(dados, g, ate)}
    rotulos = {"grafico-precos": R.rotulo_precos(dados, g, indices), "grafico-frete": R.rotulo_frete(dados, g, indices),
               "grafico-nutrientes": R.rotulo_nutrientes(dados, g, indices, moeda), "grafico-troca": R.rotulo_troca(dados, g, indices)}
    chaves = R.produtos_bm(dados, g)
    chave = bm if bm in chaves else chaves[0]  # o script volta ao primeiro produto do grupo
    frases, rot_bm = R.frases_benchmark(dados, chave, indices), R.rotulos_benchmark(dados, chave, indices)
    for x in PARTES_BM:
        texto[f"resumo-{x}"] = frases[x]
        rotulos[f"grafico-{x}"] = rot_bm[x]
    return texto, rotulos


def _conferir(pg, dados, g, de, ate, bm=None, moeda="usd"):
    texto, rotulos = _esperado(dados, g, de, ate, bm, moeda)
    obtido = pg.evaluate(CAPTURA, [FRASES, CANVAS])
    caso = f"{g} {de}..{ate} bm={bm} {moeda}"
    for id_, valor in texto.items():
        assert obtido["texto"][id_] == valor, f"{caso} #{id_}"
    for id_, valor in rotulos.items():
        assert obtido["rotulos"][id_] == valor, f"{caso} aria-label de #{id_}"
    return obtido


@pytest.mark.parametrize("largura", [1440, 390])
def test_sem_javascript_mostra_o_mesmo_que_o_script(navegador, site, largura):
    url, _ = site
    ctx, pg, _ = _abrir(navegador, url, largura, js=False)
    estatico = pg.evaluate(CAPTURA, [FRASES, CANVAS])
    ctx.close()
    for id_, html in estatico["html"].items():
        assert html.strip(), f"#{id_} vazio sem JavaScript"
        assert "Fonte: Comex Stat/MDIC" in html and html.endswith("."), f"#{id_} sem a fonte no fim"
    for id_, rotulo in estatico["rotulos"].items():
        assert rotulo and "A tabela abaixo traz os valores. " in rotulo, f"aria-label de #{id_} sem a frase de resumo"
    ctx, pg, erros = _abrir(navegador, url, largura)
    assert pg.evaluate("location.hash").startswith("#grupo=TOTAL&")  # visão padrão
    assert pg.evaluate("estado.bm") == "kcl" and pg.evaluate("estado.nutrMoeda") == "usd"
    dinamico = pg.evaluate(CAPTURA, [FRASES, CANVAS])
    for id_ in FRASES:
        assert dinamico["html"][id_] == estatico["html"][id_], f"#{id_}"
    for id_ in CANVAS:
        assert dinamico["rotulos"][id_] == estatico["rotulos"][id_], f"aria-label de #{id_}"
    assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    assert erros == []
    ctx.close()


def test_frases_do_script_iguais_as_do_python(navegador, site):
    url, dados = site
    p = dados["mensal"]["periodos"]
    # fim do período: o último mês; nitrato de amônio sem importação (2026-05) e com amostra
    # pequena (2026-06); spread da ureia perto de zero (2025-12) e do TSP (2017-04); troca da
    # ureia igual à média (2024-04); o primeiro mês (sem ano anterior); a base FOB do KCl (até
    # 2019); só meses de amostra pequena do DAP (2026-05 em diante)
    casos = [(p[0], p[-1]), (p[0], "2026-05"), (p[0], "2026-06"), (p[0], "2025-12"), ("2019-07", "2024-04"), (p[0], p[0]),
             (p[0], "2019-12"), ("2026-05", p[-1]), ("2016-02", "2017-04")]
    ctx, pg, erros = _abrir(navegador, url)
    for g in GRUPOS:
        for de, ate in casos:
            pg.evaluate(FILTRAR, [g, de, ate])
            _conferir(pg, dados, g, de, ate, bm=pg.evaluate("estado.bm"))
    # todos os produtos do benchmark e o custo por nutriente em reais
    for de, ate in casos:
        pg.evaluate(FILTRAR, ["TOTAL", de, ate])
        for chave in R.ORDEM_BM:
            assert pg.evaluate(PRODUTO_BM, chave) == chave
            _conferir(pg, dados, "TOTAL", de, ate, bm=chave)
        for g in GRUPOS:
            pg.evaluate(FILTRAR, [g, de, ate])
            pg.evaluate(MOEDA, "brl")
            _conferir(pg, dados, g, de, ate, bm=pg.evaluate("estado.bm"), moeda="brl")
            pg.evaluate(MOEDA, "usd")
    assert erros == []
    ctx.close()


def test_filtros_da_pagina_atualizam_as_frases(navegador, site):
    url, dados = site
    p = dados["mensal"]["periodos"]
    ctx, pg, erros = _abrir(navegador, url)
    padrao = _conferir(pg, dados, "TOTAL", p[0], p[-1], bm="kcl")
    # filtro de grupo pelos chips: as frases de preço e frete trocam de grupo
    for g in ("K", "N", "NPK", "P"):
        pg.click(f"#filtro-grupo .chip[data-grupo='{g}']")
        pg.wait_for_timeout(150)
        obtido = _conferir(pg, dados, g, p[0], p[-1], bm=pg.evaluate("estado.bm"))
        for id_ in ("resumo-precos", "resumo-frete"):
            assert obtido["texto"][id_] != padrao["texto"][id_], f"{g}: #{id_} ficou com o texto de Todos"
            assert R.PLURAL_GRUPO[g] in obtido["texto"][id_]
    # grupo K: só o KCl na troca e no custo por nutriente
    pg.click("#filtro-grupo .chip[data-grupo='K']")
    pg.wait_for_timeout(150)
    troca, nutr = pg.text_content("#resumo-troca"), pg.text_content("#resumo-nutrientes")
    assert "KCl" in troca and "ureia" not in troca and "no porto" in troca and "Não é o preço ao produtor" in troca
    assert "K₂O" in nutr and "P₂O₅" not in nutr and "no porto" in nutr and "Não é o preço ao produtor" in nutr
    # produto do benchmark pelos chips (grupo P: MAP, DAP e TSP)
    pg.click("#filtro-grupo .chip[data-grupo='P']")
    pg.wait_for_timeout(150)
    for nome, chave in (("DAP", "dap"), ("TSP", "tsp"), ("MAP", "map")):
        pg.locator("#chips-bm .chip", has_text=nome).click()
        pg.wait_for_timeout(150)
        obtido = _conferir(pg, dados, "P", p[0], p[-1], bm=chave)
        for x in ("bm", "spread"):
            frase = obtido["texto"][f"resumo-{x}"]
            assert nome in frase and "Não é ágio" in frase and "Banco Mundial (Pink Sheet)" in frase
        assert "PTAX" in obtido["texto"]["resumo-brl"] and "BCB/PTAX" in obtido["texto"]["resumo-brl"]
    # moeda do custo por nutriente: em reais, pela PTAX, com a fonte do BCB
    pg.locator("#unidade-nutrientes .chip").nth(1).click()
    pg.wait_for_timeout(150)
    obtido = _conferir(pg, dados, "P", p[0], p[-1], bm="map", moeda="brl")
    assert "R$" in obtido["texto"]["resumo-nutrientes"] and "BCB/PTAX" in obtido["texto"]["resumo-nutrientes"]
    pg.locator("#unidade-nutrientes .chip").nth(0).click()
    # período pelo seletor "Até": o mês das frases acompanha
    pg.click("#filtro-grupo .chip[data-grupo='TOTAL']")
    pg.select_option("#filtro-ate", "2024-03")
    pg.wait_for_timeout(150)
    _conferir(pg, dados, "TOTAL", p[0], "2024-03", bm=pg.evaluate("estado.bm"))
    for id_ in ("resumo-precos", "resumo-frete", "resumo-nutrientes", "resumo-troca", "resumo-bm"):
        assert "mar/2024" in pg.text_content(f"#{id_}"), id_
    assert erros == []
    ctx.close()
