"""Testes do build_site.sh (o site do deploy na Cloudflare e no GitHub Pages). Sem rede."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "build_site.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="precisa de bash")


def _rodar(raiz: Path, saida: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(raiz / "build_site.sh"), str(saida)], capture_output=True, text=True, timeout=60)


def test_monta_o_site_com_os_dados_na_raiz(tmp_path):
    saida = tmp_path / "site"
    r = _rodar(RAIZ, saida)
    assert r.returncode == 0, r.stderr
    # o index.html busca "dashboard.json" e "boletim.json" ao lado dele
    html = (saida / "index.html").read_text(encoding="utf-8")
    assert '"dashboard.json"' in html and '"boletim.json"' in html
    original = (RAIZ / "data" / "processed" / "dashboard.json").read_bytes()
    assert (saida / "dashboard.json").read_bytes() == original
    assert "mapa" in json.loads(original)
    json.loads((saida / "boletim.json").read_text(encoding="utf-8"))
    for arquivo in ("assets/mapa-pontos.json", "assets/fluxos.js", "assets/hero.js", "assets/mapa-hero.js", "assets/lista-espera.js", "assets/radar.css"):
        assert (saida / arquivo).stat().st_size > 0, arquivo
    # indexação e ícones (src/estatico/cabecalho.py e dashboard/)
    for arquivo in INDEXACAO:
        assert (saida / arquivo).stat().st_size > 0, arquivo
    assert "application/ld+json" in html and '<link rel="canonical" href="https://radar.graaos.cloud/">' in html
    boletim = RAIZ / "boletins" / "latest.json"
    if boletim.exists():
        assert (saida / "boletim.json").read_bytes() == boletim.read_bytes()


def test_wrangler_publica_a_pasta_do_build():
    texto = (RAIZ / "wrangler.jsonc").read_text(encoding="utf-8")
    sem_comentarios = "\n".join(linha for linha in texto.splitlines() if not linha.lstrip().startswith("//"))
    config = json.loads(sem_comentarios)
    assert config["assets"]["directory"] == "./site"
    assert config["assets"]["not_found_handling"] == "404-page"  # o 404.html gerado no build
    assert not ({"account_id", "vars"} & set(config)), "nada de conta ou variáveis no repositório público"


INDEXACAO = ("robots.txt", "sitemap.xml", "404.html", "llms.txt", "_headers", "site.webmanifest", "favicon-32.png", "favicon-192.png", "favicon-512.png", "apple-touch-icon.png")


def _repo_falso(tmp_path: Path, dashboard: str | None, index: bool = True) -> Path:
    """Cópia do dashboard/ e do src/ (o gerador do conteúdo estático) fora de um repositório git."""
    raiz = tmp_path / "repo"
    raiz.mkdir()
    shutil.copy(SCRIPT, raiz / "build_site.sh")
    # sem as capturas de tela (os ícones PNG entram: o build confere)
    shutil.copytree(RAIZ / "dashboard", raiz / "dashboard", ignore=shutil.ignore_patterns("print*.png", "preview.png", "*.gif"))
    shutil.copytree(RAIZ / "src", raiz / "src", ignore=shutil.ignore_patterns("__pycache__"))
    if not index:
        (raiz / "dashboard" / "index.html").unlink()
    if dashboard is not None:
        (raiz / "data" / "processed").mkdir(parents=True)
        (raiz / "data" / "processed" / "dashboard.json").write_text(dashboard, encoding="utf-8")
    return raiz


COMPLETO = (RAIZ / "data" / "processed" / "dashboard.json").read_text(encoding="utf-8")


def test_repo_falso_completo_monta_sem_erro(tmp_path):
    raiz = _repo_falso(tmp_path, COMPLETO)
    r = _rodar(raiz, raiz / "site")
    assert r.returncode == 0, r.stderr
    assert "sem histórico do git" in r.stderr  # fora de um repositório git, só avisa
    assert json.loads((raiz / "site" / "boletim.json").read_text()) == {}
    for arquivo in INDEXACAO:
        assert (raiz / "site" / arquivo).stat().st_size > 0, arquivo
    # fora do repositório: sem data de atualização no sitemap e no JSON-LD, e só o dashboard.json para baixar
    assert "<lastmod>" not in (raiz / "site" / "sitemap.xml").read_text()
    html = (raiz / "site" / "index.html").read_text(encoding="utf-8")
    assert "dateModified" not in html and html.count('"@type":"DataDownload"') == 1


@pytest.mark.parametrize(
    ("estragar", "mensagem"),
    [
        (lambda raiz: (raiz / "dashboard" / "favicon-192.png").unlink(), "falta favicon-192.png"),
        (lambda raiz: (raiz / "dashboard" / "site.webmanifest").write_text("{"), "site.webmanifest"),
        (lambda raiz: (raiz / "dashboard" / "assets" / "mapa-pontos.json").rename(raiz / "dashboard" / "assets" / "outro.json"), "mapa-pontos.json"),
    ],
    ids=["sem-icone", "manifest-invalido", "asset-referenciado-sumiu"],
)
def test_build_falha_sem_icone_ou_com_referencia_quebrada(tmp_path, estragar, mensagem):
    raiz = _repo_falso(tmp_path, COMPLETO)
    estragar(raiz)
    r = _rodar(raiz, raiz / "site")
    assert r.returncode == 1
    assert mensagem in r.stderr


@pytest.mark.parametrize(
    ("dashboard", "index", "mensagem"),
    [
        (None, True, "data/processed/dashboard.json não existe"),
        ("{ isto não é JSON", True, "dashboard.json inválido"),
        (json.dumps({"meta": {}, "mensal": {}}), True, "sem as chaves"),
        (COMPLETO, False, "dashboard/index.html não existe"),
    ],
    ids=["sem-dashboard", "json-invalido", "sem-chaves", "sem-index"],
)
def test_build_falha_sem_dados_validos(tmp_path, dashboard, index, mensagem):
    raiz = _repo_falso(tmp_path, dashboard, index=index)
    r = _rodar(raiz, raiz / "site")
    assert r.returncode == 1
    assert mensagem in r.stderr
