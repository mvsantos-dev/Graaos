"""Site estático gerado no build (build_site.sh): o que dá para ler sem JavaScript.

Roda depois que o build_site.sh copia dashboard/, o dashboard.json e o boletim.json para a pasta
do site, e só lê o que está lá (mais os boletins/AAAA-MM.json do repositório, com o texto de cada
mês): nenhum número é escrito à mão. Só biblioteca padrão, porque roda no build da Cloudflare e
do GitHub Pages, sem instalar pacotes.

Etapas (cada uma num módulo, chamadas em ordem por __main__.py):

- resumo e resumo_precos: o card "Resumo" já preenchido, os destaques (origens e relação de
  troca), a frase de resumo de cada gráfico e o aria-label dos canvas, iguais ao que o JavaScript
  desenha na visão padrão (todos os grupos, período inteiro). O JavaScript continua redesenhando
  por cima.
- tabelas: as tabelas de "Ver tabela" já no HTML, iguais às da visão padrão.
- boletins: uma página por mês em boletim/AAAA-MM/ e o arquivo em boletim/.
- cabecalho: JSON-LD, robots.txt, sitemap.xml, 404.html, llms.txt, _headers e a versão (?v=) dos
  arquivos de assets/ nas páginas.

Uso (pelo build_site.sh): python3 -m src.estatico PASTA_DO_SITE [--atualizado AAAA-MM-DD]

Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet); BCB/PTAX.
"""
