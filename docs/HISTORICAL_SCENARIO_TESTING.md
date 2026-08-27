# Testes historicos por cenarios

O Cashinho agora tem uma bateria de cenarios para responder uma pergunta
objetiva: como a maquina teria se comportado em momentos que ja aconteceram?

Ela nao baixa dados, nao usa internet e nao inventa cotacao. Cada cenario roda
somente quando existem CSVs locais no formato:

```text
data/historical/<ATIVO>/<timeframe>.csv
```

com cabecalho:

```text
timestamp,open,high,low,close,volume
```

O `timestamp` precisa estar em ISO-8601 com fuso, por exemplo:

```text
2020-03-09T13:00:00+00:00,20.10,20.30,19.80,20.00,100000
```

## Como rodar

```powershell
python scripts/run_scenario_suite.py
```

O relatorio sai em:

```text
data/reports/scenario_suite.md
```

`data/` e ignorado pelo Git de proposito, porque dados reais e relatorios locais
nao devem ir para o repositorio.

## Como interpretar

- `PASS`: o cenario rodou e respeitou os limites definidos.
- `FAIL`: o cenario rodou, mas violou limite de drawdown, quantidade de trades ou
  profit factor minimo.
- `SKIP`: faltam CSVs reais para aquele periodo.

Uma falta de entrada pode ser boa em crise. O objetivo nao e forcar operação; o
objetivo e sobreviver e so operar quando os filtros concordam.

## Cenarios iniciais

O arquivo versionado em `docs/scenario_suite.example.json` traz:

- smoke test sintetico com as fixtures atuais;
- crise COVID/circuit breaker de marco de 2020;
- janela longa de 2012 a 2017 citada pela CVM/FGV em estudos de day trade;
- recuperacao pos-estresse em abril/maio de 2020.

Para esses cenarios virarem prova real, exporte os candles historicos do MT5 ou
de outra fonte confiavel para `data/historical/`.

## Referencias

- B3, aviso sobre circuit breaker de 09/03/2020:
  https://www.b3.com.br/pt_br/noticias/aviso-ao-mercado-8AE490C870BF0D5D0170BF7FBAE91DA7.htm
- CVM, materiais educativos sobre day trade e funcionamento da bolsa:
  https://www.gov.br/cvm/pt-br/assuntos/noticias/2020/educacao-financeira-em-pauta--cvm-lanca-materiais-educativos-sobre-day-trade-e-funcionamento-da-bolsa-de-valores-5221f3b6650040a084fd7e3554ad9807
- CVM, serie educacional sobre riscos de day trade:
  https://www.gov.br/cvm/pt-br/assuntos/noticias/2023/cvm-lanca-serie-de-videos-educacionais-sobre-day-trade
