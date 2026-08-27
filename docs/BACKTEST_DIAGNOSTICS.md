# Diagnostico operacional

O diagnostico operacional responde onde a logica do Cashinho esta funcionando,
perdendo ou ficando parada. Ele quebra os trades simulados por:

- ano;
- mes;
- hora do dia;
- ativo;
- lado da operacao;
- timeframe;
- motivo de saida;
- regime de mercado;
- volatilidade.

Uso recomendado para começar pequeno:

```powershell
python scripts/run_backtest_diagnostics.py --symbols PETR4 --years 2026
```

Uso amplo:

```powershell
python scripts/run_backtest_diagnostics.py --symbols PETR4,VALE3,ITUB4,BOVA11 --years 2020-2026 --timeframes 5m,15m,60m,1D --decision-timeframe 60m --max-decision-points 300
```

`--decision-timeframe` controla de quanto em quanto tempo a maquina reavalia
a entrada. Candles menores continuam servindo para execucao/stop/alvo, mas o
estudo evita tomar decisoes a cada candle de 5 minutos quando a base inteira de
2020 a 2026 esta sendo analisada.

Por padrao, o gerador da politica operacional estuda todos os ativos e anos,
mas nao recalcula o mercado amplo dentro de cada candle, para terminar em tempo
pratico. Use `--market-context` quando quiser uma validacao mais pesada,
incluindo a leitura cruzada do mercado em cada decisao historica.

`--max-decision-points` limita quantos fechamentos de candle viram pontos de
decisao por ativo/ano. A amostragem e cronologica e espalhada pelo periodo; a
execucao da operacao ainda percorre os candles para entrada, stop e alvo.

Saidas locais:

```text
data/reports/diagnostics/diagnostic_report.md
data/reports/diagnostics/diagnostic_trades.csv
data/reports/diagnostics/diagnostic_groups.csv
data/reports/deep_study/operational_policy.json
```

O arquivo `operational_policy.json` e consumido pelo Scanner B3 como trava
historica automatica. Ele bloqueia ou alerta contextos que foram ruins no
estudo por ativo, horario, lado, timeframe, regime e volatilidade.

O snapshot versionado do estudo 2020-2026 fica em
[`DEEP_STUDY_2020_2026.md`](DEEP_STUDY_2020_2026.md), e a politica padrao
gerada fica em `src/cashinho/config/operational_policy.default.json`.

O relatorio nao autoriza dinheiro real. Ele serve para decidir quais filtros
precisam ser criados ou endurecidos antes de voltar ao PAPER.
