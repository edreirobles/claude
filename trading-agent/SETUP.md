# Trading Agent USD/MXN — Setup

## 1. Instalar dependencias

```bash
cd trading-agent
pip install -r requirements.txt
```

## 2. Crear el bot de Telegram

1. Abre Telegram y busca **@BotFather**
2. Envía `/newbot` y sigue las instrucciones → te da un **token**
3. Inicia una conversación con tu bot
4. Obtén tu **chat_id** visitando:
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
   El `chat.id` aparece en la respuesta

## 3. Configurar Bitso API

1. Ve a [bitso.com](https://bitso.com) → Configuración → API
2. Crea una API key con permisos: **trading** (no withdrawal)
3. Guarda el API Key y Secret

## 4. Variables de entorno

```bash
cp .env.example .env
# Edita .env con tus credenciales:
```

```
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHI...
TELEGRAM_CHAT_ID=987654321
BITSO_API_KEY=tu_api_key
BITSO_API_SECRET=tu_api_secret
```

## 5. Configurar el modo de operación

Edita `config.py`:

```python
PAPER_TRADING = True   # Cambiar a False cuando quieras operar real con Bitso
```

## 6. Ejecutar

```bash
python main.py
```

## Comandos de Telegram

| Comando | Descripción |
|---------|-------------|
| `/status` | Portafolio actual |
| `/signal` | Última señal |
| `/trades` | Últimas 5 operaciones |
| `/pause` | Pausar el agente |
| `/resume` | Reanudar |
| `/report` | Reporte completo |

## Estrategias implementadas

| Estrategia | Referencia académica | Peso |
|------------|---------------------|------|
| RSI | Wilder (1978) | 25% |
| MACD | Appel (1979) | 20% |
| Bollinger Bands | Bollinger (2002) | 25% |
| Mean Reversion (Z-score OU) | Avellaneda & Lee (2010) | 20% |
| Macro Trend 30d | — | 10% |

## Gestión de riesgo

- **Kelly Criterion fraccional (25%)**: sizing óptimo de posición (Kelly, 1956)
- **Stop-loss**: 3% por operación
- **Take-profit**: 5%
- **Drawdown máximo**: 15% → agente se detiene
