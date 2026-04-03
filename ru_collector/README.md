# RU News Collector

Автономный микросервис сбора новостей из 17 российских СМИ.
Работает на VPS в России (прямой доступ к сайтам без прокси).

## Архитектура

```
[RU VPS]                              [EU VPS]
┌──────────────────────┐              ┌─────────────────────┐
│  RU News Collector   │              │  Основное приложение │
│  ┌───────────────┐   │   HTTP API   │  ┌────────────────┐ │
│  │ 17 парсеров   │   │◄────────────►│  │ RuCollector    │ │
│  │ APScheduler   │   │  /api/...    │  │ Client         │ │
│  │ PostgreSQL    │   │              │  │ + Habr/VC/TG   │ │
│  │ FastAPI :8100 │   │              │  │ + Аналитика    │ │
│  └───────────────┘   │              │  └────────────────┘ │
└──────────────────────┘              └─────────────────────┘
```

## Источники

ТАСС, РИА Новости, Интерфакс, Коммерсант, Forbes, Ведомости, РБК,
Известия, Российская газета, Независимая газета, КП, МК, АиФ,
Gazeta.ru, RT, Lenta.ru, Экспресс газета

## Быстрый старт

### Docker (рекомендуется)

```bash
cd ru_collector
cp .env.example .env
# Отредактировать .env: задать API_TOKEN

docker compose up -d
```

### Без Docker

```bash
cd ru_collector
pip install -r requirements.txt

# Создать БД PostgreSQL: ru_news
cp .env.example .env
# Отредактировать .env

python -m ru_collector
```

### Тест парсеров

```bash
# Все источники
python -m ru_collector.test_sources

# Конкретные
python -m ru_collector.test_sources tass ria rbc
```

## API

Все эндпоинты (кроме /health) требуют заголовок:
```
Authorization: Bearer <API_TOKEN>
```

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Проверка состояния |
| GET | `/api/articles/pending?limit=500` | Непереданные статьи |
| POST | `/api/articles/ack` | Подтвердить получение `{"ids": [...]}` |
| GET | `/api/articles/search?source=tass&q=...` | Поиск по статьям |
| GET | `/api/stats` | Статистика по источникам |

## Настройка на стороне EU-приложения

В `.env` основного приложения:
```
RU_COLLECTOR_URL=http://<ru-vps-ip>:8100
RU_COLLECTOR_TOKEN=<тот же токен, что в API_TOKEN>
```
