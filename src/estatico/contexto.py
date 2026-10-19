"""O que as etapas do site estático compartilham: dados lidos, o index.html em edição e as páginas
geradas (para o sitemap).

O HTML é editado como texto, sem parser externo: cada ponto de encaixe é um elemento com id único
no index.html. preencher() só aceita elemento vazio e definir_atributo() só aceita um id que
aparece uma vez; qualquer outra coisa é erro de build (melhor um deploy que falha do que um site
com o conteúdo estático no lugar errado).
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

URL_BASE = "https://radar.graaos.cloud/"
REPOSITORIO = "https://github.com/mvsantos-dev/graaos"
RAIZ = Path(__file__).resolve().parents[2]


class ErroEstatico(Exception):
    """Falha que interrompe o build (build_site.sh termina com exit 1)."""


def esc(texto) -> str:
    """Texto para o HTML (conteúdo e atributos)."""
    return html.escape(str(texto), quote=True)


@dataclass
class Pagina:
    """Uma página do site para o sitemap: caminho a partir da raiz ("" é a home, "boletim/" o arquivo)."""

    caminho: str
    lastmod: str | None = None

    @property
    def url(self) -> str:
        return URL_BASE + self.caminho


@dataclass
class Contexto:
    site: Path
    dados: dict
    boletim: dict
    html: str
    atualizado: str | None = None  # AAAA-MM-DD da última atualização dos dados (meta "atualizado")
    raiz: Path = RAIZ
    paginas: list[Pagina] = field(default_factory=list)

    @classmethod
    def carregar(cls, site: Path, atualizado: str | None = None, raiz: Path = RAIZ) -> "Contexto":
        site = Path(site)
        try:
            dados = json.loads((site / "dashboard.json").read_text(encoding="utf-8"))
            boletim = json.loads((site / "boletim.json").read_text(encoding="utf-8"))
            pagina = (site / "index.html").read_text(encoding="utf-8")
        except (OSError, ValueError) as e:
            raise ErroEstatico(f"não consegui ler o site em {site}: {e}") from e
        if atualizado is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", atualizado):
            raise ErroEstatico(f"data de atualização inválida: {atualizado!r}")
        return cls(site=site, dados=dados, boletim=boletim if isinstance(boletim, dict) else {}, html=pagina, atualizado=atualizado, raiz=Path(raiz))

    # --- Dados ------------------------------------------------------------------------------
    @property
    def periodos(self) -> list[str]:
        return self.dados["mensal"]["periodos"]

    @property
    def primeiro_mes(self) -> str:
        return self.dados["meta"]["periodo"]["inicio"]

    @property
    def ultimo_mes(self) -> str:
        return self.dados["meta"]["periodo"]["fim"]

    # --- Edição do index.html ---------------------------------------------------------------
    def _tag_com_id(self, id_: str) -> re.Match:
        achados = list(re.finditer(r"<([a-zA-Z][\w-]*)\b[^>]*?\sid=\"" + re.escape(id_) + r"\"[^>]*>", self.html))
        if len(achados) != 1:
            raise ErroEstatico(f'index.html: esperava um elemento com id="{id_}", achei {len(achados)}')
        return achados[0]

    def preencher(self, id_: str, conteudo: str) -> None:
        """Põe `conteudo` (HTML já escapado) dentro do elemento vazio com esse id."""
        m = self._tag_com_id(id_)
        fecha = f"</{m.group(1)}>"
        if not self.html.startswith(fecha, m.end()):
            raise ErroEstatico(f'index.html: o elemento id="{id_}" não está vazio')
        self.html = self.html[: m.end()] + conteudo + self.html[m.end():]

    def definir_atributo(self, id_: str, nome: str, valor: str) -> None:
        """Cria ou troca um atributo na tag de abertura do elemento com esse id."""
        m = self._tag_com_id(id_)
        tag = m.group(0)
        padrao = re.compile(r"\s" + re.escape(nome) + r"=\"[^\"]*\"")
        novo = f' {nome}="{esc(valor)}"'
        tag_nova = padrao.sub(lambda _: novo, tag, count=1) if padrao.search(tag) else re.sub(r"\s*(/?)>$", lambda x: f"{novo}{x.group(1)}>", tag, count=1)
        self.html = self.html[: m.start()] + tag_nova + self.html[m.end():]

    def inserir_antes(self, marcador: str, conteudo: str) -> None:
        """Insere `conteudo` antes da única ocorrência de `marcador` (ex.: "</head>")."""
        if self.html.count(marcador) != 1:
            raise ErroEstatico(f"index.html: esperava uma ocorrência de {marcador!r}, achei {self.html.count(marcador)}")
        self.html = self.html.replace(marcador, conteudo + marcador, 1)

    # --- Arquivos do site -------------------------------------------------------------------
    def escrever(self, caminho: str, texto: str) -> Path:
        """Grava um arquivo do site (caminho relativo à pasta do site)."""
        destino = self.site / caminho
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
        return destino

    def gravar(self) -> None:
        (self.site / "index.html").write_text(self.html, encoding="utf-8")
