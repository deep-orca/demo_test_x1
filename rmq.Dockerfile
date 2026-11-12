FROM rabbitmq:4.2-management

# Скачиваем совместимую версию плагина для ветки RabbitMQ 4.2.x
ARG PLUGIN_VERSION=4.2.0
ADD https://github.com/rabbitmq/rabbitmq-delayed-message-exchange/releases/download/v4.2.0/rabbitmq_delayed_message_exchange-${PLUGIN_VERSION}.ez /opt/rabbitmq/plugins/

# Выдаём права пользователю rabbitmq и включаем плагин
RUN chown rabbitmq:rabbitmq /opt/rabbitmq/plugins/rabbitmq_delayed_message_exchange-${PLUGIN_VERSION}.ez \
    && rabbitmq-plugins enable --offline rabbitmq_delayed_message_exchange
