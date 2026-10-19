"""Cenários de navegador da carga da página (só em desenvolvimento): o dashboard.json chega depois
da primeira pintura e os gráficos só são montados quando o canvas chega perto da tela.

Monta o site com o build_site.sh numa pasta temporária e serve essa pasta, como no deploy. As
bibliotecas do CDN (Chart.js e anime.js) vêm de cópias locais, porque os testes não acessam a rede:

    RADAR_E2E_LIBS=/caminho/com/chart.umd.min.js/e/anime.umd.min.js python -m pytest tests/e2e

Sem o Playwright ou sem RADAR_E2E_LIBS, o teste é pulado (como no CI).
"""

import functools
import http.server
import os
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
CLIQUE = "(sel) => document.querySelector(sel).dispatchEvent(new MouseEvent('click', {bubbles: true}))"

# canvas de cada gráfico, montados (com Chart.js) ou não, e a distância de cada um até a tela
CANVAS = """() => [...document.querySelectorAll('.grafico canvas')].map((c) => { const r = c.getBoundingClientRect();
  return { id: c.id, montado: !!Chart.getChart(c), entrada: c.dataset.entrada ?? null, oculto: !!c.closest('.oculto'),
    longe: r.top > 2 * innerHeight || r.bottom < -innerHeight }; })"""
# rola aos poucos, como quem usa a roda do mouse, até o topo do canvas ficar a `fracao` da altura da tela
ROLAR_ATE = """async ([id, fracao]) => { const alvo = () => document.getElementById(id).getBoundingClientRect().top + scrollY - fracao * innerHeight;
  while (Math.abs(scrollY - alvo()) > 1) { const y = alvo(); scrollTo(0, scrollY + Math.sign(y - scrollY) * Math.min(160, Math.abs(y - scrollY)));
    await new Promise((r) => setTimeout(r, 16)); if (scrollY + innerHeight >= document.documentElement.scrollHeight - 1 && y > scrollY) break; } }"""
# salta até o canvas e responde, no quadro seguinte (antes da pintura), se o gráfico já existe
SALTO = """async (id) => { const c = document.getElementById(id); scrollTo(0, c.getBoundingClientRect().top + scrollY - 100);
  await new Promise(requestAnimationFrame); const g = Chart.getChart(c);
  return { montado: !!g, animacao: g ? g.options.animation : null, entrada: c.dataset.entrada ?? null }; }"""
# pixels pintados do canvas (nada sai em branco na impressão)
PINTADOS = """(id) => { const c = document.getElementById(id); if (!c.width || !c.height) return 0;
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0;
  for (let i = 3; i < d.length; i += 4) if (d[i]) n++; return n; }"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("desempenho") / "site"
    subprocess.run(["bash", str(RAIZ / "build_site.sh"), str(pasta)], check=True, capture_output=True)
    manipulador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(pasta))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manipulador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
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


def _pagina(navegador, site, largura=1440, altura=900, reduzido=False, tema="light"):
    ctx = navegador.new_context(viewport={"width": largura, "height": altura}, color_scheme=tema, reduced_motion="reduce" if reduzido else "no-preference")
    pg = ctx.new_page()
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" and "404" not in m.text else None)
    pg.route("https://cdn.jsdelivr.net/**", _cdn)
    pg.route("https://challenges.cloudflare.com/**", lambda rota: rota.abort())
    pg.goto(site)
    # os filtros marcados vêm do primeiro atualizar(): os gráficos já têm configuração
    pg.wait_for_function("window.anime && window.radarDados && !!document.querySelector('#filtro-grupo .chip[aria-pressed=true]')", timeout=30_000)
    pg.wait_for_timeout(600)
    return ctx, pg, erros


def _montado(pg, id_, timeout=15_000):
    pg.wait_for_function(f"!!Chart.getChart('{id_}')", timeout=timeout)


@pytest.mark.parametrize("largura", [1440, 390])
def test_dados_depois_da_primeira_pintura_e_nada_montado_longe_da_tela(navegador, site, largura):
    ctx, pg, erros = _pagina(navegador, site, largura=largura, altura=900 if largura > 600 else 844)
    tempos = pg.evaluate("""() => ({ pintura: performance.getEntriesByName('first-paint')[0]?.startTime ?? performance.getEntriesByName('first-contentful-paint')[0]?.startTime,
      json: performance.getEntriesByType('resource').find((e) => new URL(e.name).pathname === '/dashboard.json')?.startTime })""")
    assert tempos["pintura"] is not None and tempos["json"] is not None
    assert tempos["json"] >= tempos["pintura"], "o dashboard.json só é buscado depois da primeira pintura"
    canvas = pg.evaluate(CANVAS)
    assert len(canvas) >= 11
    longe = [c for c in canvas if c["longe"] or c["oculto"]]
    assert len(longe) >= 8, "no topo da página, quase todos os gráficos estão longe da tela"
    assert [c["id"] for c in longe if c["montado"]] == [], "longe da tela, nenhum gráfico é montado na carga"
    # todos têm a configuração e esperam a entrada (o mesmo "pendente" de antes)
    assert all(c["entrada"] == "pendente" for c in canvas)
    assert erros == []
    ctx.close()


def test_canvas_que_espera_nao_abre_rolagem_lateral_no_celular_estreito(navegador, site):
    # o canvas sem gráfico fica no tamanho padrão do navegador (300 px), mais largo que a caixa
    ctx, pg, erros = _pagina(navegador, site, largura=320, altura=740)
    larguras = pg.evaluate("[...document.querySelectorAll('.grafico canvas')].filter((c) => !Chart.getChart(c) && !c.closest('.oculto')).map((c) => [c.getBoundingClientRect().width, c.parentElement.clientWidth])")
    assert larguras and all(w <= caixa + 0.5 for w, caixa in larguras)
    assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    # montado, o gráfico ocupa a caixa inteira (o limite sai antes de o Chart.js medir)
    pg.evaluate(ROLAR_ATE, ["grafico-toneladas", 0.3])
    _montado(pg, "grafico-toneladas")
    r = pg.evaluate("(() => { const c = document.getElementById('grafico-toneladas'); return [c.style.maxWidth, Math.round(c.getBoundingClientRect().width), c.parentElement.clientWidth]; })()")
    assert r[0] == "" and abs(r[1] - r[2]) <= 1
    assert erros == []
    ctx.close()


def test_grafico_e_montado_ao_chegar_perto_e_a_entrada_toca_ao_aparecer(navegador, site):
    ctx, pg, erros = _pagina(navegador, site)
    # rolando aos poucos: o gráfico de preços é montado antes de entrar na tela, ainda sem a entrada
    pg.evaluate(ROLAR_ATE, ["grafico-precos", 1.6])
    _montado(pg, "grafico-precos")
    assert pg.evaluate("document.getElementById('grafico-precos').getBoundingClientRect().top") > pg.evaluate("innerHeight")
    assert pg.evaluate("document.getElementById('grafico-precos').dataset.entrada") == "pendente"
    assert not pg.evaluate("!!Chart.getChart('grafico-troca')"), "o último gráfico da página continua sem montar"
    # o gráfico montado tem os dados do período inteiro
    n = pg.evaluate("radarDados.mensal.periodos.length")
    assert pg.evaluate("Chart.getChart('grafico-precos').data.labels.length") == n
    pg.evaluate(ROLAR_ATE, ["grafico-precos", 0.3])
    pg.wait_for_function("document.getElementById('grafico-precos').dataset.entrada === 'feita'", timeout=10_000)
    # o link do menu rola até a seção (com animação) e os gráficos dela se montam e entram
    pg.evaluate("window.scrollTo(0, 0)")
    pg.wait_for_timeout(300)
    pg.evaluate(CLIQUE, "#nav-secoes a[data-secao=troca]")
    pg.wait_for_function("document.getElementById('grafico-troca').dataset.entrada === 'feita'", timeout=15_000)
    assert erros == []
    ctx.close()


def test_filtro_periodo_e_tema_antes_de_montar_valem_quando_o_grafico_nasce(navegador, site):
    ctx, pg, erros = _pagina(navegador, site)
    claro = pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--g-k').trim()")
    pg.evaluate(CLIQUE, "#filtro-grupo .chip[data-grupo=K]")
    pg.evaluate(CLIQUE, "#filtro-periodo .chip[data-preset='3a']")
    pg.evaluate(CLIQUE, "#botao-tema")
    escuro = pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--g-k').trim()")
    assert claro != escuro
    assert not pg.evaluate("!!Chart.getChart('grafico-troca')")
    pg.evaluate(ROLAR_ATE, ["grafico-troca", 0.3])
    pg.wait_for_function("document.getElementById('grafico-troca').dataset.entrada === 'feita'", timeout=15_000)
    nome = pg.evaluate("radarDados.troca.produtos.kcl.nome")
    g = pg.evaluate("(() => { const g = Chart.getChart('grafico-troca'); return { labels: g.data.labels, series: g.data.datasets.map((d) => d.label), cor: g.data.datasets[0].borderColor }; })()")
    ultimo = pg.evaluate("radarDados.mensal.periodos.at(-1)")
    assert len(g["labels"]) == 36 and g["series"] == [nome, f"Média {nome}"]
    assert g["labels"][-1].endswith(ultimo[:4])
    assert g["cor"] == escuro, "o gráfico nasce com as cores do tema escolhido antes"
    # depois de montado e visto, o filtro atualiza o mesmo gráfico no lugar
    antes = pg.evaluate("Chart.getChart('grafico-troca').id")
    pg.evaluate(CLIQUE, "#filtro-grupo .chip[data-grupo=N]")
    pg.wait_for_timeout(200)
    assert pg.evaluate("Chart.getChart('grafico-troca').id") == antes
    assert pg.evaluate("Chart.getChart('grafico-troca').data.datasets[0].label") == pg.evaluate("radarDados.troca.produtos.ureia.nome")
    assert erros == []
    ctx.close()


def test_tela_que_vira_celular_antes_de_montar_vale_quando_o_grafico_nasce(navegador, site):
    ctx, pg, erros = _pagina(navegador, site)
    assert not pg.evaluate("!!Chart.getChart('grafico-hhi')")
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.wait_for_timeout(300)
    pg.evaluate(ROLAR_ATE, ["grafico-hhi", 0.3])
    _montado(pg, "grafico-hhi")
    assert pg.evaluate("Chart.getChart('grafico-hhi').options.scales.x.ticks.maxTicksLimit") == 5  # 12 em tela larga
    assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    assert erros == []
    ctx.close()


def test_impressao_monta_todos_os_graficos(navegador, site):
    ctx, pg, erros = _pagina(navegador, site)
    assert len([c for c in pg.evaluate(CANVAS) if not c["montado"]]) >= 8
    pg.emulate_media(media="print")
    pg.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    canvas = [c for c in pg.evaluate(CANVAS) if not c["oculto"]]
    assert [c["id"] for c in canvas if not c["montado"]] == [], "na impressão, nenhum gráfico fica sem montar"
    for c in canvas:
        assert pg.evaluate(PINTADOS, c["id"]) > 0, f"{c['id']} sairia em branco"
    pg.emulate_media(media="screen")
    assert erros == []
    ctx.close()


def test_sem_movimento_nada_espera(navegador, site):
    ctx, pg, erros = _pagina(navegador, site, reduzido=True)
    canvas = pg.evaluate(CANVAS)
    assert all(c["entrada"] is None for c in canvas), "sem movimento, nenhum gráfico espera a entrada"
    # salto de rolagem: o gráfico já existe no quadro seguinte, antes da pintura, e sem animação
    r = pg.evaluate(SALTO, "grafico-troca")
    assert r == {"montado": True, "animacao": False, "entrada": None}
    # o link do menu salta (sem animação) e os gráficos da seção já estão lá no quadro seguinte
    pg.evaluate("window.scrollTo(0, 0)")
    pg.wait_for_timeout(200)
    assert not pg.evaluate("!!Chart.getChart('grafico-frete')")
    montado = pg.evaluate("""async () => { document.querySelector('#nav-secoes a[data-secao=precos]').click();
      await new Promise(requestAnimationFrame); return ['grafico-precos', 'grafico-frete'].map((id) => !!Chart.getChart(id)); }""")
    assert montado == [True, True]
    assert erros == []
    ctx.close()
    # com movimento, o salto também monta o gráfico antes da pintura; a entrada toca em seguida
    ctx, pg, erros = _pagina(navegador, site)
    r = pg.evaluate(SALTO, "grafico-nutrientes")
    assert r["montado"] and r["entrada"] == "pendente"
    pg.wait_for_function("document.getElementById('grafico-nutrientes').dataset.entrada === 'feita'", timeout=10_000)
    assert erros == []
    ctx.close()
