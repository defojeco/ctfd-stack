"""Add partial scoring settings fields

Revision ID: add_partial_settings
Revises:
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = 'add_partial_settings'
down_revision = None
branch_labels = None
depends_on = None


def upgrade(op=None):
    # Добавляем новые поля для настроек частичного зачёта
    bind = op.get_bind() if op else None

    if not bind:
        return

    # Проверяем, существуют ли уже колонки
    inspector = sa.inspect(bind)

    try:
        columns = [col['name'] for col in inspector.get_columns('multichoice_challenge')]
    except Exception:
        # Таблица не существует, ничего не делаем
        return

    # Добавляем колонки только если их нет
    if 'partial_mode' not in columns:
        try:
            with op.batch_alter_table('multichoice_challenge') as batch_op:
                batch_op.add_column(sa.Column('partial_mode', sa.String(16), nullable=True))

            # Устанавливаем значение по умолчанию для существующих записей
            bind.execute(text("UPDATE multichoice_challenge SET partial_mode = 'percentage' WHERE partial_mode IS NULL"))
        except Exception as e:
            print(f"Warning: Could not add partial_mode column: {e}")

    if 'partial_settings' not in columns:
        try:
            with op.batch_alter_table('multichoice_challenge') as batch_op:
                batch_op.add_column(sa.Column('partial_settings', sa.Text(), nullable=True))

            # Устанавливаем значение по умолчанию для существующих записей
            bind.execute(text("UPDATE multichoice_challenge SET partial_settings = '' WHERE partial_settings IS NULL"))
        except Exception as e:
            print(f"Warning: Could not add partial_settings column: {e}")


def downgrade(op=None):
    # Удаляем поля при откате миграции
    bind = op.get_bind() if op else None

    if not bind:
        return

    inspector = sa.inspect(bind)

    try:
        columns = [col['name'] for col in inspector.get_columns('multichoice_challenge')]
    except Exception:
        return

    if 'partial_settings' in columns:
        try:
            with op.batch_alter_table('multichoice_challenge') as batch_op:
                batch_op.drop_column('partial_settings')
        except Exception as e:
            print(f"Warning: Could not drop partial_settings column: {e}")

    if 'partial_mode' in columns:
        try:
            with op.batch_alter_table('multichoice_challenge') as batch_op:
                batch_op.drop_column('partial_mode')
        except Exception as e:
            print(f"Warning: Could not drop partial_mode column: {e}")
