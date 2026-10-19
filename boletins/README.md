# Boletins mensais

Um boletim por mês de dados, gerado pelo workflow [`atualizacao.yml`](../.github/workflows/atualizacao.yml)
com [`src/boletim.py`](../src/boletim.py):

- `AAAA-MM.md`: o boletim do mês, com a tabela dos números citados;
- `AAAA-MM.json`: o mesmo conteúdo do `latest.json`, guardado para cada mês (só a partir dos
  boletins gerados depois desta mudança), lido pela página do mês no site;
- `latest.json`: o boletim mais recente, lido pelo card do [dashboard](https://radar.graaos.cloud/).

O site tem uma página por mês de dados em [`/boletim/AAAA-MM/`](https://radar.graaos.cloud/boletim/)
e o arquivo de todos os meses em `/boletim/`, gerados no build (`build_site.sh`, por
`src/estatico/boletins.py`) só a partir do `dashboard.json`: os números do mês e do acumulado,
a tabela por grupo, a relação de troca no porto e, no último mês dos dados e nos dezembros,
origens, portos e rotas do ano. As frases dessas páginas são modelos preenchidos pelo programa
com o mesmo pacote de fatos do boletim; o texto da IA entra na página do mês quando existe o
`AAAA-MM.json` (ou quando o `latest.json` é daquele mês). Os meses anteriores à IA ficam só com
os números e as frases-modelo. Texto do modo `--mock` nunca entra no site.

O texto é escrito por IA, mas os números não: a IA só cita marcadores de um pacote de fatos
calculado pelo programa, que os troca pelos valores e reprova qualquer número escrito fora deles.
Detalhes no [README](../README.md#como-a-ia-é-usada-e-por-que-ela-não-inventa-números).

Texto gerado por IA a partir de dados do Comex Stat/MDIC; números inseridos e verificados automaticamente.
Quando um boletim cita números do benchmark internacional, o rodapé e as fontes dele incluem o
Banco Mundial (Pink Sheet), com uma nota fixa: o benchmark é uma referência de outro lugar e de
outro momento de contrato, e o spread não é ágio (e, para o MAP, a referência é o DAP). Quando
cita a PTAX ou o CIF em reais, incluem o BCB (PTAX); com o CIF em reais, entra a nota de que ele
usa a PTAX média do mês. As licenças das fontes (CC BY 4.0 e ODbL) estão no
[README](../README.md#licenças-das-fontes).

Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet); BCB/PTAX.
