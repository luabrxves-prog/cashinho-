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
python scripts/run_backtest_diagnostics.py --symbols PETR4,VALE3,ITUB4,BOVA11 --years 2020-2026
```

Saidas locais:

```text
data/reports/diagnostics/diagnostic_report.md
data/reports/diagnostics/diagnostic_trades.csv
data/reports/diagnostics/diagnostic_groups.csv
```

O relatorio nao autoriza dinheiro real. Ele serve para decidir quais filtros
precisam ser criados ou endurecidos antes de voltar ao PAPER.
