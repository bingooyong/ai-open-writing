"""Alembic 迁移环境:接 SQLModel metadata,db url 来自项目配置。"""

from logging.config import fileConfig

import sqlmodel  # noqa: F401  (迁移脚本中引用 sqlmodel 类型)
from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from novel_agent.config import get_settings
from novel_agent.domain import models  # noqa: F401  (注册全部表)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# db url:优先 alembic -x db_url=...,否则取项目配置
x_args = context.get_x_argument(as_dictionary=True)
db_url = x_args.get("db_url")
if not db_url:
    db_path = get_settings().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{db_path}"
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite 变更需 batch 模式
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
