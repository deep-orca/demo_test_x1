
# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm AS build

ARG python_version=3.13

SHELL ["/bin/sh", "-exc"]

RUN <<EOF
apt-get update --quiet
apt-get install --quiet --no-install-recommends --assume-yes \
  build-essential \
  libpq-dev \

EOF

COPY --link --from=ghcr.io/astral-sh/uv:0.7 /uv /usr/local/bin/uv

ENV UV_PYTHON="python$python_version" \
  UV_PYTHON_DOWNLOADS=never \
  UV_PROJECT_ENVIRONMENT=/app \
  UV_LINK_MODE=copy \
  UV_COMPILE_BYTECODE=1 \
  PYTHONOPTIMIZE=1

# Копируем файлы, необходимые для установки зависимостей без кода проекта, так как обычно зависимости меняются реже кода.
COPY pyproject.toml uv.lock README.md /_project/

RUN --mount=type=cache,destination=/root/.cache/uv <<EOF
cd /_project
uv sync \
  --no-dev \
  --no-install-project \
  --frozen
EOF

# Переключаемся на интерпретатор из виртуального окружения.
ENV UV_PYTHON=$UV_PROJECT_ENVIRONMENT

COPY VERSION /_project/
COPY src/ /_project/src

RUN --mount=type=cache,destination=/root/.cache/uv <<EOF
cd /_project
sed -Ei "s/^(version = \")0\.0\.0(\")$/\1$(cat VERSION)\2/" pyproject.toml
uv sync \
  --no-dev \
  --no-editable \
  --frozen
EOF

FROM python:3.13-slim-bookworm AS final

ARG user_id=1000
ARG group_id=1000
ARG python_version=3.13

# ENTRYPOINT ["/docker-entrypoint.sh"]
# Для приложений на Python лучше использовать сигнал SIGINT, так как не все фреймворки (например, gRPC) корректно обрабатывают сигнал SIGTERM.
STOPSIGNAL SIGINT
EXPOSE 8080/tcp

SHELL ["/bin/sh", "-exc"]

RUN <<EOF
[ $user_id -gt 0 ] && user="$(id --name --user $user_id 2> /dev/null)" && userdel "$user"

if [ $group_id -gt 0 ]; then
  group="$(id --name --group $group_id 2> /dev/null)" && groupdel "$group"
  groupadd --gid $group_id app
fi

[ $user_id -gt 0 ] && useradd --uid $user_id --gid $group_id --home-dir /app app
EOF

RUN <<EOF
apt-get update --quiet
apt-get install --quiet --no-install-recommends --assume-yes \
  libpq5 \

rm -rf /var/lib/apt/lists/*
EOF

ENV PATH=/app/bin:$PATH \
  PYTHONOPTIMIZE=1 \
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1

# COPY docker-entrypoint.sh /
# RUN chmod +x /docker-entrypoint.sh

# COPY --chown=$user_id:$group_id etc/ /app/etc
# COPY --chown=$user_id:$group_id data/ /app/data
# Копируем директорию с виртуальным окружением из предыдущего этапа.
COPY --link --chown=$user_id:$group_id --from=build /app/ /app

USER $user_id:$group_id
WORKDIR /app

# Выводим информацию о текущем окружении и проверяем работоспособность импорта модуля проекта.
RUN <<EOF
python --version
python -I -m site
python -I -c 'import tst'
EOF
