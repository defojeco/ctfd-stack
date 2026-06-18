#!/bin/bash
# Скрипт установки LDAP Plugin v2.5 с исправлением фильтрации категорий

set -e

echo "=========================================="
echo "LDAP Plugin v2.5 - Category Filter Fix"
echo "=========================================="
echo ""

# Проверка аргументов
if [ -z "$1" ]; then
    echo "Usage: $0 <container_name>"
    echo "Example: $0 ctfd"
    exit 1
fi

CONTAINER=$1

# Проверка что контейнер существует
if ! docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "❌ Error: Container '${CONTAINER}' not found"
    exit 1
fi

echo "📦 Container: ${CONTAINER}"
echo ""

# Бэкап текущей версии
echo "🔄 Creating backup..."
docker exec ${CONTAINER} cp /opt/CTFd/CTFd/plugins/ldap_plugin/__init__.py \
    /opt/CTFd/CTFd/plugins/ldap_plugin/__init__.py.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true
echo "✅ Backup created"
echo ""

# Копирование нового файла
echo "📤 Uploading new __init__.py..."
docker cp __init__.py ${CONTAINER}:/opt/CTFd/CTFd/plugins/ldap_plugin/__init__.py
echo "✅ File uploaded"
echo ""

# Проверка синтаксиса
echo "🔍 Checking Python syntax..."
docker exec ${CONTAINER} python -m py_compile /opt/CTFd/CTFd/plugins/ldap_plugin/__init__.py
if [ $? -eq 0 ]; then
    echo "✅ Syntax OK"
else
    echo "❌ Syntax error detected!"
    echo "🔄 Restoring backup..."
    docker exec ${CONTAINER} bash -c "cp /opt/CTFd/CTFd/plugins/ldap_plugin/__init__.py.backup.* /opt/CTFd/CTFd/plugins/ldap_plugin/__init__.py"
    exit 1
fi
echo ""

# Перезапуск контейнера
echo "🔄 Restarting container..."
docker restart ${CONTAINER}
echo "✅ Container restarted"
echo ""

# Ожидание запуска
echo "⏳ Waiting for CTFd to start (30 seconds)..."
sleep 30
echo ""

# Проверка логов
echo "📋 Checking logs..."
docker logs ${CONTAINER} 2>&1 | grep "LDAP-PLUGIN" | tail -10
echo ""

# Проверка патчей
echo "🔍 Verifying patches..."
if docker logs ${CONTAINER} 2>&1 | grep -q "Challenge API patched.*list + detail + attempts"; then
    echo "✅ Challenge API patch: OK"
else
    echo "⚠️  Challenge API patch: NOT FOUND"
fi

if docker logs ${CONTAINER} 2>&1 | grep -q "Challenge view patched"; then
    echo "✅ Challenge view patch: OK"
else
    echo "⚠️  Challenge view patch: NOT FOUND"
fi
echo ""

echo "=========================================="
echo "✅ Installation completed!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Open /admin/ldap-settings"
echo "2. Enable category filtering"
echo "3. Configure team mappings"
echo "4. Test with: python test_category_filter.py <url> <user> <pass>"
echo ""
echo "Documentation:"
echo "- QUICKSTART.md - Quick start guide"
echo "- README_v2.5.md - Full documentation"
echo "- CATEGORY_FILTER_FIX.md - Technical details"
echo ""
