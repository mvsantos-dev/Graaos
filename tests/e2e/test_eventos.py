"""Marcos de mercado (data/eventos.yml) no navegador: a linha vertical nos gráficos dos produtos
citados, a dica perto dela e a linha "Marcos" com o link da fonte.

Monta o site com o build_site.sh duas vezes, numa pasta temporária: numa cópia do repositório com
um eventos.yml de dois eventos e no próprio repositório (o arquivo de hoje, sem eventos, não muda
nada na página). As bibliotecas do CDN vêm de cópias locais, porque os testes não acessam a rede:

    RADAR_E2E_LIBS=/caminho/com/chart.umd.min.js/e/anime.umd.min.js python -m pytest tests/e2e

Sem o Playwright ou sem RADAR_E2E_LIBS, o teste é pulado (como no CI).
"""

import functools
import http.server
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
LIBS = os.environ.get("RADAR_E2E_LIBS")
if not LIBS:
    pytest.skip("defina RADAR_E2E_LIBS com chart.umd.min.js e anime.umd.min.js", allow_module_level=True)

RAIZ = Path(__file__).resolve().parents[2]
CHROMIUM = os.environ.get("RADAR_E2E_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
EVENTOS = """\
# dois eventos de teste
- data: 2026-03-15
  titulo: "Marco de teste A"
  fonte_url: https://www.exemplo.gov.br/noticia-a
  produtos: [kcl]
- data: 2024-06
  titulo: Marco de teste B
  fonte_url: https://exemplo.org/b?x=1
  produtos: [ureia, enxofre]
"""
A = {"titulo": "Marco de teste A", "rotulo": "mar/2026", "data": "15/03/2026", "url": "https://www.exemplo.gov.br/noticia-a", "dominio": "exemplo.gov.br"}
B = {"titulo": "Marco de teste B", "rotulo": "jun/2024", "data": "jun/2024", "url": "https://exemplo.org/b?x=1", "dominio": "exemplo.org"}
GRAFICOS = ["grafico-toneladas", "grafico-origens", "grafico-hhi", "grafico-portos", "grafico-precos", "grafico-frete",
            "grafico-nutrientes", "grafico-bm", "grafico-spread", "grafico-brl", "grafico-troca"]
# monta todos os gráficos que esperam (como na impressão) e devolve, por gráfico, os meses com linha
MARCADOS = """(ids) => { window.dispatchEvent(new Event('beforeprint'));
  return Object.fromEntries(ids.map((id) => [id, (Chart.getChart(id)?.$marcos?.desenhados ?? []).map((d) => [d.rotulo, d.titulos])])); }"""
LISTAS = """() => [...document.querySelectorAll('.marcos')].map((p) => ({ id: p.id, texto: p.textContent,
  links: [...p.querySelectorAll('a')].map((a) => [a.textContent, a.href, a.title]), dentro: p.closest('.cartao')?.id ?? null,
  depoisDe: p.previousElementSibling?.querySelector('canvas')?.id ?? null }))"""
FILTRAR = "([g, de]) => { estado.grupo = g; if (de) estado.de = de; atualizar(); }"


def _montar(origem: Path, destino: Path, eventos: str | None) -> Path:
    """Site do build_site.sh: do próprio repositório (eventos None) ou de uma cópia dele com outro eventos.yml."""
    if eventos is not None:
        raiz = destino.parent / "repo"
        raiz.mkdir()
        shutil.copy(origem / "build_site.sh", raiz / "build_site.sh")
        shutil.copytree(origem / "dashboard", raiz / "dashboard", ignore=shutil.ignore_patterns("print*.png", "preview.png", "*.gif"))
        shutil.copytree(origem / "src", raiz / "src", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(origem / "data" / "processed", raiz / "data" / "processed")
        for extra in ("data/sinais.json", "boletins"):  # o que outras etapas do build leem, se existir
            if (origem / extra).is_dir():
                shutil.copytree(origem / extra, raiz / extra)
            elif (origem / extra).is_file():
                shutil.copy(origem / extra, raiz / extra)
        (raiz / "data" / "eventos.yml").write_text(eventos, encoding="utf-8")
        origem = raiz
    r = subprocess.run(["bash", str(origem / "build_site.sh"), str(destino)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    return destino


def _servir(pasta: Path):
    manipulador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(pasta))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manipulador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    srv, url = _servir(_montar(RAIZ, tmp_path_factory.mktemp("marcos") / "site", EVENTOS))
    yield url
    srv.shutdown()


@pytest.fixture(scope="module")
def site_vazio(tmp_path_factory):
    srv, url = _servir(_montar(RAIZ, tmp_path_factory.mktemp("marcos-vazio") / "site", None))
    yield url
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


def _pagina(navegador, url, largura=1280, altura=900, tema="light", reduzido=True, toque=False):
    ctx = navegador.new_context(viewport={"width": largura, "height": altura}, color_scheme=tema, has_touch=toque, is_mobile=toque,
                                reduced_motion="reduce" if reduzido else "no-preference")
    pg = ctx.new_page()
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" and "net::ERR_FAILED" not in m.text and "404" not in m.text else None)
    pg.route("https://cdn.jsdelivr.net/**", _cdn)
    pg.route("https://challenges.cloudflare.com/**", lambda rota: rota.abort())
    pg.goto(url)
    pg.wait_for_function("!!(window.radarDados && window.Chart && document.querySelector('#filtro-grupo .chip[aria-pressed=true]'))", timeout=30_000)
    return ctx, pg, erros


def _apontar(pg, id_, rotulo, toque=False, dy=0.5):
    """Põe o ponteiro (ou o dedo) sobre o mês `rotulo` do gráfico; devolve a dica."""
    pg.evaluate("(id) => document.getElementById(id).scrollIntoView({ block: 'center' })", id_)
    pg.wait_for_timeout(150)
    ponto = pg.evaluate("""([id, rotulo, dy]) => { const g = Chart.getChart(id); const r = g.canvas.getBoundingClientRect();
      const i = g.data.labels.indexOf(rotulo); const a = g.chartArea;
      return { x: r.left + g.scales.x.getPixelForValue(i), y: r.top + a.top + dy * (a.bottom - a.top) }; }""", [id_, rotulo, dy])
    if toque:
        pg.touchscreen.tap(ponto["x"], ponto["y"])
    else:
        pg.mouse.move(ponto["x"] - 30, ponto["y"])
        pg.mouse.move(ponto["x"], ponto["y"], steps=4)
    pg.wait_for_timeout(120)
    return pg.evaluate("""() => { const d = document.getElementById('dica'); return { visivel: !d.hidden, titulo: d.querySelector('.titulo')?.textContent,
      marcos: [...d.querySelectorAll('.marco')].map((m) => m.textContent), linhas: d.querySelectorAll('.linha').length }; }""")


def _pixel(pg, id_, rotulo):
    """Cor do pixel no centro do losango do topo, no mês dado (em pixels do canvas)."""
    return pg.evaluate("""([id, rotulo]) => { const g = Chart.getChart(id); const k = g.currentDevicePixelRatio;
      const x = Math.round(g.scales.x.getPixelForValue(g.data.labels.indexOf(rotulo)) * k), y = Math.round((g.chartArea.top + 5) * k);
      return [...g.ctx.getImageData(x, y, 1, 1).data]; }""", [id_, rotulo])


def test_linhas_so_nos_graficos_dos_produtos_citados(navegador, site):
    ctx, pg, erros = _pagina(navegador, site)
    assert pg.evaluate("MARCOS.map((m) => [m.data, m.dominio, m.produtos])") == [["2024-06", "exemplo.org", ["ureia", "enxofre"]], ["2026-03-15", "exemplo.gov.br", ["kcl"]]]
    marcados = pg.evaluate(MARCADOS, GRAFICOS)
    # visão padrão: troca (KCl, ureia, MAP) e nutrientes (ureia, MAP, KCl) com os dois; benchmark do KCl só com o A
    assert marcados["grafico-troca"] == [[B["rotulo"], [B["titulo"]]], [A["rotulo"], [A["titulo"]]]]
    assert marcados["grafico-nutrientes"] == marcados["grafico-troca"]
    for id_ in ("grafico-bm", "grafico-spread", "grafico-brl"):
        assert marcados[id_] == [[A["rotulo"], [A["titulo"]]]], id_
    # os gráficos que não são de produto ficam sem marcos
    for id_ in ("grafico-toneladas", "grafico-origens", "grafico-hhi", "grafico-portos", "grafico-precos", "grafico-frete"):
        assert marcados[id_] == [], id_
    # a linha "Marcos" embaixo dos gráficos, com o link da fonte; a do benchmark vem depois do 3º gráfico
    listas = {item["id"]: item for item in pg.evaluate(LISTAS)}
    assert set(listas) == {"marcos-grafico-troca", "marcos-grafico-nutrientes", "marcos-grafico-brl"}
    troca = listas["marcos-grafico-troca"]
    assert troca["links"] == [[B["titulo"], B["url"], f"Fonte: {B['dominio']}"], [A["titulo"], A["url"], f"Fonte: {A['dominio']}"]]
    assert troca["texto"] == f"Marcos: {B['titulo']} ({B['rotulo']}) · {A['titulo']} ({A['rotulo']})"
    assert (troca["dentro"], troca["depoisDe"]) == ("secao-troca", "grafico-troca")
    assert listas["marcos-grafico-nutrientes"]["depoisDe"] == "grafico-nutrientes"
    assert listas["marcos-grafico-brl"]["links"] == [[A["titulo"], A["url"], f"Fonte: {A['dominio']}"]]
    assert (listas["marcos-grafico-brl"]["dentro"], listas["marcos-grafico-brl"]["depoisDe"]) == ("secao-bm", "grafico-brl")
    assert erros == []
    ctx.close()


def test_filtros_atualizam_linhas_e_lista_no_mesmo_grafico(navegador, site):
    ctx, pg, erros = _pagina(navegador, site)
    pg.evaluate(MARCADOS, GRAFICOS)
    pg.evaluate("() => { window.__graficos = Object.fromEntries(%s.map((id) => [id, Chart.getChart(id)])); }" % GRAFICOS)
    # produto do benchmark: ureia (o B); o gráfico é o mesmo, atualizado no lugar
    pg.evaluate("document.querySelector('#chips-bm .chip:nth-child(2)').click()")
    marcados = pg.evaluate(MARCADOS, GRAFICOS)
    assert pg.evaluate("estado.bm") == "ureia"
    for id_ in ("grafico-bm", "grafico-spread", "grafico-brl"):
        assert marcados[id_] == [[B["rotulo"], [B["titulo"]]]], id_
    assert [item["links"][0][0] for item in pg.evaluate(LISTAS) if item["id"] == "marcos-grafico-brl"] == [B["titulo"]]
    # grupo K: só o KCl na troca e nos nutrientes
    pg.evaluate(FILTRAR, ["K", None])
    marcados = pg.evaluate(MARCADOS, GRAFICOS)
    assert marcados["grafico-troca"] == marcados["grafico-nutrientes"] == [[A["rotulo"], [A["titulo"]]]]
    assert [len(item["links"]) for item in pg.evaluate(LISTAS) if item["id"] == "marcos-grafico-troca"] == [1]
    # 12 meses com todos os grupos: o B (jun/2024) sai do eixo, da linha e da lista
    pg.evaluate("document.querySelector('#filtro-periodo .chip[data-preset=\"12m\"]').click()")
    pg.evaluate("document.querySelector('#filtro-grupo .chip[data-grupo=TOTAL]').click()")
    marcados = pg.evaluate(MARCADOS, GRAFICOS)
    assert marcados["grafico-troca"] == [[A["rotulo"], [A["titulo"]]]]
    assert pg.evaluate("estado.bm") == "kcl" and marcados["grafico-bm"] == [[A["rotulo"], [A["titulo"]]]]  # o grupo K voltou o benchmark ao KCl
    # benchmark na ureia: sem o B no período, sem linha e sem a linha "Marcos"
    pg.evaluate("document.querySelector('#chips-bm .chip:nth-child(2)').click()")
    marcados = pg.evaluate(MARCADOS, GRAFICOS)
    assert marcados["grafico-bm"] == marcados["grafico-brl"] == [] and "marcos-grafico-brl" not in [x["id"] for x in pg.evaluate(LISTAS)]
    mesmos = pg.evaluate("() => Object.entries(window.__graficos).filter(([id, g]) => g && Chart.getChart(id) !== g).map(([id]) => id)")
    assert mesmos == [], "trocar filtro, produto e período atualiza o mesmo gráfico, sem recriar"
    assert erros == []
    ctx.close()


def test_dica_perto_da_linha_com_titulo_data_e_fonte(navegador, site):
    ctx, pg, erros = _pagina(navegador, site)
    pg.evaluate(MARCADOS, GRAFICOS)
    dica = _apontar(pg, "grafico-troca", A["rotulo"])
    assert dica["visivel"] and dica["titulo"] == A["rotulo"] and dica["linhas"] >= 1
    assert dica["marcos"] == [f"{A['titulo']}{A['data']} · fonte: {A['dominio']}"]
    # a linha sob o ponteiro fica destacada (sólida); a outra continua tracejada
    assert pg.evaluate("Chart.getChart('grafico-troca').$marcos.perto.map((m) => m.titulo)") == [A["titulo"]]
    # longe dos marcos, a dica de sempre, sem eles
    dica = _apontar(pg, "grafico-troca", "jan/2020")
    assert dica["visivel"] and dica["marcos"] == [] and dica["linhas"] >= 1
    assert pg.evaluate("Chart.getChart('grafico-troca').$marcos.perto") == []
    # o mês do B (sem dia) e o benchmark (gráfico de barras do spread)
    assert _apontar(pg, "grafico-nutrientes", B["rotulo"])["marcos"] == [f"{B['titulo']}{B['data']} · fonte: {B['dominio']}"]
    assert _apontar(pg, "grafico-spread", A["rotulo"], dy=0.9)["marcos"] == [f"{A['titulo']}{A['data']} · fonte: {A['dominio']}"]
    # fora do gráfico, a dica some
    pg.mouse.move(5, 5)
    pg.wait_for_timeout(100)
    assert pg.evaluate("document.getElementById('dica').hidden")
    assert erros == []
    ctx.close()


@pytest.mark.parametrize("tema", ["light", "dark"])
def test_cores_do_tema_nos_dois_temas(navegador, site, tema):
    ctx, pg, erros = _pagina(navegador, site, tema=tema)
    pg.evaluate(MARCADOS, GRAFICOS)
    pg.evaluate("document.getElementById('grafico-troca').scrollIntoView({ block: 'center' })")
    pg.wait_for_timeout(200)
    forte = pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--marco-forte').trim()")
    assert forte == {"light": "#4b4f7a", "dark": "#b6bae6"}[tema]
    alvo = [int(forte[i:i + 2], 16) for i in (1, 3, 5)]
    for rotulo in (A["rotulo"], B["rotulo"]):
        r, g, b, a = _pixel(pg, "grafico-troca", rotulo)
        assert a == 255 and max(abs(r - alvo[0]), abs(g - alvo[1]), abs(b - alvo[2])) <= 6, (rotulo, [r, g, b, a])
    # num mês sem marco, nada no lugar do losango
    r, g, b, a = _pixel(pg, "grafico-troca", "jan/2020")
    assert a == 0 or max(abs(r - alvo[0]), abs(g - alvo[1]), abs(b - alvo[2])) > 40
    # trocar o tema redesenha com a cor do outro
    pg.evaluate("document.getElementById('botao-tema').click()")
    pg.wait_for_timeout(300)
    outro = {"light": [182, 186, 230], "dark": [75, 79, 122]}[tema]
    r, g, b, _ = _pixel(pg, "grafico-troca", A["rotulo"])
    assert max(abs(r - outro[0]), abs(g - outro[1]), abs(b - outro[2])) <= 6
    assert erros == []
    ctx.close()


def test_com_movimento_as_linhas_vem_com_a_entrada_do_grafico(navegador, site):
    ctx, pg, erros = _pagina(navegador, site, reduzido=False)
    pg.evaluate("document.getElementById('grafico-troca').scrollIntoView({ block: 'center' })")
    pg.wait_for_function("document.getElementById('grafico-troca').dataset.entrada === 'feita' && (Chart.getChart('grafico-troca')?.$marcos?.desenhados?.length ?? 0) === 2", timeout=15_000)
    pg.wait_for_timeout(1800)  # fim da entrada
    assert _apontar(pg, "grafico-troca", A["rotulo"])["marcos"] == [f"{A['titulo']}{A['data']} · fonte: {A['dominio']}"]
    assert erros == []
    ctx.close()


def test_celular_toque_mostra_a_dica_e_nada_passa_da_tela(navegador, site):
    ctx, pg, erros = _pagina(navegador, site, largura=390, altura=844, toque=True)
    marcados = pg.evaluate(MARCADOS, GRAFICOS)
    assert marcados["grafico-troca"] == [[B["rotulo"], [B["titulo"]]], [A["rotulo"], [A["titulo"]]]]
    dica = _apontar(pg, "grafico-troca", A["rotulo"], toque=True)
    assert dica["visivel"] and dica["marcos"] == [f"{A['titulo']}{A['data']} · fonte: {A['dominio']}"]
    caixa = pg.evaluate("(() => { const r = document.getElementById('dica').getBoundingClientRect(); return [r.left, r.right]; })()")
    assert caixa[0] >= 0 and caixa[1] <= 390
    assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    assert all(item["texto"].startswith("Marcos: ") for item in pg.evaluate(LISTAS))
    assert erros == []
    ctx.close()


def test_impressao_mostra_as_linhas_e_a_lista(navegador, site):
    ctx, pg, erros = _pagina(navegador, site)
    pg.emulate_media(media="print")
    marcados = pg.evaluate(MARCADOS, GRAFICOS)  # o beforeprint monta todos os gráficos
    assert marcados["grafico-brl"] == [[A["rotulo"], [A["titulo"]]]]
    visiveis = pg.evaluate("[...document.querySelectorAll('.marcos')].map((p) => getComputedStyle(p).display !== 'none' && p.getBoundingClientRect().height > 0)")
    assert visiveis and all(visiveis)
    assert erros == []
    ctx.close()


def test_sem_eventos_nada_muda(navegador, site_vazio):
    ctx, pg, erros = _pagina(navegador, site_vazio)
    assert pg.evaluate("document.getElementById('marcos-dados').textContent") == "[]"
    marcados = pg.evaluate(MARCADOS, GRAFICOS)
    assert all(v == [] for v in marcados.values())
    assert pg.evaluate("Chart.registry.plugins.get('marcos') === undefined"), "sem eventos, o plugin nem é registrado"
    assert pg.evaluate(f"{GRAFICOS}.filter((id) => Chart.getChart(id)?.$marcos)") == []
    assert pg.evaluate(LISTAS) == []
    dica = _apontar(pg, "grafico-troca", "mar/2026")
    assert dica["visivel"] and dica["marcos"] == []
    assert erros == []
    ctx.close()
