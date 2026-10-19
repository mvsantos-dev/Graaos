"""Card Resumo e frases dos gráficos de volumes, origens, HHI, portos e rotas no site montado pelo
build_site.sh (src/estatico/resumo.py), no navegador.

- Sem JavaScript (o que os buscadores e quem lê sem script recebem), o HTML do build é igual ao
  que o script desenha na visão padrão: mesmo innerHTML e mesmos aria-labels.
- Com JavaScript, as frases e os destaques acompanham os filtros, e para cada grupo e mês são as
  mesmas que o Python escreveria (as duas versões das regras não podem divergir).

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

from src.estatico import dados as D  # noqa: E402
from src.estatico import resumo as R  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
CHROMIUM = os.environ.get("RADAR_E2E_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
GRUPOS = ["TOTAL", "N", "P", "K", "NPK"]

# o que o build preenche (innerHTML) e os aria-labels que ele define
PREENCHIDOS = [
    "titulo-kpis", "nota-kpis", "titulo-mes", "titulo-acumulado", "kpis-mes", "kpis-acumulado", "destaques-kpis",
    "nota-toneladas", "resumo-toneladas", "nota-origens", "resumo-origens", "nota-hhi", "resumo-hhi",
    "nota-portos", "resumo-portos", "nota-rotas", "resumo-rotas",
]
ROTULOS = ["grafico-toneladas", "grafico-origens", "grafico-hhi", "grafico-portos", "sankey"]
CAPTURA = """([ids, rotulos]) => ({
  html: Object.fromEntries(ids.map((id) => [id, document.getElementById(id).innerHTML])),
  rotulos: Object.fromEntries(rotulos.map((id) => [id, document.getElementById(id).getAttribute("aria-label")])),
})"""
TEXTOS = """([ids, rotulos]) => ({
  texto: Object.fromEntries(ids.map((id) => [id, document.getElementById(id).textContent])),
  rotulos: Object.fromEntries(rotulos.map((id) => [id, document.getElementById(id).getAttribute("aria-label")])),
  kpis: ["kpis-mes", "kpis-acumulado"].map((id) => document.getElementById(id).innerHTML),
})"""
# HTML escrito pelo Python, serializado pelo navegador (para comparar com o innerHTML do script)
SERIALIZAR = "(html) => { const t = document.createElement('template'); t.innerHTML = html; return t.innerHTML; }"
FILTRAR = "([g, de, ate]) => { estado.grupo = g; estado.de = de; estado.ate = ate; estado.anoRotas = null; atualizar(); }"


class _Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    saida = tmp_path_factory.mktemp("estatico-resumo") / "site"
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


def _esperado(dados, g, de, ate, ano_rotas=None):
    """Textos e aria-labels que o Python escreveria para esse filtro (o build usa a visão padrão)."""
    ano = int(ate[:4])
    ano_r = ano_rotas or ano
    bloco = (dados["rotas"]["dados"].get(str(ano_r)) or {}).get(g)
    k = D.kpis(dados, g, ate)
    texto = {
        "titulo-kpis": k["titulo"], "nota-kpis": k["nota"], "titulo-mes": k["titulo_mes"], "titulo-acumulado": k["titulo_acumulado"],
        "destaques-kpis": R.texto_destaques(dados, g, ate),
        "nota-toneladas": R.nota_toneladas(dados, g, de, ate), "resumo-toneladas": R.frase_toneladas(dados, g, ate),
        "nota-origens": R.nota_ranking(dados, "origens", g, ano), "resumo-origens": R.frase_ranking(dados, "origens", g, ano),
        "nota-hhi": R.nota_hhi(dados, g, de, ate), "resumo-hhi": R.frase_hhi(dados, g, ano),
        "nota-portos": R.nota_ranking(dados, "portos", g, ano), "resumo-portos": R.frase_ranking(dados, "portos", g, ano),
        "nota-rotas": R.nota_rotas(dados, bloco, g, ano_r), "resumo-rotas": R.frase_rotas(dados, bloco, g, ano_r),
    }
    rotulos = {
        "grafico-toneladas": R.rotulo_toneladas(dados, g, de, ate),
        "grafico-origens": R.rotulo_ranking(dados, "origens", g, ano),
        "grafico-hhi": R.rotulo_hhi(dados, g, de, ate),
        "grafico-portos": R.rotulo_ranking(dados, "portos", g, ano),
        "sankey": R.rotulo_sankey(dados, bloco, g, ano_r),
    }
    return texto, rotulos, [R.kpis_html(k["mes"]), R.kpis_html(k["acumulado"])]


def _conferir(pg, dados, g, de, ate, ano_rotas=None):
    texto, rotulos, kpis = _esperado(dados, g, de, ate, ano_rotas)
    obtido = pg.evaluate(TEXTOS, [list(texto), ROTULOS])
    caso = f"{g} {de}..{ate}"
    for id_, valor in texto.items():
        assert obtido["texto"][id_] == valor, f"{caso} #{id_}"
    for id_, valor in rotulos.items():
        assert obtido["rotulos"][id_] == valor, f"{caso} aria-label de #{id_}"
    assert obtido["kpis"] == [pg.evaluate(SERIALIZAR, h) for h in kpis], caso
    return obtido


@pytest.mark.parametrize("largura", [1440, 390])
def test_sem_javascript_mostra_o_mesmo_que_o_script(navegador, site, largura):
    url, _ = site
    ctx, pg, _ = _abrir(navegador, url, largura, js=False)
    estatico = pg.evaluate(CAPTURA, [PREENCHIDOS, ROTULOS])
    ctx.close()
    for id_, html in estatico["html"].items():
        assert html.strip(), f"#{id_} vazio sem JavaScript"
    for id_, rotulo in estatico["rotulos"].items():
        assert rotulo and rotulo.count(". ") >= 2, f"aria-label de #{id_} sem a frase de resumo"
    ctx, pg, erros = _abrir(navegador, url, largura)
    assert pg.evaluate("location.hash").startswith("#grupo=TOTAL&")  # visão padrão
    # o script redesenhou por cima (os números dele guardam o valor para contar ao aparecer)
    assert pg.evaluate("[...document.querySelectorAll('#kpis-mes .numero, #kpis-acumulado .numero')].every((n) => typeof n.__valor === 'number')")
    dinamico = pg.evaluate(CAPTURA, [PREENCHIDOS, ROTULOS])
    for id_ in PREENCHIDOS:
        assert dinamico["html"][id_] == estatico["html"][id_], f"#{id_}"
    for id_ in ROTULOS:
        assert dinamico["rotulos"][id_] == estatico["rotulos"][id_], f"aria-label de #{id_}"
    assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    assert erros == []
    ctx.close()


def test_frases_do_script_iguais_as_do_python_em_todos_os_grupos(navegador, site):
    url, dados = site
    p = dados["mensal"]["periodos"]
    # fim do período: o último mês, janeiro (sem acumulado), dezembro, o primeiro ano (sem
    # comparação) e um começo que tira o ano parcial do HHI
    casos = [(p[0], p[-1]), (p[0], f"{p[-1][:4]}-01"), ("2019-07", "2025-12"), (p[0], p[0]), (p[0], "2015-08"), ("2021-01", "2023-06")]
    ctx, pg, erros = _abrir(navegador, url)
    for g in GRUPOS:
        for de, ate in casos:
            pg.evaluate(FILTRAR, [g, de, ate])
            _conferir(pg, dados, g, de, ate)
    assert erros == []
    ctx.close()


def test_filtros_da_pagina_atualizam_destaques_e_frases(navegador, site):
    url, dados = site
    p = dados["mensal"]["periodos"]
    ctx, pg, erros = _abrir(navegador, url)
    padrao = _conferir(pg, dados, "TOTAL", p[0], p[-1])
    # filtro de grupo pelos chips: nada fica com o texto de "Todos"
    for g in ("K", "N", "NPK", "P"):
        pg.click(f"#filtro-grupo .chip[data-grupo='{g}']")
        pg.wait_for_timeout(150)
        obtido = _conferir(pg, dados, g, p[0], p[-1])
        for id_ in ("destaques-kpis", "resumo-toneladas", "resumo-origens", "resumo-hhi", "resumo-portos", "resumo-rotas"):
            assert obtido["texto"][id_] != padrao["texto"][id_], f"{g}: #{id_} ficou com o texto de Todos"
    # NPK não entra na relação de troca; K só tem o KCl
    pg.click("#filtro-grupo .chip[data-grupo='NPK']")
    assert "troca" not in pg.text_content("#destaques-kpis")
    pg.click("#filtro-grupo .chip[data-grupo='K']")
    destaques = pg.text_content("#destaques-kpis")
    assert "KCl" in destaques and "Ureia" not in destaques and "no porto" in destaques and "Não é o preço ao produtor" in destaques
    # ano do diagrama de rotas: a frase e o aria-label seguem o ano escolhido
    pg.select_option("#filtro-ano-rotas", "2020")
    pg.wait_for_timeout(150)
    _conferir(pg, dados, "K", p[0], p[-1], ano_rotas=2020)
    # período pelo seletor "Até": o mês das frases e dos destaques acompanha
    pg.click("#filtro-grupo .chip[data-grupo='TOTAL']")
    pg.select_option("#filtro-ate", "2024-03")
    pg.wait_for_timeout(150)
    _conferir(pg, dados, "TOTAL", p[0], "2024-03")
    assert "mar/2024" in pg.text_content("#resumo-toneladas") and "mar/2024" in pg.text_content("#destaques-kpis")
    assert erros == []
    ctx.close()
