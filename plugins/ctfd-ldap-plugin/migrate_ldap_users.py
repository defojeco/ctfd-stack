#!/usr/bin/env python3
"""
Скрипт миграции существующих LDAP-пользователей для работы с новой логикой displayName.

Что делает:
1. Находит всех пользователей с email @<ldap_domain>
2. Извлекает sAMAccountName из email (часть до @)
3. Сохраняет маппинг user_id → sAMAccountName в конфиг ldap_user_map
4. При следующем входе их name обновится на displayName из LDAP

Использование:
    python migrate_ldap_users.py [--dry-run]

Опции:
    --dry-run    Показать изменения без сохранения в БД
"""

import sys
import json
import argparse

# Добавляем путь к CTFd
sys.path.insert(0, '/opt/CTFd')

from CTFd import create_app
from CTFd.models import Users, db
from CTFd.utils import get_config, set_config


def migrate_users(dry_run=False):
    """Мигрирует существующих LDAP-пользователей."""
    app = create_app()

    with app.app_context():
        # Получаем текущий маппинг (если есть)
        mapping = json.loads(get_config("ldap_user_map") or "{}")
        original_count = len(mapping)

        # Получаем домен из конфига
        domain = get_config("ldap_domain")
        if not domain:
            print("❌ ERROR: ldap_domain not configured in CTFd settings")
            return 1

        print(f"🔍 Searching for LDAP users with email @{domain}...")
        print(f"📊 Current mapping size: {original_count} entries\n")

        # Находим всех LDAP-пользователей
        ldap_users = Users.query.filter(Users.email.like(f"%@{domain}")).all()

        if not ldap_users:
            print(f"✅ No LDAP users found with domain @{domain}")
            return 0

        print(f"Found {len(ldap_users)} LDAP users:\n")

        migrated = 0
        skipped = 0

        for user in ldap_users:
            user_id_str = str(user.id)

            # Извлекаем sAMAccountName из email
            sam = user.email.split("@")[0]

            # Проверяем, не мигрирован ли уже
            if user_id_str in mapping:
                existing_sam = mapping[user_id_str]
                if existing_sam == sam:
                    print(f"⏭️  SKIP: user_id={user.id:3d} name={user.name:30s} "
                          f"sAMAccountName={sam:20s} (already migrated)")
                    skipped += 1
                else:
                    print(f"⚠️  WARN: user_id={user.id:3d} name={user.name:30s} "
                          f"sAMAccountName conflict: {existing_sam} → {sam}")
                    if not dry_run:
                        mapping[user_id_str] = sam
                    migrated += 1
            else:
                print(f"✅ MIGRATE: user_id={user.id:3d} name={user.name:30s} "
                      f"→ sAMAccountName={sam:20s}")
                if not dry_run:
                    mapping[user_id_str] = sam
                migrated += 1

        print(f"\n{'─' * 80}")
        print(f"📊 Summary:")
        print(f"   Total users found:    {len(ldap_users)}")
        print(f"   Migrated:             {migrated}")
        print(f"   Skipped (existing):   {skipped}")
        print(f"   Mapping size:         {original_count} → {len(mapping)}")

        if dry_run:
            print(f"\n🔍 DRY RUN MODE — no changes saved to database")
            print(f"   Run without --dry-run to apply changes")
            return 0

        # Сохраняем маппинг
        set_config("ldap_user_map", json.dumps(mapping, ensure_ascii=False))
        db.session.commit()

        print(f"\n✅ Migration complete — mapping saved to ldap_user_map")
        print(f"\n📝 Next steps:")
        print(f"   1. Users will keep their current names until next login")
        print(f"   2. On next login, their name will update to displayName from LDAP")
        print(f"   3. If displayName is already taken, suffix _2, _3 will be added")

        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Migrate existing LDAP users to new displayName logic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview changes without saving
  python migrate_ldap_users.py --dry-run

  # Apply migration
  python migrate_ldap_users.py

  # Run inside Docker container
  docker exec -it <container> python /opt/CTFd/CTFd/plugins/ldap_plugin/migrate_ldap_users.py
        """
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show changes without saving to database"
    )

    args = parser.parse_args()

    try:
        return migrate_users(dry_run=args.dry_run)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
