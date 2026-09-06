# Glider Score F5J

Aplicativo Android (Kivy) para cronometragem e pontuação de competições de
**F5J — RC Electric Powered Thermal Duration Gliders**, seguindo o
regulamento oficial da FAI (*FAI Sporting Code, Section 4 — Aeromodelling,
Volume F5*, seção 5.5.11, edição 2026).

## Funcionalidades

- Cadastro de evento, número de pilotos e número de rounds.
- Tela de voo por round, com entrada de:
  - Tempo de voo (formato MM:SS)
  - Distância de pouso (m)
  - Altura de lançamento / Start Height (m)
  - Marcadores de pouso >10 m, pouso >75 m e reinício de motor
- Cálculo automático da pontuação de cada voo conforme o regulamento (ver
  abaixo) e normalização do round (1000 pontos para o melhor voo).
- Tela de resultados no estilo GliderScore (Rank, Nome, Score, Pcnt, Raw,
  pontuação por round).
- Exportação dos resultados em PDF.
- Dados salvos localmente em JSON (`f5j_data.json`), persistindo entre
  sessões do app.

## Regras de pontuação aplicadas (5.5.11.12)

- **Tempo de voo**: 1 ponto por segundo completo, truncado, com teto de
  900 pontos (15 min — cobre também o Working Time do fly-off, 5.5.11.13 e).
- **Bônus de pouso**: tabela oficial — até 1 m = 50 pts, decrescendo
  5 pts por metro até 10 m (5 pts), acima de 10 m = 0.
- **Dedução por altura de lançamento**: 0,5 pt por metro até 200 m e
  3 pts por metro acima de 200 m, truncada ao metro inteiro.
- **Voo zerado** quando: o motor é reiniciado durante o voo, o pouso
  ocorre a mais de 75 m do centro da área designada, ou o piloto ultrapassa
  o Working Time em mais de 1 minuto.
- O total nunca fica negativo (pontuação mínima = 0).

> **Não implementado ainda:** penalidades de segurança e de organização
> (5.5.11.4), como infrações de corredor de acesso ou de área de segurança.
> Essas deduções precisam ser aplicadas manualmente por enquanto.

## Estrutura do projeto

```
.
├── main.py            # Aplicativo Kivy (telas, lógica e pontuação)
├── buildozer.spec      # Configuração de build para Android
├── icon.png            # Ícone do app
└── f5j_data.json        # Gerado automaticamente ao usar o app (dados da competição)
```

## Requisitos

- Python 3
- [Kivy](https://kivy.org/)
- [fpdf2](https://pypi.org/project/fpdf2/) (para exportação em PDF)
- [Buildozer](https://buildozer.readthedocs.io/) (para gerar o APK Android)

## Rodando no desktop (para testes rápidos)

```bash
pip install kivy fpdf2
python main.py
```

## Build para Android

```bash
buildozer -v android debug
```

O APK gerado fica em `./bin/`. Para instalar direto num aparelho conectado
por USB (com depuração USB ativada):

```bash
buildozer android deploy run
```

Para ver o log do app rodando no celular (útil se ele fechar sozinho):

```bash
buildozer android logcat
```

## Uso

1. **Ajustes**: defina o nome do evento, número de pilotos, número de
   rounds e os nomes dos pilotos.
2. **Voar**: navegue entre os rounds e registre tempo, pouso, altura e os
   marcadores de cada voo. A pontuação do round é recalculada
   automaticamente a cada alteração.
3. **Resultados**: veja a classificação geral, com a soma normalizada de
   cada round, e exporte em PDF quando quiser.

## Licença

Defina aqui a licença do projeto (ex.: MIT, ou "uso interno").
